# Spec — `#group` quick-entry sigil + create-form group field (#24)

_2026-07-15. Follow-up to #22/#23. Adds group assignment to the create flow._

## Problem

Quick-entry (#22) pre-fills the create form from one free-text line, but has no way
to assign the new contact to a group. Group membership is not a property on the
contact's own vCard — it lives on the group card's `X-ADDRESSBOOKSERVER-MEMBER` list
(ADR-0002/0004) — and the create form exposes no group field at all. So a `#group`
sigil was deferred at #22.

## Intended behaviour

1. **Create form gains a group field.** `GET /contacts/new` renders a multi-select
   (checkboxes) of the user's **existing** groups (`store.list_groups`). Create-only
   — the edit form is unchanged (membership editing keeps its own group-page UI).
2. **`#group` sigil pre-fills it.** `parse_quick_entry` extracts `#token` tags
   (`#family #work`) into `fields.groups` (raw names). `token` = `[^\s#]+`; matching is
   case-insensitive against group display names. Multi-word group names aren't
   reachable by the sigil (checkbox still selects them) — accepted limitation.
3. **Unknown group name → ignore + flag.** A `#name` that matches no existing group is
   **not** created and does **not** block save; the form shows a note
   ("No group named 'x' — not assigned") so the user sees it wasn't applied. Matched
   names arrive as pre-checked boxes.
4. **Save writes membership after create.** `POST /contacts` creates the card, reads
   its new UID, then for each checked `group_uid`: load the group rec, append the UID
   to its member list, `set_group` + etag-conditional PUT + `cache_after_write` — the
   existing `_mutate_group` write path, through the store helpers under the per-user
   lock. Sequential (one PUT per group). Then redirect to the new contact.

## Out of scope

- Auto-creating groups from unknown names (rejected — silent server write from a typo).
- Editing group membership from the edit form (the group page already does this).
- Multi-word group names via the sigil (checkbox covers it).
- Removing a contact from a group at create time (nothing to remove yet).

## Design notes / invariants

- Group names never enter the contact's own vCard — `new_vcard(fields)` ignores
  `fields.groups`; membership is a separate write to each group card.
- Extraction order: run `#group` extraction **after** email/url/phone so a `#fragment`
  inside a URL is already consumed (URL regex grabs `\S+` incl. fragment).
- A conflict (409) on a group PUT during the post-create loop: the contact is already
  created. Surface it rather than silently dropping — the contact exists but that group
  assignment didn't land. (Match `_mutate_group`'s conflict handling; don't mask.)
- Per-user lock: go through the store helpers / `locked_*` path; never hold the lock
  across an `await` (ADR-0004 / PITFALLS).

## Test approach

- **Parser (unit, TDD):** `#family` / `#family #work` → `fields.groups`; `#` inside a
  URL not misread; a lone `#` / empty tag ignored; case preserved (matching is the
  route's job).
- **Route (unit):** `GET /contacts/new?q=...#family` pre-checks the matching box;
  unknown `#x` renders the not-assigned note; `POST /contacts` with `group_uid` checked
  appends the new contact's UID to that group's member list (assert via store/raw vCard).
- **Live:** browser-verify against local Radicale — quick-add with `#group`, review the
  pre-checked box on the form, Save, confirm the group card's member list gained the
  contact on the server.

# Spec — Choose which fields show in list / card views (#27)

_2026-07-16 · enhancement · surface: web UI (templates + inline JS/CSS)_

## Problem

The fields shown in the contacts index are hardcoded in `_contacts.html`:

- **List view:** name + org.
- **Card view:** name + org + first phone + first email.

Users can't tailor what shows. The list is especially sparse — one reason #25's
widened index still leaves the list view mostly empty. What's worth showing at a
glance is a per-user preference, not a fixed choice.

## Intended behavior

Field selection becomes a client-side display preference, reusing the
display-settings idiom exactly (localStorage + pre-paint attribute + CSS,
driven from the `⚙` settings popover). **List and card have independent
selections.** Name + avatar always render (the anchor).

**Toggleable fields (both views):** org, phone, email, birthday, url, address.

**Mechanism — render-all + CSS-hide:**

| Concern | Approach |
|---|---|
| Rendering | Both list and card branches of `_contacts.html` render **every** toggleable field, each still guarded by `{% if contact has data %}` so empty fields emit nothing. Each element carries a stable `field-<name>` class beside its style class. |
| Selection storage | Two localStorage keys — `peopledb-list-fields`, `peopledb-card-fields` — each a space-separated token set (e.g. `"org phone"`). |
| Applied via | Root attributes `data-list-fields` / `data-card-fields`, stamped by the `base.html` pre-paint script **before first paint**. |
| Show/hide | Each toggleable field defaults hidden inside its view; revealed only when its token is present, via the whole-word attribute match: `:root[data-list-fields~="org"] ul.contacts .field-org { display: … }` (and the parallel `data-card-fields` / `.contact-card` block). |
| Values | Multi-value fields show the **first** entry (`phones[0]`, `emails[0]`, `urls[0]`, `addresses[0]`), matching today's card. Address renders as a single compact line. |

**Defaults preserve current behavior.** Unlike the sizing keys' "`md` = no
attribute," the field attribute is **always** present — the pre-paint script,
when a key is absent from localStorage, writes the current-behavior default so
untouched installs render exactly as today:

- `data-list-fields` default = `org`
- `data-card-fields` default = `org phone email`

**Popover UI.** Two new groups in the `#settings-panel` popover, below the size
groups: **"List fields"** and **"Card fields"**, each a row of checkboxes (org /
phone / email / birthday / url / address). On change: rebuild the space-separated
string from the checked boxes → write localStorage → update the root attribute
live (no reload). Each group is keyed off `data-fields-storage-key` /
`data-fields-attr` data-attributes and driven by a small dedicated checkbox
handler (the existing size-group handler is S/M/L-specific).

**Only known field tokens are ever written** to the attribute (allow-list of the
six names) — no CSS-injection surface, same guard discipline as the accent/size
allow-lists.

## Out of scope

- **Server-side / cross-device persistence.** localStorage is per-browser,
  matching theme/accent/sizes and the no-user-DB auth invariant (ADR-0003).
  (Field selection is a *display-density* preference, **not** an access-control
  or redaction boundary: the viewer is always the authenticated owner, who can
  already see every field on the detail page. Rendering a deselected field into
  that owner's own page source exposes nothing new. If a future "share a
  read-only list" feature ever needs redaction, it builds its own server-side
  omission path — it does not make this client-side choice wrong here.)
- The `note` field (text-heavy, not row-friendly).
- Field **ordering** within a view; per-contact overrides.
- Widening/re-laying-out the list or card CSS beyond making the new fields
  show/hide (the card grid already reflows; the list already stacks).

## Test approach

- **Route-render / template-output tests** (repo's existing style — and note the
  PITFALLS gotcha that these assert exact markup): both views emit every
  `field-*` span with the correct class when the contact has that data; spans are
  omitted when the field is absent; the popover renders both field groups with
  all six checkboxes; only allow-listed tokens appear. Update any existing
  list/card markup assertions to the new classes. `pytest` unit suite stays green.
- **Browser live-verify** (Radicale, the real proof for CSS + inline JS): toggle
  each checkbox and confirm the field shows/hides in the **right** view only;
  the selection persists across reload; a fresh profile (no localStorage) renders
  the current-behavior default (list = name+org; card = name+org+phone+email);
  no pre-paint flash.

## Notes

Extends the established display-settings localStorage + pre-paint convention — no
ADR. The one property of the render-all + CSS-hide choice: deselected field data
is present in page source though visually hidden — a non-issue here (owner-only
viewer, see Out of scope). This is the natural companion to #25: giving the list
view content to fill its widened width.

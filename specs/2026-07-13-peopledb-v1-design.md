# peopleDB v1 — Cardhop-style CardDAV web client

Date: 2026-07-13 · Status: approved design

## Problem

Household members want a fast, browsable web UI over the existing Baikal CardDAV server —
Cardhop's essentials (add/edit contacts, search, interact, birthdays) plus relationships and
group management — without replacing Baikal as the store of record.

## Intended behavior

- **Stack:** Single FastAPI app (Python, `uv`), Jinja2 + HTMX UI, SQLite cache, one Docker
  container. See ADR-0001 for rationale.
- **Auth:** Login with Baikal username/password, validated against the CardDAV endpoint.
  Credentials Fernet-encrypted in a server-side session (key from env); all CardDAV requests
  use the logged-in user's own credentials, so Baikal ACLs govern visibility.
- **Layers** (each independently testable):
  1. *CardDAV client* (hand-rolled over `httpx`; see ADR-0001 amendment — the `caldav` lib
     is CalDAV-only): discovery, sync-collection REPORT, etag-conditional writes.
  2. *vCard mapper* (`vobject`): parses cards to a Contact model; edits mutate the stored raw
     vCard in place so unrendered properties round-trip untouched. vCard 3.0 with Apple
     conventions is the primary dialect; 4.0 parsed if encountered.
  3. *Cache/sync store* (SQLite): raw vCard blob + extracted columns + FTS5 index, keyed per
     user per addressbook, with server sync token. Cache is disposable; Baikal is canonical.
  4. *Web layer*: routes, templates, auth, ICS feed.
- **Sync:** Read path refreshes via sync-token on login + periodic background job, upserting
  only changed cards. Write path is write-through: form POST → mutate raw vCard →
  `PUT If-Match: <etag>` → update cache on success. On 412, re-fetch and surface the conflict
  to the user; never overwrite.
- **Features:**
  - Add/edit via structured forms. A command-bar UI slot is reserved for a later
    natural-language quick-entry parser (out of scope for v1).
  - Search: FTS5 over name/org/emails/phones/notes; HTMX results as you type.
  - Interact: `mailto:` / `tel:` / `sms:` / maps links on relevant fields.
  - Relationships: written as Apple `X-ABRELATEDNAMES` (the vCard 3.0 convention); vCard 4
    `RELATED` is read and round-tripped on cards that already use it, never introduced.
    Rendered as labeled links navigating to the related contact when a match exists.
  - Groups: Apple-style member-list group vCards (`X-ADDRESSBOOKSERVER-KIND:group`) to match
    existing Contacts/Cardhop data — create, rename, delete, add/remove members, filter by group.
  - Birthdays: upcoming-birthdays view + per-user tokened ICS feed URL for calendar apps.
- **Error handling:** Baikal unreachable → cached read-only mode with staleness banner; writes
  fail loudly, never queue. Unparseable vCards are listed, not fatal. Conflicts always surface.

## Out of scope (v1)

Natural-language quick entry; web push / email notifications (ICS feed covers it); deep service
integrations (WhatsApp, Meet, in-app compose); offline writes / two-way sync engine; app-level
account system; CATEGORIES-based groups.

## Test approach

`/tdd` at layer seams. Property-based round-trip tests on the vCard mapper (parse → edit →
serialize preserves unknown properties — the main data-loss risk). CardDAV client live-verifies
against a throwaway local CardDAV server, never prod. **Implementation note:** the automated
live suite uses **Radicale** (pip-installable, no Docker daemon) rather than the originally
planned dockerized Baikal — Docker wasn't available in the build environment. Radicale and
sabre/dav differ in sync-collection/etag detail, so a manual pass against the real Baikal is
recorded separately in `docs/context/active-work.md` (done 2026-07-13). `.workflow.yaml` gains `test_command` /
`live_verify` at scaffold time.

## Implementer's choice (no hidden requirement)

Background sync cadence, session-store mechanism (in-memory vs. persistent), ICS token
format/rotation.

## Assumptions

Apple vCard 3.0 conventions are the compatibility target (other sync clients are Contacts and
Cardhop). Household scale: a few users, hundreds of contacts.

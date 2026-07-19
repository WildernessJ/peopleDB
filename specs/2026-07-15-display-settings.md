# Spec — Display settings (size controls + settings popover)

_2026-07-15 · enhancement · surface: web UI (templates + inline JS/CSS)_

## Problem

peopleDB has three display prefs today, split across two mechanisms and two
locations: theme + accent (localStorage, fixed top-right controls) and
list/card view (`peopledb_view` cookie, index-page buttons), plus a detail-page
avatar S/M/L toggle (localStorage `peopledb-avatar-size`, inline on the detail
page). There is no single place to adjust how the UI is sized, and text/avatar
sizing is fixed everywhere except the detail avatar.

## Intended behavior

A `⚙` button joins the fixed top-right control cluster (beside theme + accent).
It opens a **settings popover** (same `<details>` + light-dismiss pattern as the
accent picker) holding every display control:

**Six new/relocated size controls, each a segmented S/M/L (`md` = default):**

| Area | Scales | localStorage key | Applied via |
|---|---|---|---|
| Top bar | all header text + the 3 control icons | `peopledb-size-topbar` | `:root[data-size-topbar]` |
| List view | text **and** avatar together (one control) | `peopledb-size-list` | `:root[data-size-list]` |
| Card view | text | `peopledb-size-card-text` | `:root[…] .contact-card` |
| Card view | avatar | `peopledb-size-card-avatar` | `:root[…] .contact-card .avatar` |
| Detail | avatar (reuses existing sizes/key) | `peopledb-avatar-size` | `:root[…] #detail-avatar` |
| Detail | text | `peopledb-size-detail-text` | `:root[…] main.contact-detail` |

The **list/card view toggle stays on the index page** (unchanged `POST /view` +
`peopledb_view` cookie) — it was *not* moved into the popover (a server
round-trip control among instant client controls, and only meaningful where a
contact list renders). The **gear icon is deliberately larger** than the
theme/accent icons at every top-bar size, as the entry point to all display
sizing.

**Rules (mirror theme/accent exactly):**
- The `base.html` pre-paint inline script reads the size keys and stamps root
  `data-size-*` attributes **before first paint** — no flash / layout shift.
- `md` writes **no attribute** → current appearance is the default; nothing
  changes until a control is touched.
- Only `sm`/`md`/`lg` are ever written to the DOM (validated allow-list, same
  guard as the accent picker) — no CSS-injection surface.
- Size changes apply instantly (client, no reload); the view toggle reloads
  (server round-trip) — deliberate, accepted.
- Card vs. detail avatar both use `.avatar` but get distinct selectors
  (`.contact-card .avatar` vs `#detail-avatar`) and live on separate pages, so
  their two independent settings never collide.

**Removed:** the inline detail-page avatar toggle + its script (control now in
the popover; same key, existing choices survive).

**Refactor — all text within a scaled region scales with it:** child font-sizes
that were absolute `rem` switch to `em` (`.org`, `.detail`, and the detail
field **labels** `dl.card dt`) so one container font-size scales the whole group
proportionally, labels included — not just the values. Detail text is scoped to
the detail page's own `main.contact-detail` marker so it doesn't leak into the
index/form/birthdays `<main>` or compound with the em-based list/card controls.

## Out of scope

- Server-side / cross-device persistence (localStorage is per-browser, matching
  theme/accent; consistent with the no-user-DB auth invariant, ADR-0003).
- Making the list/card view a client-only CSS toggle (the two layouts are
  structurally different DOM; view stays server-rendered).
- New accent/theme options; any non-size preference.
- Fine-grained per-element sizing beyond the six controls above.

## Test approach

- **Route-render tests** (repo's existing style): the gear + popover render with
  all six S/M/L controls; the view toggle stays on the index and is *not* in the
  popover; defaults present; only the allow-listed values in markup. `pytest`
  unit suite stays green.
- **Browser live-verify** (Radicale, the real proof for CSS + inline JS):
  each control resizes the right region and nothing else; no pre-paint flash;
  popover light-dismiss (outside-click + Escape); detail-avatar choice persists
  under the reused key; view toggle still switches server-side.

## Notes

Extends the established theme/accent localStorage + pre-paint convention — no
ADR. S/M/L scale factors are tuned in the browser during live-verify and are a
**clearly-visible spread** (text ≈ .8em / 1 / 1.35em; card/list avatars ≈ .65× /
1 / 1.6×) so each step reads as distinct, not a subtle nudge. `md` is always the
untouched default (no attribute). Detail avatar reuses the existing, already-wide
sm 3rem / md 4rem / lg 8rem.

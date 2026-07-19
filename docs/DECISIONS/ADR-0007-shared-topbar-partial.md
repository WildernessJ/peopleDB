---
status: Accepted
date: 2026-07-17
deciders: WildernessJ
phase: post-v1 (UI)
---

# ADR-0007: One shared top-bar partial; theme/accent/settings controls move in-flow

## Context

Issue #26 asked to reorganize the top bar. Two structural facts made this more than a CSS
tweak. First, every authenticated page (index, detail, form, group, birthdays, merge) hand-rolled
its own `<header>` — six near-identical copies, drifting (form/merge had no Sign out). Second, the
theme toggle, accent picker, and settings gear were `position: fixed` in `base.html`, floating over
*every* page (including login) top-right, with the header reserving `padding-right: 9rem` and the
top-bar S/M/L size control shipping a set of per-icon `right`/`top` offset rules purely to stop the
fixed icons overlapping as they scaled. The requested control order (palette → theme → gear → **Sign
out at the far right**) cannot be produced while the cluster is fixed and Sign out lives in the
header flow — delivering that order forces the controls into the header.

## Decision

Introduce a single `_topbar.html` partial holding the whole bar — brand (icon + wordmark), an
optional centered search/quick-add slot (rendered only when the includer sets `show_search`, i.e.
index), and the controls group in order accent → theme → settings → Sign out. All six authenticated
templates `{% include "_topbar.html" %}` instead of hand-rolling a header. The three controls move
**out of `base.html`'s fixed position into the partial's in-flow flex group**; the bar is
`position: sticky; top: 0` so they stay reachable on scroll. The driving JS stays in `base.html`
(it binds by id/class, which still resolve). `login.html` deliberately does **not** include the
partial: pre-auth it shows no Sign out and no controls (the pre-paint script still applies the saved
theme, so there is no flash — the user just can't toggle from the login screen). The `padding-right`
hack and every `data-size-topbar` `right`/`top` offset rule are deleted; the flex layout reflows on
its own.

## Alternatives considered

- **A — keep controls fixed, reorder only:** smallest diff, but cannot place Sign out to the right of
  a fixed gear, and preserves the padding-right + offset hacks. Rejected — doesn't meet the ask.
- **B — in-flow, but edit all six headers individually (no partial):** same visual result, but keeps
  six copies to maintain — the drift that already produced the missing-Sign-out inconsistency.
  Rejected.
- **C — centralize the header directly in `base.html` (no partial):** DRY, but `base.html` wraps
  login too, so the header (Sign out + search) would leak onto the login page; guarding it re-adds
  the conditional complexity the partial avoids. Rejected.

## Consequences

- **Positive:** one header definition instead of six; the fixed-position hacks and offset CSS are
  gone; controls scroll with a sticky bar; form/merge gain a Sign out for free (consistency); the
  icon doubles as favicon.
- **Negative / trade-offs:** login loses its in-page theme/accent/settings controls (saved theme
  still applies). The controls now scroll with the (sticky) bar rather than being viewport-pinned.
  The provided icon has a teal background, so it reads as an app-icon tile, not a transparent glyph,
  and won't invert in dark mode. `show_search` is a soft coupling — the partial knows about the
  index-only search block.

## Confirmation

`tests/test_accent_contrast.py::test_accent_keys_in_sync` reads swatch markup from `_topbar.html`
(CSS presets + both ACCENTS allowlists from `base.html`) and enforces they agree.
`tests/test_theme.py::test_login_page_has_pre_paint_theme_script_but_no_toggle` asserts login carries
the pre-paint script but *not* the toggle, and that the toggle exists in `_topbar.html`.
`tests/test_display_settings.py` asserts `#settings-panel` + the popover render on both an index and a
detail page (i.e. via the shared partial). Browser live-verify: controls order, popover anchoring,
and the narrow-viewport two-row collapse.

## Links

- Issue: #26
- Related ADRs: ADR-0001 (server-rendered Jinja + HTMX, inline first-party JS)

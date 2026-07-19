# Natural-language quick-entry parser

## Problem
Adding a contact today means filling the structured form field by field. The v1 design
(`specs/2026-07-13-peopledb-v1-design.md`) reserved a "command-bar slot" for a natural-language
quick-entry parser but left it out of scope. Typing one line — a name, an email, a phone — and
getting a ready-to-review contact is faster for the common case.

## Intended behavior
1. **Quick-entry input on the index page.** A bare HTML `GET` form (input `name=q`), separate
   from the existing search box so the two actions don't collide. Enter submits to
   `GET /contacts/new?q=<text>`.
2. **Parse `q` into the existing add form, pre-filled.** The route parses the text into
   `ContactFields` and renders the *existing* `form.html` with those values. Nothing is written
   to CardDAV until the user reviews and hits **Save** (reuses `POST /contacts` and its
   validation/normalization unchanged). Empty/absent `q` → today's blank form, unchanged.
3. **Rule-based, minimal-sigil grammar.** A pure function `parse_quick_entry(text) -> ContactFields`.
   Each match is removed from the working string before the next step:
   1. **Email** — `\S+@\S+\.\S+`; an immediately trailing `(label)` sets that email's label.
   2. **URL** — only `http://`, `https://`, or `www.` (so it can't grab an email domain or an org word).
   3. **Phone** — a run of `+`/digits/spaces/dashes/parens (no `.`, so decimals/IPs/versions
      aren't misread) with ≥7 digits; trailing `(label)` sets its label. A run spanning two
      `+`-prefixed numbers is split on the interior `+` (a trailing label goes to the last).
   4. **`bday <date>`** — best-effort normalize to `YYYY-MM-DD` (with year) or `--MM-DD` (without),
      accepting only **unambiguous** forms: ISO (`2026-03-03`) and named-month (`3 Mar` / `Mar 3`).
      Bare numeric slash dates (`3/4`) are D/M-vs-M/D ambiguous and feed the birthday ICS feed, so
      they are **not** parsed — left for the user to type in the reviewed form. Emitted as freeform text.
   5. **`org <name>`** — consumes to end-of-string or the next recognized sigil (org is multi-word).
   6. **Leading words** (before the first match/marker) → name: first token `given`, remainder `family`.
   7. **Any leftover text → Note**, verbatim. Nothing is silently dropped.
4. **Forgiving by design.** Because the user reviews every field before Save, a misplaced token
   landing in Note or the name is acceptable — it is corrected in the form.

## Out of scope
- **`#group` sigil / group assignment** — the create form has no group field, and group
  membership is a separate member-list write path. Deferred as its own change.
- **Inline addresses** — multi-component and unreliable to shape-detect; the form already has a
  full address UI. Not parsed from the quick-entry line.
- **Related names.** Not parsed.
- **LLM / external parsing.** Rule-based only; no network dependency, no key, stays local-first.
- **Create-immediately or inline-preview UX.** Pre-fill-the-form is the chosen flow.

## Test approach
- **Parser unit tests** (`tests/test_quickparse.py`, table-driven — the `/tdd` seam): name-only;
  name + email; email/phone/url shape detection; `(label)` attachment; `bday` in several date
  forms (with and without year); multi-word `org` consuming to end / next sigil; leftover text →
  Note; ordering (email/url removed before phone so digits aren't mis-grabbed); empty string.
- **Route test** (`tests/test_web_live.py` or equivalent): `GET /contacts/new?q=...` renders the
  form with parsed values in the right inputs; empty `q` renders the unchanged blank form.
- **Live-verify:** type a line in the browser against a local CardDAV server, confirm the form
  pre-fills correctly and Save writes a valid card.

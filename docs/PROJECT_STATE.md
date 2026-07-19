# Project State — peopleDB

> **One-page living snapshot.** The committed "current truth" of where the build is. Read this
> first when resuming work. Keep it to roughly one screen — push detail into
> [RUN_LOG.md](RUN_LOG.md), rationale into [DECISIONS/](DECISIONS/), cross-session gotchas into
> [PITFALLS.md](PITFALLS.md). Update it at the end of every working session.
>
> This file does **not** restate architecture, invariants, or scope — those live in `CLAUDE.md`.
> It tracks *progress and live decisions only*.
>
> **Memory-spine protocol.** At session **start**: read this file + the latest [RUN_LOG.md](RUN_LOG.md)
> entry (a `.claude/` SessionStart hook auto-injects the top of this file). At session **end**: run
> `/checkpoint` — doc-drift sweep → add an ADR to [DECISIONS/](DECISIONS/) if a real decision was made →
> update this file → prepend a RUN_LOG entry → record any new gotcha in [PITFALLS.md](PITFALLS.md).
>
> **This spine is destined to be PUBLIC.** `WildernessJ/peopleDB` is private today but intended to go
> public once it's more ready, and git history is permanent — write every entry as public documentation
> from the start: no secrets, credentials, private paths, internal hostnames/LAN IPs, personal accounts,
> or exploitable detail on an unmitigated weakness. Refer to deploys generically ("the LAN deploy"). A
> leaked secret must be rotated, not just edited out.

_Last updated: 2026-07-18 (**#33** shipped via autonomous `/flow --auto` — the first `--auto` run on this
repo: deterministic `ORDER BY href LIMIT 1` tiebreak in `store.get_by_uid` (`8e63eaa`, merged `31bbc9a`).
The query had no `ORDER BY`, so a duplicate `(user, uid)` collision returned an arbitrary row; scope held
to the deterministic tiebreak (issue option 1), UNIQUE-invariant enforcement left out. Machine-verified
(258 unit + 44 live green — command-mode verify, no browser surface). Cold `/session-audit` **REFUTED the
test's regression-guard value**: on the current schema the `(user, href)` PK autoindex already scans in
href order, so the fix is belt-and-suspenders and a red-without-fix test isn't constructible via the
public API — the audit also caught the test comment asserting a false causal claim (fixed to scope
honestly what it guards). `/code-review` no-blocker. **#33 closed manually** (the `fix(#33)`
conventional-commit form does not trip GitHub auto-close). Post-run advisory **#34** (`flow-review`) notes
the pre-approved `is_group`-awareness residual. No ADR (bugfix). `/pb` recreated the LAN container on
`:latest` post-merge. **Open enhancements: none (#34 is a non-blocking advisory).** Prior entry: —
**#31** (`1fdb168`): `GET /contacts/{uid}/merge/search` filtered groups out of the candidate list but
never checked whether the *primary* `uid` was itself a group, returning 200 + a populated list for a
group primary instead of rejecting — added a `get_by_uid` lookup that returns an empty candidate partial
when the primary `is_group` (defense-in-depth; the real merge action is already guarded, picker hidden
on group pages since #30). Failing repro test first (`test_merge_search_guard.py`). **Refactor** (same
commit): extracted the detail-page field-box guard into a `Contact.has_display_fields` property,
removing the duplicated seven-field disjunction (the #32 audit residual). `/code-review` (high)
no-blocker, `security` (Opus/high) **Clean**, cold `/session-audit` **SURVIVES**, browser live-verified
(group primary → no candidates, contact primary → offered; bare group → no box, contact → box).
**Filed #33** (the `get_by_uid` uid-uniqueness gap the audit surfaced). No ADR (bugfix + refactor).
**Deploy mishap caught + fixed:** the first commit (`1fdb168`) captured only the staged test — the three
source edits were unstaged (the audit's main-file swap reset the index), so `main` briefly had the
regression test without its fix; `15b1ed8` restored the source changes (suite green on `main`). All
pushed, **#31 auto-closed**, `/pb` recreated the LAN container on `:latest`. New PITFALLS entry on the
index-clobber. **Follow-up (done):** the index-clobber trap now has a systemic guard — a `tree-check`
pre-merge step built and shipped in the `/flow` tooling (a separate private tooling repo) blocks a
merge when the working tree has uncommitted tracked changes or HEAD drifted off the gated commit; the
PITFALLS entry here is annotated with that mitigation. **Open enhancements: #33 only.**)_

---

## Current position

- **Stage:** Working household CardDAV web client. v1 shipped 2026-07-13. Opening backlog, the
  #22/#23/#24 quick-entry line, #25 index widening, #27 field selection, #29 a11y labels,
  **#28 merge duplicate contacts**, #30 hide merge picker on group pages, **#26 reorganize the top
  bar**, a **card-view long-value overflow fix**, **#32 empty field box**, **#31 merge/search
  group-primary guard**, and **#33 `get_by_uid` deterministic tiebreak** all cleared. **No open
  enhancements** (#34 is a non-blocking `flow-review` advisory). Deployed and running on the LAN —
  **current through #33** (`/pb` recreated the container on `:latest` after the #33 merge).
- **Deployment:** CI publishes images to `ghcr.io/wildernessj/peopledb` on every push to `main`
  (test-gated). The LAN deploy now runs from the Unraid Docker-tab template (`unraid/peopledb.xml`)
  pulling `:latest`, off the old hand-built container (behind a reverse proxy). See ADR-0005; deploy
  gotchas in PITFALLS.
- **Active gate:** none. Per Coding Workflow v2 — one `/code-review` on the full diff before merge.
- **Branch:** `main` is the working line; new work starts from `main`.
- **Verification:** **258 unit tests green + 44 live tests** (`uv run pytest`; `-m live` boots a
  throwaway local CardDAV server; +1 for #33's `test_get_by_uid_deterministic_on_duplicate_uid`, a
  contract test — see the #33 RUN_LOG entry / #34 for why it can't be a red-without-fix guard on this
  schema). **#31 browser-verified**
  against a seeded store + real app: a group primary's `/merge/search` returns "No contacts found." (no
  `?with=` links); a contact primary still lists other non-group contacts (self + group excluded); bare
  group detail shows no field box, a contact-with-email shows the box. `/code-review` (high) no-blocker,
  `security` (Opus/high) **Clean** (no auth/IDOR/concurrency/info-leak regression), cold
  `/session-audit` **SURVIVES** (auditor independently reproduced the guard test red on `main` / green
  on HEAD, confirmed the refactor behavior-preserving term-for-term). Prior sessions
  (#32/#26/#30/#28/#29/#27/#25) similarly shipped via live `/flow` and browser-verified; #28's
  destructive path had a `security` pass (delete-last ordering, per-user lock never across `await`,
  auth/IDOR).
- **Bugs/enhancements** are tracked as **GitHub issues** (`WildernessJ/peopleDB`), not in these docs.

## Recently shipped

- **#31 merge/search group-primary guard + field-box refactor** (2026-07-18, live `/flow`) — two
  bundled changes. **#31:** `GET /contacts/{uid}/merge/search` excluded groups from the *candidate*
  list but never validated the *primary* `uid` in the path, so `…/{group_uid}/merge/search` returned
  200 + a populated list rather than rejecting. Fix = look up the primary via `store.get_by_uid` and
  return an empty candidate partial when it `is_group` (`app.py`); defense-in-depth — the real merge is
  already 400-guarded and the picker is hidden on group pages (#30). Failing repro test first
  (`test_merge_search_guard.py`). **Refactor:** extracted the detail-page field-box guard into a
  `Contact.has_display_fields` property, removing the duplicated seven-field disjunction (the #32
  residual below — now resolved). Behavior-preserving (property returns the exact old `{% if %}` terms).
  `security` (Opus/high) **Clean**; cold `/session-audit` **SURVIVES**. Audit surfaced a pre-existing
  low-severity gap → **filed #33** (`get_by_uid` has no uid-uniqueness guarantee). Closes #31.
- **#32 empty field box on fieldless detail pages** (2026-07-17) — a bare group (no
  phones/emails/urls/addresses/related/bday/note) rendered an empty bordered `<dl class="card">` box
  between the name and the action buttons. Fix = a Jinja guard so the `<dl>` renders only when ≥1 of
  those seven fields is present (`detail.html`); a fieldless contact is covered too. The guard chose
  "any populated field" over an `is_group` check, so a group that legitimately carries a field still
  shows its box. Template-only — server unchanged. Regression test (`test_empty_field_box.py`): bare
  group omits the box, a contact with a field keeps it (verified red on `main`, green on the fix).
  Shipped via live `/flow` (repro → guard → `/code-review` no-blocker → browser live-verify → cold
  `/session-audit` SURVIVES → merge). **Residual (RESOLVED 2026-07-18):** the guard duplicated the
  field list implicit in the `<dl>` body — refactored into `Contact.has_display_fields` in the #31
  session, so the guard now has a single source of truth (though it must still stay in sync with the
  template loop body). Closes #32.
- **Card-view long-value overflow fix** (2026-07-17) — in card view, a field value that is a single
  unbreakable token (a long email/url, or a no-space display name) rendered as one line and spilled
  past the card border, because `.contact-card .org/.detail` and `.contact-card a` had no word-break
  rule. Fix = `overflow-wrap: anywhere` on those selectors (`base.html`) — breaks only when there is no
  normal opportunity, and lets the grid track shrink to the cell. Live-verified at the real 170px card
  width (pre-fix content 187px overflowed by 17px; fixed wraps to 170px), holding at large card-text
  size and in light theme. 253 → still green. No issue filed (found-and-fixed in session, per the
  user); deployed to the LAN via `/pb`.
- **#26 reorganize the top bar** (2026-07-17) — shipped in two parts on one branch. Part 1: relocated
  `New contact` + `Birthdays` out of the index `<header>` into the view-toggle action row (beside
  List/Cards, pushed right with `margin-left:auto`). Part 2 (the redesign): a new shared
  `_topbar.html` partial included by all six authenticated pages (index/detail/form/group/birthdays/
  merge), replacing six drifting hand-rolled headers; a **brand icon** left of the wordmark
  (`src/peopledb/static/peopledb-icon.png`, 128px, also wired as the favicon); and the
  theme/accent/settings controls **moved out of `base.html`'s `position:fixed` blocks into the bar's
  in-flow flex group**, ordered palette → theme → gear → Sign out. The bar is `position:sticky`; the
  old `padding-right:9rem` hack and every `data-size-topbar` `right`/`top` offset rule are deleted;
  a `@media (max-width:720px)` rule collapses the bar to two rows. `login.html` deliberately omits the
  partial (no pre-auth controls; the pre-paint script still applies the saved theme). The driving JS
  stays in `base.html` (binds by id/class, still resolves; login no-ops via `if (!el) return`). Two
  tests updated (swatches now read from `_topbar.html`; login asserts no toggle) + a new
  search-render guard. **ADR-0007.** Shipped via live `/flow` (brainstorm → design approval → implement
  → `/code-review` no-blocker → cold `/session-audit` SURVIVES, 2 concerns fixed → browser live-verify
  → merge). Closes #26.
- **#30 hide merge picker on group pages** (2026-07-17) — the group detail page (`/contacts/{group_uid}`,
  rendered by `detail.html`) showed the same `Merge with…` htmx picker as a contact page, but merging
  *from* a group is rejected downstream (`app.py` `is_group` → 400 "Groups can't be merged"), so the
  control was a dead end. Fix = a 4-line Jinja guard `{% if not contact.is_group %}` around the
  merge-picker `<section>`; contact pages unchanged. Template-only, as #30 scoped it — the server guard
  already blocks the actual merge. New render test (picker present on contact, absent on group).
  Shipped via live `/flow` (bugfix → repro test → guard → `/code-review` no-blocker → browser
  live-verify → cold `/session-audit` SURVIVES → merge). Closes #30; filed **#31** (`/merge/search`
  group-uid validation, defense-in-depth) and **#32** (empty group field box, cosmetic).
- **#28 merge duplicate contacts** (2026-07-16) — the largest enhancement. Manual **pick-two** merge
  (no detection heuristics): a `Merge with…` htmx contact-search picker on the detail page (reuses the
  FTS `store.search`, excludes self + groups) → a review screen (keeper radio + **per-field `a`/`b`
  radios** + multi-value union checkboxes) → a non-transactional **delete-last** write sequence — keeper
  PUT (etag-conflict → abort, zero writes) → group memberships moved source→keeper → source DELETE
  **last**; partial failures warn via `?merge_warn=`, never roll back (ADR-0006). All cache mutation
  under the per-user lock, never across an `await` (ADR-0004). Pure logic in new `merge.py`
  (union/dedup, self-relation drop, group-member rewrite); the **single-valued field choice is decoupled
  from keeper identity** — keeper only decides which card/UID/unknown-props survive, never which value
  wins (conflating them inverted every field on a keeper-flip; see PITFALLS). Spec:
  `specs/2026-07-16-merge-duplicate-contacts.md`; ADR-0006. Shipped via live `/flow` (spec+ADR → executor
  TDD → `/code-review` (1 BLOCKER + 1 LOW, fixed) → `security` → live-verify + browser-verify →
  `/session-audit` (4 findings, all fixed) → merge). Closes #28; filed #30 (merge picker on group pages).
- **#29 screen-reader labels for index field values** (2026-07-16) — index list/card field values
  were bare `<span>`s (unlike the detail page's `<dl>`/`<dt>`), so a screen reader read an
  undifferentiated run. Now each value carries a visually-hidden `<span class="sr-only">Label: </span>`
  prefix **inside** its `.field-*` span (Org/Phone/Email/Birthday/URL/Address), in both views; a new
  `.sr-only` clip-pattern utility class hides it visually. Placed inside the `.field-*` span so #27's
  `display:none` field-hide drops the label with its value (no orphan labels — this correctness
  **depends** on `display:none` specifically, not `visibility`/`opacity`; see PITFALLS). Values stay
  Jinja auto-escaped; labels are static. Vocabulary aligned to the app's existing terms (URL/Org).
  No server change. The issue was the spec (small); no ADR (extends the field-rendering convention).
  Shipped via live `/flow` (executor TDD → `/code-review` no-blocker → browser a11y verify →
  `/session-audit` → merge → push/CI). Closes #29.
- **#27 choose which fields show in list/card views** (2026-07-16) — the index list + card views had
  hardcoded fields (list = name+org; card = name+org+phone+email). Now user-selectable via two
  checkbox groups in the ⚙ settings popover: **org / phone / email / birthday / url / address**,
  **independent per view**, name always shown. Same client-side idiom as display settings — two
  localStorage keys (`peopledb-list-fields` / `-card-fields`), stamped as root `data-list-fields` /
  `data-card-fields` before first paint, with CSS **rendering all fields then hiding unselected** ones
  (`~=` whole-word reveal). Defaults preserve prior behavior; an explicit empty selection is durable
  (name-only). No server change. Spec: `specs/2026-07-16-list-card-field-selection.md`; no ADR
  (extends the display-settings convention). Companion to #25 — gives the widened list content to fill
  it. Shipped via live `/flow` (spec → executor → `/code-review` → browser verify → `/session-audit` →
  merge → `/pb`). Audit finding #4 (index field values lack screen-reader labels) filed as **#29**.
- **#25 widen contacts index** (2026-07-16) — the index list + card grid were boxed to the global
  720px `main`, leaving large empty gutters on wide screens. A scoped `main.contact-index { max-width:
  1400px }` class widens **only** the index (card grid reflows ~7 columns); detail, edit form, groups,
  and birthdays keep the 720px default (readability). List view is left wide-but-sparse deliberately —
  #27 (field selection) will give it more content to fill the width. No JS, no server change. Shipped
  direct-to-`main` (3-line diff, cold-reviewed by `/session-audit` in lieu of `/code-review`) and
  deployed to the LAN via `/pb`.
- **Display settings popover** (2026-07-16) — a ⚙ gear joins the fixed top-right control cluster
  (deliberately larger than the theme/accent icons) and opens a popover with **six independent S/M/L
  size controls**: top bar (header text + icons), list view (text + avatar together), card text, card
  avatar, detail avatar, detail text. Each persists in localStorage and applies via a root
  `data-size-*` attribute stamped **before first paint** (same no-flash pattern as theme/accent);
  `md` writes no attribute so untouched installs render unchanged. Detail avatar reuses the pre-existing
  `peopledb-avatar-size` key (the old inline detail-page toggle was removed). All text within a scaled
  region scales — labels included (`dl.card dt` → `em`). Detail text is scoped to the detail page's own
  `<main class="contact-detail">` so it can't leak into other pages' `<main>` or compound with the
  em-based list/card controls. Scale factors are a clearly-visible spread (text ≈ .8/1/1.35em). The
  list/card **view toggle stays on the index** (server `POST /view`), not in the popover. Spec:
  `specs/2026-07-15-display-settings.md`; no ADR (extends the theme/accent convention).
- **Deploy pipeline: ghcr publish + Unraid template** (2026-07-15) — a GitHub Actions workflow
  (`.github/workflows/docker-publish.yml`) gates on the unit suite then builds a `linux/amd64` image
  and pushes to `ghcr.io/wildernessj/peopledb`: `:latest` (main), `:vX.Y.Z` (`v*` tags), `:sha-…`
  (every build). Kills the Apple-Silicon→amd64 cross-build (GH runners are amd64). Added an Unraid
  Docker-tab template (`unraid/peopledb.xml`, private-image pull via a one-time PAT login) and rewrote
  the README Docker section. First publish ran green (215-test gate + push). The Unraid cutover was
  then done off the hand-run container (now behind a reverse proxy), surfacing three deploy gotchas —
  uid-999 appdata ownership, host `:8000` collision, reverse-proxy Docker network — recorded in
  PITFALLS + README. Package visibility (should be **private** until the repo flips public) is a manual
  check in the ghcr Packages view. Rationale in ADR-0005.
- **#24 `#group` quick-entry sigil + create-form group field** (2026-07-15) — the create form gained a
  **create-only** Groups checkbox list (existing groups only); a `#name` sigil in quick-entry pre-checks
  the matching group, an unknown name shows a "not assigned" note and is **never auto-created**. On Save,
  `POST /contacts` creates the contact then writes membership to each checked group's
  `X-ADDRESSBOOKSERVER-MEMBER` list — the existing `set_group` / per-user-lock write path, one PUT per
  group. Group names never touch the contact's own vCard. **Two failures the harness caught pre-merge:** a
  stale/non-group `group_uid` no longer 404s-after-create (resolves via `get_by_uid` + `is_group`); and a
  non-409 group-PUT failure no longer masks the created contact — both surface via `?group_warn=`. Multi-word
  group names aren't reachable by the single-token sigil (checkbox still selects them) — accepted. Rationale
  in `specs/2026-07-15-group-quick-entry-sigil.md`.
- **#23 split domestic phone pairs** (2026-07-15) — the quick-entry parser now splits a
  whitespace-joined domestic phone run (`555-123-4567 555-987-6543`) into two phone entries via a
  greedy digit-count rule: within each `+`-delimited piece, accumulate space-separated groups and
  close a number at ≥10 digits, so a single grouped number (`555 123 4567`) stays whole. A trailing
  <7-digit remainder folds back rather than emitting a fragment. No real E.164 number (≤15 digits)
  can fragment — a spurious split needs ≥17 digits (audit-proven). **Accepted residual:** two
  whitespace-joined *7-digit locals* still merge (ambiguous without a delimiter; reviewed-before-Save
  is the net) — noted on the now-closed #23.
- **#22 NL quick-entry parser** (2026-07-15) — quick-add bar on the index page parses a one-line
  contact into the existing add form, pre-filled for review before Save (`GET /contacts/new?q=`,
  reusing the `POST /contacts` write path). Pure `parse_quick_entry(text) -> ContactFields` in
  `quickparse.py`: rule-based, minimal sigils, forgiving-by-design (the reviewed form is the safety
  net). Shape-detects email/phone/url; `bday`/`org` keyword sigils. Deliberately **no LLM** (stays
  local-first / dependency-free) and only **unambiguous** dates parse (`YYYY-MM-DD`, named-month) —
  bare `D/M` is left for the form since it feeds the ICS feed. `#group`/addresses/related deferred.
  Rationale in `specs/2026-07-15-nl-quick-entry.md`.
- **#15 FTS search → address + URL** (2026-07-14) — added `address`/`url` columns to `contacts_fts`;
  one shared `_fts_row` projection feeds upsert + rebuild; `PRAGMA user_version`-gated one-time
  drop+rebuild for existing caches (FTS5 has no ALTER ADD COLUMN — see PITFALLS).
- **#18 crop resize hit-zone** (2026-07-14) — hit-zone now matches the visible handle on a mouse;
  generous outward margin kept only on `(pointer: coarse)`.
- **#16 detail-page avatar S/M/L toggle** (2026-07-14) — remembered via localStorage
  (`peopledb-avatar-size`, default `md`), matching the theme/accent idiom; `_avatar.html` gained an
  opt-in auto-escaped `id` param (default off → other call sites unchanged).
- **#14 avatar-size photo preview + #17 client-side square crop** (2026-07-14) — canvas crop swapped
  into the file input via DataTransfer; server pipeline untouched (still validates + re-encodes).
- **#12 accent contrast fix + #13 user-selectable accent picker** (13 AA-validated presets).
- **Dockerization** — `Dockerfile` + `.dockerignore` + README "Running with Docker"; runs non-root.
- **v1 + overnight issue sweep** (#1–#11) — photos, dark mode, card view, address editing, session
  idle timeout, thread-local SQLite + WAL, event-loop offload + per-user write serialization,
  sync-token recovery, relationship disambiguation.

## Next actions

- **Everything shipped is deployed.** `main` is in sync with origin; CI published `:latest`; **#32
  auto-closed** on push (the merge carried `Closes #32`); `/pb` on 2026-07-17 recreated the LAN
  container on `:latest`, current through #32. #26/#30 were closed manually earlier (their merge commits
  omitted `Closes` — see PITFALLS). Nothing awaiting push or redeploy.
- **Open enhancement — start from the filed issue:**
  - **#31 `/merge/search` group-uid validation** *(defense-in-depth)* — the route excludes groups from
    the *candidate* list but doesn't reject a group *primary* uid, so `GET /contacts/{group_uid}/merge/search`
    returns 200 with candidates. Reachable only by hand-crafted URL (no UI trigger since #30); the actual
    merge still 400s. Mirror the review-screen guard on the search route.
  - (ghcr package confirmed **private** 2026-07-15; revisit at the public-visibility flip — see ADR-0005.)
- **Accepted residual from #32 (audit-noted, not filed):** `detail.html`'s box-guard duplicates the
  seven-field list implicit in the `<dl>` body; a future field row added inside the box without updating
  the guard would wrongly suppress the box for a contact that has only that field.
- **Deferred merge residuals (accepted, on the closed #28 / spec):** inbound `RELATED` to a merged-away
  contact is left dangling (degrades gracefully, not cleaned); union dedup is exact-string only (no
  phone/email normalization — both kept, uncheck one on the review screen); no duplicate *detection*
  (manual pick-two only — a later cycle can feed candidate pairs into the same review flow).
- **Noted from the #29 audit (not filed):** the six field spans + their labels are duplicated verbatim
  across the card and list blocks in `_contacts.html` (12 sr-only literals) — the #27 FIELDS
  duplication, now doubled. A `{% macro %}` would collapse both blocks; worth the next `_contacts.html`
  touch, not urgent. Also: an axe/AT scan would fully confirm announcement (mechanism verified in
  Chrome via the DOM/a11y tree, not a real screen reader).
- Quick-entry residual (not filed): two whitespace-joined *7-digit local* numbers still merge — the
  ≥10-digit greedy close can't disambiguate them without a delimiter (see #23's closing note).
- Not-yet-verified on real hardware (opportunistic): crop **coarse-pointer** branch (couldn't emulate
  a touch pointer in the automation browser — the generous margin is the original behavior, verified by
  inspection only), plus the standing touch-drag / EXIF / 12MP residue below.

## Open questions / accepted residue

- **Untested (accepted, opportunistic):** real touch-device drag, EXIF-rotated phone JPEG through the
  crop path, and large-photo (12MP) canvas performance — all need a phone against the LAN deploy.
- **#15 boot rebuild on a large book (accepted):** the one-time `contacts_fts` rebuild runs
  synchronously at app construction; unmeasured on a large address book. Gated (runs once), re-parses
  `contacts.raw` only. Revisit only if a slow first boot after upgrade is observed.
- **Revisit: 2-tier spine layout?** (raised 2026-07-14 during the vikunja spine rollout.) vikunja adopted
  a two-tier split — progress files (`PROJECT_STATE`/`RUN_LOG`/`PITFALLS`) kept **local/gitignored**, only
  ADRs committed — because it's a *public fork of go-vikunja* and personal working notes shouldn't land in
  someone else's project. peopleDB is different: it's **your own app** (private→public), so its committed,
  public spine is defensible as the project's real history. Open question: once peopleDB actually goes
  public, do the progress files stay committed, or move local like vikunja's? Decide before the visibility flip.

## References

- Architecture / invariants / scope: [`../CLAUDE.md`](../CLAUDE.md)
- Decisions: [DECISIONS/](DECISIONS/) — ADR-0001 (stack), 0002 (CardDAV/sync), 0003 (auth), 0004 (cache concurrency), 0005 (ghcr/Unraid deploy), 0006 (merge delete-last/no-rollback)
- Gotchas: [PITFALLS.md](PITFALLS.md)
- Session history: [RUN_LOG.md](RUN_LOG.md)
- Specs: `specs/`

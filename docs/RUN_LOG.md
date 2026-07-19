# Run Log — peopleDB

> **Append-only session history, newest first.** One entry per working session: Goal · Did ·
> Verified · Open/blockers · Memory artifacts touched. Point-in-time records — never rewrite past
> entries. Rationale for decisions lives in [DECISIONS/](DECISIONS/); current state in
> [PROJECT_STATE.md](PROJECT_STATE.md); gotchas in [PITFALLS.md](PITFALLS.md).
>
> Entries 2026-07-13 → 2026-07-14 were backfilled on 2026-07-14 from the pre-spine narrative
> handoffs (seq 1–4) when the memory spine was adopted; they are condensed and sanitized for a
> public repo. Those raw handoffs were removed ahead of the public release (they carried
> home-network deploy detail); this log is the canonical history from here on.

---

## 2026-07-18 — #33 get_by_uid deterministic tiebreak via `/flow --auto` (first autonomous run)

- **Goal:** ship #33 — `store.get_by_uid` queried `WHERE user=? AND uid=?` with no `ORDER BY`, so a
  duplicate `(user, uid)` cache collision returned an arbitrary row. Defense-in-depth (the #31
  `merge_search` guard and `_get_or_404` both trust this lookup). First `/flow --auto` run on the repo.
- **Did:** approved scope = deterministic tiebreak only (issue option 1; UNIQUE-invariant enforcement
  scoped out). `executor` (TDD) added `ORDER BY href LIMIT 1` (`8e63eaa`) + a contract test. Autonomous
  self-verify: classifier → `live`, but no browser-drivable surface (store-internal), so verified via the
  `pytest -m live` command per the ceiling-is-not-a-fixed-route rule. Merged `31bbc9a`, pushed, **#33
  closed manually** (the `fix(#33)` conventional-commit form does **not** trip GitHub auto-close), advisory
  **#34** (`flow-review`) opened for the residual.
- **Verified:** `uv run pytest -q` → **258 passed, 44 deselected**; `uv run pytest -q -m live` → **44
  passed**. `/code-review` no-blocker (all 9 `get_by_uid` call sites take `(user, uid)`→`StoredContact|None`,
  return shape unchanged, query stays parameterized). Cold `/session-audit` **REFUTED the test's
  regression-guard value**: proved by monkeypatching the pre-fix method body back in — the test still
  passed, because SQLite satisfies the query via the `(user, href)` PK autoindex (`EXPLAIN QUERY PLAN`),
  whose B-tree is walked in href order for a fixed user, so `fetchone()` returns the smallest href with or
  without `ORDER BY`. The `ORDER BY` fix is belt-and-suspenders (future-proofs a schema/index change); a
  red-without-fix test isn't constructible through the public API on this schema. Audit also caught the
  test comment asserting a false causal claim ("insertion/rowid order would surface the larger href
  first") — rewrote it to scope honestly (pins tiebreak *direction*, catches an accidental `DESC`).
- **Open/blockers:** none. #34 is a non-blocking advisory (the href tiebreak is deterministic but not
  `is_group`-aware — pre-approved out of scope by the issue; the #31 guard re-checks `is_group` anyway).
  `/pb` recreated the LAN container on `:latest` post-merge (`docker-publish` green for `af87c72`;
  Watchtower `Found new image` → recreated, `updated=1 failed=0`).
- **Memory:** PROJECT_STATE header/Current-position/Verification refreshed (257→258 unit); new PITFALLS
  entry on the PK-index masking a missing `ORDER BY`; this RUN_LOG entry. No ADR (bugfix).

---

## 2026-07-18 — follow-up: systemic guard for the truncated-commit trap (tooling)

- **Goal:** remediate the index-clobber trap this session hit during #31 (a truncated commit briefly
  put the #31 test on `main` without its fix) at the source, not just document it.
- **Did:** built a `tree-check` pre-merge guard in the `/flow` tooling (a separate private
  repo, not peopleDB): a pure `tree_integrity()` predicate + a git-aware CLI subcommand that blocks the
  merge if the working tree has any uncommitted tracked change or HEAD drifted off the gated commit —
  closing the gap where the gate-only guard passed a commit that didn't contain the reviewed diff.
  Repro-test-first, `/code-review` clean (coverage gaps closed → 33 tests), landed on that repo's `main`
  and pushed. Annotated this repo's PITFALLS index-clobber entry with the mitigation.
- **Verified:** peopleDB itself unchanged this turn (`git status` clean, in sync with origin at
  `2f581e8`); the tooling change verified in its own repo (33 tests green, dirty-tree/HEAD-drift/
  zero-commit paths all block by execution).
- **Open/blockers:** none for peopleDB. Open enhancement remains **#33**.
- **Memory:** PITFALLS mitigation line added to the truncated-commit entry; this RUN_LOG note. No spine
  code/state change in peopleDB (the remediation lives in the tooling repo).

---

## 2026-07-18 — #31 merge/search group-primary guard + field-box refactor via live `/flow`

- **Goal:** ship #31 (defense-in-depth: `merge_search` should reject a group *primary*), bundled — at
  the user's direction — with the #32 audit residual (dedup the detail-page field-box guard).
- **#31 (`1fdb168`):** `GET /contacts/{uid}/merge/search` filtered groups out of the *candidate* list
  but never validated the primary `uid`, so `…/{group_uid}/merge/search` returned 200 + a populated
  list. Fix = `store.get_by_uid(user, uid)` → return an empty candidate partial when the primary
  `is_group` (`app.py`). Chose an **empty result** over a 400: it's a search-as-you-type partial feeding
  a picker already hidden on group pages (#30), and the real merge action stays 400-guarded
  (`_merge_validation_error`). Failing repro test first (`test_merge_search_guard.py`, 2 cases: group
  primary → no candidates; contact primary → still offered, self+group excluded).
- **Refactor (same commit):** extracted the field-box `{% if %}` disjunction into a
  `Contact.has_display_fields` property (`vcard.py`) and swapped the template guard (`detail.html`).
  Behavior-preserving — property returns the exact seven old terms.
- **Verified:** `uv run pytest -q` → **257 passed, 44 deselected** (was 255); live suite **44 passed**.
  #31 repro proven red-first (offered `?with=person-2` without the guard). `/code-review` (high) →
  no-blocker. `security` (Opus/high) → **Clean** (guard sufficient, no auth/IDOR, read-only so no lock
  needed, refactor no security surface); noted one pre-existing edge (broken/unparseable group card).
  **Browser live-verify** (seeded store + real app on a local port): group primary → "No contacts
  found."; contact primary → offers the other contact, self+group excluded; bare group detail → 0 field
  boxes; contact-with-email → 1 box showing the email. Cold `/session-audit` → **SURVIVES** (auditor
  reproduced the guard test red on `main` / green on HEAD, confirmed the refactor term-for-term).
- **`get_by_uid` uniqueness gap → filed #33:** the audit surfaced that `get_by_uid` does
  `WHERE user=? AND uid=?` + `.fetchone()` with no `ORDER BY` and no `UNIQUE(user,uid)` — an arbitrary
  row pick if a uid is ever duplicated. Pre-existing, low severity; filed as an enhancement, not fixed.
- **Index-clobber mishap (caught in verification, fixed):** `1fdb168` captured only the staged new test
  — the three source edits had been **unstaged** (the `/session-audit` auditor swapped `main`'s files
  into the working tree and restored them, resetting the index), so `main` briefly held the #31
  regression test *without* its fix. Caught by a post-push `git show main:…` grep for the guard; the
  working-tree edits were still intact and verified identical to the reviewed diff, so `15b1ed8`
  restored them (suite green on `main`). New PITFALLS entry added.
- **Merge/deploy:** guard green → merged `flow/31-merge-search-guard` → `main` (`6c72fe6`, Closes #31)
  → recovery commit `15b1ed8` → pushed → **#31 auto-closed** → CI published `:latest` → `/pb` Watchtower
  `--run-once peopledb` recreated the LAN container (old→new image id). `main` in sync with origin.
- **Open/blockers:** none blocking. Open enhancement: **#33** only.
- **Memory:** PROJECT_STATE refreshed (257+44, #31 shipped, #32 residual resolved, #33 the lone open
  enh); this RUN_LOG entry; new PITFALLS entry (post-audit index-clobber); no ADR (bugfix + refactor).

---

## 2026-07-17 — housekeeping + card-overflow fix + #32 empty field box

- **Goal:** a sitrep-driven cleanup session: reconcile GitHub issue state against the spine, ship two
  small UI bugfixes, and get the LAN deploy current.
- **Housekeeping:** discovered #26 and #30 were merged/shipped but still **OPEN** on GitHub — their
  merge commits said "Merge #N" without a `Closes` keyword, so they never auto-closed. Closed both
  manually (`gh issue close`, pointing at their merge commits). Verified `main` was in sync with origin
  and `docker-publish` CI had published `:latest`; corrected the stale "not-yet-pushed / not-redeployed"
  next-action in PROJECT_STATE (`49d6d6e`).
- **Card-overflow fix (`10a36cd`):** card-view field values (`.contact-card .org/.detail`) and the name
  link had no word-break rule, so a long email/url (or no-space name) spilled past the card border.
  Added `overflow-wrap: anywhere` to those selectors in `base.html`. Not a `/flow` run (found mid-session
  from the user's report); reviewed inline + browser live-verified.
- **#32 (`0bb3353`, via live `/flow`):** a bare group rendered an empty bordered `<dl class="card">`.
  Guarded the `<dl>` to render only when ≥1 of the seven field sources (phones/emails/urls/addresses/
  related/bday/note) is present (`detail.html`); chose "any populated field" over an `is_group` check so
  a group that legitimately has a field still shows its box. New `test_empty_field_box.py`. No ADR
  (bugfix). Phase 0 classified **live**, confirmed; reconcile held live.
- **Verified:** `uv run pytest -q` → **255 passed, 44 deselected** (was 253; +2 for #32). #32 repro
  proven by stash-toggle (red without the guard, green with it) and re-proven independently by the cold
  auditor (checked out `main`, ran the test → fail; fix branch → pass). `/code-review` (high) on the #32
  diff → **no blockers, no findings**. Not security-touching → no `security` pass. **Browser
  live-verify** (seeded Radicale + real app): #32 — bare group "Empties" shows no box, contact "Jane
  Person" (one email) shows the box; card-overflow — measured content vs. available at the 170px card
  width (pre-fix 187px overflowed by 17px, fixed wraps to 170px), held at large text + light theme.
  Cold `/session-audit` on #32 → **SURVIVES**, 0 findings.
- **Deploy:** ran `/pb` — pushed the card fix, waited for the green CI publish, then a one-time
  Watchtower `--run-once peopledb` on the LAN recreated the container on `:latest` (old→new image id).
  This brought the LAN current for #26/#28/#30 + the card fix (all had been awaiting a redeploy).
- **Merge:** #32 guard green (suite + review + audit + live-verify recorded via flowlib) → merged
  `flow/32-empty-group-field-box` → `main` (`0bb3353`, closes #32). No `deliver_command`.
- **Push + deploy (end of session):** pushed `main` → CI published `:latest` → **#32 auto-closed** (the
  merge carried `Closes #32`) → `/pb` Watchtower `--run-once peopledb` recreated the LAN container on
  `:latest` (old→new image id). `main` in sync with origin; nothing awaiting push or redeploy.
- **Open/blockers:** none blocking. Only open enhancement is **#31**. Accepted residual: #32's box-guard
  duplicates the field list (audit-noted).
- **Memory:** PROJECT_STATE refreshed (255+44, #32 + card fix shipped, #31 the lone open enh, push/deploy
  status); this RUN_LOG entry; no ADR (both bugfixes); no new PITFALLS.

---

## 2026-07-17 — #26 reorganize the top bar via live `/flow`

- **Goal:** #26 — reorganize the index top bar. Started as a small decluttering ask, grew (mid-session,
  at the user's direction) into a full top-bar redesign spanning every page.
- **Design (brainstorm):** two decisions locked with the user — (1) keep quick-add, relocate `New
  contact` + `Birthdays` down to the view-toggle row; then (2) a bigger reorg: brand icon left of the
  wordmark, controls reordered palette → theme → gear → Sign out on the right, search centered. The
  crux surfaced in exploration: the theme/accent/gear cluster was `position:fixed` in `base.html`
  (floating over *every* page, dodged by a `padding-right:9rem` hack), so the requested order forced
  the controls **into** the header. Chose a **shared `_topbar.html` partial** over six edited headers
  or centralizing in `base.html` (which would leak the bar onto login). User supplied the icon file.
- **Phase 0 (live `/flow`):** classifier → **live** (templates/UI = runtime surface); confirmed.
- **Did:** Part 1 (committed first) — moved `New contact` + `Birthdays` into index's `.view-toggle`
  section, view toggle pushed right. Part 2 — new `_topbar.html` included by all six authenticated
  pages; brand icon (`static/peopledb-icon.png`, `sips`-downscaled to 128px, also the favicon);
  controls moved out of the fixed blocks into the in-flow **sticky** bar; deleted the `padding-right`
  hack + `data-size-topbar` offset rules; `@media (max-width:720px)` two-row collapse; `login.html`
  omits the bar (JS binds by id and no-ops on login via `if (!el) return`). Two tests updated (swatches
  read from `_topbar.html`; login asserts no toggle, toggle in partial) + new search-render guard.
  **ADR-0007** (structural: shared partial + un-fixing the cluster).
- **Verified:** `uv run pytest -q` → **253 passed, 44 deselected**; live **44 passed**. `/code-review`
  (two parallel finder passes): **no blockers** — no dangling refs, no duplicate ids, popovers still
  anchor, no broken nesting. Not security-touching → no `security` pass. **Browser live-verify** (seeded
  Radicale + real app, at 606px — see PITFALLS on the pinned automation viewport): icon + wordmark;
  search centered w/ stronger outline; controls order 🎨→◐→⚙→Sign out; accent + settings popovers
  anchor under their in-flow buttons; narrow two-row collapse clean; birthdays shows the bar w/o search;
  login shows no controls. Desktop-width centering checked via computed values (search sits ~45px left
  of true center — controls group wider than brand; negligible).
- **Audit:** cold `/session-audit` (fresh `verifier`) → **SURVIVES**. Two non-blocking concerns, both
  fixed before merge: (1) no test asserted the `show_search`-gated search rendered on `/` (added
  `test_search_and_quick_add_render_on_index_only`); (2) two stale docstrings still calling the controls
  "fixed"/`base.html` (corrected).
- **Merge:** guard green (suite + review + audit + live-verify recorded) → merged `flow/26-topbar` →
  `main` (`27bfe8d`, closes #26). No `deliver_command`; `pending_verify` null. **`main` NOT pushed**
  this session (left for the user); LAN redeploy still owed alongside #28/#30.
- **Memory:** ADR-0007 added (+ DECISIONS/README row); PROJECT_STATE refreshed (253+44, #26 shipped,
  open enh now #31/#32, push/deploy status); new PITFALLS entry (606px automation viewport); this entry.

---

## 2026-07-17 — #30 hide merge picker on group pages via live `/flow`

- **Goal:** #30 — the group detail page rendered the `Merge with…` htmx picker (same as a contact
  page), but merging *from* a group is rejected downstream, making it a dead-end control. Scoped (per
  the issue) to a template guard only; the server already blocks the actual merge.
- **Phase 0 (live `/flow`):** classifier → **live** (template = runtime surface); confirmed. Bugfix,
  so the issue is the spec — no doc, no ADR.
- **Did (orchestrator, trivial change):** wrote a failing render test first
  (`tests/test_merge_picker_visibility.py` — picker present on a contact page, absent on a group page),
  then wrapped the merge-picker `<section>` in `detail.html` with `{% if not contact.is_group %}`.
  `contact.is_group` is already in the template context on all 6 `render("detail.html", …)` call sites.
- **Verified:** `uv run pytest -q` → **252 passed, 44 deselected**; live **44 passed**. `/code-review`
  (high): **no blockers**. Not security-touching → no `security` pass. **Browser live-verify** against a
  seeded throwaway Radicale + the real app (a "Family" group + a "Jane Person" contact): the group page
  shows Edit/Delete only (no picker); the contact page still shows the picker. Also curl-confirmed at
  the HTTP level (group HTML = 0 `merge-picker`, contact = 1).
- **Audit:** cold `/session-audit` (fresh `verifier`, no transcript) → **SURVIVES**. It refuted the
  in-session "least confident" worry — a `merge_warn` banner ("Merge completed with warnings") does
  **not** reintroduce the substring my test asserts absent (`"Merge with" in "Merge completed with
  warnings"` is `False`). Surfaced two out-of-scope items, both filed: **#31** (`/merge/search` doesn't
  validate the primary uid is a non-group — reachable only by hand-crafted URL, the real merge still
  400s) and **#32** (empty bordered field box on group detail pages).
- **Merge/deliver:** merge guard green (suite + review + audit + live-verify recorded) → merged
  `feat/30-hide-merge-picker-groups` → `main` (`ea5764f`, closes #30), pushed → CI publishing. No
  `deliver_command`; `pending_verify` already null. **Not yet redeployed to the LAN** (`/pb` when ready,
  alongside #28).
- **Memory:** PROJECT_STATE refreshed (verification 252+44, #30 shipped, #31/#32 opened); this entry.
  No ADR (routine template guard); no new PITFALLS gotcha.

## 2026-07-16 — #28 merge duplicate contacts via live `/flow`

- **Goal:** the largest open enhancement — detect/merge duplicate contacts (#28). Scoped in Phase 0 to
  a **manual pick-two** merge (no detection heuristics, no review queue) after a brainstorming cycle.
- **Design (approved):** keeper survives (keeps UID/photo/unknown-props); multi-valued fields unioned
  (exact-dedup, keeper-first), single-valued fields resolved by an explicit choice; groups-only
  referential cleanup (source→keeper membership move; inbound `RELATED` left dangling, accepted);
  **abort-on-keeper-conflict, warn-on-cleanup, delete-source-last, no rollback**. Wrote a 30-60-line
  spec (`specs/2026-07-16-merge-duplicate-contacts.md`) + **ADR-0006** (the non-transactional
  delete-last semantics — the one ADR-worthy call).
- **Did (executor TDD + orchestrator):** new `merge.py` (pure union/dedup, self-relation drop,
  group-member rewrite); `GET/POST /contacts/{uid}/merge` + a merge-flavored `GET
  /contacts/{uid}/merge/search` (reuses FTS `store.search`, excludes self+groups); `merge.html` review
  screen + `_merge_candidates.html` fragment; a distinct `?merge_warn=` banner. All cache mutation via
  the existing `cache_after_write`/`locked_delete` helpers under the per-user lock.
- **Review caught real defects (all fixed pre-merge):** `/code-review` (3 finders) + a `security` pass
  found a **HIGH keeper-flip bug** — the review radios were valued `keeper`/`source` but labelled by
  card, so choosing card B as keeper **inverted every single-valued field** and then deleted the card
  whose value the user thought they kept (silent data loss). Fixed by decoupling the field choice
  (`a`/`b`, independent of keeper) + validating `keeper_uid ∈ {a,b}`. Also fixed a URI-only-photo empty
  `PHOTO` write. Cold `/session-audit` (live-server probes) then found: garbled warning banner (reused
  #24's wording), the photo silent-drop still needing a warning, a `<select>` picker vs the spec's
  search, and a missing multi-group test — **all fixed** (per the maintainer's "fix everything incl. /search").
- **Verified:** `uv run pytest -q` → **250 passed, 44 deselected**; live **44 passed**. **Browser-verified**
  end-to-end (seeded Radicale + real app, two "Jane Smith" dups + a Family group): picker excludes self;
  keeper-flip fix confirmed (keeper=B + kept A's company → survivor holds A's value); union correct;
  source 404'd; group membership moved B. Merged `feat/28-merge-contacts` → `main` (`ed2904b`, closes
  #28), pushed → CI publishing. Filed **#30** (hide merge picker on group pages).
- **Memory:** ADR-0006 added + indexed; PROJECT_STATE refreshed; PITFALLS gained the
  keeper-identity-vs-field-value gotcha. Not yet redeployed to the LAN (`/pb` when ready).

## 2026-07-16 — #29 screen-reader labels for index field values via live `/flow`

- **Goal:** label the contacts-index field values for screen readers (#29) — filed from the #27
  session audit. Index list/card values were bare `<span>`s (unlike the detail page's `<dl>`/`<dt>`),
  so a screen reader read an undifferentiated run of strings.
- **Phase 0 (live `/flow`):** classifier → **live** (templates are a runtime surface); confirmed. The
  issue was the spec (small a11y fix); no ADR. Settled the approach up front: a **visually-hidden
  prefix span inside each `.field-*` span**, *not* `aria-label` — `aria-label` on a non-interactive
  `<span>` is unreliably announced across AT, whereas real hidden DOM text is read inline everywhere.
- **Did (executor TDD + orchestrator):** `_contacts.html` gained a `<span class="sr-only">Label: </span>`
  prefix inside each of the six field spans in **both** the card and list blocks; `base.html` gained a
  `.sr-only` clip-pattern utility class. Placed inside the `.field-*` span so #27's `display:none`
  field-hide drops the label with its value. `/code-review` (2 cold finders + verify): no blocker;
  correctness verifier confirmed autoescape on (`app.py:233`) and no layout shift.
- **Verified:** `uv run pytest -q` → **235 passed, 32 deselected**; live suite **32 passed**.
  **Browser-verified** against a seeded throwaway HTTP server (full + bare contact): all six values
  announce label+value inline, each label 1×1 and visually absent (screenshot), deselecting a field
  drops span+label from the a11y tree via `display:none`, bare contact emits zero labels. **Setup
  gotcha** hit + recorded: a stale HttpOnly `peopledb_session` cookie on `127.0.0.1` blocked JS cookie
  injection and switching *ports* didn't help (cookies aren't port-scoped) — verified via the
  `localhost` hostname instead.
- **`/session-audit` (cold):** found the list-view **Address** sr-only label had **no test coverage**
  (safe only because the card/list blocks are byte-identical) → closed with an explicit assertion
  before merge. Also surfaced a label-vocabulary divergence: the maintainer chose to **align** the sr-only
  labels to the app's existing terms (`Website`→`URL`, `Organization`→`Org`) so a screen reader hears
  the same word on index and detail. Applied post-audit; re-ran suite green.
- **Shipped:** merged `feat/29-index-field-a11y-labels` → `main` (`1ff515d`, closes #29), pushed → CI
  `docker-publish`. **LAN redeploy (`/pb`) still owed** — deferred as an a11y-only change.
- **Open/blockers:** none. Open enhancements #26, #28. Noted (not filed): the 12 duplicated sr-only
  label literals across the two blocks (a `{% macro %}` would collapse them); an axe/AT scan for full
  announcement confirmation (mechanism verified in Chrome, not a real screen reader).
- **Memory artifacts:** `PROJECT_STATE.md` (last-updated, current position, verification, recently
  shipped, next actions); two new `PITFALLS.md` entries (a11y label hiding depends on `display:none`;
  browser-verify cookie/hostname trap); this entry.

## 2026-07-16 — #27 user-selectable list/card fields via live `/flow`

- **Goal:** make the hardcoded index list/card fields user-selectable (#27) — one of the three
  enhancements filed at the end of the #25 session.
- **Brainstormed + approved:** the open fork was client-side (localStorage + popover, the
  display-settings idiom) vs server-side (a cookie like `POST /view`). Established that `POST /view`
  persists via a plain **cookie**, and localStorage is per-browser — so **neither syncs across
  devices** (no user DB, ADR-0003), collapsing the main reason to go server-side. Chose client-side.
  The maintainer asked whether the repo going **public** changes it: no — "public" means the *source* is public,
  not any instance's *data*; field selection is a display-density preference, not an access-control
  boundary (viewer is always the authenticated owner). Decisions: client-side; **independent per
  view**; toggle set org/phone/email/birthday/url/address (name always shown). Spec:
  `specs/2026-07-16-list-card-field-selection.md`; no ADR (extends display settings).
- **Did (executor + orchestrator):** `_contacts.html` renders **all six** fields in both views (each
  guarded by data-presence, each carrying a `field-<name>` class); `base.html` pre-paint stamps
  `data-list-fields`/`data-card-fields` from two localStorage keys (allow-list sanitized), CSS hides
  all then reveals by `~=` whole-word token match, and two popover checkbox groups drive it live. Two
  `/code-review` fixes: **durable empty selection** (null=default vs ''=keep, so uncheck-all no longer
  reverts on reload) and skip the **blank address span** for an all-empty ADR. Address uses the
  existing `AddressParts.formatted` (comma-joined single line).
- **Verified:** `uv run pytest -q` → **231 passed, 32 deselected**; live suite **32 passed**.
  Browser-verified against a seeded local Radicale (full/partial/bare/empty-address contacts): defaults
  correct, per-view independence, live toggle without reload, reload persistence, durable uncheck-all,
  compact address, empty-ADR omission. **`/session-audit`** (cold) caught **vacuous omission tests**
  (`test_{card,list}_view_omits_field_spans_for_bare_contact` sliced the bare `<li>` before the name,
  where field spans never render → could not fail); fixed to isolate the full `<li>` and
  **mutation-verified** (removing a guard now fails both). Also added cross-ref comments at the two
  duplicated `FIELDS` allow-lists (silent-strip trap for future fields). Audit finding #4 (index a11y
  labels) filed as **#29**.
- **Shipped:** merged `feat/27-field-selection` → `main` (`cfc130f`, closes #27), pushed → CI
  `docker-publish` green + image to ghcr, then **`/pb`** one-time Watchtower recreate → `peopledb`
  live on `:latest` on the LAN deploy.
- **Open/blockers:** none. Open enhancements #26, #28, #29. Accepted (spec-intended): multi-value
  fields show entry `[0]` only.
- **Memory artifacts:** `PROJECT_STATE.md` (last-updated, current position, verification, recently
  shipped, next actions); new spec; new `PITFALLS.md` entry (absence-assertions on a mis-sliced region
  pass vacuously — mutation-test them); this entry.

## 2026-07-16 — #25 widen contacts index + file #26/#27/#28

- **Goal:** cut the large empty left/right gutters on the contacts index (raised as one of four
  enhancement ideas: index width, top-bar reorg, list/card field selection, merge duplicates).
- **Brainstormed + scoped:** the four ideas are independent sub-projects of very different size/risk;
  filed all four as GitHub enhancements (#25 index width, #26 top bar, #27 field selection, #28 merge
  duplicates), then designed **#25 only**. Root cause: index list + card grid boxed to the global
  `main { max-width: 720px }`. Decision (approved): scope a wider cap to a new `main.contact-index`
  class rather than widen global `main` (which would blow out the vertical edit form + detail page).
  Width **1400px for both list and card**, chosen for standardness; the card grid is elastic
  (`auto-fill minmax(180px,1fr)` + `1fr`) so it reflows cleanly to ~7 columns at any width — no ugly
  remainder. List left wide-but-sparse deliberately (#27 will fill it).
- **Did:** `base.html` — `main.contact-index { max-width: 1400px }`; `index.html` — `<main>` →
  `<main class="contact-index">`. Two-line change, no JS, no server change.
- **Verified:** browser-verified against a local Radicale (24 seeded contacts) via the app on
  `:8000`, computed-style checks — index `main` 1400px / 7 card columns; detail + edit-form `main`
  still 720px (scoping holds). Then **`/session-audit`** (cold fresh-agent read) caught a broken test:
  `test_display_settings.py:144` asserted the index `<main>` was class-less. `uv run pytest -q` →
  `1 failed, 224 passed`; updated the assertion to the new `contact-index` class (guard intent
  intact) → **225 passed, 32 deselected**. Chose to **skip `/code-review`** — the audit was an
  adversarial cold review of a 3-line diff with no logic surface; running the tool too would be
  process theater (#26/#27/#28 will each get a real review).
- **Shipped:** committed direct to `main` (`a566656`, closes #25), pushed → CI `docker-publish`
  green + image to ghcr, then **`/pb`** one-time Watchtower recreate → `peopledb` up on `:latest` on
  the LAN deploy.
- **Open/blockers:** none. #26/#27/#28 open, each owed a design cycle before code (#28 also a spec +
  likely ADR + `security` agent for the CardDAV writes).
- **Memory artifacts:** `PROJECT_STATE.md` (last-updated, current position, verification, recently
  shipped, next actions — cleared the stale "not pushed / no open issues" drift); new `PITFALLS.md`
  entry (template-output tests assert exact markup — run pytest after any template edit); this entry.

## 2026-07-16 — display settings popover (six S/M/L size controls) via live `/flow`

- **Goal:** a real "display settings" surface — user-adjustable text/avatar sizing across the top bar,
  list view, card view, and contact detail, persisted per browser.
- **Brainstormed + approved:** gear popover in the fixed top-right cluster (over a `/settings` page);
  existing toggles consolidated; localStorage per-browser (matches theme/accent + the no-user-DB auth
  invariant, ADR-0003). Six controls: top bar (text + icons), list (text + avatar together), card text,
  card avatar, detail avatar (reuses the `peopledb-avatar-size` key), detail text. Spec:
  `specs/2026-07-15-display-settings.md`; no ADR (extends the theme/accent pre-paint convention).
- **Did (executor, then orchestrator for feedback):** pre-paint inline script stamps root `data-size-*`
  from localStorage before first paint; a generic popover JS handler drives all six groups off
  `data-*` attrs (allow-list `{sm,md,lg}`, `md` = no attribute = untouched default); CSS per control.
  Removed the old inline detail-avatar toggle. Feedback rounds: enlarged the gear (larger than
  theme/accent, re-spaced so nothing overlaps); **kept the view toggle on the index** (reverted a
  popover migration — `index.html`/`app.py` net-unchanged vs main); made **all** text in a scaled
  region scale, labels included (`dl.card dt` rem→em); **widened the S/M/L spread** (text .8/1/1.35em)
  after card details scaled too subtly.
- **`/code-review` + cold `/session-audit`:** two rounds. Review caught a scoping bug pre-merge
  (detail-text via bare `main` leaked to every page + compounded with the em list/card controls) —
  fixed by scoping to `main.contact-detail`. Audit caught the view toggle misreporting state off the
  index; resolved by keeping it index-only. Re-review of the final diff: no blocking defects (two low
  cosmetics — popover-over-gear, narrow-viewport clamp — both fixed).
- **Verified:** `uv run pytest -q` → **225 passed, 32 deselected**; live suite **32 passed**.
  Browser-driven live-verify against a throwaway Radicale with computed-style checks (h1 19.84px / gear
  54.4px at top-bar L; card detail 10.5/13.1/17.7px across S/M/L; detail `dt` label scales; no icon
  overlap; Escape + outside-click dismiss; no cross-page leak).
- **Open/blockers:** none. `main` merged but **not pushed** (a push triggers the ghcr CI publish — held
  as merge≠deploy).
- **Memory artifacts:** `PROJECT_STATE.md`, this `RUN_LOG.md`, the spec. No ADR, no new PITFALLS entry.

## 2026-07-15 — formalize deployment: ghcr CI publish + Unraid Docker-tab template (ADR-0005)

- **Goal:** replace the hand-built-on-a-Mac + `docker run` LAN deploy with a formal path — an image
  built from the repo, published on merge, consumed as a managed container in the Unraid Docker tab,
  pulling a `:latest` built from our work.
- **Decisions (brainstormed, user-approved):** ghcr.io (**private** image, parity with the repo), CI
  publishing `:latest` (main) + `:vX.Y.Z` (`v*` tags) + `:sha-…` (every build), and **manual** Unraid
  updates (no auto-update plugin). `linux/amd64` only. Recorded in ADR-0005.
- **Did:** added `.github/workflows/docker-publish.yml` (test job gates a build-and-push job; `uv sync
  --frozen` + `uv run pytest`, then `docker/metadata-action` + `build-push-action` to
  `ghcr.io/wildernessj/peopledb`), an Unraid CA template `unraid/peopledb.xml` (named env fields,
  masked `PEOPLEDB_SECRET_KEY`, `/data` volume), rewrote the README Docker section (pull-from-ghcr +
  Unraid, dropped the cross-arch build warning), and excluded `.github/`/`unraid/` from the build
  context. ADR-0005 + its index row added.
- **`/code-review`:** the workflow YAML is the only executable artifact; one fresh-context adversarial
  verifier attacked the tag rules, ghcr lowercasing, permissions, the test gate, and action versions —
  **no blocking defects** (redundant `prefix=sha-` and a benign branch-push metadata warning noted).
- **Verified:** unit gate green locally (**215 passed, 32 deselected**); workflow YAML + Unraid XML
  well-formed. **Merged to `main` and pushed → first CI run `29438537891` green**: test job passed,
  build-and-push built `linux/amd64` and pushed to ghcr (the push step succeeding is the proof).
  **Not verified from here:** package visibility (the local `gh` token lacks `read:packages` — 403;
  confirm **private** in the Packages view) and the Unraid deploy (host-side, owed).
- **Unraid cutover (done, host-side by the maintainer):** deployed from the template off the hand-run container,
  now behind a reverse proxy. Surfaced three gotchas, all fixed + documented (README + PITFALLS):
  `/data` appdata must be writable by uid/gid `999` (else `unable to open database file` crash-loop),
  host `:8000` collides on a homelab box (change the WebUI Port; container port stays `8000`), and a
  reverse-proxied container must sit on the proxy's Docker network (not default `bridge`).
- **Open/blockers:** none. Non-blocking: GH annotation that pinned actions still target Node 20
  (force-run on 24) — a future version bump.
- **Memory artifacts:** ADR-0005 (+ index row), `PROJECT_STATE.md`, this `RUN_LOG.md`, and a new
  `PITFALLS.md` entry (XML comments can't contain `--`, which broke the template mid-authoring).

## 2026-07-15 — `#group` quick-entry sigil + create-form group field via live `/flow` (#24)

- **Goal:** the last open quick-entry follow-up — let a `#group` token in the quick-add line assign the
  new contact to existing groups. The issue flagged the real work as plumbing group assignment into the
  create flow (the create form had no group field) + a design call on unknown-group behaviour.
- **Phase 0 (spec + two design calls).** Wrote `specs/2026-07-15-group-quick-entry-sigil.md`. Two forks
  put to the user: (1) **form field + sigil** (group checkboxes on the create form, sigil pre-checks —
  keeps the "reviewed form is the safety net" invariant) over quick-entry-only; (2) unknown group name →
  **ignore + flag** (surface a "not assigned" note; never auto-create — no surprise server write from a
  typo) over reject/auto-create. Classifier + reconcile both `live`.
- **Did (executor, TDD).** Parser: `#token` sigil → `ContactFields.groups`, run after email/url/phone so
  a `#frag` in a URL isn't misread. Create-only Groups checkbox fieldset in `form.html`. `new_contact_form`
  resolves parsed names against `store.list_groups` (case-insensitive) → pre-checked boxes + unmatched
  note. `create_contact` writes membership after create via a new `_add_member_to_group` helper reusing
  the `set_group` / per-user-lock path; failures surface via `?group_warn=`.
- **`/code-review` (high): 1 real bug fixed.** A stale/crafted `group_uid` (deleted group, or one pointing
  at a normal contact) would 404 *after* the contact was created, or `set_group`-rewrite a contact into a
  group. Fixed: resolve via `get_by_uid` + require `is_group`, fold misses into `group_warn`. (Dedup vs
  `_mutate_group` and the query-param surfacing judged acceptable, not blockers.)
- **Cold `/session-audit`: 1 MAJOR fixed.** `_add_member_to_group` caught only `ConflictError`; a non-409
  `DavError`/`UnreachableError` on the group PUT propagated as "not saved" **while the contact was already
  created** → retry → duplicate. Fixed: broadened to `except DavError`, surface via `group_warn`. Audit
  artifact captured in `.flow-audit.md` (git-excluded). Both fixes got regression guards.
- **Verified:** **215 unit + 32 live** green (`uv run pytest`). **Browser-verified** against a local
  Radicale: `Greta Member #family` pre-filled the form with the **Family checkbox pre-checked** (Hiking
  Crew, two words, correctly unchecked + noted as unreachable by the single-token sigil); Save wrote
  `X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:…` to the **group card on the server**, redirect clean (no
  `group_warn`), and the contact's own card carried no group props.
- **Open/blockers:** none. No open issues remain.
- **Memory artifacts:** updated `PROJECT_STATE.md`, this `RUN_LOG.md`, and added a `PITFALLS.md` entry
  (secondary writes after a create must not mask the create). No ADR — feature work; design rationale
  lives in the spec.

## 2026-07-15 — split domestic phone pairs in quick-entry via live `/flow` (#23)

- **Goal:** the first of two quick-entry follow-ups filed this session — split a whitespace-joined
  domestic phone run (`555-123-4567 555-987-6543`) into two phone entries, without fragmenting a
  single grouped number (`555 123 4567`). (The session also filed #23 and #24 from the #22
  follow-up notes before flowing #23.)
- **Did:**
  - **Phase 0 correction.** Reading the parser first showed the problem was narrower than the issue
    framed it: comma/slash-separated pairs *already* split (those chars aren't in the phone char
    class → separate regex matches) and `+`-separated pairs already split; only the **whitespace-only
    domestic** case was unsolved. Agreed the heuristic with the user: **greedy ≥10-digit close** per
    `+`-delimited piece. Live variant confirmed (classifier + reconcile both `live`).
  - **Implemented (executor, TDD).** `_greedy_domestic_split` + `_split_phone_run` in `quickparse.py`;
    `_extract_phones` calls the latter. Accumulate space-separated groups, close a number at ≥10
    digits; a trailing <7-digit remainder folds back rather than emitting a fragment.
  - **`/code-review` (high, parallel finders): no blocker.** Two correctness candidates
    (`(work)`-token absorbed; paren area codes fragmented) **refuted empirically** — `(work)`'s letters
    break the regex match so it becomes a *label* at the run boundary, never entering the splitter, and
    `(555) 123-4567` stays one number. Two cleanup nits applied (redundant digit recount → reuse
    `digits`; docstring "`+`-free" → "may start with `+`").
  - **Cold `/session-audit`: SURVIVES.** Proved no real E.164 number (≤15 digits) can fragment — a
    spurious split needs ≥10 + ≥7 = ≥17 digits. Flagged the threshold/fold-back branches as untested →
    added two regression guards (long-international-stays-one, sub-7 fold-back) plus a route-level
    render test asserting two pre-filled phone fields.
- **Verified:** **206 unit + 29 live** green (`uv run pytest`). **Browser-verified** against a local
  Radicale (Chrome): a two-domestic-phone quick-add pre-filled the form as **two separate phone
  rows**; Save round-tripped and the **raw vCard on the server persisted two `TEL:` lines** (detail
  page renders both). Merge guard green → `--no-ff` merge to `main`; branch deleted; #23 closed with
  the residual documented.
- **Open:** **#24** (`#group` sigil) still open — needs group-assignment in the create flow first.
  Accepted residual on #23: two whitespace-joined 7-digit locals still merge (ambiguous, no delimiter).
- **Memory:** updated PROJECT_STATE, this RUN_LOG entry, PITFALLS (flow merge-guard `live_verify_passed`
  gate). No ADR (routine enhancement; the design rationale is the greedy-threshold note above).

## 2026-07-15 — NL quick-entry parser via live `/flow` (#22)

- **Goal:** build the last deferred backlog item — a natural-language quick-entry bar that turns a
  one-line contact into a ready-to-review add form.
- **Did:**
  - **Brainstormed → thesis.** Two forks settled with the user: **pre-fill the form** (not
    create-immediately / inline-preview) and a **rule-based minimal-sigil** parser (**not an LLM** —
    keeps the app local-first/dependency-free; output is user-reviewed anyway). `#group` deferred (the
    create form has no group field; group membership is a separate member-list write path). Spec:
    `specs/2026-07-15-nl-quick-entry.md`.
  - **Implemented (executor, TDD).** Pure `parse_quick_entry(text) -> ContactFields` in
    `quickparse.py` (email→url→phone→bday→org→name→note, each match sentinel-spliced out); wired
    `GET /contacts/new?q=` to build a `Contact` directly and pre-fill `form.html`; quick-add GET form
    on the index. Reuses the `POST /contacts` write path unchanged.
  - **`/code-review` (high, cold finders)** found 3 real defects beyond the forgiving contract, fixed:
    a `str.find`-on-rejoined-string splice that duplicated org/bday text into the name on irregular
    whitespace (→ span-based splice); a labeled second phone silently dropped (a label's `)` started a
    bogus overlapping candidate → dropped `)` from the phone first-char class); and a header layout
    shift (quick-add reused `.inline`'s `margin-left:auto` → own inline style). Rarer adversarial cases
    accepted per the reviewed-before-Save design.
  - **Cold `/session-audit`** caught that the phone fix only covered the *labeled* case and flagged
    date/`.` issues. Three user decisions applied: **split phone runs on interior `+`** (unlabeled
    `+1… +1…` → two entries); **remove `.`** from the phone class (spec-conform; IPs/decimals no longer
    joined into a phone); **drop bare `D/M` dates** (D/M-vs-M/D ambiguous and feeds the ICS feed — only
    ISO + named-month parse now).
- **Verified:** 199 unit + 29 live green (`uv run pytest`). **Browser-verified** against a local
  Radicale (Chrome): a rich one-liner pre-filled name/org/`--03-03` bday/labeled email/**two split
  phones**/url correctly, Save round-tripped to CardDAV (detail page renders the saved card), header
  layout held. Merge guard green → `--no-ff` merge to `main`; branch deleted.
- **Open:** backlog empty; #22 done. Follow-ups noted (not filed): domestic (no-`+`) phone-pair split;
  `#group` sigil pending group-assignment in the create flow.
- **Note:** `.workflow-run.json` / `.flow-audit.md` (flow run-artifacts) were swept into a feature
  commit by `git add -A`; caught before merge, untracked + gitignored (see PITFALLS).
- **Memory:** updated PROJECT_STATE, this RUN_LOG entry, PITFALLS (flow-artifact git hygiene). No ADR
  (routine feature; design rationale lives in the spec).

## 2026-07-14 — Backlog close-out via non-live `/flow`: #15, #18, #16

- **Goal:** clear the remaining open enhancement issues (#15, #16, #18), each through the full
  Coding Workflow v2 harness driven by `/flow --no-live` (autonomous; owed browser verify tracked
  as `needs-verification` issues).
- **Did:**
  - **#15 — FTS search → address + URL.** Spec (`specs/2026-07-14-search-address-url.md`) → executor
    (TDD). Added `address`/`url` columns to `contacts_fts`; a single `_FTS_COLUMNS` constant + shared
    `_fts_row` projection so schema/upsert/rebuild can't drift; `PRAGMA user_version`-gated one-time
    drop+rebuild of the FTS index from `contacts.raw` (FTS5 has no ALTER ADD COLUMN → PITFALLS).
    Cold audit caught a **tautological migration-idempotency test** — rewrote it with a sentinel row +
    `user_version` assertion and **mutation-verified** it now fails if the gate breaks.
  - **#18 — crop resize hit-zone.** `hitTest` accepted a ±handle box centered on the corner (~2× the
    drawn handle, extending outside the crop). Gated the outward margin on `(pointer: coarse)`: mouse
    now matches the visible handle; touch keeps the fat target.
  - **#16 — detail avatar S/M/L toggle.** Remembered via localStorage (default `md`), matching the
    theme/accent idiom. `_avatar.html` gained an **opt-in `id`** param (default off → other call sites
    byte-for-byte unchanged); review flagged a `|safe` XSS foot-gun on it, **fixed** by switching to an
    inline auto-escaped conditional attribute.
  - Each run: `/code-review` (cold reviewer) + `/session-audit` (fresh-context) + merge guard before
    a `--no-ff` merge to `main`.
- **Verified:** 172 unit + 29 live green (`uv run pytest -q`). Then **browser-verified all three**
  same session against a local Radicale (Chrome extension): #15 search discriminates by address
  component + URL token via `/search`; #16 avatar S/M/L resizes, highlights, and persists across
  contacts (localStorage); #18 crop hit-zone measured from the canvas — a drag just outside the corner
  (fine pointer) no longer resizes, while handle-resize and body-move still work. Doc-drift sweep:
  bumped test count 163→172, refreshed status/shipped/next.
- **Open:** #15/#16/#18 closed; owed-verify issues #19/#20/#21 opened **and closed same session** after
  the browser pass. Backlog now empty. Accepted-untested: #15 boot rebuild on a large book; crop
  coarse-pointer branch (couldn't emulate touch — inspection only).
- **Note:** a parallel actor committed `061b445` (PROJECT_STATE 2-tier-spine note) onto the #18 branch
  mid-run — benign, isolated from the feature commits, carried to `main` via the #18 merge.
- **Memory:** updated PROJECT_STATE, this RUN_LOG entry, PITFALLS (FTS5 migration gotcha).

## 2026-07-14 — Photo preview + client-side crop (#14, #17)

- **Goal:** avatar-size photo preview (#14) and client-side square crop-on-upload (#17).
- **Did:** spec → executor (TDD, template tests red-first) → `/code-review` (8 finder angles +
  per-candidate verifiers; 3 confirmed findings fixed) → live-verify against a local app + throwaway
  CardDAV server (drag/resize/save round-trip, stored-JPEG pixel check, dark mode) → `/session-audit`
  → its one real finding (double-submit race) fixed; hit-zone UX filed as #18. Crop is canvas
  `toBlob` swapped into the file input via DataTransfer; **server pipeline untouched** (still
  validates + re-encodes). Transparent PNGs flatten to white client-side to match the server.
- **Verified:** 163 unit + 29 live green; live-verified locally and on the LAN deploy.
- **Open:** #15, #16, #18 open. Accepted-untested: real touch drag, EXIF-rotated JPEG, 12MP perf.

## 2026-07-14 — Dockerization + accent picker (#12, #13)

- **Goal:** close out live-verify debt; fix #12 (light accent below AA) and build #13 (accent picker).
- **Did:** added `Dockerfile` + `.dockerignore` + README Docker section; built and verified on the LAN
  deploy (boots, serves login, non-root). Cleared the prior live-verify debt against a real CardDAV
  server (photos, address edit, dark mode, and #4 sync-token recovery — corrupt the stored token, watch
  the background refresher full-resync). Fixed #12; built #13 — a 🎨 accent picker with 13 AA-validated
  presets, client-side (localStorage + `data-accent` + pre-paint), mirroring the theme toggle.
  `/session-audit` fixes applied. Banner links decoupled to `color: inherit` so the accent palette
  stays unconstrained by banner-tint contrast.
- **Verified:** 159 unit + 29 live green; deploy live-verified; accent-picker browser glance handed to
  the user (automation browser can't reach the LAN deploy — see PITFALLS).
- **Open:** #12/#13 closed; #14–#17 filed. `test_accent_keys_in_sync` guards the 4-way accent sync.

## 2026-07-14 — Overnight issue sweep (#1–#11)

- **Goal:** work the full open issue backlog to completion (autonomous, user away).
- **Did:** all 11 open issues shipped and closed — #9 photo display, #8 dark mode, #7 strftime, #6
  blocking-httpx→event-loop offload, #4 sync-token heuristic pinned by tests, #2 relationship
  collisions, #5 SQLite global-lock → thread-local + WAL + per-user locks (→ ADR-0004), #3 session
  idle timeout, #1 address editing, #10 card view, #11 photo upload. Each: executor (TDD) →
  per-change code review → cold session-audit → commit/push. New module `photos.py`; `pillow` added.
- **Verified:** suite grew 46 → 185 (156 unit + 29 live), all green; UI work browser-verified against
  a seeded local CardDAV server.
- **Open:** #12 filed (light-accent contrast). Live-verify debt against a real server recorded.

## 2026-07-13 — v1 greenfield build

- **Goal:** take peopleDB from scaffold to a working Cardhop-style CardDAV web client.
- **Did:** all six v1 features (add/edit/search, interact links, relationships, groups, birthdays)
  built TDD; one high-effort `/code-review` (10 findings fixed); `/session-audit` (3 correctness/leak
  findings fixed, rest filed as issues #1–#11). Chose the stack (→ ADR-0001); dropped the CalDAV-only
  library for a hand-rolled `httpx` CardDAV client (→ ADR-0002); Fernet-encrypted in-memory sessions
  (→ ADR-0003). Recorded the "bugs/enhancements → GitHub issues, not doc lists" convention in CLAUDE.md.
- **Verified:** 46 unit + 18 live green; manual pass against a real CardDAV server worked.
- **Open:** issues #1–#11 filed. Live tests use a local test server (sabre/dav differs in sync/etag
  detail — some paths test-server-only).

# Pitfalls — peopleDB

Topic-specific gotchas ("don't do X") accumulated as we hit them. Read at session start; add entries as
Trigger → Wrong → Correct.

## CardDAV library

- **Trigger:** reaching for a CardDAV client library in Python.
- **Wrong:** `caldav` (v3.2) — it's CalDAV-only, no addressbook support despite the name.
- **Correct:** hand-rolled httpx layer in `dav.py` (PROPFIND/REPORT/PUT). See ADR-0001 amendment.

## A missing `ORDER BY` can be silently masked by the PK index

- **Trigger:** writing a "red-without-the-fix" regression test for a query that adds an `ORDER BY`
  tiebreak (e.g. #33's `get_by_uid`), or reasoning about which row `.fetchone()` returns without one.
- **Wrong:** assuming `SELECT … WHERE user=? AND uid=?` with no `ORDER BY` returns rows in insertion /
  rowid order, so inserting the "wrong" row first will make an unordered query surface it. It won't:
  SQLite satisfies `WHERE user=?` via the `(user, href)` PRIMARY-KEY autoindex (`EXPLAIN QUERY PLAN` →
  `SEARCH … USING INDEX sqlite_autoindex_contacts_1 (user=?)`), whose B-tree is physically ordered by
  `href` for a fixed user — so `fetchone()` already returns the smallest `href` with or without the
  `ORDER BY`. A test written this way passes even against the unfixed code (verify by monkeypatching the
  pre-fix method body back in — assertions still green), i.e. it documents intent but is **not** a
  regression guard.
- **Correct:** recognise when a tiebreak is *belt-and-suspenders* — correct and worth adding (it
  future-proofs against a schema/index change that removes the incidental ordering, e.g. adding a `uid`
  index), but not something a black-box test can turn red on the current schema. Say so in the test's
  comment (pin the *direction* — it still catches an accidental `ORDER BY … DESC`) rather than asserting
  a false causal mechanism. Don't claim "regression test added" when the coverage is a contract test.

## Jinja autoescaping ≠ safe in every context

- **Trigger:** interpolating contact data into templates.
- **Wrong:** assuming `{{ value }}` is safe everywhere because autoescape is on. It escapes HTML
  entities only — inside an inline `onsubmit="confirm('{{ name }}')"` the browser decodes `&#39;`
  back to `'` and the JS string breaks out (stored XSS); and `href="{{ url }}"` still allows
  `javascript:` schemes.
- **Correct:** keep user data out of inline JS (static confirm text); pass URLs through the
  `safe_url` filter (allowlist of schemes).

## Write-through: a failed post-write refetch is not a failed write

- **Trigger:** re-GETting a card after PUT/create to capture server normalization.
- **Wrong:** letting that GET raise — the global unreachable handler then reports "not saved"
  though the write already succeeded, and the cache stays stale (next edit gets a spurious 412).
- **Correct:** `cache_after_write` treats the write as done and falls back to the sent bytes +
  the write's etag if the refetch fails.

## Secrets / TLS

- **Trigger:** setting the session cookie.
- **Wrong:** omitting `Secure` — the cookie is the only key to the Fernet-encrypted CardDAV
  credentials; over plain HTTP it's sniffable.
- **Correct:** `secure=True` by default (`PEOPLEDB_SECURE_COOKIES=0` only for local HTTP dev).

## XML comments can't contain a double hyphen (2026-07-15, ADR-0005)

- **Trigger:** documenting a shell command inside an `<!-- ... -->` comment in an XML file (e.g. the
  Unraid template `unraid/peopledb.xml`).
- **Wrong:** pasting a command with a `--flag` (`docker run --rm ...`) into the comment — `--` is
  illegal inside an XML comment, so the whole file fails to parse (`not well-formed (invalid token)`).
- **Correct:** keep `--` out of XML comments — reword, or point at the README/docs for the literal
  command. Validate any hand-authored XML (`python3 -c "import xml.dom.minidom as m; m.parse('f.xml')"`).

## Unraid deploy: appdata must be owned by uid 999, and host :8000 collides (2026-07-15, ADR-0005)

- **Trigger:** first managed-container deploy from `unraid/peopledb.xml` on Unraid.
- **Wrong (crash):** letting Unraid auto-create the `/data` bind path (`/mnt/user/appdata/peopledb`) —
  it's created `root`-owned, but the container runs as `app` (uid/gid `999`), so the app can't open the
  SQLite cache and crash-loops on `sqlite3.OperationalError: unable to open database file`. The boot log
  keeps replaying the old traceback, so it's easy to misread a *later* clean start as still-broken.
- **Wrong (won't start):** leaving the default host port `8000` — it commonly collides on a homelab box
  (Paperless-ngx publishes `8000`), and `docker run` fails with `Bind for 0.0.0.0:8000 failed: port is
  already allocated`. The container is created but networking never comes up; remove it before retrying.
- **Correct:** `chown -R 999:999 /mnt/user/appdata/peopledb` once, and set a free host port (container
  port stays `8000`). When fronting with a reverse proxy, the container must share the proxy's Docker
  network (not the default `bridge`) so it resolves by name, proxy → `peopledb:8000`, `SECURE_COOKIES=1`.

## Concurrency: per-user lock convention (2026-07-13, issue #6)

Route handlers are async but all DAV I/O runs in `asyncio.to_thread`. Cache
mutations (`store.upsert` / `store.delete` / `store.set_sync_token`) must only
happen inside `with lock_for(user):` (see app.py: `try_sync`,
`cache_after_write`'s `fetch_and_store`, `locked_delete`). The lock restores
per-user serialization of sync batches vs. write-backs; different users run in
parallel. **A new route that mutates the store directly, outside those helpers,
silently reintroduces the last-writer-wins race** — go through the helpers or
take the lock. Never hold the lock across an `await` on the event loop.

## Managed-prop rewrites drop unknown params (2026-07-13, issue #1)

`apply_edits` delete-and-rewrites every property in `_MANAGED_PROPS` (fn, note,
bday, email, tel, url, x-abrelatednames, adr). Unknown *params* on those props
(X-CUSTOM, vCard 4 LABEL, PREF ordering beyond TYPE) do not survive an edit —
only the value and our label handling do. ADR sub-components pobox/extended DO
survive (carried through the form). This is a deliberate convention-wide
trade-off; don't assume a managed prop round-trips verbatim.

## Browser automation can't reach the LAN deploy; hand visual verify to the user (2026-07-14)

The Docker build runs on an internal host on the LAN. The local shell reaches it fine
(`curl` → 200), but the **Chrome automation extension cannot** — it returns
`ERR_ADDRESS_UNREACHABLE` (different network context / VPN split) **and refuses
`data:` URLs** ("Can't interact with browser-internal or unparseable URLs").
So UI live-verify of the *deployed* app is not possible from this agent. Verify
everything mechanically (unit tests, served-markup grep, contrast math, `docker`
boot/curl from the build host) and hand the pixel-level check to the user, whose
own browser does reach the LAN deploy. Don't burn turns retrying the browser.

**Amendment (2026-07-14 pm):** `127.0.0.1` IS reachable from the automation
Chrome — run the app locally (throwaway Radicale via `python -m radicale`, same
recipe as `tests/conftest.py::_spawn_radicale`, then `uv run peopledb` with
`PEOPLEDB_SECURE_COOKIES=0`) and UI live-verify works fully. Only the LAN
deploy is blocked. Two more automation quirks: the MCP `file_upload` tool no longer
accepts host filesystem paths (errors "must pass contents via files param") —
inject files instead via in-page JS: draw/create the bytes in a canvas,
`toBlob` → `new File` → `DataTransfer` → `input.files = dt.files` +
`dispatchEvent(new Event('change', {bubbles:true}))`, which exercises the real
change-handler path. And `form_input` + click on a login form can silently not
submit (POST never hits the server) — click the field and `type` + `Return`
via the computer tool instead, then confirm the POST in the app log.

## The automation Chrome render viewport is pinned (~606px) — screenshots can't show wide layouts (2026-07-17, #26)

- **Trigger:** browser live-verifying a responsive layout and wanting to see how it looks at a normal
  desktop width (1200px+).
- **Wrong:** calling `resize_window` and assuming the screenshot now shows the wide layout. The window
  resizes but the captured render — and `window.innerWidth` — stays ~606px, so every screenshot is the
  narrow layout. You verify a media-query/`1fr` grid at the wrong breakpoint and miss desktop-only
  issues (or, worse, "confirm" a wide layout you never actually rendered).
- **Correct:** treat 606px as the only width you can screenshot. Verify wider layouts **numerically** in
  `javascript_tool`: read `window.innerWidth`, `getComputedStyle(el).gridTemplateColumns`, and
  `el.getBoundingClientRect()` to reason about column widths / centering at the real width, and hand the
  pixel-level desktop check to the user (whose own browser renders full-width). Design the CSS so the
  606px view is itself a correct, tested state (e.g. an explicit narrow-viewport rule).

## Template-output tests assert exact markup — changing a tag breaks them silently (2026-07-16, #25)

- **Trigger:** editing a structural tag or its attributes in a template — e.g. adding a class to
  `<main>` — during "just a CSS/layout" work.
- **Wrong:** assuming layout/markup tweaks are untested and skipping `uv run pytest` before calling
  the change done. `test_display_settings.py` does exact-substring assertions on rendered HTML
  (`assert '<main>' in index`); adding a class turned that into `<main class="...">`, so the literal
  match failed even though the test's *intent* (no detail-text-scope leak into the list) still held.
  A `/session-audit` cold read caught it after it was declared "browser-verified."
- **Correct:** run the full suite after any template edit, however cosmetic. When a template-output
  assertion breaks on a deliberate markup change, update the assertion to the new string (keep the
  guard's intent) rather than assuming the change is wrong.

## An absence-assertion on a mis-sliced region passes vacuously (2026-07-16, #27)

- **Trigger:** a template-output test that asserts markup is **absent** (`assert "field-org" not in
  li`) after isolating one element out of the rendered HTML by string-slicing.
- **Wrong:** trusting the slice without checking it spans the region where the markup would appear.
  #27's `test_..._omits_field_spans_for_bare_contact` isolated the bare contact via
  `body.split("Bare Bones")[0].rsplit("<li", 1)[1]` — but field spans render *after* the name, so the
  slice ended mid-`<a>` tag and never reached them. Every `not in` assertion was **vacuously true**;
  the tests passed even with the `{% if %}` guards deleted. A green suite proved nothing. Caught by a
  `/session-audit` cold read that mutation-tested the guards.
- **Correct:** for any absence-assertion, **mutation-test it** — break the thing it guards (delete the
  guard / force the markup) and confirm the test now *fails*. A test that can't fail isn't a test.
  Prefer isolating a full element (`next(chunk for chunk in body.split("<li") if NAME in chunk)`) over
  a fragile before/after slice.

## FTS5 schema changes need a versioned rebuild (2026-07-14, issue #15)

- **Trigger:** adding or changing a column on the `contacts_fts` FTS5 virtual table.
- **Wrong:** relying on `CREATE VIRTUAL TABLE IF NOT EXISTS` alone (FTS5 has **no** `ALTER TABLE …
  ADD COLUMN`) — an existing cache keeps its old-shaped table, so the new column silently indexes
  nothing and search for it returns empty with no error. Equally wrong: duplicating the column list
  across the `CREATE` and the rebuild — they drift and you index the wrong fields.
- **Correct:** define the column list **once** (`_FTS_COLUMNS`) and the insert projection **once**
  (`_fts_row`, shared by upsert + rebuild). Bump `_SCHEMA_VERSION` and let `_migrate` drop+rebuild the
  index from `contacts.raw` (the cache is disposable), gated by `PRAGMA user_version` so it runs once.
  The rebuild + version stamp must commit in the **same** transaction so a mid-migration crash rolls
  back to version 0 and self-heals next boot — never stamp the version before the rows land. Test the
  gate with a **sentinel row a re-run would wipe**, not just "search still works" (that passes either
  way — tautological).

## Flow run-artifacts must stay untracked (2026-07-15, issue #22)

- **Trigger:** running `/flow`, which writes `.workflow-run.json` (gate state) and `.flow-audit.md`
  (session-audit output) to the repo root, then staging with `git add -A` / `git add .`.
- **Wrong:** blanket-staging sweeps those ephemeral run-artifacts into a feature commit. They carry no
  secrets, but they're per-run scratch (like the already-excluded `.workflow.yaml`) and a `--no-ff`
  merge drags them into permanent — soon public — history.
- **Correct:** they're gitignored now (alongside `.workflow.yaml`), so this specific slip is
  self-healing. General rule: during a flow, prefer explicit `git add <paths>` over `git add -A`, and
  glance at `git status` before committing. If one already got tracked, `git rm --cached` it and
  `--amend` the tip **before** merging (only that commit needs fixing if it's the sole one touching it).

## Flow merge-guard: `has_runtime_surface` needs a separate `live_verify_passed` (2026-07-15, issue #23)

- **Trigger:** a live-variant `/flow` on a runtime-surface change — you record the gates the protocol's
  `set` example shows (`suite_green`, `code_review`, `has_runtime_surface=true`, `head_sha`) and run the
  merge guard.
- **Wrong:** assuming those gates are enough. The guard treats `has_runtime_surface=true` as a
  *requirement*, not a pass: it then demands **`live_verify_passed=true` OR a `needs_verification_issue`**
  and exits non-zero (`BLOCKED: runtime-surface change lacks a live-verify pass…`) if neither is set. The
  `set` example in the flow protocol doesn't list `live_verify_passed`, so it's easy to finish the browser
  verify and still get blocked.
- **Correct:** after the live-verify actually passes, record it explicitly —
  `flowlib.py set live_verify_passed=true` — then re-run the guard. (Unlike `session_audit_ran`, this
  field is *not* protected, so a plain `set` works; but only set it once the verify genuinely passed.)
  For a predicted-non-live diff that reconciles to live where you're *not* doing a blocking verify, record
  a `needs_verification_issue` number instead.

## A create route that does secondary writes must not let them mask the create

- **Trigger:** a route that creates the primary record and then does one or more *follow-up* server
  writes in the same request — e.g. `POST /contacts` creating the contact card, then PUTing each selected
  group's `X-ADDRESSBOOKSERVER-MEMBER` list (#24).
- **Wrong:** letting a follow-up write's failure propagate. If the group PUT raises (a bare `DavError`
  from a 500/403, or `UnreachableError` on a transport drop — both subclass `DavError`) it reaches the
  app-level exception handler, which renders **"your change was NOT saved."** But the contact was already
  created and cached, so the user retries and makes a **duplicate**. Catching only `ConflictError` leaves
  every other failure on this path. (Also: never resolve the follow-up target with `_get_or_404` — a
  stale/crafted id would 404 *after* the create, and an id pointing at a non-group card would
  `set_group`-rewrite a normal contact into a group. Resolve with `store.get_by_uid` + require
  `is_group`.)
- **Correct:** the primary create is the commit point — once it succeeds, no secondary-write failure may
  raise past it. Catch `DavError` (covers `UnreachableError`) around each follow-up write, keep the
  contact, and **surface** the failed target to the user (e.g. a `?group_warn=` param rendered as a
  banner) rather than masking it. Surfacing ≠ masking: the create stands, the partial failure is visible
  and retryable.

## Page-scoped CSS via a bare `main` selector leaks to every page

- **Trigger:** wiring a "detail-page text size" (or any page-specific style) to `:root[data-…] main`,
  reasoning that the rule only matters where that content renders. Root `data-*` attributes are stamped
  on `<html>` on *every* page (they persist in localStorage and the pre-paint script runs everywhere).
- **Wrong:** `:root[data-size-detail-text="lg"] main { font-size: 1.35em }`. **Every** template
  (`index`, `form`, `birthdays`, `group`, `login`) renders a bare `<main>`, so the "detail text" knob
  silently resizes the contact list, the edit form, etc. Worse: the list/card size controls use `em`
  on containers *inside* `main`, so the two settings **compound multiplicatively** (detail-text=L ×
  card-text=L ≈ 1.35² instead of 1.35). A green unit suite won't catch it — nothing asserts computed
  cross-page sizing.
- **Correct:** give the page's own element a marker class (`<main class="contact-detail">`) and scope
  the rule to it (`:root[…] main.contact-detail`). Add a render test that the marker is present on the
  intended page and **absent** on the others, so the scoping can't silently regress. General rule: a
  root-attribute style must target a selector unique to where it should apply, never a tag shared across
  templates.

## Visually-hidden a11y labels: hide the field with `display:none`, not `visibility`/`opacity`

- **Trigger:** adding a screen-reader-only label (`<span class="sr-only">Phone: </span>`) inside a
  field span that a separate toggle (the #27 field selection) shows/hides.
- **Wrong:** assuming the label is inert when its field is deselected. It is only safe because #27's
  toggle uses `display:none` on the `.field-*` span — which removes the whole subtree (label included)
  from the render **and accessibility** tree. If someone later reimplements the field-hide with
  `visibility:hidden` or `opacity:0` (still "invisible" visually), the `.sr-only` label stays in the
  a11y tree, so a screen reader announces "Phone:" with **no value** for every deselected field.
- **Correct:** keep the field-hide on `display:none` (or `hidden`), and place the `.sr-only` label
  *inside* the toggled element so the two can't diverge. If the hiding mechanism ever changes, re-verify
  the deselected-field a11y tree, not just the visual result.

## Browser-verifying a session-gated page: cookies aren't port-scoped, and JS can't overwrite an HttpOnly session cookie

- **Trigger:** driving the app in a browser for a live GUI/a11y check by booting a throwaway server
  (seeded cache + an in-memory session id) and injecting the session via `document.cookie`.
- **Wrong:** setting `document.cookie = "peopledb_session=…"` on `http://127.0.0.1:<port>/` and
  expecting auth. A prior real login left an **HttpOnly** `peopledb_session` cookie for host
  `127.0.0.1`; JS silently cannot overwrite an HttpOnly cookie of the same name, so the set no-ops, the
  stale value is sent, and the server bounces you to `/login`. Changing the **port** does not help —
  cookies are scoped by host, not host:port, so `127.0.0.1:8100` shares the jar with `127.0.0.1:8099`.
- **Correct:** use a **different hostname** for a clean cookie jar — navigate to `http://localhost:<port>/`
  (distinct cookie host from `127.0.0.1`, same server). Then `document.cookie` sticks and the fetch to
  `/` returns 200. Confirm by reading `document.cookie` back before relying on it.

## Merging contacts: keep field-value choice separate from keeper identity

- **Trigger:** a merge UI where the user picks a *keeper* (the card that survives, keeps its UID and
  unknown props) **and** picks, per field, which card's value wins.
- **Wrong:** letting the "keeper" choice also drive which field value is written — e.g. review-screen
  radios valued `keeper`/`source` (resolved at submit against whichever card was chosen as keeper) while
  the labels/values shown are bound statically to card A / card B. Flip the keeper to card B and the
  mapping **inverts**: the value the user saw selected is discarded, the opposite value is written, and
  the card whose value they meant to keep is then **deleted** — silent data loss on a supported action.
- **Correct:** the keeper decides only *which card/UID/photo/unknown-props survive and which is deleted*
  — **never** which field VALUES win. Value the per-field radios by the card (`a`/`b`), resolve them
  from `contact_a`/`contact_b` independent of keeper, and validate the posted `keeper_uid` is one of the
  two cards. (`apply_edits` overwrites all managed props from the built fields regardless of whose raw is
  the base, so field values are genuinely independent of keeper — there is no reason to couple them.)
  See ADR-0006 and `merge.py`.

## Reusing a warning banner across flows garbles the message

- **Trigger:** a new flow (merge) surfaces a partial-failure warning and reuses an existing flow's
  `?warn=` query param + banner template.
- **Wrong:** merge reused #24's create-flow banner `"Contact saved, but could not be added to: {warn}."`
  Merge's own warn strings substitute into it → *"Contact saved, but could not be added to: 'Dana'
  could not be deleted."* On a **destructive** feature whose whole safety story is the user reading and
  acting on the warning (ADR-0006), a nonsensical warning is a real defect, not cosmetic.
- **Correct:** give each flow its own warning param + banner wording (`?merge_warn=` → "Merge completed
  with warnings: …"). And **test the rendered banner**, not just that the param is present in the
  redirect URL — a redirect-URL assertion passes while the sentence reads as garbage.

## A "Merge #N" commit does not close issue #N — only a `Closes` keyword does (2026-07-17)

- **Trigger:** merging a branch for issue #N with a commit subject like `Merge #N: <summary>`.
- **Wrong:** assuming the `#N` reference closes the issue. GitHub auto-closes an issue only when a commit
  pushed to the default branch (or a merged PR body) contains a **closing keyword** — `Closes`/`Fixes`/
  `Resolves #N`. A bare `Merge #N: …` subject just *links* the issue; it stays OPEN. This silently
  desynced the spine (which recorded #26/#30 as shipped/closed) from GitHub (both still OPEN) until a
  later `gh issue list` caught it.
- **Correct:** put `Closes #N` in the merge commit **body** (the `/flow` merge step now does this). When
  reconciling, trust `gh issue list`, not the merge-commit subject — and if an issue lingered open,
  `gh issue close N` manually rather than assuming the link closed it.

## A mid-session file swap (e.g. `/session-audit`) can silently unstage your edits before commit (2026-07-18)

- **Trigger:** you `git add -A` early, then later in the session something swaps files through the
  working tree and restores them — most commonly the cold `/session-audit` auditor checking out
  `main`'s version of a file (`git show main:… > file` / `git checkout main -- file`) to reproduce a
  test red/green, then restoring. Any such round-trip **resets the index** for those paths.
- **Wrong:** trusting the earlier `git add -A` and committing with `git commit` (no `-a`). The restored
  source files are now ` M` (worktree-modified, **unstaged**); only files staged *after* the swap (e.g. a
  brand-new test) get committed. Here `1fdb168` captured only the new test — the `app.py`/`vcard.py`/
  `detail.html` fix was left behind, and `main` briefly had the regression test **without** its fix
  (CI would have gone red). It survived review/audit because those ran against the working tree, which
  was correct — only the *commit* was truncated.
- **Correct:** immediately before committing, `git status -s` and confirm every intended path shows as
  staged (`M `/`A `, not ` M`); or just `git add -A` again (or `git commit -a`) right before the commit.
  After a merge/push, cheap-verify the change actually landed — `git show main:<file> | grep <marker>`
  for each source file, not just the test. The `/flow` merge guard checks gates, not diff *content*, so
  a truncated commit passes it.
- **Mitigation (2026-07-18):** `/flow` gained a `tree-check` pre-merge step that blocks exactly this —
  it fails the merge if the working tree has any uncommitted tracked change (or HEAD drifted off the
  gated commit), so a truncated commit no longer sails through. The manual `git status -s` habit above
  is still the first line of defence; `tree-check` is the backstop.

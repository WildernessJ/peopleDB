# CLAUDE.md — peopleDB

Guidance for Claude Code when working in this repo.

## What this is

**peopleDB** is a web app / API client for a **CardDAV server** (e.g. [Baikal](https://sabre.io/baikal/)).
The core domain is **contacts**: vCards fetched over CardDAV, exposed through a browsable web UI.

Think of it as a friendlier front-end over a CardDAV address book — not a new store of record. The CardDAV
server remains canonical; peopleDB reads and writes back against it.

## Status

**Working household CardDAV web client — public, `v1.0.0` released (2026-07-19).** v1 shipped
2026-07-13; the opening issue backlog is cleared. Current progress and next actions live in
[`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) — read it first.

## Architecture & invariants

The resolved shape of the system (the *why* for each is an ADR in [`docs/DECISIONS/`](docs/DECISIONS/)):

- **Stack** — Python/FastAPI, server-rendered Jinja2 + HTMX, SQLite cache, `uv` for env. No JS build
  step; `/static` holds only vendored htmx; first-party JS is inline in templates. (ADR-0001)
- **CardDAV layer** — a hand-rolled client over `httpx` in `dav.py` (PROPFIND discovery,
  sync-collection REPORT, etag-conditional PUT/DELETE). The off-the-shelf `caldav` lib is CalDAV-only —
  **don't reach for it** (PITFALLS). (ADR-0002)
- **Sync model** — the server is **canonical**; the local SQLite cache is disposable (delete = re-sync).
  Reads serve from cache; writes go server-first then update cache from the normalized response;
  incremental sync via sync-collection tokens with a full-resync fallback on invalid token. (ADR-0002)
- **Auth** — users log in with their CardDAV credentials; requests run **as that user** so the server's
  ACLs govern visibility. Credentials live in a Fernet-encrypted **in-memory** session store (no second
  user DB, nothing at rest), keyed by a `Secure` cookie with a sliding idle timeout. (ADR-0003)
- **Concurrency** — all DAV I/O runs off the event loop (`asyncio.to_thread`); SQLite is
  connection-per-thread + WAL; cache *mutations* go through the store helpers under a **per-user lock**.
  A new route that mutates the store outside those helpers silently reintroduces a write race — go
  through the helpers or take the lock; never hold the lock across an `await`. (ADR-0004, PITFALLS)
- **vCard** — 3.0 with Apple conventions (X-ABRELATEDNAMES, KIND=group via X-ADDRESSBOOKSERVER-KIND).
  Unknown *properties* are preserved on edit; managed-prop *params* are rewritten — a managed prop does
  **not** round-trip verbatim (PITFALLS). Source in `src/peopledb/` (vcard, store, dav, auth, app, sync,
  config, birthdays, photos).

## Workflow

Follows the global **Coding Workflow (v3 — model-per-phase, adopted 2026-08-09)** section in
`~/.claude/CLAUDE.md`, driven by `/flow`: **one change, three phases, three sessions** — plan and
review on the judgment model (default Fable), execute on the volume model (default Opus). Models are
defaults, not mandates. What is fixed is **phase discipline** (convention, not enforced — nothing can
read the session model): plan and review never implement, review runs in a **fresh** session, build
never merges.

- **Plan** (`/flow start`) — sitrep → worktree off `main` → settle design → **write and commit
  `specs/<slug>.md` on the feature branch** → light checkpoint on `main` (PROJECT_STATE in-flight
  line + one-line RUN_LOG; not the full `/checkpoint`). Ends at the spec, no implementation.
- **Execute** (`/flow build`) — arm `pending_verify: <slug>` in the MAIN checkout's `.workflow.yaml`
  **first, before implementing**, so a dead session can't end silently → build strictly from the
  spec, dispatching per its Execution routing → `uv run pytest -q` green → commit the whole change.
  Ambiguity or a stop criterion → append it to the spec's Execution Log and **halt**; design
  questions go back to a plan session.
- **Review** (`/flow review`, fresh session) — `verifier` + spec-conformance + the session's own
  judgment pass → `/session-audit` → live-verify → merge → clear `pending_verify` → full
  `/checkpoint`. `live_verify_mode: browser`, so `/flow review --auto` may self-verify — it prefers
  the `pytest -q -m live` command where that covers the change, and drives the card-view /
  quick-entry routes via Claude-in-Chrome for UI-only work.

**Floor:** trivial changes (a one-liner, a small bugfix) skip the cycle — fix in session with a repro
test; the GitHub issue is the spec. No handoff without a spec, no spec without a handoff.

**Concurrency work goes to `executor-max`.** This repo's per-user locks, `asyncio.to_thread` DAV I/O,
and connection-per-thread SQLite are exactly the shared-mutable-state shape that tier exists for
(ADR-0004, PITFALLS). Route it there in the spec's Execution routing section, and send anything
touching auth or the Fernet session store to the `security` agent.

- **Artifacts scale with the change.** ADRs in [`docs/DECISIONS/`](docs/DECISIONS/) (MADR format) only for
  hard-to-reverse, surprising trade-offs. **Specs are the v3 artifact, not v2's 30–60-line sketch**:
  `specs/<slug>.md`, committed on the feature branch, required for anything above the floor, with all
  eight sections — Intent · Design · Implementation plan (files, seams, signatures, edge cases) ·
  Execution routing · Tests (red-first list) · Verification (exact commands, done-looks-like) · Stop
  criteria · Execution Log (appended during execution). It freezes as history after merge.
- **Testing by change type.** Feature → `/tdd`. Bug → failing repro test first. Refactor → keep suite green.
  Network/UI-flavored work → live-verify against a real (or test) CardDAV server.
- **One review per change before merge:** dispatch the `verifier` agent on the full **committed** diff
  (untracked files are invisible to a diff ref), plus a spec-conformance check where a spec exists.
  Filter the report — the verifier reports everything and tags low-relevance items rather than
  withholding. `/code-review` is Jason's to fire by choice: Claude cannot invoke it (it is
  `disable-model-invocation`), must never claim it ran, and must never ask him to run it.
- **Bugs & enhancements are tracked as GitHub issues** (`WildernessJ/peopleDB`), not as lists in
  repo docs. File findings with `gh issue create` (labels: `bug` / `enhancement`).
- **Checkpointing is phase-specific under v3.** The plan session ends with a *light* checkpoint on
  `main` (in-flight line + one-line RUN_LOG, done by hand — the `/checkpoint` skill has no light
  mode); the review session ends with the full `/checkpoint`, closing the cycle the plan opened.
  Outside a `/flow` cycle, end substantive sessions with `/checkpoint` as before.

## Context system (the memory spine)

Committed, version-controlled project memory — read at session start, updated at session end:

- [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) — one-page current truth. **Read first.**
- [`docs/RUN_LOG.md`](docs/RUN_LOG.md) — append-only session history (newest first).
- [`docs/DECISIONS/`](docs/DECISIONS/) — the ADRs (why the non-trivial calls were made).
- [`docs/PITFALLS.md`](docs/PITFALLS.md) — topic-specific gotchas ("don't do X"), Trigger → Wrong → Correct.

A `.claude/` SessionStart hook auto-injects git state + the top of `PROJECT_STATE.md`. Run `/checkpoint`
at session end to keep the spine current.

> **This repo is public.** `WildernessJ/peopleDB` is a public repository, and git history is permanent —
> everything committed is immediately world-visible and cannot be un-published. Never commit secrets,
> credentials, private paths, internal hostnames/LAN IPs, or personal accounts — to the spine *or*
> anywhere else. A leaked secret must be rotated, not just edited out.

## Conventions

- **Dates:** ISO format (YYYY-MM-DD).
- **Secrets:** never commit CardDAV credentials or server URLs. Use env (`PEOPLEDB_*`) / a git-excluded
  config; document the shape in the README, not the values.

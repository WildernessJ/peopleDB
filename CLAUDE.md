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

@./docs/coding-workflow.md

(For anyone cloning this public repo: that import is a gitignored symlink and silently
resolves to nothing — fine, it carries no peopleDB-specific instruction.)

Repo-specific deviations and config only, from here down.

**Concurrency work goes to `executor-max`.** This repo's per-user locks, `asyncio.to_thread` DAV I/O,
and connection-per-thread SQLite are exactly the shared-mutable-state shape that tier exists for
(ADR-0004, PITFALLS). Route it there in the spec's Execution routing section, and send anything
touching auth or the Fernet session store to the `security` agent.

- **Live-verify is repo-shaped.** `live_verify_mode: browser`, so `/flow review --auto` may
  self-verify: it prefers `uv run pytest -q -m live` where that covers the change, and drives
  the card-view / quick-entry routes via Claude-in-Chrome for UI-only work. Network-flavored
  work verifies against a real (or test) CardDAV server.
- **Suite:** `uv run pytest -q`. ADRs in [`docs/DECISIONS/`](docs/DECISIONS/); specs in `specs/`.
- **Bugs & enhancements are tracked as GitHub issues** (`WildernessJ/peopleDB`), not as lists in
  repo docs. File findings with `gh issue create` (labels: `bug` / `enhancement`).

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

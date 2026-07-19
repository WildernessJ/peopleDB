---
status: Enacted
date: 2026-07-13
deciders: WildernessJ
phase: v1
---

# ADR-0002: Hand-rolled CardDAV client + local-cache write-through sync

> Recorded retrospectively on 2026-07-14 when the memory spine was adopted.

## Context

peopleDB fronts an existing CardDAV server that stays **canonical**. We need to read contacts
responsively, write edits back safely, and survive the server being briefly unreachable — without
becoming a second store of record. Two questions had to be answered together: what CardDAV client
to use, and what sync model to run.

## Decision

**Hand-rolled CardDAV client over `httpx`** (`dav.py`: PROPFIND discovery, sync-collection REPORT,
etag-conditional PUT/DELETE) feeding a **local SQLite cache with write-through**. The server is
canonical; the cache is disposable (delete = full re-sync). Reads serve from the cache; writes go
to the server first, then update the cache from the server's normalized response. Incremental sync
uses **sync-collection tokens**, with a **full-resync fallback** when the server rejects the stored
token as invalid. A background refresher keeps the cache warm and degrades loudly (offline banner,
surfaced write failures) when the server is unreachable.

## Alternatives considered

- **A — an off-the-shelf CardDAV library:** the obvious candidate was CalDAV-only (no addressbook
  support), so "battle-tested client" didn't hold; the needed surface (discovery, sync REPORT, etag
  writes) is small and well-specified, so hand-rolling was cheaper than fighting a mismatched lib.
- **B — read-only proxy (no cache):** every view would hit the server; too slow and fragile, and
  offers no offline degradation.
- **C — full two-way sync / local as co-authority:** turns the cache into a second store of record
  with conflict-merge complexity we don't need — the server is authoritative and write-through +
  etag-conditional writes (412 on conflict) covers the real cases.

## Consequences

- **Positive:** responsive reads, safe conflict-aware writes (etag/412), and graceful offline
  behavior; the cache can be deleted and rebuilt at any time.
- **Negative / trade-offs:** we own the CardDAV protocol edge cases (sync-token semantics vary
  across server implementations); some paths are verifiable only against a real server, so a
  test-server-only pass carries residual risk (tracked as live-verify debt).

## Confirmation

`uv run pytest -m live` boots a throwaway local CardDAV server and exercises discovery, sync-token
REPORT, write-through, and the invalid-token full-resync path. The invalid-sync-token recovery is
pinned by unit + live tests (see ADR notes / PITFALLS).

## Links

- Source: `specs/2026-07-13-peopledb-v1-design.md`
- Related ADRs: ADR-0001 (stack), ADR-0004 (the cache's concurrency model)

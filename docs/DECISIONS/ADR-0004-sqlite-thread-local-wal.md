---
status: Enacted
date: 2026-07-14
deciders: WildernessJ
phase: v1 (issues #5, #6)
---

# ADR-0004: Thread-local SQLite + WAL + per-user locks for cache concurrency

> Recorded retrospectively on 2026-07-14 when the memory spine was adopted.

## Context

The SQLite cache is written by concurrent request handlers and a background refresher. The original
design used a single global lock, which serialized *all* cache access across users. Removing it (to
let different users proceed in parallel) exposed **same-user races**: a stale sync batch could
clobber a fresh write-back, and a check-then-insert on the feed token was TOCTOU across connections.
We needed cross-user parallelism without reintroducing last-writer-wins within a user.

## Decision

Replace the global lock with **connection-per-thread SQLite + WAL journaling + per-method
transactions**. All CardDAV I/O runs off the event loop (`asyncio.to_thread`). Cache *mutations*
(`upsert` / `delete` / `set_sync_token`) for a given user run inside a **per-user `threading.Lock`**
via the store helpers, serializing that user's sync batches against their own write-backs while
different users run in parallel. WAL readers don't block writers, so cache *reads* stay inline on the
event loop. The feed-token creation was rewritten `INSERT OR IGNORE` + re-`SELECT` to remove the
cross-connection TOCTOU.

## Alternatives considered

- **A — keep the single global lock:** correct but serializes unrelated users; needless contention.
- **B — etag/freshness checks in the store:** more invasive and easy to get subtly wrong; the
  per-user lock is a minimal restoration of the prior serialization semantics with cross-user
  parallelism added.

## Consequences

- **Positive:** different users no longer block each other; per-user write ordering is preserved;
  no TOCTOU on token creation.
- **Negative / trade-offs:** a **new route that mutates the store directly, outside the helpers,
  silently reintroduces the race** — this is now a standing pitfall, not a compiler-enforced
  invariant. The lock must never be held across an `await` on the event loop.

## Confirmation

Store concurrency is covered by `tests/test_store_concurrency.py`. The per-user-lock convention and
its failure mode are recorded in `docs/PITFALLS.md` ("Concurrency: per-user lock convention"), which
is the review-checklist item for any new store-mutating route.

## Links

- Source: peopleDB issues #5, #6
- Related ADRs: ADR-0002 (the cache this governs)

# Architecture Decision Records — Index

> **Purpose:** the single entry point for *why* the non-trivial calls were made — one row
> per decision, with status, and how the ADRs relate.

This index complements the project guide (`CLAUDE.md`), which holds the **WHAT** (architecture,
invariants, scope). The ADRs are the **WHY / point-in-time detail**. When the guide and an ADR
appear to disagree, the guide is the *current rule* and the ADR is the *historical record* —
check the **Status** column first. Progress and history live in [`../PROJECT_STATE.md`](../PROJECT_STATE.md)
and [`../RUN_LOG.md`](../RUN_LOG.md); cross-session gotchas in [`../PITFALLS.md`](../PITFALLS.md).

Format: **MADR** (see [`ADR-TEMPLATE.md`](ADR-TEMPLATE.md)). ADRs 0001–0004 were recorded/reformatted
on **2026-07-14** when the memory spine was adopted (migrated from the older `docs/adr/` layout) —
their `date:` front matter carries the real decision date; the bodies note the retrospective recording.

## Status legend

| Status | Meaning |
|---|---|
| **Proposed** | Written; not yet committed to. |
| **Accepted** | Agreed and binding, but not necessarily in code yet. |
| **Enacted** | Accepted *and* realised in the codebase today. |
| **Superseded by ADR-XXXX** | Replaced by a later decision; kept for history. |
| **Deprecated** | No longer applies, not directly replaced. |

## The index

| ID | Title | Status | Date | Relations |
|---|---|---|---|---|
| [ADR-0001](ADR-0001-python-fastapi-htmx.md) | Python/FastAPI + HTMX stack | Enacted | 2026-07-13 | precedes 0002 |
| [ADR-0002](ADR-0002-carddav-sync-model.md) | Hand-rolled CardDAV client + local-cache write-through sync | Enacted | 2026-07-13 | pairs-with 0004 |
| [ADR-0003](ADR-0003-fernet-inmemory-sessions.md) | Auth via CardDAV credentials + Fernet-encrypted in-memory sessions | Enacted | 2026-07-13 | — |
| [ADR-0004](ADR-0004-sqlite-thread-local-wal.md) | Thread-local SQLite + WAL + per-user locks for cache concurrency | Enacted | 2026-07-14 | pairs-with 0002 |
| [ADR-0005](ADR-0005-ghcr-github-actions-deploy.md) | Ship images via GitHub Actions → ghcr.io; tag-based release contract (`:edge`/`:latest`) | Enacted · amended 2026-07-19 | 2026-07-15 | builds on 0001, 0003 |
| [ADR-0006](ADR-0006-merge-nontransactional-delete-last.md) | Merge is a non-transactional, delete-last sequence with no rollback | Accepted | 2026-07-16 | builds on 0002, 0004 |
| [ADR-0007](ADR-0007-shared-topbar-partial.md) | One shared top-bar partial; theme/accent/settings controls move in-flow | Accepted | 2026-07-17 | builds on 0001 |
| [ADR-0008](ADR-0008-public-release-history-squash.md) | Squash history to a single commit for the first public release | Enacted | 2026-07-19 | — |

## How to add a new ADR

1. **Pick the next number** (never reused, even if an ADR is later superseded) — next is **0009**.
2. **Copy [`ADR-TEMPLATE.md`](ADR-TEMPLATE.md)** to `ADR-NNNN-<short-slug>.md`; fill in front matter + body.
3. If it **supersedes** an existing ADR, set `supersedes:` here and `superseded-by:` + `status:` on the old one.
4. **Add a row above** and link it from `PROJECT_STATE.md` → References.

> **When to add one:** a real decision with alternatives and lasting consequences — a structural
> call, a tooling commitment, a guardrail, a deliberate deviation. Routine feature work and bugfixes
> do **not** earn an ADR; that history lives in `RUN_LOG.md`.

---
status: Accepted
date: 2026-07-16
deciders: WildernessJ
phase: post-v1 (feature #28)
---

# ADR-0006: Merge is a non-transactional, delete-last sequence with no rollback

## Context

Merging two contacts (#28) is inherently **multi-write**: update the surviving
("keeper") card with the unioned fields, rewrite every group whose member list
names the deleted ("source") card, then delete the source. CardDAV has **no
transaction** — each PUT/DELETE is an independent, etag-conditional HTTP request
against the canonical server (ADR-0002). Any request in the sequence can fail or
409/412 on a stale etag. There is no server primitive that makes the whole set
atomic, and the local SQLite cache is disposable, so a cache-level transaction
would not protect the source of truth. We must pick a failure model that cannot
silently lose contact data.

## Decision

Perform the merge as a **fixed-order sequence with a hard "delete last" rule and
no rollback**:

1. **Keeper PUT first**, etag-conditional. If the keeper's etag is stale, **abort
   the entire merge before any other write** and re-render with the existing
   conflict banner — the server is left completely untouched.
2. **Group moves** (source→keeper in each affected group's member list),
   etag-conditional. A failure here **warns but does not abort** and does not
   roll back the keeper (`?group_warn=` non-masking pattern, from #24).
3. **Source DELETE last**, etag-conditional. On failure, **warn**; the source
   card survives.

No step is ever undone. The keeper is only written once it holds the full union,
and the source is only deleted after the keeper safely holds that data — so the
worst outcome of any mid-sequence failure is a **harmless leftover duplicate**
(the merge simply didn't finish), never lost fields or lost group membership.

## Alternatives considered

- **A — attempt all-or-nothing with rollback:** if the source DELETE (or a group
  move) fails after the keeper PUT, re-PUT the keeper's pre-merge raw to "undo."
  Rejected — the rollback PUT can itself fail or conflict, so the atomicity it
  promises is **illusory on CardDAV**; it adds moving parts and a second failure
  surface to deliver a guarantee it cannot actually keep.
- **B — delete source first, then write keeper:** simpler ordering, but a failure
  after the delete and before the keeper PUT **destroys the source's data** —
  exactly the outcome we must never risk. Rejected outright.
- **C — batch/transaction extension (e.g. a server-side atomic op):** no such
  primitive in the hand-rolled client's target servers; would couple merge to a
  non-portable server feature. Rejected (YAGNI, portability).

## Consequences

- **Positive:** the failure floor is a benign duplicate the user can re-merge —
  never data loss. Reuses two proven patterns (ConflictError→conflict-banner for
  the pre-write abort, `?group_warn=` for non-masking post-write warnings). No new
  rollback code path to test or trust.
- **Negative / trade-offs:** a partially-applied merge is possible — keeper updated
  and source still present, or a group not yet moved. The user sees a warning and
  retries; the second run is idempotent-ish (union of already-unioned fields is a
  no-op; the group move / delete simply completes). Inbound `RELATED` to the source
  is **not** cleaned (accepted residual, see spec) — a separate, non-destructive
  gap, not part of this ordering decision.

## Confirmation

Enforced by the merge handler's control flow and covered by live tests
(`-m live`): a keeper-etag-conflict case asserting **zero** server writes; a
delete-fails case asserting the keeper holds the union **and** the source still
exists **and** a warning is surfaced; a group-move case asserting membership moved
source→keeper. `/code-review` + the `security` agent review the destructive path
before merge.

## Links

- Spec: `specs/2026-07-16-merge-duplicate-contacts.md`
- ADR-0002 (server canonical / etag-conditional writes), ADR-0004 (per-user lock)
- Issue #28

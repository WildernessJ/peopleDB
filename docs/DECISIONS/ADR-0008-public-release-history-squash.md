---
status: Accepted
date: 2026-07-19
deciders: WildernessJ
phase: pre-public-release
---

# ADR-0008: Squash history to a single commit for the first public release

## Context

`WildernessJ/peopleDB` was developed as a private repository and is being made
public. Git history is permanent and public forever once published: a clone
carries every blob from every commit, including files later deleted from the
working tree.

A full-history leak audit (read-only, all 114 commits across every ref) found
**no rotatable secret** — no CardDAV credentials, Fernet keys, API tokens, or
`PEOPLEDB_SECRET_KEY` values anywhere in history or the tree. It did find the
maintainer's **home-network topology** — a real CardDAV hostname under a
personal domain and a LAN IP with co-hosted-service detail — in the pre-spine
narrative handoffs (`docs/context/handoffs/`), present in **both** the current
tree and in history-only files that had already been removed from the tree
(`active-work.md`, an old `live-verify-pending.md`, an earlier `PITFALLS.md`).
A committed-then-removed SQLite WAL blob was also inspected and confirmed to
hold only test fixtures.

Because the leaks live in old commits, deleting the current files is not enough:
the strings survive in history. The options were (a) surgical history rewrite
(`git filter-repo`) preserving the 114-commit history minus the leaks, or
(b) squash the whole history into one fresh commit off a redacted tree.

## Decision

**Squash to a single "Initial public release" commit** off the cleaned working
tree, replacing `main`, before the repository is flipped to public.

Redactions applied to the tree first: removed `docs/context/handoffs/` in its
entirety (the whole topology-leak surface; the memory spine supersedes it),
scrubbed the maintainer's given name to the `WildernessJ` handle, generalized a
private tooling repo's name, and fixed the now-dangling references. Test
fixtures using `jason`/`hunter2` as a throwaway username/password are left as-is
(fixture data, not identity). The MIT `LICENSE` was added in the same pass.

## Consequences

- **Positive:** eliminates *all* history-only leaks by construction — there is no
  need to enumerate and catch every offending path, which is the failure mode of
  a surgical rewrite. The git history collapses, but the meaningful project
  narrative is preserved in the committed spine (`RUN_LOG.md`, the ADRs,
  `PITFALLS.md`), which was already written as public documentation.
- **Negative:** the granular per-commit development history is gone from the
  public repo. The GitHub issue history (#1–34) and the repo URL are retained by
  squashing the existing repo in place rather than starting a fresh one.
- **Residual risk (accepted):** force-pushing a squash over the existing repo can
  leave the old commits reachable by SHA on GitHub until garbage-collected. No
  external party has ever seen those SHAs (the repo was private throughout), and
  nothing in them is a rotatable secret — only topology — so the residual is
  low. A fresh repository would drive it to zero at the cost of the issue
  history; that trade was declined.

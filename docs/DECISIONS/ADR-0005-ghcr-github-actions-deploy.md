---
status: Accepted (amended 2026-07-19 — see Amendment)
date: 2026-07-15
deciders: WildernessJ
phase: post-v1 (deployment)
---

# ADR-0005: Ship images via GitHub Actions → ghcr.io, deploy on Unraid from `:latest`

## Context

The v1 deploy was a container built by hand on a Mac (`docker build --platform linux/amd64`) and
`docker run` on the Unraid box — untracked, unrepeatable, and cross-arch-fiddly. We want a formal path:
an image built from the repo, published on merge, and consumed as a first-class **managed** container
in the Unraid Docker tab. The repo is private today but destined to go public, so the registry choice
must not commit us to leaking anything and should stay in the GitHub ecosystem we already use. Unraid
is amd64.

## Decision

CI builds and publishes on GitHub Actions to **GitHub Container Registry (`ghcr.io`)**. A workflow
gates on the unit suite (`uv run pytest`, live tests excluded), then builds **`linux/amd64` only** and
pushes to `ghcr.io/wildernessj/peopledb` with three tag classes: `:latest` (default branch only),
`:vX.Y.Z` (on a `v*` git tag — the deliberate marked release), and `:sha-<short>` (every build, for
pinning/rollback). The package stays **private**; Unraid pulls it via a one-time read-only PAT login.
Deployment is a committed Unraid template (`unraid/peopledb.xml`) with named env fields; updates are
**manual** — a new `:latest` surfaces "update ready" in the Docker tab and the maintainer applies it. No
auto-update plugin, no arm64, no Docker Hub mirror, no version automation.

## Alternatives considered

- **A — Docker Hub:** familiar, but a second account/registry outside GitHub and public-by-default on
  the free tier, which fights the "don't signal readiness before the repo flip" constraint.
- **B — public ghcr image now:** zero-auth pull on Unraid (simplest), but publishes the image before
  the repo goes public. Rejected for parity: the image goes public when the repo does, not before.
- **C — auto-update (CA Auto Update plugin):** hands-off, but deploys land unwatched. Rejected —
  "manage it in my Docker tab" wants deploys on click, not on a timer.
- **D — keep building by hand:** the status quo; unrepeatable and cross-arch-painful. Rejected.

## Consequences

- **Positive:** every merge to `main` yields a reproducible, tested amd64 image; the Apple-Silicon →
  amd64 cross-build dance is gone (GH runners are amd64); rollback is pinning a `:sha-…`/`:vX.Y.Z`
  tag; the Unraid container is declarative and managed, not a shell-history `docker run`.
- **Negative / trade-offs:** a private image means Unraid needs a stored registry PAT (one-time, but a
  credential to rotate/track). The `:latest` gate is the **non-live** suite only — a bug only the live
  tests would catch can still reach `:latest` (mitigated: live tests run locally in `/flow` before
  merge). Publishing is coupled to `main`, so a broken merge is a broken `:latest` until the next push
  (manual-update means it isn't auto-pulled, which softens this).

## Confirmation

The workflow (`.github/workflows/docker-publish.yml`) is the enforcement: a red `pytest` job blocks
the publish, so a `:latest` push implies a green unit suite. Presence of the expected tags in the
ghcr **Packages** view after a merge confirms the pipeline ran. The Unraid template
(`unraid/peopledb.xml`) is the review-checklist artifact for the deploy shape — env fields, `/data`
volume, port. Image visibility (private until the repo flips) is a manual review item at the
public-visibility flip.

## Amendment (2026-07-19) — public-release tagging contract

**Trigger.** The repo (and, at the flip, the ghcr package) goes public. The original tag scheme made
`:latest` = tip of `main` (every merge). Docker convention is that `:latest` = the newest *stable*
release, and `docker run …/peopledb` defaults to `:latest` — so an outside user would land on
mid-feature `main`. This is a **tagging** problem, not a branching one.

**Considered and rejected: a stable/dev branch split (git-flow).** A long-lived second branch earns its
keep only when an old release line must be patched while `main` diverges toward the next major — i.e.
users on 1.x you must support while building 2.x. Not this project: solo maintainer, one deploy, no
supported legacy line. The cost (backporting across branches, divergence, release-branch bookkeeping)
buys nothing here, and it wouldn't fix the `:latest` semantics anyway. **We stay trunk-based.**

**Revised decision.** Stability is expressed through **tags, not branches**:

- `:edge` — tip of `main`, every merge (the old `:latest` behaviour, renamed and opt-in).
- `:X.Y.Z`, `:X.Y`, `:X` — on a `v*` git tag, the deliberate marked release, rolling. The `v` prefix is
  dropped from the image tag (`v1.2.0` git tag → `1.2.0` image tag) per Docker convention. `:X` is
  emitted for `>= 1.0.0`.
- `:latest` — moved to the **newest non-prerelease** release only (a `-` in the tag ref, e.g.
  `v1.2.0-rc1`, is excluded).
- `:sha-<short>` — unchanged, every build.

Release flow is a one-line `git tag v1.2.0 && git push --tags` — the "stable vs dev" line is a tag, not
a branch.

**Deploy / homelab.** The LAN deploy's Watchtower target is now an explicit choice, decoupled from what
the public pulls: `:edge` keeps riding tip-of-main (prior behaviour), or `:latest` moves only on a
release. This supersedes the ADR title's "deploy … from `:latest`" for the new tag semantics.
**Resolved (2026-07-19):** the LAN deploy tracks **`:edge`** — the user-instance Unraid template and the
live container were switched off `:latest`; the public repo template stays `:latest`.

**Package visibility.** The original decision kept the ghcr package **private** (Unraid pulling via a
read-only PAT) to avoid signalling readiness before the repo flip — the position Alternative B deferred
("the image goes public when the repo does, not before"). At the public flip the package is made
**public**, so `docker pull` needs no auth and the stored Unraid PAT is no longer required for pulls.

**Confirmation.** The enforcement is the same workflow; the tag change lives entirely in the
`docker/metadata-action` `tags:`/`flavor:` block. After the next release tag, the ghcr **Packages** view
should show `:latest`, `:X.Y.Z`, `:X.Y`, `:X`; after a plain merge to `main`, only `:edge` and `:sha-…`
move.

## Links

- Source PR: infra/ghcr-unraid-deploy
- Related ADRs: ADR-0001 (stack — the `uv` build this packages), ADR-0003 (why `PEOPLEDB_SECRET_KEY`
  must be fixed across restarts, which the Unraid template enforces as a required field)

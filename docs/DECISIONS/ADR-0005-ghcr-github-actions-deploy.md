---
status: Accepted
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

## Links

- Source PR: infra/ghcr-unraid-deploy
- Related ADRs: ADR-0001 (stack — the `uv` build this packages), ADR-0003 (why `PEOPLEDB_SECRET_KEY`
  must be fixed across restarts, which the Unraid template enforces as a required field)

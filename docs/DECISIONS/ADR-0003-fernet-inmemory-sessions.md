---
status: Enacted
date: 2026-07-13
deciders: WildernessJ
phase: v1
---

# ADR-0003: Auth via CardDAV credentials + Fernet-encrypted in-memory sessions

> Recorded retrospectively on 2026-07-14 when the memory spine was adopted.

## Context

peopleDB needs authenticated, per-user access to the CardDAV server, at household scale. The
CardDAV server already owns identity and access control (its own accounts and ACLs). We must hold
each user's CardDAV credentials long enough to make requests on their behalf, without standing up a
parallel identity system or persisting credentials to disk.

## Decision

Users log in with their **CardDAV-server credentials**; peopleDB makes CardDAV requests **as that
user**, so the server's own ACLs govern what each user can see. The session holds the credentials in
a **Fernet-encrypted, in-memory store** (no second user database, no on-disk credential storage),
keyed by an encrypted session cookie with a **sliding idle timeout**. There is no separate password
store to breach.

## Alternatives considered

- **A — a local user/password database:** a second identity system to secure, migrate, and reconcile
  with the CardDAV server's accounts — unnecessary when the server already authenticates.
- **B — persisting credentials (e.g. in the SQLite cache):** credentials on disk is a larger attack
  surface; keeping them in-memory-only means a process restart simply requires re-login (accepted).

## Consequences

- **Positive:** no parallel identity system; the CardDAV server remains the single source of auth
  and authorization; no credentials at rest.
- **Negative / trade-offs:** sessions do not survive a process restart (users re-login); the session
  cookie is the only key to the encrypted credentials, so cookie transport security is load-bearing
  (see Confirmation).

## Confirmation

The session cookie is `Secure` by default (plain-HTTP local dev is the only opt-out, via an env
flag) — see PITFALLS "Secrets / TLS". The sliding idle timeout is unit-tested; internal background
polling must not reset the idle clock (a regression caught in review and guarded).

## Links

- Source: `specs/2026-07-13-peopledb-v1-design.md`
- Related ADRs: ADR-0002 (the per-user CardDAV requests this enables)

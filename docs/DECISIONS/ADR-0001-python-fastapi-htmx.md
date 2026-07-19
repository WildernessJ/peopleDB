---
status: Enacted
date: 2026-07-13
deciders: WildernessJ
phase: v1
---

# ADR-0001: Python/FastAPI + HTMX stack

> Recorded retrospectively on 2026-07-14 when the memory spine was adopted; migrated from
> the original `docs/adr/0001`. The `date:` above is the real decision date.

## Context

peopleDB is a Cardhop-style web client for an existing CardDAV server (sabre/dav family),
at household scale (a few users, hundreds of contacts). The project's real risk lives in
**CardDAV/vCard correctness**, not front-end framework power. Candidate stacks: Python/FastAPI
+ HTMX; Python API + React SPA; full TypeScript (SvelteKit/Next with `tsdav`/`vcard4`).

## Decision

Python/FastAPI with server-rendered Jinja2 + HTMX for the UI, `vobject` for vCard parsing,
SQLite for the local cache, and `uv` for environment management. A single server-rendered
codebase, no separate front-end build.

## Alternatives considered

- **A — Python API + React SPA:** a second codebase, an API contract, duplicated models, and a
  JS build pipeline — cost not justified when HTMX partial updates cover the needed interactivity
  (search-as-you-type, inline edit, a future command bar) at this scale.
- **B — Full TypeScript (tsdav / vcard4):** the TS CardDAV/vCard libraries are younger and would
  push more protocol edge cases (sync-token REPORTs, etag handling, unrendered-property round-trip)
  into hand-rolled code. Python's ecosystem was the safer bet for the protocol surface.

## Consequences

- **Positive:** one codebase, minimal build tooling, fastest path to a working v1; matches sibling
  projects' tooling (`uv`, pytest). The FastAPI backend survives a later migration to a richer
  front-end if the UI outgrows HTMX.
- **Negative / trade-offs:** a highly dynamic UI (drag-and-drop, optimistic updates) costs more
  fragment endpoints than an SPA would — accepted at this scale.

## Amendment (2026-07-13, same day)

The originally-named CardDAV client library turned out to be **CalDAV-only** — no addressbook
support despite the name. Replaced with a small **hand-rolled CardDAV layer over `httpx`**
(PROPFIND discovery, sync-collection REPORT, etag-conditional writes; see ADR-0002), verified live
against a local CardDAV server. `vobject` is unaffected. The Python choice stands: the protocol
surface needed is small and well-specified.

## Confirmation

The repo builds and tests under `uv` (`uv run pytest`); the UI is HTMX/Jinja with no JS build step
(`/static` holds only vendored htmx). Any move to a separate front-end would supersede this ADR.

## Links

- Source: `specs/2026-07-13-peopledb-v1-design.md`
- Related ADRs: ADR-0002 (the CardDAV/sync layer this stack sits on)

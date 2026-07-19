---
name: checkpoint
description: Use at the end of a working session, before finishing or committing, to persist project
  memory and keep the docs current — runs a fast doc-drift sweep (fixing stale status/version/link
  drift), adds an ADR if a non-trivial decision was made, updates docs/PROJECT_STATE.md, prepends
  a docs/RUN_LOG.md entry, and records any new gotcha in docs/PITFALLS.md.
---

# Checkpoint — persist project memory

Run this before wrapping up a session so the **committed memory spine** reflects reality. The spine
lives in the repo (version-controlled, rides along in the session's commit/PR) — distinct from any
tool's machine-local auto-memory.

## Steps

1. **Review what changed this session.** Run `git status` and `git diff --stat`. Recall the session's
   goal, what actually changed, and what's still open.

2. **Doc-drift sweep** (keep the docs honest — a *fast, mechanical* pass, not a full audit). Establish
   **ground truth from code/config/git, not from another doc**, then scan for drift against it:
   - **Status drift.** Anything naming a phase/stage, "complete/planned/pending", PR numbers, or dates
     as a *current* claim — does it still hold? Usual offenders: `README.md`, `PROJECT_STATE.md`
     "Last updated" / "Verification" lines.
   - **Version / fact drift.** Tool versions, dependency versions, module/file names, IDs, paths,
     command targets — grep the value and confirm it matches the project's actual config files.
   - **Broken internal links.** Verify the target of each changed/added relative `.md` link exists.
   - **Duplication that drifted.** If two docs state the same fact and now disagree, the one that isn't
     the authority is the bug — fix it to *point at* the authority rather than re-state it.

   **Scope it to the session.** Default to the docs this session plausibly affected (what `git diff`
   touched, plus `README` / `CLAUDE.md` / the spine). A full repo-wide audit is a separate task.

   **Fix policy:**
   - **Auto-fix** unambiguous drift (stale status line, wrong version string, dead link, a duplicated
     fact that should be a pointer). Make the minimal edit.
   - **Never rewrite history.** `RUN_LOG.md` entries and ADR decision bodies are point-in-time records —
     do not "correct" them. If an ADR's body states a fact later superseded, record the supersession in
     its front matter (`status`, `superseded-by`) and in `DECISIONS/README.md` (with a dated note);
     never edit the body itself.
   - **Surface, don't guess.** If a discrepancy needs a judgment call, list it for the user instead of editing.

3. **Add an ADR** *only if* a non-trivial decision was made this session (a choice with alternatives and
   lasting consequences — a structural call, a tooling commitment, a guardrail, a deliberate deviation).
   Routine feature work and bugfixes do **not** earn an ADR. Copy `docs/DECISIONS/ADR-TEMPLATE.md` to
   `docs/DECISIONS/ADR-NNNN-<slug>.md` (next number in sequence), fill it in (MADR format), and add its
   row to `docs/DECISIONS/README.md`. Steps 4–5 link to it.

4. **Update `docs/PROJECT_STATE.md`** (keep it ~one page):
   - Bump `_Last updated:_` to today (with a one-line "what changed + what's next").
   - Refresh **Current position** (Verification line with real numbers), **Recently shipped**,
     **Next actions**, and **Open questions** (linking any ADR from Step 3).

5. **Prepend an entry to `docs/RUN_LOG.md`** at the **top** (newest first), using the template in that
   file: Goal, Did, Verified (commands/tests + results, or "n/a"), Open/blockers, and which memory
   artifacts you updated (linking any ADR from Step 3). Include the sweep's fixes/flags from Step 2.

6. **Record any new gotcha in `docs/PITFALLS.md`** — a cross-session "don't do X / do Y" that isn't a
   decision (append-only; supersede, don't delete). Distinct from an ADR: pitfalls are *traps*, ADRs are
   *choices*.

7. **Report** a short summary of what you updated — including what the sweep fixed and anything it
   flagged. Do **not** commit unless the user asks — surface the changed files so they can review. The
   normal expectation is that spine updates ride along with the session's work in the same commit/PR.

## Guardrails

- **The spine is DESTINED TO BE PUBLIC — write for the public.** `WildernessJ/peopleDB` is private today
  but intended to go public once it's more ready, and **git history is permanent** — anything written to
  the spine now becomes public at that flip. So write every `PROJECT_STATE` / `RUN_LOG` / `PITFALLS` / ADR
  entry as public documentation from the start: **no secrets, credentials, tokens, or private paths
  (`/Users/...`, `unraid:/...`); no internal hostnames or LAN IPs (use "the LAN deploy" / "an internal
  host"); no personal accounts, usernames, or infrastructure details; and no candor that would embarrass
  or hand a reader an exploitable, unmitigated weakness** — record *what* was decided, not a live attack
  recipe. Sharp internal reasoning that fails this bar stays in a private channel, not the spine. A slip
  can't be un-published: a leaked secret must be **rotated**, not just edited out. If unsure whether
  something is safe to commit, surface it for the user instead of writing it.
- **Write surface.** The memory steps (3–6) write **only** to `docs/PROJECT_STATE.md`, `docs/RUN_LOG.md`,
  `docs/DECISIONS/`, and `docs/PITFALLS.md`. The doc-drift sweep (Step 2) may also edit other docs **but
  only to correct verified drift** per its fix policy — never to add features, restructure, or rewrite
  content. Never touch code.
- Do not duplicate architecture/scope rules into the spine — those live in `CLAUDE.md`. The spine tracks
  *progress and decisions*, then *points* at the authority.
- The sweep is a **fast scan, not a full audit.** If it balloons, stop and tell the user a full doc audit
  is warranted as its own task.
- If nothing meaningful changed, it's fine to run a quick sweep, prepend a brief RUN_LOG entry, and skip
  the rest. Don't manufacture state changes.

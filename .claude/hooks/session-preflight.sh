#!/usr/bin/env bash
# SessionStart "Context Preflight" hook.
# Injects current git state + the top of docs/PROJECT_STATE.md into the agent's context
# at the start of each session, so work resumes against the committed memory spine.
# Output goes to the agent via the SessionStart hook's additionalContext field.
set -euo pipefail

# Hooks run with $CLAUDE_PROJECT_DIR set to the project root; fall back to cwd.
DIR="${CLAUDE_PROJECT_DIR:-$PWD}"

ctx="$(
  {
    echo '## Git state'
    git -C "$DIR" status --short --branch 2>/dev/null || echo '(not a git repo)'
    echo
    echo '## Recent commits'
    git -C "$DIR" log --oneline -10 2>/dev/null || true
    echo
    echo '## docs/PROJECT_STATE.md (top — read this, then the latest docs/RUN_LOG.md entry)'
    head -n 60 "$DIR/docs/PROJECT_STATE.md" 2>/dev/null || echo '(PROJECT_STATE.md not found)'
  }
)"

jq -n --arg ctx "$ctx" \
  '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'

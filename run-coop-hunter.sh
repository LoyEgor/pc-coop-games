#!/usr/bin/env bash
# coop-hunter overnight runner (macOS / Linux)
#
# Differences from the Windows .ps1 version:
#   - max_phase=4 (cascading: easy → medium → niche → re-evaluation + exhaustive)
#   - auto_push_every_n=25 (commits and pushes to GitHub after every 25 added games)
#   - Goal is only marked done when a full phase yields 0 new games
#
# Usage:
#   1. Open Terminal
#   2. cd "/path/to/Games for Two 2"
#   3. ./run-coop-hunter.sh
#
# First time: chmod +x run-coop-hunter.sh
#
# To stop: Ctrl+C. State is persistent — safe to restart later, picks up exactly where it stopped.

set -u

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
PROGRESS_FILE="$REPO_ROOT/.claude/skills/coop-hunter/state/progress.json"
TRANSCRIPT="$REPO_ROOT/coop-hunter-transcript.log"

cd "$REPO_ROOT"

# -------- locate claude CLI --------
CLAUDE_CMD=""
if command -v claude >/dev/null 2>&1; then
  CLAUDE_CMD="$(command -v claude)"
elif [ -x "$HOME/.npm-global/bin/claude" ]; then
  CLAUDE_CMD="$HOME/.npm-global/bin/claude"
  export PATH="$HOME/.npm-global/bin:$PATH"
elif [ -x "/opt/homebrew/bin/claude" ]; then
  CLAUDE_CMD="/opt/homebrew/bin/claude"
  export PATH="/opt/homebrew/bin:$PATH"
elif [ -x "/usr/local/bin/claude" ]; then
  CLAUDE_CMD="/usr/local/bin/claude"
fi

if [ -z "$CLAUDE_CMD" ]; then
  echo "ERROR: claude CLI not found in PATH, ~/.npm-global/bin, /opt/homebrew/bin, or /usr/local/bin." >&2
  echo "Install with: npm install -g @anthropic-ai/claude-code" >&2
  exit 1
fi

# -------- locate python3 --------
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "ERROR: python3 not found. Install via Homebrew: brew install python" >&2
  exit 1
fi

# -------- seed progress.json with Mac config --------
mkdir -p "$(dirname "$PROGRESS_FILE")"
"$PY" - "$PROGRESS_FILE" <<'PYEOF'
import json, os, sys
path = sys.argv[1]
defaults = {
  "current_source_idx": 0,
  "current_offset": 0,
  "current_phase": 1,
  "max_phase": 4,
  "phase_start_count": 0,
  "added_count": 0,
  "skipped_count": 0,
  "last_validation_at": 0,
  "auto_push_every_n": 25,
  "last_push_at": 0,
  "completed_sources": [],
  "done": False,
  "last_added": None,
  "last_run_timestamp": None,
}
if os.path.exists(path):
    with open(path) as f:
        cur = json.load(f)
else:
    cur = {}

# Backfill missing fields. Force Mac-specific settings even if already present
# (in case file was created by Windows runner with different values).
for k, v in defaults.items():
    if k not in cur:
        cur[k] = v
cur["max_phase"] = 4
cur["auto_push_every_n"] = 25

with open(path, "w") as f:
    json.dump(cur, f, indent=2)
print(f"progress.json initialized: max_phase=4, auto_push_every_n=25, added_count={cur['added_count']}, current_phase={cur['current_phase']}")
PYEOF

# -------- header --------
echo ""
echo "================================================================"
echo "  coop-hunter — overnight runner (macOS, cascading + auto-push)"
echo "================================================================"
echo "  Started:       $(date)"
echo "  Repo:          $REPO_ROOT"
echo "  Claude CLI:    $CLAUDE_CMD"
echo "  Transcript:    $TRANSCRIPT"
echo ""
echo "  Cascading enabled: 4 phases. Goal closes only when a phase adds 0 games."
echo "  Auto-push enabled: commits + pushes every 25 added games."
echo "  Permissions auto-approved (--dangerously-skip-permissions)."
echo "  Auto-restart on early exit (up to 20 times)."
echo ""
echo "  To stop: Ctrl+C. State is persistent — safe to restart later."
echo "================================================================"
echo ""

# -------- the one-shot prompt --------
GOAL_PROMPT=$(cat <<'PROMPT_EOF'
/goal Run the coop-hunter skill from .claude/skills/coop-hunter/ to expand data.js with new PC co-op games.

This is the macOS overnight run. progress.json has been seeded with max_phase=4 and auto_push_every_n=25.

Strict rules (read SKILL.md, classification.md, and sources.json before starting):

1. Process candidates sequentially. Sleep 1.5s between Steam API calls. Process ONLY 3-5 candidates per turn before returning control.

2. Persist progress to state/progress.json AFTER EVERY game added or skipped. Append to state/added.tsv and state/skipped.tsv. Non-negotiable.

3. Run validation pass (spawn fresh general-purpose Agent) every 50 added games. Log failures to state/validation-fails.tsv.

4. AUTO-PUSH IS ENABLED. After every 25 added games (since the last push), commit data.js and the state files to git and push to origin. Use the exact procedure in SKILL.md "Auto-push" section. If git push fails, log to state/push-fails.tsv and continue — do not halt.

5. CASCADING IS ENABLED. When all sources of the current phase are completed:
   - If that phase added > 0 games AND current_phase < 4 → escalate to next phase (procedure in SKILL.md "Phase transition logic").
   - If a phase adds 0 games OR current_phase == 4 is exhausted with 0 new → set done=true and STOP.

6. Phase 4 has special source methods (revalidate_existing, reeval_skipped, steam_more_like_this, websearch_queries). Read SKILL.md "Phase 4 source methods" for each. revalidate_existing is especially important — it catches false positives like Deep Rock Galactic / Lethal Company / R.E.P.O. that may have been added as finite but are actually endless. Log mismatches to state/bad-existing.tsv (do NOT auto-remove entries).

7. NEVER ASK QUESTIONS. For every decision, use the deterministic rules in classification.md. If a candidate is genuinely ambiguous, log to skipped.tsv with reason "ambiguous" and continue. The user is asleep.

8. If a tool call fails, retry once with 5s extra sleep. On second failure, log and continue. Do NOT halt for transient errors.

9. Do NOT modify app.js, index.html, or styles.css. Modify data.js only via scripts/append_entry.py.

10. Spawn sub-agents one at a time (sequentially, not in parallel) when delegating source-scraping or candidate evaluation. Each sub-agent should handle ONE specific task and return its output. This keeps per-turn token usage modest.

Continue until done=true. Output a single summary line every 10 additions: "[P=phase N=added K=skipped src=source_id last=<title>]".

Make autonomous, conservative, rule-based decisions. When in doubt, SKIP rather than add — quality beats volume. The user will review the morning's git history.
PROMPT_EOF
)

# -------- read initial state for delta tracking --------
INITIAL_ADDED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['added_count'])")
echo "Starting added_count: $INITIAL_ADDED"
echo ""

# -------- start transcript (script command captures interactive output) --------
# 'script' on macOS writes the entire session to a file while still showing it live.
USE_SCRIPT=0
if command -v script >/dev/null 2>&1; then
  USE_SCRIPT=1
fi

# -------- main loop --------
MAX_RESTARTS=20
RUN=0

while true; do
  RUN=$((RUN + 1))
  echo ""
  echo "[$(date)] ============ Run #$RUN ============"
  echo ""

  if [ "$USE_SCRIPT" -eq 1 ]; then
    # macOS script syntax: script [-a] file command ...
    script -a -q "$TRANSCRIPT" "$CLAUDE_CMD" --dangerously-skip-permissions "$GOAL_PROMPT"
  else
    "$CLAUDE_CMD" --dangerously-skip-permissions "$GOAL_PROMPT"
  fi

  # Check state after claude exits
  if [ ! -f "$PROGRESS_FILE" ]; then
    echo ""
    echo "[$(date)] WARNING: progress.json missing after run. Stopping." >&2
    break
  fi

  ADDED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['added_count'])")
  SKIPPED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['skipped_count'])")
  DONE=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['done'])")
  PHASE=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['current_phase'])")

  echo ""
  echo "[$(date)] Claude exited. added=$ADDED skipped=$SKIPPED done=$DONE phase=$PHASE"

  if [ "$DONE" = "True" ] || [ "$DONE" = "true" ]; then
    echo ""
    echo "[$(date)] SKILL DONE."
    break
  fi

  if [ "$RUN" -ge "$MAX_RESTARTS" ]; then
    echo ""
    echo "[$(date)] Max $MAX_RESTARTS restarts reached. Stopping." >&2
    break
  fi

  echo ""
  echo "[$(date)] Restarting claude in 30s. Ctrl+C to stop."
  sleep 30
done

# -------- final report --------
echo ""
echo "================================================================"
echo "  Finished at $(date)"
echo "================================================================"
if [ -f "$PROGRESS_FILE" ]; then
  FINAL_ADDED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['added_count'])")
  FINAL_SKIPPED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['skipped_count'])")
  DELTA=$((FINAL_ADDED - INITIAL_ADDED))
  echo "  Added this session:   $DELTA"
  echo "  Total added:          $FINAL_ADDED"
  echo "  Skipped total:        $FINAL_SKIPPED"
fi
echo ""
echo "Review:"
echo "  Transcript:        $TRANSCRIPT"
echo "  Added games:       $REPO_ROOT/.claude/skills/coop-hunter/state/added.tsv"
echo "  Skipped:           $REPO_ROOT/.claude/skills/coop-hunter/state/skipped.tsv"
echo "  Validation fails:  $REPO_ROOT/.claude/skills/coop-hunter/state/validation-fails.tsv"
echo "  Bad existing:      $REPO_ROOT/.claude/skills/coop-hunter/state/bad-existing.tsv"
echo "  Push fails:        $REPO_ROOT/.claude/skills/coop-hunter/state/push-fails.tsv"
echo ""
echo "Git log of overnight commits:"
git log --oneline -n 30 origin/main..HEAD 2>/dev/null || git log --oneline -n 10

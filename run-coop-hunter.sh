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
/goal Run the coop-hunter skill (.claude/skills/coop-hunter/) to expand data.js with PC co-op games and fix broken entries. Mac overnight; progress.json already has max_phase=4 and auto_push_every_n=25.

Read SKILL.md, classification.md, sources.json first — they hold the full procedure. This prompt is the contract; the details live in those files.

RULES (non-negotiable):

1. Sequential, 3–5 candidates per turn, 1.5s sleep between Steam API calls.

2. Persist state after every add or skip: progress.json + added.tsv / skipped.tsv. Resume relies on this — without it a crash loses work.

3. Auto-push every 25 adds per SKILL.md "Auto-push". Push failure → log push-fails.tsv, continue, never halt.

4. Cascade phases 1→4. Phase finished with yield>0 AND current_phase<4 → escalate. Phase 4 fully exhausted → set done=true.

5. Phase 4 = revalidate_existing (auto-removes endless via remove_entry.py, auto-fixes YouTube via fix_youtube.py, auto-fixes images via fix_image.py) + reeval_skipped + steam_more_like_this + websearch_niche_queries + drill sources (Backloggd top-completed, Steam community, YouTube curator playlists, Reddit just_finished, Wikipedia). Run revalidate_existing BEFORE declaring done.

6. NEVER ASK QUESTIONS. Use classification.md. Ambiguous candidate → skipped.tsv reason "ambiguous", continue. The user is asleep.

7. NEVER touch app.js / index.html / styles.css. data.js only via append_entry.py (exits 4 without a real 11-char video_id; exits 3 if id is in removed-entries.tsv).

8. DRILL MODE — don't give up on the first failure:
   - YouTube not found → run §8's 6-query cascade, then Steam page scrape, then youtube.com/results, then Reddit. Refuse only after all exhaust.
   - Source 403/404/empty → use the fallback in state/NOTES.md, write a substitute query, or pull from a different domain.
   - Phase yield 0 → re-check with a fresh page-window before declaring exhausted.
   - Niche WebSearches dry → Wikipedia "List of cooperative video games", Backloggd top-completed, Steam community discussions.
   - Treat "I couldn't find X" as a hypothesis to disprove, not an exit signal.

9. Tool call fails → retry once with +5s sleep. Second fail → log, continue.

10. Sub-agents sequentially, one task each, not in parallel.

Stop only when ALL hold: every source in every phase exhausted, phase 4 revalidate_existing actually ran, every auto-fixable image/video got fixed-or-logged-as-irrecoverable. Phase 4 yield=0 alone is NOT enough.

Output every 10 adds: "[P=phase N=added K=skipped src=source_id last=<title>]".

Doubt about adding → SKIP. Doubt about giving up on a search → KEEP DRILLING. User reviews the git history in the morning.
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
# Crash restarts (process died for non-rate-limit reasons) are capped at
# MAX_RESTARTS. Rate-limit pauses are NOT counted — we just sleep until the
# Anthropic 5-hour window resets and try again. This lets the script run
# overnight / multi-day without you having to babysit the token quota.
MAX_RESTARTS=200
RATE_LIMIT_SLEEP=1800   # 30 minutes — typical Anthropic 5h window reset granularity
CRASH_SLEEP=30
RUN=0
CRASH_COUNT=0

is_rate_limited() {
  # Inspect the tail of the transcript for Anthropic rate-limit markers.
  # The exact message has varied across versions; we match generously.
  tail -n 400 "$TRANSCRIPT" 2>/dev/null | grep -qiE \
    'rate limit|message limit|usage limit|too many requests|try again in [0-9]+ ?(hour|hr|h)|quota exceeded|429'
}

while true; do
  RUN=$((RUN + 1))
  echo ""
  echo "[$(date)] ============ Run #$RUN (crashes counted: $CRASH_COUNT / $MAX_RESTARTS) ============"
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

  # Distinguish rate-limit vs other exit.
  if is_rate_limited; then
    HOURS=$((RATE_LIMIT_SLEEP / 3600))
    MINS=$(((RATE_LIMIT_SLEEP % 3600) / 60))
    echo ""
    echo "[$(date)] Rate limit detected in transcript. Sleeping ${HOURS}h${MINS}m before resuming."
    echo "[$(date)] This pause does NOT count toward the crash budget — the script will keep retrying"
    echo "[$(date)] until the Anthropic 5-hour window resets. Ctrl+C to stop."
    sleep "$RATE_LIMIT_SLEEP"
    continue
  fi

  CRASH_COUNT=$((CRASH_COUNT + 1))
  if [ "$CRASH_COUNT" -ge "$MAX_RESTARTS" ]; then
    echo ""
    echo "[$(date)] Reached $MAX_RESTARTS non-rate-limit crashes. Stopping." >&2
    break
  fi

  echo ""
  echo "[$(date)] Restarting claude in ${CRASH_SLEEP}s. Ctrl+C to stop."
  sleep "$CRASH_SLEEP"
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

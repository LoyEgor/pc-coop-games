#!/usr/bin/env bash
# fact-checker runner (macOS / Linux)
#
# Walks every non-hidden entry in data.js and verifies its recorded fields
# against authoritative sources (Steam, HowLongToBeat, YouTube). Auto-fixes
# safe drift (rating, price, broken media). Logs everything else to TSVs in
# .claude/skills/fact-checker/state/ for owner review.
#
# Differences from run-coop-hunter.sh:
#   - Different skill (fact-checker, not coop-hunter)
#   - No phase cascade — single linear pass over data.js
#   - Auto-push DISABLED (data changes here are tiny edits, not bulk inserts;
#     batched commit by hand at the end is cleaner)
#   - Same rate-limit-aware loop and 200-crash budget as coop-hunter
#
# Usage:
#   1. chmod +x run-fact-checker.sh   (first time only)
#   2. ./run-fact-checker.sh
#
# Monitor from a second Terminal:
#   tail -f fact-checker-transcript.log
#   tail -f .claude/skills/fact-checker/state/discrepancies.tsv
#   tail -f .claude/skills/fact-checker/state/proposed-fixes.tsv
#   cat    .claude/skills/fact-checker/state/progress.json
#
# To stop: Ctrl+C. progress.json persists, restart picks up at current_idx.

set -u

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
PROGRESS_FILE="$REPO_ROOT/.claude/skills/fact-checker/state/progress.json"
TRANSCRIPT="$REPO_ROOT/fact-checker-transcript.log"

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
  echo "ERROR: claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code" >&2
  exit 1
fi

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "ERROR: python3 not found. Install via Homebrew: brew install python" >&2
  exit 1
fi

# -------- seed progress.json + fill total_entries if missing --------
mkdir -p "$(dirname "$PROGRESS_FILE")"
"$PY" - "$PROGRESS_FILE" <<'PYEOF'
import json, os, sys, subprocess
from pathlib import Path
path = sys.argv[1]
defaults = {
  "current_idx": 0,
  "total_entries": None,
  "checked_count": 0,
  "fixed_count": 0,
  "proposed_count": 0,
  "partial_entries": [],
  "done": False,
  "last_run_timestamp": None,
}
if os.path.exists(path):
    with open(path) as f:
        cur = json.load(f)
else:
    cur = {}
for k, v in defaults.items():
    if k not in cur:
        cur[k] = v

# Fill total_entries from list_entries.py --count
if cur["total_entries"] is None:
    skill_root = Path(path).resolve().parents[1]
    list_script = skill_root / "scripts" / "list_entries.py"
    out = subprocess.check_output(["python3", str(list_script), "--count"]).decode().strip()
    cur["total_entries"] = int(out)

with open(path, "w") as f:
    json.dump(cur, f, indent=2)
print(f"progress.json: current_idx={cur['current_idx']}, total={cur['total_entries']}, checked={cur['checked_count']}, fixed={cur['fixed_count']}, proposed={cur['proposed_count']}, done={cur['done']}")
PYEOF

# -------- header --------
echo ""
echo "================================================================"
echo "  fact-checker — drill-mode runner (macOS)"
echo "================================================================"
echo "  Started:       $(date)"
echo "  Repo:          $REPO_ROOT"
echo "  Claude CLI:    $CLAUDE_CMD"
echo "  Transcript:    $TRANSCRIPT"
echo ""
echo "  Mode: walks data.js end-to-end, verifies every recorded field."
echo "  Auto-fix scope: rating drift, price drift, broken youtube/image only."
echo "  Everything else logged to state/proposed-fixes.tsv for owner review."
echo "  Auto-restart on early exit (200 crashes; rate-limit pauses uncapped)."
echo ""
echo "  To stop: Ctrl+C. State is persistent — restart picks up at current_idx."
echo "================================================================"
echo ""

# -------- one-shot goal prompt --------
GOAL_PROMPT=$(cat <<'PROMPT_EOF'
/goal Run the fact-checker skill (.claude/skills/fact-checker/) to verify every non-hidden entry in data.js against authoritative sources and persist findings.

Read SKILL.md first; this prompt is the contract, the details live there.

RULES:

1. Resumable. Read state/progress.json; start from current_idx. Persist after every entry processed.

2. One entry per ~2 turns. 4-6 web calls each (Steam appdetails, appreviews, HLTB, YouTube WebFetch, image HEAD, optional Steam store page). Sleep 1.5s between Steam API calls. Sequential, not parallel.

3. CONSERVATIVE AUTO-FIX (only):
   - rating drift >= 5pp → update_field.py <id> rating <new>
   - price drift >= 10% but < 25% → update_field.py <id> price <new>
   - youtubeUrl is youtubeSearch(...) or 404 or unrelated → run the 6-query drill cascade in coop-hunter SKILL.md §8, replace via ../coop-hunter/scripts/fix_youtube.py
   - imageUrl HEAD non-200 → ../coop-hunter/scripts/fix_image.py <id> <app_id>
   - Everything else → log to state/proposed-fixes.tsv (genres, endingType, playersMax, oneCopy, tier, hours, year). Owner reviews manually.

4. DRILL MODE — never refuse on first failure. Retry Steam with different UA, fall back to store-page scrape, fall back to appdetails genres[] if tags unscrapable. Do not declare an entry "checked" if you skipped >2 of 11 checks; mark partial in progress.partial_entries[].

5. NEVER ASK QUESTIONS. Owner is asleep. Classify genres + endingType strictly via .claude/skills/shared/taxonomy.json (axis-structured: tier/perspective/mechanic/setting/structure; never invent tags). taxonomy.json wins over classification.md. Ambiguous → log discrepancies.tsv reason "ambiguous", continue.

6. NEVER remove entries. If a game now looks blocklist-worthy, log to state/proposed-removals.tsv. coop-hunter phase 4 handles removals; fact-checker only logs.

7. NEVER touch app.js / index.html / styles.css. data.js only via update_field.py and ../coop-hunter/scripts/fix_youtube.py / fix_image.py.

8. PROGRESS LINE every entry, to stdout:
   [N/TOTAL] <id>: rating <state> | hours <state> | genres <state> | media <state> | other <state>
   Where state ∈ {OK, drift, fix, propose, fail}. This is how owner sees progress.

9. Tool call fails → retry once with +5s sleep. Second fail → log and continue.

Stop only when ALL: current_idx >= total_entries AND partial_entries is empty AND every bad_video / no_image was fixed-or-logged. Re-walk partial entries in a second pass if needed.

Doubt about fixing → LOG, do not write. Doubt about giving up on a source → DRILL another source.
PROMPT_EOF
)

# -------- read initial state for delta tracking --------
INITIAL_CHECKED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['checked_count'])")
TOTAL=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['total_entries'])")
echo "Starting checked: $INITIAL_CHECKED / $TOTAL"
echo ""

# -------- transcript via 'script' for live + log --------
USE_SCRIPT=0
if command -v script >/dev/null 2>&1; then
  USE_SCRIPT=1
fi

# -------- main loop --------
# Same rate-limit-aware machinery as run-coop-hunter.sh: rate-limit pauses
# don't count toward the crash budget; only real crashes do.
MAX_RESTARTS=200
RATE_LIMIT_SLEEP=1800   # 30 minutes
CRASH_SLEEP=30
RUN=0
CRASH_COUNT=0

is_rate_limited() {
  tail -n 400 "$TRANSCRIPT" 2>/dev/null | grep -qiE \
    'rate limit|message limit|usage limit|too many requests|try again in [0-9]+ ?(hour|hr|h)|quota exceeded|429'
}

while true; do
  RUN=$((RUN + 1))
  echo ""
  echo "[$(date)] ============ Run #$RUN (crashes counted: $CRASH_COUNT / $MAX_RESTARTS) ============"
  echo ""

  if [ "$USE_SCRIPT" -eq 1 ]; then
    script -a -q "$TRANSCRIPT" "$CLAUDE_CMD" --dangerously-skip-permissions "$GOAL_PROMPT"
  else
    "$CLAUDE_CMD" --dangerously-skip-permissions "$GOAL_PROMPT"
  fi

  if [ ! -f "$PROGRESS_FILE" ]; then
    echo "[$(date)] WARNING: progress.json missing after run. Stopping." >&2
    break
  fi

  CHECKED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['checked_count'])")
  FIXED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['fixed_count'])")
  PROPOSED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['proposed_count'])")
  DONE=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['done'])")
  IDX=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['current_idx'])")

  echo ""
  echo "[$(date)] Claude exited. checked=$CHECKED/$TOTAL  fixed=$FIXED  proposed=$PROPOSED  idx=$IDX  done=$DONE"

  if [ "$DONE" = "True" ] || [ "$DONE" = "true" ]; then
    echo ""
    echo "[$(date)] FACT-CHECK COMPLETE."
    break
  fi

  if is_rate_limited; then
    HOURS=$((RATE_LIMIT_SLEEP / 3600))
    MINS=$(((RATE_LIMIT_SLEEP % 3600) / 60))
    echo ""
    echo "[$(date)] Rate limit detected. Sleeping ${HOURS}h${MINS}m. This pause does NOT count toward crash budget."
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
  CHECKED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['checked_count'])")
  FIXED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['fixed_count'])")
  PROPOSED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['proposed_count'])")
  DELTA=$((CHECKED - INITIAL_CHECKED))
  echo "  Checked this session:  $DELTA"
  echo "  Checked total:         $CHECKED / $TOTAL"
  echo "  Auto-fixed:            $FIXED"
  echo "  Proposed for review:   $PROPOSED"
fi
echo ""
echo "Review the logs:"
echo "  Transcript:           $TRANSCRIPT"
echo "  Discrepancies (info): $REPO_ROOT/.claude/skills/fact-checker/state/discrepancies.tsv"
echo "  Proposed fixes:       $REPO_ROOT/.claude/skills/fact-checker/state/proposed-fixes.tsv"
echo "  Proposed removals:    $REPO_ROOT/.claude/skills/fact-checker/state/proposed-removals.tsv"
echo "  Applied fixes:        $REPO_ROOT/.claude/skills/fact-checker/state/applied-fixes.tsv"
echo ""
echo "Auto-fixes (if any) staged in your working tree — review the diff before commit:"
echo "  git diff data.js"

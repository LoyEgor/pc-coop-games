#!/usr/bin/env bash
# fact-checker runner (macOS / Linux) — verifies every data.js entry vs Steam / HLTB / YouTube.
#
# ARCHITECTURE (changed 2026-05-27): headless bursts, NOT /goal — same reason as
# run-coop-hunter.sh (the /goal evaluator overflowed on long runs and hung). Each
# burst is one fresh `claude -p` process that verifies ~12 entries, persists
# state, and exits. The bash loop runs the next burst. No evaluator, no overflow.
#
#   - Auto-fix scope: broken youtube/image only. Rating/price are cron-owned
#     (skipped when the refresh-prices cron is healthy). Editorial fields are
#     LOGGED to proposed-fixes.tsv, never auto-written.
#   - Leaves changes in the working tree for you to review + commit.
#
# Usage:   ./run-fact-checker.sh      (chmod +x once)
# Stop:    Ctrl+C. State persists; restart resumes at current_idx.
# Watch:   tail -f fact-checker-transcript.log

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

# -------- seed progress.json --------
mkdir -p "$(dirname "$PROGRESS_FILE")"
"$PY" - "$PROGRESS_FILE" <<'PYEOF'
import json, os, sys, subprocess
from pathlib import Path
path = sys.argv[1]
defaults = {
  "current_idx": 0, "total_entries": None, "checked_count": 0,
  "fixed_count": 0, "proposed_count": 0, "partial_entries": [],
  "done": False, "mode": "normal", "last_run_timestamp": None,
}
if os.path.exists(path):
    with open(path) as f:
        cur = json.load(f)
else:
    cur = {}
for k, v in defaults.items():
    if k not in cur:
        cur[k] = v

# Always refresh total_entries — the catalog grows over time.
skill_root = Path(path).resolve().parents[1]
list_script = skill_root / "scripts" / "list_entries.py"
out = subprocess.check_output(["python3", str(list_script), "--count"]).decode().strip()
cur["total_entries"] = int(out)

# An explicit launch means "go". Clear stale done; this launcher is NORMAL mode
# (run-migration.sh handles taxonomy_migration). If the previous run finished
# (idx past the end), rewind for a fresh full pass; else resume at current_idx.
cur["done"] = False
cur["mode"] = "normal"
if cur["current_idx"] >= cur["total_entries"]:
    cur["current_idx"] = 0
    cur["partial_entries"] = []

with open(path, "w") as f:
    json.dump(cur, f, indent=2)
print(f"progress.json: mode={cur['mode']}, current_idx={cur['current_idx']}, total={cur['total_entries']}, done={cur['done']}")
PYEOF

# -------- header --------
echo ""
echo "================================================================"
echo "  fact-checker — headless-burst runner (macOS)"
echo "================================================================"
echo "  Started:    $(date)"
echo "  Repo:       $REPO_ROOT"
echo "  Claude CLI: $CLAUDE_CMD"
echo "  Transcript: $TRANSCRIPT"
echo ""
echo "  Each burst = one fresh 'claude -p' process (~12 entries) that exits."
echo "  Auto-fix: broken youtube/image only. Rating/price = cron-owned."
echo "  Editorial findings logged to state/proposed-fixes.tsv for your review."
echo "  Changes left in the working tree; review 'git diff data.js' after."
echo "================================================================"
echo ""

# -------- the per-burst prompt (NO /goal) --------
BURST_PROMPT=$(cat <<'PROMPT_EOF'
Run the fact-checker skill (.claude/skills/fact-checker/) for ONE BURST, then EXIT. This is a headless invocation; a bash loop re-invokes you per burst and you resume from state/progress.json. Do NOT verify the whole catalog in one invocation.

Read first: SKILL.md; .claude/skills/shared/taxonomy.json (AUTHORITATIVE for genre + endingType — classify by axis, never invent tags); state/progress.json.

THIS BURST:
- Resume from progress.json.current_idx. Verify AT MOST 12 entries this invocation, sequentially, 1.5s sleep between Steam API calls. After each entry: current_idx += 1 and persist progress.json.
- After ~12 entries, STOP and exit. The loop starts your next burst.

PER ENTRY, verify vs Steam / HowLongToBeat / YouTube: rating, price, hours, playersMax, oneCopy, genres (by taxonomy axes), tier, endingType, youtubeUrl, imageUrl.

AUTO-FIX (only these): broken youtubeUrl (youtubeSearch placeholder / 404 / unrelated) via ../coop-hunter/scripts/fix_youtube.py; broken imageUrl via ../coop-hunter/scripts/fix_image.py. EVERYTHING editorial (genres / endingType / playersMax / oneCopy / hours / year / tier) -> LOG to state/proposed-fixes.tsv, do NOT auto-write.

CRON COORDINATION (priority: cron > fact-checker): read .github/refresh-status.json. If last_success < 30h old, SKIP rating + price checks entirely — the cron owns them. If stale/missing, you MAY log rating/price drift to proposed-fixes.tsv, but do not fight the cron.

NEVER touch app.js / index.html / styles.css. NEVER remove entries (log blocklist-worthy ones to proposed-removals.tsv). NEVER ASK QUESTIONS — ambiguous -> discrepancies.tsv, continue.

COMPLETION: when current_idx >= total_entries AND partial_entries is empty, set progress.done=true. Otherwise leave done=false; the loop runs the next burst.

End with one line: [N/TOTAL checked | F fixed | P proposed]
PROMPT_EOF
)

# -------- delta tracking --------
INITIAL_CHECKED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['checked_count'])")
TOTAL=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['total_entries'])")
echo "Starting at entry $("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['current_idx'])") / $TOTAL"
echo ""

# -------- consistency audit (cheap, no network) — refresh inconsistencies.tsv --------
# Catches catalog self-contradictions (same franchise added vs skipped, mixed
# endingType) that per-entry checks miss. Output is a short owner-review queue.
echo "[$(date)] Running consistency audit (find_neighbors.py)..."
"$PY" "$REPO_ROOT/.claude/skills/fact-checker/scripts/find_neighbors.py" || true
echo ""

# -------- main loop: one claude -p burst per iteration --------
MAX_BURSTS=600
RATE_LIMIT_SLEEP=1800
TRANSCRIPT_CAP_BYTES=$((20 * 1024 * 1024))   # cap the log at ~20 MB
BURST=0

# Fresh log each run (transcript is for tail -f + rate-limit detection, not state).
: > "$TRANSCRIPT"

is_rate_limited() {
  tail -n 200 "$TRANSCRIPT" 2>/dev/null | grep -qiE \
    'rate limit|message limit|usage limit|too many requests|try again in [0-9]+ ?(hour|hr|h)|quota exceeded|429'
}

cap_transcript() {
  local sz
  sz=$(wc -c < "$TRANSCRIPT" 2>/dev/null || echo 0)
  if [ "$sz" -gt "$TRANSCRIPT_CAP_BYTES" ]; then
    tail -n 4000 "$TRANSCRIPT" > "$TRANSCRIPT.keep" && cat "$TRANSCRIPT.keep" > "$TRANSCRIPT" && rm -f "$TRANSCRIPT.keep"
  fi
}

while true; do
  BURST=$((BURST + 1))
  if [ "$BURST" -gt "$MAX_BURSTS" ]; then
    echo "[$(date)] Reached MAX_BURSTS=$MAX_BURSTS. Stopping (runaway guard)." >&2
    break
  fi

  echo ""
  echo "[$(date)] ================= Burst #$BURST ================="
  echo ""

  "$CLAUDE_CMD" -p --dangerously-skip-permissions "$BURST_PROMPT" 2>&1 | tee -a "$TRANSCRIPT"
  cap_transcript

  if [ ! -f "$PROGRESS_FILE" ]; then
    echo "[$(date)] WARNING: progress.json missing. Stopping." >&2
    break
  fi

  CHECKED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['checked_count'])")
  FIXED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['fixed_count'])")
  PROPOSED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['proposed_count'])")
  DONE=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['done'])")
  IDX=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['current_idx'])")

  echo ""
  echo "[$(date)] Burst #$BURST done. idx=$IDX/$TOTAL fixed=$FIXED proposed=$PROPOSED done=$DONE"

  if [ "$DONE" = "True" ] || [ "$DONE" = "true" ]; then
    echo "[$(date)] FACT-CHECK COMPLETE."
    break
  fi

  if is_rate_limited; then
    echo "[$(date)] Rate limit detected. Sleeping 30m before the next burst (Ctrl+C to stop)."
    sleep "$RATE_LIMIT_SLEEP"
    continue
  fi

  sleep 3
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
  echo "  Checked total:        $CHECKED / $TOTAL"
  echo "  Auto-fixed:           $FIXED"
  echo "  Proposed for review:  $PROPOSED"
  echo "  Bursts run:           $BURST"
fi
echo ""
echo "Review the logs:"
echo "  Transcript:        $TRANSCRIPT"
echo "  Proposed fixes:    $REPO_ROOT/.claude/skills/fact-checker/state/proposed-fixes.tsv"
echo "  Proposed removals: $REPO_ROOT/.claude/skills/fact-checker/state/proposed-removals.tsv"
echo "  Applied fixes:     $REPO_ROOT/.claude/skills/fact-checker/state/applied-fixes.tsv"
echo ""
echo "Review the diff before committing:  git diff data.js"

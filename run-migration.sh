#!/usr/bin/env bash
# Taxonomy migration runner (macOS / Linux) — ONE-TIME bulk tag rewrite.
#
# Brings every existing data.js entry onto the new axis-structured taxonomy
# defined in .claude/skills/shared/taxonomy.json:
#   - split FPS -> First-person (+ Shooter where it really is a shooter)
#   - merge any Top-down into Isometric
#   - narrow Adventure to narrative-led games only
#   - enrich: give every perspective-less entry exactly one perspective tag
#
# This is the fact-checker skill running in mode=taxonomy_migration. It AUTO-
# APPLIES the deterministic rewrites to data.js and logs each to
# state/applied-fixes.tsv. It does NOT commit or push — review `git diff data.js`
# and commit yourself when happy.
#
# Usage:
#   ./run-migration.sh
#
# Resume: safe to Ctrl+C and restart — progress.json.current_idx tracks where
# it stopped. Re-running after completion rewinds to a fresh full pass.
#
# Monitor from a second Terminal:
#   tail -f migration-transcript.log
#   tail -f .claude/skills/fact-checker/state/applied-fixes.tsv
#   git diff --stat data.js

set -u

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
PROGRESS_FILE="$REPO_ROOT/.claude/skills/fact-checker/state/progress.json"
TRANSCRIPT="$REPO_ROOT/migration-transcript.log"

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

# -------- seed progress.json into migration mode --------
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

skill_root = Path(path).resolve().parents[1]
list_script = skill_root / "scripts" / "list_entries.py"
out = subprocess.check_output(["python3", str(list_script), "--count"]).decode().strip()
cur["total_entries"] = int(out)

# Enter migration mode. If a previous run wasn't migration, or it had finished,
# rewind to a fresh full pass. Otherwise keep current_idx to resume.
was_migrating = cur.get("mode") == "taxonomy_migration"
cur["mode"] = "taxonomy_migration"
cur["done"] = False
if (not was_migrating) or cur["current_idx"] >= cur["total_entries"]:
    cur["current_idx"] = 0
    cur["partial_entries"] = []

with open(path, "w") as f:
    json.dump(cur, f, indent=2)
print(f"progress.json: mode={cur['mode']}, current_idx={cur['current_idx']}, total={cur['total_entries']}, done={cur['done']}")
PYEOF

# -------- header --------
echo ""
echo "================================================================"
echo "  taxonomy migration — ONE-TIME bulk tag rewrite (macOS)"
echo "================================================================"
echo "  Started:    $(date)"
echo "  Repo:       $REPO_ROOT"
echo "  Transcript: $TRANSCRIPT"
echo ""
echo "  Rewrites all data.js entries onto taxonomy.json axes. Auto-applies."
echo "  Does NOT commit or push — review 'git diff data.js' afterward."
echo "  Auto-restart on early exit; rate-limit pauses uncapped. Ctrl+C to stop."
echo "================================================================"
echo ""

# -------- one-shot goal prompt (NO apostrophes — macOS bash 3.2 heredoc) --------
GOAL_PROMPT=$(cat <<'PROMPT_EOF'
/goal Run the fact-checker skill (.claude/skills/fact-checker/) in TAXONOMY MIGRATION mode to rewrite every data.js entry onto the new axis-structured taxonomy.

progress.json has mode=taxonomy_migration. Read fact-checker SKILL.md (the "taxonomy_migration phase" section) and .claude/skills/shared/taxonomy.json FIRST.

RULES:

1. Resumable. Read progress.json; start at current_idx. After EVERY entry: current_idx += 1, persist. Sleep 1.5s between Steam API calls. Sequential.

2. For each entry, AUTO-APPLY the deterministic rewrites from the taxonomy_migration phase:
   - FPS split: replace "FPS" with "First-person"; add "Shooter" only if the game is actually a shooter (Steam tags + verdict). The 6 known exceptions (portal-2, dying-light, dying-light-2, vermintide-2, dead-island-de, dead-island-2) get First-person only, no Shooter.
   - Top-down: any "Top-down" tag becomes "Isometric".
   - Adventure narrowing: keep "Adventure" only for narrative-led + exploration + dialogue games (Chicory-style). If the game is action / shooter / pure-puzzle / sim, REMOVE Adventure. Use verdict + Steam description; WebFetch the Steam page if unsure.
   - Perspective enrichment: if the entry has no perspective tag, derive exactly one (First-person / Third-person / Isometric / Side-view) from Steam tags + verdict + screenshots. Insert it right after the tier, before mechanics.
   - If a perspective cannot be determined confidently, leave it and log perspective_undetermined to state/proposed-fixes.tsv (do not guess).

3. NEVER touch price or rating — those are owned by the refresh-prices cron.

4. NEVER touch app.js / index.html / styles.css. Edit data.js genres arrays only (via direct edits or update_field is NOT for arrays — edit the genres line in place, preserving order tier -> perspective -> mechanic -> setting -> structure). Log each rewrite to state/applied-fixes.tsv.

5. NEVER ASK QUESTIONS. Owner is asleep. Classify strictly by taxonomy.json decision-trees. Ambiguous -> log, do not guess.

6. DRILL MODE: if Steam 403/empty, retry with different UA, then fall back to verdict-only classification. Do not skip an entry silently.

7. DO NOT commit or push. Leave all changes in the working tree for owner review.

Stop only when current_idx >= total_entries AND every entry has been processed once. Output every 10 entries: "[N/TOTAL] <id>: perspective <added|kept> | FPS <split|n/a> | Adventure <kept|removed>".
PROMPT_EOF
)

INITIAL_IDX=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['current_idx'])")
TOTAL=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['total_entries'])")
echo "Starting at entry $INITIAL_IDX / $TOTAL"
echo ""

USE_SCRIPT=0
if command -v script >/dev/null 2>&1; then
  USE_SCRIPT=1
fi

# -------- main loop (rate-limit aware, same as the other launchers) --------
MAX_RESTARTS=200
RATE_LIMIT_SLEEP=1800
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
  echo "[$(date)] ======== Migration run #$RUN (crashes $CRASH_COUNT / $MAX_RESTARTS) ========"
  echo ""

  if [ "$USE_SCRIPT" -eq 1 ]; then
    script -a -q "$TRANSCRIPT" "$CLAUDE_CMD" --dangerously-skip-permissions "$GOAL_PROMPT"
  else
    "$CLAUDE_CMD" --dangerously-skip-permissions "$GOAL_PROMPT"
  fi

  if [ ! -f "$PROGRESS_FILE" ]; then
    echo "[$(date)] WARNING: progress.json missing. Stopping." >&2
    break
  fi

  IDX=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['current_idx'])")
  DONE=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['done'])")
  FIXED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['fixed_count'])")

  echo ""
  echo "[$(date)] Claude exited. idx=$IDX/$TOTAL fixed=$FIXED done=$DONE"

  if [ "$DONE" = "True" ] || [ "$DONE" = "true" ] || [ "$IDX" -ge "$TOTAL" ]; then
    echo ""
    echo "[$(date)] MIGRATION COMPLETE. Review: git diff data.js"
    break
  fi

  if is_rate_limited; then
    echo ""
    echo "[$(date)] Rate limit detected. Sleeping 30m (does not count toward crash budget)."
    sleep "$RATE_LIMIT_SLEEP"
    continue
  fi

  CRASH_COUNT=$((CRASH_COUNT + 1))
  if [ "$CRASH_COUNT" -ge "$MAX_RESTARTS" ]; then
    echo "[$(date)] Reached $MAX_RESTARTS crashes. Stopping." >&2
    break
  fi
  echo "[$(date)] Restarting in ${CRASH_SLEEP}s. Ctrl+C to stop."
  sleep "$CRASH_SLEEP"
done

# -------- reset mode back to normal so a later ./run-fact-checker.sh is clean --------
"$PY" - "$PROGRESS_FILE" <<'PYEOF'
import json, sys
path = sys.argv[1]
with open(path) as f: cur = json.load(f)
cur["mode"] = "normal"
with open(path, "w") as f: json.dump(cur, f, indent=2)
print("mode reset to normal")
PYEOF

echo ""
echo "================================================================"
echo "  Migration finished at $(date)"
echo "================================================================"
echo "  Applied fixes:  $REPO_ROOT/.claude/skills/fact-checker/state/applied-fixes.tsv"
echo "  Proposed (review): $REPO_ROOT/.claude/skills/fact-checker/state/proposed-fixes.tsv"
echo ""
echo "  Review the rewrite, then commit yourself:"
echo "    git diff data.js"
echo "    git add data.js && git commit -m 'data: migrate to axis taxonomy'"

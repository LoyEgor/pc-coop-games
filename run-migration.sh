#!/usr/bin/env bash
# Finish-strength migration runner (macOS / Linux) — ONE-TIME bulk pass.
#
# Brings every data.js entry onto the finish_strength model (CLAUDE.md section 2
# + taxonomy.json finish_strength):
#   - co-op gate (co-op drives progression not just fights; co-op finish > 1h)
#   - hard / soft / none classification
#   - soft finishes get a leading orange-circle marker in the verdict + reason
#   - conservative co-op-hours recalc (only where it differs from the whole game)
#   - verdict rewrite ONLY where needed (soft / hours-changed / non-coop verdict)
#   - endingType corrected per the current taxonomy
#
# This is the fact-checker skill running in mode=finish_migration. It AUTO-APPLIES
# to data.js and logs each change to state/migration-applied.tsv. It does NOT
# commit or push — review `git diff data.js` and commit yourself.
#
# Execution model: headless `claude -p` bursts in a bash loop (same as
# run-fact-checker.sh) — NOT /goal (its evaluator overflowed on long runs).
#
# Usage:   ./run-migration.sh
# Monitor: tail -f migration-transcript.log
#          tail -f .claude/skills/fact-checker/state/migration-applied.tsv
#          git diff --stat data.js

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
  CLAUDE_CMD="$HOME/.npm-global/bin/claude"; export PATH="$HOME/.npm-global/bin:$PATH"
elif [ -x "/opt/homebrew/bin/claude" ]; then
  CLAUDE_CMD="/opt/homebrew/bin/claude"; export PATH="/opt/homebrew/bin:$PATH"
elif [ -x "/usr/local/bin/claude" ]; then
  CLAUDE_CMD="/usr/local/bin/claude"
fi
if [ -z "$CLAUDE_CMD" ]; then
  echo "ERROR: claude CLI not found. Install: npm install -g @anthropic-ai/claude-code" >&2
  exit 1
fi
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then echo "ERROR: python3 not found." >&2; exit 1; fi

# -------- seed progress.json into finish_migration mode --------
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
cur = json.load(open(path)) if os.path.exists(path) else {}
for k, v in defaults.items():
    cur.setdefault(k, v)
skill_root = Path(path).resolve().parents[1]
out = subprocess.check_output(["python3", str(skill_root / "scripts" / "list_entries.py"), "--count"]).decode().strip()
cur["total_entries"] = int(out)
was = cur.get("mode") == "finish_migration"
cur["mode"] = "finish_migration"
cur["done"] = False
if (not was) or cur["current_idx"] >= cur["total_entries"]:
    cur["current_idx"] = 0
    cur["partial_entries"] = []
json.dump(cur, open(path, "w"), indent=2)
print(f"progress.json: mode={cur['mode']}, current_idx={cur['current_idx']}, total={cur['total_entries']}, done={cur['done']}")
PYEOF

echo ""
echo "================================================================"
echo "  finish-strength migration — ONE-TIME bulk pass (macOS)"
echo "================================================================"
echo "  Started:    $(date)"
echo "  Repo:       $REPO_ROOT"
echo "  Claude CLI: $CLAUDE_CMD"
echo "  Transcript: $TRANSCRIPT"
echo ""
echo "  Auto-applies finish-strength edits to data.js. Does NOT commit/push."
echo "  Resumable (current_idx). Ctrl+C to stop. Review git diff data.js after."
echo "================================================================"
echo ""

# -------- headless burst prompt (NO apostrophes — macOS bash 3.2 heredoc) --------
BURST_PROMPT=$(cat <<'PROMPT_EOF'
Run the fact-checker skill (.claude/skills/fact-checker/) in FINISH MIGRATION mode for ONE BURST, then EXIT. Headless; a bash loop re-invokes you per burst, resume from state/progress.json.

progress.json has mode=finish_migration. Read FIRST: fact-checker SKILL.md (the "finish_migration phase" section); .claude/skills/shared/taxonomy.json (finish_strength + ending_types + tier); CLAUDE.md section 2.

THIS BURST:
- Resume from progress.json.current_idx. Process AT MOST 10 entries this invocation (migration is heavy: co-op hours + verdict). After EACH entry: current_idx += 1 and persist progress.json. Sleep 1.5s between Steam API calls. Sequential.
- After ~10 entries, STOP and exit. The loop starts your next burst.

PER ENTRY, AUTO-APPLY directly to data.js and log each change to state/migration-applied.tsv (id, field, old, new, reason):
1. CO-OP GATE: co-op must drive the progression, not just the fights; the co-op finish content must be > 1h. Fails (fights-only — one player owns the story; or co-op <=1h) -> remove via ../coop-hunter/scripts/remove_entry.py (clear case) or log state/proposed-removals.tsv (judgment). Do nothing else for that entry.
2. FINISH STRENGTH: none (truly endless) -> remove/propose-removal. soft (finish is an accumulated status/checklist/threshold inside a loop) -> the verdict MUST start with a leading 🟠 marker + a short reason. hard -> no marker.
3. CO-OP HOURS recalc, CONSERVATIVE: only where co-op progression clearly differs from the whole game (open-ended / survival / soft). Linear story co-op (campaign IS the co-op) -> leave hours. Cannot get a defensible number -> leave hours, log discrepancies.tsv reason coop_hours_unclear. Integer only.
4. VERDICT rewrite ONLY WHERE NEEDED: soft (needs 🟠 + reason), OR hours changed, OR the current verdict does not describe the co-op. Otherwise leave a good verdict alone. <=120 chars, English.
5. endingType per the current taxonomy decision_tree (e.g. an old arcade-goal that is really a level set -> levels).

CRON COORDINATION: NEVER touch price or rating (the refresh-prices cron owns them).
NEVER touch app.js / index.html / styles.css. NEVER ASK QUESTIONS (owner asleep; classify by taxonomy, log ambiguous). NEVER commit or push — leave changes in the working tree.

COMPLETION: when current_idx >= total_entries AND partial_entries is empty, set progress.done=true. Otherwise leave done=false.

End with one line: [N/TOTAL migrated | A applied | R removed]
PROMPT_EOF
)

INITIAL_IDX=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['current_idx'])")
TOTAL=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['total_entries'])")
PREV_IDX=$INITIAL_IDX
echo "Starting at entry $INITIAL_IDX / $TOTAL"
echo ""

# -------- main loop: one claude -p burst per iteration --------
MAX_BURSTS=120            # ~10 entries/burst over ~557 entries + retries
RATE_LIMIT_SLEEP=1800
STAGNATION_THRESHOLD=3
TRANSCRIPT_CAP_BYTES=$((20 * 1024 * 1024))
BURST=0
STAGNANT_BURSTS=0
: > "$TRANSCRIPT"

is_rate_limited() {
  tail -n 200 "$TRANSCRIPT" 2>/dev/null | grep -qiE \
    "rate limit|message limit|usage limit|weekly limit|too many requests|try again in [0-9]+ ?(hour|hr|h)|quota exceeded|error[: ]*429|you'?ve hit your (session|usage|weekly) limit|session limit.*reset|hit your (session|usage|weekly) limit"
}
cap_transcript() {
  local sz; sz=$(wc -c < "$TRANSCRIPT" 2>/dev/null || echo 0)
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
  echo "[$(date)] ========= STAGE 1/2 (catalog) — migration burst #$BURST ========="
  echo ""

  "$CLAUDE_CMD" -p --model opus --dangerously-skip-permissions "$BURST_PROMPT" < /dev/null 2>&1 | tee -a "$TRANSCRIPT"
  cap_transcript

  if [ ! -f "$PROGRESS_FILE" ]; then
    echo "[$(date)] WARNING: progress.json missing. Stopping." >&2
    break
  fi

  read -r IDX DONE FIXED <<<"$("$PY" -c "
import json
p=json.load(open('$PROGRESS_FILE'))
print(p.get('current_idx',0), p.get('done',False), p.get('fixed_count',0))
")"
  IDX_DELTA=$((IDX - PREV_IDX)); PREV_IDX=$IDX

  echo ""
  echo "[$(date)] Burst #$BURST done. idx=$IDX/$TOTAL (+$IDX_DELTA) fixed=$FIXED done=$DONE"

  if [ "$DONE" = "True" ] || [ "$DONE" = "true" ] || { [ "$IDX" != "?" ] && [ "$IDX" -ge "$TOTAL" ]; }; then
    echo "[$(date)] MIGRATION COMPLETE. Review: git diff data.js"
    break
  fi

  if is_rate_limited; then
    echo "[$(date)] Rate/session limit detected. Sleeping 30m before the next burst (Ctrl+C to stop)."
    STAGNANT_BURSTS=0
    sleep "$RATE_LIMIT_SLEEP"
    continue
  fi

  if [ "$IDX_DELTA" -le 0 ]; then
    STAGNANT_BURSTS=$((STAGNANT_BURSTS + 1))
    echo "[$(date)] Stagnation: idx did not advance. streak=$STAGNANT_BURSTS/$STAGNATION_THRESHOLD"
    if [ "$STAGNANT_BURSTS" -ge "$STAGNATION_THRESHOLD" ]; then
      echo "[$(date)] STAGNATION STOP — $STAGNATION_THRESHOLD consecutive no-progress bursts. Aborting." >&2
      break
    fi
  else
    STAGNANT_BURSTS=0
  fi
  sleep 3
done

# -------- reset fact-checker mode back to normal --------
"$PY" - "$PROGRESS_FILE" <<'PYEOF'
import json, sys
path = sys.argv[1]
cur = json.load(open(path))
cur["mode"] = "normal"
json.dump(cur, open(path, "w"), indent=2)
print("fact-checker mode reset to normal")
PYEOF

# ================================================================
#  STAGE 2/2 — coop-hunter reeval_only: re-judge skipped.tsv and add back the
#  games that now qualify under the new finish_strength rules. NO new search.
# ================================================================
CH_PROGRESS="$REPO_ROOT/.claude/skills/coop-hunter/state/progress.json"

"$PY" - "$CH_PROGRESS" <<'PYEOF'
import json, os, sys
path = sys.argv[1]
cur = json.load(open(path)) if os.path.exists(path) else {}
cur["reeval_only"] = True
cur["current_phase"] = 4
cur["current_source_idx"] = 12          # reeval_skipped
cur["current_offset"] = 0
cur["done"] = False
# un-mark reeval_skipped so it re-walks skipped.tsv under the NEW rules
cur["completed_sources"] = [s for s in cur.get("completed_sources", []) if s != "reeval_skipped"]
json.dump(cur, open(path, "w"), indent=2)
print("coop-hunter: reeval_only=True, source=reeval_skipped, current_offset=0, done=False")
PYEOF

echo ""
echo "================================================================"
echo "  STAGE 2/2 — coop-hunter reeval_only (skipped -> add back)"
echo "  Started: $(date)  — re-judges skipped.tsv only, NO new-game search."
echo "================================================================"
echo ""

CH_PROMPT=$(cat <<'PROMPT_EOF'
Run the coop-hunter skill (.claude/skills/coop-hunter/) in REEVAL-ONLY mode for ONE BURST, then EXIT. Headless; a bash loop re-invokes you per burst, resume from state/progress.json.

progress.json has reeval_only=true. Read FIRST: coop-hunter SKILL.md (the "reeval_only mode" + "reeval_skipped" sections); .claude/skills/shared/taxonomy.json (finish_strength); CLAUDE.md section 2.

THIS BURST:
- reeval_only is true -> process ONLY skipped.tsv via reeval_skipped. Do NOT search for new games (no steam_more_like_this / websearch / any phase 1-3 source).
- Re-evaluate AT MOST 12 eligible skipped rows this invocation under the new finish_strength rules. Advance current_offset and persist progress.json after EACH row. Sleep 1.5s between Steam API calls.
- A row that NOW qualifies: hard finish -> add via scripts/append_entry.py; soft finish -> add with a leading 🟠 in the verdict + the reason. Still none / fights-only / co-op <=1h -> leave it skipped.
- SKIP mechanical reasons (duplicate, no_coop, not_on_steam, pvp_primary, invalid_app_id, online_broken).
- After ~12 rows, STOP and exit. The loop starts your next burst.

NEVER touch price or rating (the refresh-prices cron owns them). NEVER touch app.js / index.html / styles.css. NEVER ASK QUESTIONS. NEVER commit or push.

COMPLETION: when every eligible skipped.tsv row has been re-evaluated, set progress.done=true.

End with one line: [reeval offset=N | added A this burst | done=<bool>]
PROMPT_EOF
)

CH_PREV_OFFSET=0
CH_BURST=0
CH_STAGNANT=0
while true; do
  CH_BURST=$((CH_BURST + 1))
  if [ "$CH_BURST" -gt "$MAX_BURSTS" ]; then
    echo "[$(date)] STAGE 2 reached MAX_BURSTS=$MAX_BURSTS. Stopping." >&2; break
  fi
  echo ""
  echo "[$(date)] ===== STAGE 2 reeval burst #$CH_BURST ====="
  echo ""
  "$CLAUDE_CMD" -p --model opus --dangerously-skip-permissions "$CH_PROMPT" < /dev/null 2>&1 | tee -a "$TRANSCRIPT"
  cap_transcript
  [ -f "$CH_PROGRESS" ] || { echo "[$(date)] coop-hunter progress.json missing. Stopping." >&2; break; }
  read -r CH_OFFSET CH_ADDED CH_DONE <<<"$("$PY" -c "
import json
p=json.load(open('$CH_PROGRESS'))
print(p.get('current_offset',0), p.get('added_count',0), p.get('done',False))
")"
  CH_DELTA=$((CH_OFFSET - CH_PREV_OFFSET)); CH_PREV_OFFSET=$CH_OFFSET
  echo ""
  echo "[$(date)] STAGE 2 burst #$CH_BURST done. offset=$CH_OFFSET (+$CH_DELTA) added=$CH_ADDED done=$CH_DONE"
  if [ "$CH_DONE" = "True" ] || [ "$CH_DONE" = "true" ]; then
    echo "[$(date)] STAGE 2 COMPLETE — skipped.tsv fully re-evaluated."; break
  fi
  if is_rate_limited; then
    echo "[$(date)] Rate/session limit. Sleeping 30m before the next burst."; CH_STAGNANT=0; sleep "$RATE_LIMIT_SLEEP"; continue
  fi
  # Stagnation on OFFSET (not adds): reeval legitimately adds 0 across many rows
  # that still don't qualify, so progress = how far through skipped.tsv we are.
  if [ "$CH_DELTA" -le 0 ]; then
    CH_STAGNANT=$((CH_STAGNANT + 1))
    echo "[$(date)] STAGE 2 offset did not advance. streak=$CH_STAGNANT/3"
    if [ "$CH_STAGNANT" -ge 3 ]; then
      echo "[$(date)] STAGE 2 stop — 3 bursts with no offset progress; treating skipped as re-evaluated." >&2; break
    fi
  else
    CH_STAGNANT=0
  fi
  sleep 3
done

# reset reeval_only so a later normal coop-hunter run isn't stuck in this mode
"$PY" - "$CH_PROGRESS" <<'PYEOF'
import json, sys
path = sys.argv[1]
cur = json.load(open(path))
cur["reeval_only"] = False
json.dump(cur, open(path, "w"), indent=2)
print("coop-hunter: reeval_only reset to False")
PYEOF

echo ""
echo "================================================================"
echo "  Migration finished at $(date)"
echo "================================================================"
echo "  Catalog rewrite (audit):  $REPO_ROOT/.claude/skills/fact-checker/state/migration-applied.tsv"
echo "  Proposed removals:        $REPO_ROOT/.claude/skills/fact-checker/state/proposed-removals.tsv"
echo "  Re-added from skipped:    $REPO_ROOT/.claude/skills/coop-hunter/state/added.tsv"
echo ""
echo "  Both stages done (catalog re-judged + skipped re-evaluated, no new search)."
echo "  Review, then commit yourself:  git diff data.js"
echo "  When happy with the migration, you can delete run-migration.sh."

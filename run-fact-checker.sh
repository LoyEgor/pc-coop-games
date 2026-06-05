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
# Usage:   ./run-fact-checker.sh [new|all]   (chmod +x once)
#            all (default) — verify the WHOLE catalog, resuming at current_idx.
#            new           — verify ONLY entries that lack `reviewed: true` in
#                            data.js (the games coop-hunter just added), stamping
#                            each via mark_reviewed.py, then exits. Cheap pass to
#                            run right after an overnight hunt.
# Stop:    Ctrl+C. State persists; restart resumes (all: at current_idx; new: by flag).
# Watch:   tail -f fact-checker-transcript.log

set -u

SCOPE="${1:-all}"
case "$SCOPE" in
  new|all) ;;
  *) echo "Usage: $0 [new|all]   (new = only games coop-hunter just added; all = whole catalog, default)" >&2; exit 1 ;;
esac

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
PROGRESS_FILE="$REPO_ROOT/.claude/skills/fact-checker/state/progress.json"
DATA_JS="$REPO_ROOT/data.js"   # 'new' scope = entries in data.js lacking `reviewed: true`
TRANSCRIPT="$REPO_ROOT/fact-checker-transcript.log"
BURST_OUT="$REPO_ROOT/.fact-checker-burst.tmp"   # ONLY the latest burst's output — what is_rate_limited inspects

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
"$PY" - "$PROGRESS_FILE" "$SCOPE" "$DATA_JS" <<'PYEOF'
import json, os, re, sys, subprocess
from pathlib import Path
path, scope, data_js = sys.argv[1], sys.argv[2], sys.argv[3]

def count_unreviewed():
    # entries WITHOUT `reviewed: true` = not yet checked by the fact-checker
    txt = open(data_js, encoding="utf-8").read()
    blocks = re.findall(r"\n  \{\n.*?\n  \}", txt, re.DOTALL)
    return sum(1 for b in blocks if "hidden: true" not in b and not re.search(r"\n    reviewed:\s*true", b))
defaults = {
  "current_idx": 0, "total_entries": None, "checked_count": 0,
  "fixed_count": 0, "proposed_count": 0, "partial_entries": [],
  "done": False, "mode": "normal", "scope": "all", "last_run_timestamp": None,
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
# (run-migration.sh handles taxonomy_migration).
cur["done"] = False
cur["mode"] = "normal"
cur["scope"] = scope

queue_n = 0
if scope == "new":
    # The skill verifies ONLY entries lacking `reviewed: true`, stamping each as it
    # goes (mark_reviewed.py) — progress is the flag itself, so current_idx is N/A.
    queue_n = count_unreviewed()
else:
    # all-scope: if the previous full pass finished (idx past the end), rewind for
    # a fresh pass; else resume at current_idx.
    if cur["current_idx"] >= cur["total_entries"]:
        cur["current_idx"] = 0
        cur["partial_entries"] = []

with open(path, "w") as f:
    json.dump(cur, f, indent=2)
if scope == "new":
    print(f"progress.json: scope=new, queue={queue_n} games to verify, total_catalog={cur['total_entries']}")
else:
    print(f"progress.json: scope=all, current_idx={cur['current_idx']}, total={cur['total_entries']}")
PYEOF

# -------- new-scope: nothing unreviewed => nothing to do --------
if [ "$SCOPE" = "new" ]; then
  QUEUE_N=$("$PY" -c "
import re
t=open('$DATA_JS',encoding='utf-8').read()
b=re.findall(r'\n  \{\n.*?\n  \}', t, re.DOTALL)
print(sum(1 for x in b if 'hidden: true' not in x and not re.search(r'\n    reviewed:\s*true', x)))
")
  if [ "$QUEUE_N" -eq 0 ]; then
    echo ""
    echo "fact-checker (new): every entry already has 'reviewed: true' — nothing new to verify."
    echo "  Run coop-hunter to add games, or use './run-fact-checker.sh all'."
    echo ""
    exit 0
  fi
fi

# -------- header --------
echo ""
echo "================================================================"
echo "  fact-checker — headless-burst runner (macOS)"
echo "================================================================"
echo "  Started:    $(date)"
echo "  Scope:      $SCOPE$([ "$SCOPE" = "new" ] && echo " ($QUEUE_N games queued by coop-hunter)" || echo " (whole catalog)")"
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

SCOPE — read progress.json.scope (the launcher set it):
- scope=="all": verify the WHOLE catalog in catalog order. Resume from progress.json.current_idx; after each entry current_idx += 1 and persist. COMPLETION: when current_idx >= total_entries AND partial_entries is empty, set progress.done=true.
- scope=="new": verify ONLY entries in data.js that LACK a `reviewed: true` field (the games coop-hunter just added — it appends without the flag). Verify up to 12 such entries this burst; after EACH is fully verified, stamp it via `python3 .claude/skills/fact-checker/scripts/mark_reviewed.py <id>` so it drops out of the unreviewed set. Ignore current_idx in this scope. COMPLETION: when every non-hidden entry has `reviewed: true`, set progress.done=true. The flag lives on the game, so progress survives pauses without any queue file.

THIS BURST: verify AT MOST 12 entries, sequentially, 1.5s sleep between Steam API calls. Persist progress.json after each. After ~12 entries, STOP and exit; the loop starts your next burst.

PER ENTRY, verify vs Steam / HowLongToBeat / YouTube: rating, price, hours, playersMax, oneCopy, genres (by taxonomy axes), tier, endingType, youtubeUrl, imageUrl.

AUTO-FIX (only these): broken youtubeUrl (youtubeSearch placeholder / 404 / unrelated) via ../coop-hunter/scripts/fix_youtube.py; broken imageUrl via ../coop-hunter/scripts/fix_image.py. EVERYTHING editorial (genres / endingType / playersMax / oneCopy / hours / year / tier) -> LOG to state/proposed-fixes.tsv, do NOT auto-write.

CRON COORDINATION (priority: cron > fact-checker): read .github/refresh-status.json. If last_success < 30h old, SKIP rating + price checks entirely — the cron owns them. If stale/missing, you MAY log rating/price drift to proposed-fixes.tsv, but do not fight the cron.

ENDLESS REMOVAL (you are the enforcer now): if an entry matches the hardcoded blocklist OR has Steam tags MMO/Massively Multiplayer/Battle Royale OR >=3 negative-review endless hits -> AUTO-REMOVE via ../coop-hunter/scripts/remove_entry.py <id>. Borderline/judgment cases -> log to state/proposed-removals.tsv only. NEVER touch app.js / index.html / styles.css. NEVER ASK QUESTIONS — ambiguous -> discrepancies.tsv, continue.

COMPLETION: per the SCOPE rules above (all: current_idx past the end; new: queue drained). When complete set progress.done=true; otherwise leave done=false and the loop runs the next burst.

End with one line: [scope=<all|new> checked=N fixed=F proposed=P]
PROMPT_EOF
)

# -------- delta tracking --------
INITIAL_CHECKED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['checked_count'])")
TOTAL=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['total_entries'])")
PREV_IDX=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['current_idx'])")
PREV_CHECKED=$INITIAL_CHECKED   # mode-agnostic progress signal for the stagnation guard
if [ "$SCOPE" = "new" ]; then
  echo "Starting: scope=new, $QUEUE_N games queued by coop-hunter"
else
  echo "Starting: scope=all, at entry $PREV_IDX / $TOTAL"
fi
echo ""

# -------- consistency audit (cheap, no network) — refresh inconsistencies.tsv --------
# Catches catalog self-contradictions (same franchise added vs skipped, mixed
# endingType) that per-entry checks miss. Output is a short owner-review queue.
echo "[$(date)] Running consistency audit (find_neighbors.py)..."
"$PY" "$REPO_ROOT/.claude/skills/fact-checker/scripts/find_neighbors.py" || true
echo ""

# -------- main loop: one claude -p burst per iteration --------
MAX_BURSTS=80             # runaway guard. Earlier 600 combined with the missing
                          # session-limit detector produced 600 instant-fail bursts
                          # in ~30s when Anthropic capped the session overnight.
RATE_LIMIT_SLEEP=1800     # 30 min — Anthropic 5h-window reset granularity
STAGNATION_THRESHOLD=3    # N consecutive bursts where current_idx didn't move => stop
TRANSCRIPT_CAP_BYTES=$((20 * 1024 * 1024))   # cap the log at ~20 MB
BURST=0
STAGNANT_BURSTS=0         # rolling counter for stagnation guard

# Fresh log each run (transcript is for tail -f + rate-limit detection, not state).
: > "$TRANSCRIPT"

is_rate_limited() {
  # See run-coop-hunter.sh for the full rationale; the session-limit branch is
  # what caught us out on 2026-05-28.
  # See run-coop-hunter.sh: the bare "429" matched entry index "[429/484]" and
  # caused a false 30-min sleep. Keep every alternative specific to limit wording.
  # Inspect ONLY the latest burst's output ($BURST_OUT), NOT the accumulated
  # transcript — a stale "session limit · resets 11:10pm" line from hours ago
  # (already reset) must not re-trigger a sleep after a successful burst.
  grep -qiE \
    "rate limit|message limit|usage limit|weekly limit|too many requests|try again in [0-9]+ ?(hour|hr|h)|quota exceeded|error[: ]*429|you'?ve hit your (session|usage|weekly) limit|session limit.*reset|hit your (session|usage|weekly) limit" \
    "$BURST_OUT" 2>/dev/null
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

  # < /dev/null is the fix for the burst hang: claude -p otherwise keeps stdin
  # on the terminal and BLOCKS waiting for input after finishing the burst,
  # instead of exiting (confirmed via lsof: fd 0 = /dev/ttysNNN). EOF on stdin
  # makes it exit cleanly. | tee keeps live output in this window + the log.
  # --model opus = LATEST Opus alias (see run-coop-hunter.sh for the rationale).
  # tee to a per-burst file (overwritten each burst) so is_rate_limited sees only
  # THIS burst, then append to the accumulated transcript for live tail/history.
  "$CLAUDE_CMD" -p --model opus --dangerously-skip-permissions "$BURST_PROMPT" < /dev/null 2>&1 | tee "$BURST_OUT"
  cat "$BURST_OUT" >> "$TRANSCRIPT"
  cap_transcript

  if [ ! -f "$PROGRESS_FILE" ]; then
    echo "[$(date)] WARNING: progress.json missing. Stopping." >&2
    break
  fi

  read -r CHECKED FIXED PROPOSED DONE IDX <<<"$("$PY" -c "
import json
p=json.load(open('$PROGRESS_FILE'))
print(p.get('checked_count',0), p.get('fixed_count',0), p.get('proposed_count',0),
      p.get('done',False), p.get('current_idx',0))
")"
  # checked_count advances per verified entry in BOTH scopes, so it (not idx, which
  # stays put in new-scope) is the universal "did we make progress" signal.
  CHECKED_DELTA=$((CHECKED - PREV_CHECKED))
  PREV_CHECKED=$CHECKED
  PREV_IDX=$IDX

  echo ""
  if [ "$SCOPE" = "new" ]; then
    # new-scope progress = entries in data.js still lacking `reviewed: true`.
    QUEUE_LEFT=$("$PY" -c "
import re
t=open('$DATA_JS',encoding='utf-8').read()
b=re.findall(r'\n  \{\n.*?\n  \}', t, re.DOTALL)
print(sum(1 for x in b if 'hidden: true' not in x and not re.search(r'\n    reviewed:\s*true', x)))
" 2>/dev/null || echo "?")
    echo "[$(date)] Burst #$BURST done. scope=new unreviewed_left=$QUEUE_LEFT (+$CHECKED_DELTA checked) fixed=$FIXED proposed=$PROPOSED done=$DONE"
  else
    echo "[$(date)] Burst #$BURST done. idx=$IDX/$TOTAL (+$CHECKED_DELTA checked) fixed=$FIXED proposed=$PROPOSED done=$DONE"
  fi

  if [ "$DONE" = "True" ] || [ "$DONE" = "true" ]; then
    echo "[$(date)] FACT-CHECK COMPLETE."
    break
  fi

  if is_rate_limited; then
    echo "[$(date)] Rate/session limit detected. Sleeping 30m before the next burst (Ctrl+C to stop)."
    STAGNANT_BURSTS=0
    sleep "$RATE_LIMIT_SLEEP"
    continue
  fi

  # Stagnation guard: fact-checker should always move forward (checked_count
  # increments per verified entry, in BOTH scopes). If 3 consecutive bursts left
  # it unchanged, the skill is stuck or hitting some unhandled error — bail out
  # instead of spinning.
  if [ "$CHECKED_DELTA" -le 0 ]; then
    STAGNANT_BURSTS=$((STAGNANT_BURSTS + 1))
    echo "[$(date)] Stagnation: checked_count did not advance. streak=$STAGNANT_BURSTS/$STAGNATION_THRESHOLD"
    if [ "$STAGNANT_BURSTS" -ge "$STAGNATION_THRESHOLD" ]; then
      echo "[$(date)] STAGNATION STOP — $STAGNATION_THRESHOLD consecutive no-progress bursts. Aborting fact-checker."
      break
    fi
  else
    STAGNANT_BURSTS=0
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

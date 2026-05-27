#!/usr/bin/env bash
# coop-hunter runner (macOS / Linux) — finds new PC co-op games, appends to data.js.
#
# ARCHITECTURE (changed 2026-05-27): headless bursts, NOT /goal.
#   /goal kept ONE claude process alive across all turns; its evaluator reads the
#   whole transcript every turn and on long runs overflowed ("Prompt is too long")
#   and hung, forcing a manual Ctrl+C. Instead, this loop invokes `claude -p` once
#   per BURST: a fresh process does ~20 candidates, persists state, and EXITS. The
#   bash loop then starts the next burst (fresh transcript). No evaluator, no
#   overflow, no hang — truly hands-off.
#
#   - max_phase=4 (cascading); resumes from state/progress.json each burst.
#   - PUSH POLICY: zero interim pushes; ONE commit + push at the very end (Final
#     pass), done by the skill when the catalog is exhausted.
#   - Classification reads .claude/skills/shared/taxonomy.json (authoritative).
#
# Usage:   ./run-coop-hunter.sh      (chmod +x once)
# Stop:    Ctrl+C. State persists; safe to restart — resumes where it stopped.
# Watch:   tail -f coop-hunter-transcript.log

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
  "auto_push_every_n": 0,
  "last_push_at": 0,
  "phase_4_zero_yield_passes": 0,
  "session_added_ids": [],
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
for k, v in defaults.items():
    if k not in cur:
        cur[k] = v
cur["max_phase"] = 4
cur["auto_push_every_n"] = 0

# An explicit launch means "go again". A previous run may have set done=true
# after two dry phase-4 passes; the owner re-launches precisely because sources
# refresh over time. Clear done + reset the dry-pass counter so a new burst run
# resumes hunting from current_offset.
if cur.get("done"):
    cur["done"] = False
    cur["phase_4_zero_yield_passes"] = 0

with open(path, "w") as f:
    json.dump(cur, f, indent=2)
print(f"progress.json: added={cur['added_count']}, phase={cur['current_phase']}, p4dry={cur.get('phase_4_zero_yield_passes',0)}, done={cur['done']}")
PYEOF

# -------- header --------
echo ""
echo "================================================================"
echo "  coop-hunter — headless-burst runner (macOS)"
echo "================================================================"
echo "  Started:    $(date)"
echo "  Repo:       $REPO_ROOT"
echo "  Claude CLI: $CLAUDE_CMD"
echo "  Transcript: $TRANSCRIPT"
echo ""
echo "  Each burst = one fresh 'claude -p' process (~20 candidates) that exits."
echo "  No /goal, no evaluator overflow, no hang. Loop ends when done=true."
echo "  Push: NONE until the very end (skill Final pass makes one commit + push)."
echo "  Rate-limit pauses are uncapped; Ctrl+C stops; state resumes on restart."
echo "================================================================"
echo ""

# -------- the per-burst prompt (NO /goal — plain headless task) --------
BURST_PROMPT=$(cat <<'PROMPT_EOF'
Run the coop-hunter skill (.claude/skills/coop-hunter/) for ONE BURST, then EXIT. This is a headless invocation; a bash loop re-invokes you for each burst and you resume from state/progress.json. Do NOT try to finish the whole catalog in one invocation.

Read first: SKILL.md; .claude/skills/shared/taxonomy.json (AUTHORITATIVE for genre + endingType — classify by axis tier/perspective/mechanic/setting/structure, never invent tags, taxonomy.json wins over classification.md); classification.md; sources.json; state/progress.json.

THIS BURST:
- Resume from progress.json (current_source_idx / current_offset / current_phase). Process AT MOST 20 candidates (added + skipped) this invocation, sequentially, 1.5s sleep between Steam API calls.
- Persist progress.json + added.tsv / skipped.tsv after EACH candidate. Append every added id to session_added_ids.
- After ~20 candidates (or at a source/phase boundary), STOP and exit. The loop starts your next burst fresh.

RULES:
1. data.js only via scripts/append_entry.py (exit 4 = no real 11-char video_id; exit 3 = id in removed-entries.tsv). Find a REAL gameplay video via SKILL.md §8 drill cascade — never a youtubeSearch placeholder.
2. CRON COORDINATION: the GitHub Actions cron owns price + rating on EXISTING entries. If .github/refresh-status.json last_success is < 30h old, SKIP price/rating checks for existing entries. NEW entries: fetch fresh once. NEVER overwrite cron-owned fields otherwise.
3. NEVER touch app.js / index.html / styles.css.
4. GROWTH ONLY. Phase cascade 1->4 (SKILL.md). Phase 4 = reeval_skipped + steam_more_like_this + websearch_niche_queries + drill sources. coop-hunter NO LONGER re-validates existing entries (that moved to the fact-checker skill) — do not re-walk the catalog.
5. FINAL FIT-GATE before every add (SKILL.md §8b): confirm PC+Steam, real 2+ co-op, a CLEAR finite ending, >=50 reviews & >=50% positive, not blocklisted, real video+image. On ANY doubt -> SKIP (skipped.tsv reason low_fit / taxonomy_gap). Prevention beats cleanup; the owner wants a small trustworthy catalog, not volume.
6. NEVER ASK QUESTIONS. Ambiguous classification -> skipped.tsv reason taxonomy_ambiguous. Owner is asleep.
7. DRILL MODE: exhaust alternative queries / sources before giving up; treat "cannot find X" as a hypothesis to disprove.

COMPLETION: only when the catalog is exhausted — TWO consecutive dry phase-4 passes (phase_4_zero_yield_passes >= 2) — run the Final pass on session_added_ids (verify image + youtube only, NEVER price/rating), make ONE git commit + push, then set progress.done=true and session_added_ids=[]. Otherwise leave done=false; the loop runs the next burst.

End with one line: [P=phase N=added K=skipped p4dry=X last=<title>]
PROMPT_EOF
)

# -------- delta tracking --------
INITIAL_ADDED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['added_count'])")
echo "Starting added_count: $INITIAL_ADDED"
echo ""

# -------- main loop: one claude -p burst per iteration --------
MAX_BURSTS=600            # runaway guard (each burst ~ up to 20 candidates)
RATE_LIMIT_SLEEP=1800     # 30 min — Anthropic 5h-window reset granularity
TRANSCRIPT_CAP_BYTES=$((20 * 1024 * 1024))   # cap the log at ~20 MB
BURST=0

# Start every run with a FRESH log (was: tee -a accumulated across all runs and
# grew to ~70 MB). The transcript is just for live `tail -f` + rate-limit
# detection; it is not state, so resetting it costs nothing.
: > "$TRANSCRIPT"

is_rate_limited() {
  tail -n 200 "$TRANSCRIPT" 2>/dev/null | grep -qiE \
    'rate limit|message limit|usage limit|too many requests|try again in [0-9]+ ?(hour|hr|h)|quota exceeded|429'
}

cap_transcript() {
  # Bound a single long run: if the log passes the cap, keep only the last
  # 4000 lines (in place, same inode — `tail -f` survives the truncation).
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

  # Headless single burst: fresh process, fresh transcript, exits when done.
  "$CLAUDE_CMD" -p --dangerously-skip-permissions "$BURST_PROMPT" 2>&1 | tee -a "$TRANSCRIPT"
  cap_transcript

  if [ ! -f "$PROGRESS_FILE" ]; then
    echo "[$(date)] WARNING: progress.json missing. Stopping." >&2
    break
  fi

  ADDED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['added_count'])")
  SKIPPED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['skipped_count'])")
  DONE=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['done'])")
  PHASE=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['current_phase'])")

  echo ""
  echo "[$(date)] Burst #$BURST done. added=$ADDED skipped=$SKIPPED phase=$PHASE done=$DONE"

  if [ "$DONE" = "True" ] || [ "$DONE" = "true" ]; then
    echo "[$(date)] SKILL DONE — catalog exhausted, Final pass + push completed by the skill."
    break
  fi

  if is_rate_limited; then
    echo "[$(date)] Rate limit detected. Sleeping 30m before the next burst (Ctrl+C to stop)."
    sleep "$RATE_LIMIT_SLEEP"
    continue
  fi

  # Normal burst boundary — brief pause, next fresh burst.
  sleep 3
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
  echo "  Bursts run:           $BURST"
fi
echo ""
echo "Review:"
echo "  Transcript:   $TRANSCRIPT"
echo "  Added games:  $REPO_ROOT/.claude/skills/coop-hunter/state/added.tsv"
echo "  Skipped:      $REPO_ROOT/.claude/skills/coop-hunter/state/skipped.tsv"
echo ""
echo "Git log of this session's commits:"
git log --oneline -n 30 origin/main..HEAD 2>/dev/null || git log --oneline -n 10

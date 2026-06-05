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
#   - ETERNAL: there is no "done". The skill walks the structured sources, then
#     switches to creative discovery (invents fresh search angles) and keeps
#     going. Resumes from state/progress.json each burst. Stop with Ctrl+C.
#   - PUSH POLICY: the LAUNCHER pushes periodically (this loop's do_push), every
#     ~PUSH_EVERY_SEC seconds OR every PUSH_EVERY_N new adds — not the skill.
#   - Classification reads .claude/skills/shared/taxonomy.json (authoritative).
#
# Usage:   ./run-coop-hunter.sh      (chmod +x once)
# Stop:    Ctrl+C. State persists; safe to restart — resumes where it stopped.
# Watch:   tail -f coop-hunter-transcript.log

set -u

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
PROGRESS_FILE="$REPO_ROOT/.claude/skills/coop-hunter/state/progress.json"
SOURCES_FILE="$REPO_ROOT/.claude/skills/coop-hunter/sources.json"
TRANSCRIPT="$REPO_ROOT/coop-hunter-transcript.log"
BURST_OUT="$REPO_ROOT/.coop-hunter-burst.tmp"   # ONLY the latest burst's output — what is_rate_limited inspects

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
  "last_push_at": 0,
  "session_added_ids": [],
  "completed_sources": [],
  "source_pass_log": [],
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

# ETERNAL model: there is no "done". Older runs may have persisted done=true (a
# now-removed exit condition) — strip it so it can never short-circuit a burst.
cur.pop("done", None)
cur.pop("auto_push_every_n", None)
cur.pop("phase_4_zero_yield_passes", None)

with open(path, "w") as f:
    json.dump(cur, f, indent=2)
print(f"progress.json: added={cur['added_count']}, phase={cur['current_phase']}, src_idx={cur.get('current_source_idx',0)}")
PYEOF

# -------- tunables (defined BEFORE the header, which prints them) --------
RATE_LIMIT_SLEEP=1800        # 30 min — wait out an Anthropic session/usage cap
PUSH_EVERY_SEC=3600          # push at least hourly...
PUSH_EVERY_N=10              # ...or every 10 new games, whichever comes first
RUNAWAY_BURSTS=100000        # NOT a real stop — just a sanity backstop against an infinite tight loop
TRANSCRIPT_CAP_BYTES=$((20 * 1024 * 1024))   # cap the log at ~20 MB

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
echo "  ETERNAL: no done — sources, then creative discovery, forever. Ctrl+C stops."
echo "  Push: periodic (every ~${PUSH_EVERY_SEC}s or ${PUSH_EVERY_N} new adds), by this launcher."
echo "  Rate-limit pauses sleep ${RATE_LIMIT_SLEEP}s; state resumes on restart."
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
- Append every added id to session_added_ids. (append_entry.py adds entries WITHOUT a `reviewed` flag, so `fact-checker new` picks them up automatically — no separate queue file.)

RULES:
1. data.js only via scripts/append_entry.py (exit 4 = no real 11-char video_id; exit 3 = id in removed-entries.tsv; it also dedupes by Steam app_id). Find a REAL gameplay video via SKILL.md §8 drill cascade — never a youtubeSearch placeholder.
2. CRON COORDINATION: the GitHub Actions cron owns price + rating on EXISTING entries. If .github/refresh-status.json last_success is < 30h old, SKIP price/rating checks for existing entries. NEW entries: fetch fresh once.
3. NEVER touch app.js / index.html / styles.css.
4. GROWTH ONLY (no re-validating existing entries — that's the fact-checker). Walk the structured sources (phase cascade 1->4); when they run dry, switch to CREATIVE DISCOVERY (SKILL.md) — invent fresh search angles (recent Steam releases, YouTube, niche subreddits, 2026 articles, More-like-this) and log them in discovery-log.tsv. There is NO done — keep finding.
5. FINAL FIT-GATE before every add (SKILL.md §8b + finish_strength): PC+Steam, real 2+ co-op, a finish (hard, or soft -> leading 🟠 in verdict), >=50 reviews & >=50% positive, not blocklisted, real video+image. On doubt -> SKIP (low_fit). A changeable-reason reject (EA/rating/finish-unverified) -> also log to borderline-watch.tsv.
6. NEVER ASK QUESTIONS. Ambiguous -> skipped.tsv via scripts/log_skip.py. Owner is asleep.
7. DRILL MODE: exhaust alternatives before giving up; "cannot find X" is a hypothesis to disprove.

NO COMPLETION: never set progress.done in normal hunting — there is no "finished". Persist after each candidate; the launcher pushes periodically. Just keep searching, burst after burst.

End with one line: [P=phase N=added K=skipped src=<id> last=<title>]
PROMPT_EOF
)

# -------- delta tracking --------
INITIAL_ADDED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE'))['added_count'])")
echo "Starting added_count: $INITIAL_ADDED"
echo ""

# -------- main loop: ETERNAL — one claude -p burst per iteration, never stops --------
# coop-hunter is a never-stop searcher: it walks the structured sources, then invents
# its own discovery angles (SKILL.md "Creative discovery"). There is NO done/stagnation/
# max-bursts stop — only Ctrl+C (or a rate-limit wait) pauses it. The launcher pushes
# periodically so finds reach the site without a "final" push.
# (RATE_LIMIT_SLEEP / PUSH_EVERY_* / RUNAWAY_BURSTS / TRANSCRIPT_CAP_BYTES are
#  defined above the header so the header can print them under `set -u`.)
BURST=0
LAST_PUSH_EPOCH=$(date +%s)
LAST_PUSH_ADDED=$INITIAL_ADDED

# Fast-fail backoff (#8): the only long pause is the rate-limit branch. A burst
# that dies FAST for a non-rate-limit reason (bad API key, network down, script
# crash) returns in ~2s with no "limit" string, so without this the loop would
# relaunch every ~5s forever, hammering the API unattended. We measure per-burst
# PROGRESS = growth of (added+skipped); a healthy ~20-candidate burst grows it by
# >0, a dead/empty burst grows it by 0. On zero progress we double the pre-burst
# sleep (3->6->12->...->300s cap); any productive burst resets it to 3. This is
# NOT a stop — the loop stays eternal and recovers instantly once finds resume.
BACKOFF=3
PREV_ADDED=$INITIAL_ADDED
PREV_SKIPPED=$("$PY" -c "import json; print(json.load(open('$PROGRESS_FILE')).get('skipped_count',0))")

# Start every run with a FRESH log (was: tee -a accumulated across all runs and
# grew to ~70 MB). The transcript is just for live `tail -f` + rate-limit
# detection; it is not state, so resetting it costs nothing.
: > "$TRANSCRIPT"

is_rate_limited() {
  # NB: Anthropic surfaces two distinct kinds of "you must wait" message:
  #   (1) per-request rate limits  -> "rate limit", "429", "too many requests"
  #   (2) per-session usage caps   -> "You've hit your session limit ·
  #                                    resets 6:10am (Europe/Kiev)"
  # The session-cap line is THE one we missed before — without it the burst
  # returned in ~1s with the cap message, the loop counted it as a "normal
  # burst boundary", slept 3s, and tried again 600 times in ~30 minutes.
  # IMPORTANT: every alternative here must be SPECIFIC enough not to match the
  # skill's own progress output. The bare token "429" was a bug — it matched the
  # entry index in lines like "[429/484] sine-mora-ex: ..." and triggered a false
  # 30-min sleep at 45% session usage. HTTP 429 is already covered semantically by
  # "too many requests"; the "hit your <X> limit" branches are scoped to the words
  # Anthropic actually uses (session/usage/weekly) so game text can't trip them.
  # Inspect ONLY the latest burst's output ($BURST_OUT), NOT the accumulated
  # transcript — a stale "session limit · resets 11:10pm" line from a burst hours
  # ago (already reset) must not re-trigger a sleep after a successful burst.
  grep -qiE \
    "rate limit|message limit|usage limit|weekly limit|too many requests|try again in [0-9]+ ?(hour|hr|h)|quota exceeded|error[: ]*429|you'?ve hit your (session|usage|weekly) limit|session limit.*reset|hit your (session|usage|weekly) limit" \
    "$BURST_OUT" 2>/dev/null
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

do_push() {
  # Periodic commit + rebase-onto-cron + push, called between bursts on a cadence.
  # On any failure it leaves the commit in place and retries next cadence — finds
  # are never lost. Reads $ADDED / updates $LAST_PUSH_* (loop-scope vars).
  git add data.js \
          .claude/skills/shared/reeval.tsv \
          .claude/skills/shared/hard-block.tsv \
          .claude/skills/shared/owner-review.tsv \
          .claude/skills/coop-hunter/state/progress.json 2>/dev/null
  if git diff --cached --quiet; then return; fi
  local n=$((ADDED - LAST_PUSH_ADDED))
  git commit -m "coop-hunter: +${n} games (total ${ADDED})" >/dev/null 2>&1
  if ! git pull --rebase origin main >/dev/null 2>&1; then
    echo "[$(date)] push deferred — rebase conflict; committed locally, will retry next cadence." >&2
    git rebase --abort >/dev/null 2>&1 || true
    return
  fi
  if git push origin main >/dev/null 2>&1; then
    echo "[$(date)] pushed +${n} games (total ${ADDED})"
    LAST_PUSH_EPOCH=$(date +%s); LAST_PUSH_ADDED=$ADDED
  else
    echo "[$(date)] push failed — committed locally, will retry next cadence." >&2
  fi
}

while true; do
  BURST=$((BURST + 1))
  if [ "$BURST" -gt "$RUNAWAY_BURSTS" ]; then
    echo "[$(date)] Hit RUNAWAY_BURSTS backstop ($RUNAWAY_BURSTS). Stopping." >&2
    break
  fi

  echo ""
  echo "[$(date)] ================= Burst #$BURST ================="
  echo ""

  # Headless single burst: fresh process, exits when its burst is done.
  # < /dev/null fixes the stdin-TTY hang (claude -p would otherwise block on the
  # terminal after finishing instead of exiting). --model opus = latest-Opus alias.
  # tee to a per-burst file ($BURST_OUT, overwritten each burst) so is_rate_limited
  # sees ONLY this burst, then append to the accumulated transcript for tail/history.
  "$CLAUDE_CMD" -p --model opus --dangerously-skip-permissions "$BURST_PROMPT" < /dev/null 2>&1 | tee "$BURST_OUT"
  cat "$BURST_OUT" >> "$TRANSCRIPT"
  cap_transcript

  if [ ! -f "$PROGRESS_FILE" ]; then
    echo "[$(date)] WARNING: progress.json missing. Stopping." >&2
    break
  fi

  read -r ADDED SKIPPED PHASE SRC_IDX OFFSET <<<"$("$PY" -c "
import json
p=json.load(open('$PROGRESS_FILE'))
print(p.get('added_count',0), p.get('skipped_count',0), p.get('current_phase','?'),
      p.get('current_source_idx','?'), p.get('current_offset','?'))
")"
  # The python print can come back empty (transient JSON read error, progress.json
  # corrupted mid-write, interpreter hiccup) — `read -r` still returns 0, leaving
  # ADDED empty. Empty in $(( )) silently behaves as 0, which would corrupt the
  # push delta / push timing. If the counter we do arithmetic on is non-numeric,
  # skip this burst's push accounting rather than let empty propagate.
  if ! [[ "$ADDED" =~ ^[0-9]+$ ]]; then
    echo "[$(date)] WARNING: burst #$BURST produced no readable added_count (got '$ADDED') — skipping push accounting this burst." >&2
    if is_rate_limited; then
      echo "[$(date)] Rate/session limit detected. Sleeping 30m (Ctrl+C to stop)."
      sleep "$RATE_LIMIT_SLEEP"
      continue
    fi
    # Unreadable counters == no progress this burst -> back off (do NOT reset).
    BACKOFF=$(( BACKOFF * 2 )); [ "$BACKOFF" -gt 300 ] && BACKOFF=300
    echo "[$(date)] no progress this burst; backing off to ${BACKOFF}s"
    sleep "$BACKOFF"
    continue
  fi
  echo ""
  echo "[$(date)] Burst #$BURST done. added=$ADDED (+$((ADDED-LAST_PUSH_ADDED)) since push) skipped=$SKIPPED phase=$PHASE src_idx=$SRC_IDX off=$OFFSET"

  # NO done/stagnation/max-bursts stop — coop-hunter is an eternal searcher. The
  # only pauses are a rate-limit wait and the owner's Ctrl+C.
  if is_rate_limited; then
    echo "[$(date)] Rate/session limit detected. Pushing pending finds, then sleeping 30m (Ctrl+C to stop)."
    do_push    # don't sit on unpushed finds through a 30m wait
    sleep "$RATE_LIMIT_SLEEP"
    continue
  fi

  # Periodic push: at least hourly OR every PUSH_EVERY_N adds, whichever first.
  NOW=$(date +%s)
  if [ $((NOW - LAST_PUSH_EPOCH)) -ge "$PUSH_EVERY_SEC" ] || [ $((ADDED - LAST_PUSH_ADDED)) -ge "$PUSH_EVERY_N" ]; then
    do_push
  fi

  # Fast-fail backoff: PROGRESS = growth of (added+skipped) vs the previous burst.
  # SKIPPED is already validated numeric by the guard above? No — only ADDED was;
  # default a non-numeric SKIPPED to 0 so the arithmetic stays set -u / numeric-safe.
  [[ "$SKIPPED" =~ ^[0-9]+$ ]] || SKIPPED=0
  PROGRESS=$(( (ADDED - PREV_ADDED) + (SKIPPED - PREV_SKIPPED) ))
  PREV_ADDED=$ADDED; PREV_SKIPPED=$SKIPPED
  if [ "$PROGRESS" -gt 0 ]; then
    BACKOFF=3
    sleep 3
  else
    BACKOFF=$(( BACKOFF * 2 )); [ "$BACKOFF" -gt 300 ] && BACKOFF=300
    echo "[$(date)] no progress this burst; backing off to ${BACKOFF}s"
    sleep "$BACKOFF"
  fi
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

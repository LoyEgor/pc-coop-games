#!/usr/bin/env bash
# run-all — hands-off maintenance cycle for the co-op catalog (macOS / Linux).
#
# Runs the two repeatable jobs back-to-back, each to completion, with NO manual
# steps in between:
#   STAGE 1 — coop-hunter   (./run-coop-hunter.sh): find new games, append to
#             data.js, and (in its Final pass) make ONE commit + push.
#   STAGE 2 — fact-checker  (./run-fact-checker.sh): verify the whole catalog,
#             auto-fix safe drift (broken media), log editorial proposals.
#   FINAL   — commit + push anything fact-checker left in the working tree, so
#             the run ends clean with nothing dangling.
#
# Each sub-launcher is self-contained: its own rate-limit-aware restart loop,
# 200-crash budget, transcript, and resume-from-state. This wrapper just chains
# them and adds the closing commit.
#
# NOT included: the one-time taxonomy migration (./run-migration.sh) — that is a
# separate, already-completed step. run-all is the ongoing grow+verify cycle.
#
# Usage:
#   ./run-all.sh
#
# Stop everything: Ctrl+C (kills the current stage and exits the whole wrapper).
#
# Monitor from a second Terminal:
#   tail -f coop-hunter-transcript.log     # during stage 1
#   tail -f fact-checker-transcript.log    # during stage 2

set -u

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

PY="$(command -v python3 || true)"

# Ctrl+C stops the whole pipeline, not just the current stage.
trap 'echo ""; echo "[run-all] Interrupted by user — stopping the whole pipeline."; exit 130' INT

banner() {
  echo ""
  echo "################################################################"
  echo "#  $1"
  echo "#  $(date)"
  echo "################################################################"
  echo ""
}

banner "run-all START — coop-hunter then fact-checker, hands-off"

# -------- STAGE 1: coop-hunter --------
banner "STAGE 1/2 — coop-hunter (find new games)"
./run-coop-hunter.sh
echo ""
echo "[run-all] Stage 1 (coop-hunter) finished at $(date)."

# -------- STAGE 2: fact-checker --------
banner "STAGE 2/2 — fact-checker (verify catalog)"
./run-fact-checker.sh
echo ""
echo "[run-all] Stage 2 (fact-checker) finished at $(date)."

# -------- FINAL: commit + push anything left in the working tree --------
banner "FINAL — committing any leftover working-tree changes"
# coop-hunter already pushed its own batch. fact-checker leaves safe media
# fixes + state logs uncommitted; capture them in one commit so nothing dangles.
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -m "run-all: fact-checker media fixes + state logs"
  # Pull/rebase in case the refresh-prices cron landed during the run.
  git pull --rebase origin main || true
  if git push origin main; then
    echo "[run-all] Final commit pushed."
  else
    echo "[run-all] WARNING: final push failed — changes are committed locally, push by hand." >&2
  fi
else
  echo "[run-all] Nothing left to commit."
fi

banner "run-all COMPLETE"
echo "Review:"
echo "  coop-hunter added:   .claude/skills/coop-hunter/state/added.tsv"
echo "  fact-checker fixes:  .claude/skills/fact-checker/state/applied-fixes.tsv"
echo "  fact-checker review: .claude/skills/fact-checker/state/proposed-fixes.tsv"
echo "  git log:             git log --oneline -15"

# Skills + automation in this project

Two long-running, `/goal`-driven, drill-mode skills + one fully-automated
GitHub Actions cron that handles price/rating drift without any LLM needed.

| Component | Purpose | Trigger | State |
|---|---|---|---|
| **coop-hunter** (skill) | Discovers new PC co-op games and appends them to `data.js`. | `./run-coop-hunter.sh` (manual) | `.claude/skills/coop-hunter/state/` |
| **fact-checker** (skill) | Walks every existing entry in `data.js` and verifies each field against Steam / HowLongToBeat / YouTube. | `./run-fact-checker.sh` (manual) | `.claude/skills/fact-checker/state/` |
| **refresh-prices** (cron) | Owns `price` and `rating` on existing entries. Re-fetches from Steam daily, commits drift > threshold. No LLM, pure stdlib Python. | `.github/workflows/refresh-prices.yml` (daily 04:00 UTC, GitHub-hosted) | `.github/refresh-status.json` |

**Both skills check `.github/refresh-status.json` before touching price/rating
on existing entries.** If `last_success` is within 30h → cron is healthy,
they skip those two checks and focus on editorial fields. If stale or missing
→ they fall back to doing the fetch themselves and warn. For NEW entries
they always fetch fresh (cron only updates, never inserts).

---

## coop-hunter — *grow the catalog*

Crawls Steam tags, Co-Optimus, curators, Reddit lists, then niche / Wikipedia
sources. For each candidate: dedupes, validates online co-op + finite content +
≥50% Steam reviews, classifies tier and endingType, finds a real YouTube
gameplay video, appends via `scripts/append_entry.py`. Auto-pushes to
`origin/main` every 25 adds. Cascades phases 1→4; phase 4 also auto-removes
endless false positives and auto-fixes broken media. Stops when a phase yields
0 new entries AND revalidation has actually run.

**Read first:** [coop-hunter/SKILL.md](coop-hunter/SKILL.md), [coop-hunter/classification.md](coop-hunter/classification.md), [coop-hunter/sources.json](coop-hunter/sources.json).

**Watch progress:** `tail -f coop-hunter-transcript.log` + `tail -f .claude/skills/coop-hunter/state/added.tsv`.

---

## fact-checker — *verify what's there*

Independent of coop-hunter. Walks the 240 non-hidden entries in order, sleeps
1.5s between Steam API calls, and verifies: `rating`, `price`, `hours`,
`playersMax`, `oneCopy`, `genres` (all applicable taxonomy tags), `tier`,
`endingType`, `youtubeUrl`, `imageUrl`. **Conservative auto-fix scope**:
rating drift ≥5pp, price drift ≥10%, broken YouTube placeholder / 404, broken
image. Everything editorial (genres, endingType, playersMax, oneCopy, hours)
is logged to `state/proposed-fixes.tsv` for the owner to review by hand.
Stops when every entry has been checked AND no partial-check entries remain.

**Read first:** [fact-checker/SKILL.md](fact-checker/SKILL.md). Re-uses
`coop-hunter/scripts/fix_youtube.py` and `coop-hunter/scripts/fix_image.py`
for media auto-fixes.

**Watch progress:** `tail -f fact-checker-transcript.log` + `cat .claude/skills/fact-checker/state/progress.json`.

---

## Shared mechanics (both skills)

- **`/goal` runs the loop.** Each launcher passes a `/goal <…>` prompt that
  defines the completion condition. Claude Code's Haiku evaluator checks after
  every turn; if not satisfied, Claude starts another turn automatically.
  ([docs](https://code.claude.com/docs/en/goal))
- **Rate-limit aware.** Both `./run-*.sh` detect Anthropic rate-limit messages
  in the transcript and sleep 30 min before retrying, without consuming the
  200-crash budget. Multi-day runs survive the 5h-window reset cycle.
- **Resume on Ctrl+C.** Each skill persists state after every unit of work
  (one entry added / one entry verified). Re-running picks up exactly where
  it stopped — no manual flag-flipping required.
- **Never modify `app.js` / `index.html` / `styles.css`.** Both skills are
  forbidden from touching the UI. UI translation / styling is a separate
  session's job.
- **No silent placeholders.** `append_entry.py` exits 4 without a real
  11-char YouTube `video_id` and exit 3 for ids in `removed-entries.tsv`.
- **Python 3.9+, stdlib only.** No `pip install` needed. All scripts have a
  `#!/usr/bin/env python3` shebang and run as `python3 <script>`.

## When to use which

- **You want more games in the catalog** → `coop-hunter`.
- **You suspect existing entries have drifted (price, rating, broken video,
  wrong tag)** → `fact-checker`.
- **You want both** → run them sequentially. They don't share state, so
  parallel runs are safe but will both fight for Steam's rate limit; one at
  a time is cheaper.

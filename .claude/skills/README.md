# Skills + automation in this project

Two `/goal`-driven, drill-mode skills (run via three launchers) + one
fully-automated GitHub Actions cron that handles price/rating drift with no LLM.

| Component | Purpose | Launcher / trigger | State |
|---|---|---|---|
| **coop-hunter** (skill) | Discovers new PC co-op games and appends them to `data.js`. | `./run-coop-hunter.sh` | `.claude/skills/coop-hunter/state/` |
| **fact-checker** (skill) | Walks every existing entry and verifies each field against Steam / HLTB / YouTube. Logs editorial discrepancies. | `./run-fact-checker.sh` | `.claude/skills/fact-checker/state/` |
| **taxonomy migration** (fact-checker, special mode) | One-time: rewrites all entries onto the axis taxonomy (split FPS, narrow Adventure, fill perspective). | `./run-migration.sh` | shares fact-checker state (`mode=taxonomy_migration`) |
| **refresh-prices** (cron) | Owns `price` and `rating` on existing entries. Re-fetches from Steam daily, commits drift > threshold. Pure stdlib Python, no LLM. | `.github/workflows/refresh-prices.yml` (daily 04:00 UTC, GitHub-hosted) | `.github/refresh-status.json` |

**The single source of truth for genres + endingType is
[`shared/taxonomy.json`](shared/taxonomy.json).** Both skills read it and classify
by axis (tier / perspective / mechanic / setting / structure); they never invent
tags. `classification.md` and `CLAUDE.md` carry prose for humans but defer to
taxonomy.json on any conflict.

**Both skills check `.github/refresh-status.json` before touching price/rating
on existing entries.** If `last_success` is within 30h → cron is healthy,
they skip those two checks and focus on editorial fields. If stale or missing
→ they fall back to doing the fetch themselves and warn. For NEW entries
they always fetch fresh (cron only updates, never inserts).

**Push policy:** coop-hunter makes exactly ONE commit + push at the end of a run
(after its Final pass) — no interim pushes. fact-checker and migration leave
changes in the working tree for you to review + commit. The cron commits itself.

---

## coop-hunter — *grow the catalog*

Crawls Steam tags, Co-Optimus, curators, Reddit lists, then niche / Wikipedia
sources. For each candidate: dedupes, validates online co-op + finite content +
≥50% Steam reviews, classifies tier and endingType, finds a real YouTube
gameplay video, appends via `scripts/append_entry.py`. Cascades phases 1→4;
phase 4 also auto-removes endless false positives and auto-fixes broken media.
Stops only after TWO consecutive phase-4 passes yield 0 new games (sources
refresh over time, so one dry pass is not enough). One commit + push at the end.

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

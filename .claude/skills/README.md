# Skills + automation in this project

Two headless-burst, drill-mode skills (run via three launchers) + one
fully-automated GitHub Actions cron that handles price/rating drift with no LLM.

Each launcher is a bash loop: one fresh `claude -p` process per BURST does a
small chunk of work (~20 candidates / ~12 entries), persists state, and EXITS;
the loop starts the next burst. (Earlier they used `/goal`, but its evaluator
re-reads the whole transcript every turn and overflowed on long runs — "Prompt
is too long" — so everything moved to headless bursts.)

| Component | Purpose | Launcher / trigger | State |
|---|---|---|---|
| **coop-hunter** (skill) | ETERNAL searcher — discovers new PC co-op games and appends them to `data.js`. Never "done"; Ctrl+C to stop. | `./run-coop-hunter.sh` | `.claude/skills/coop-hunter/state/` |
| **fact-checker** (skill) | Verifies entry fields against Steam / HLTB / YouTube; auto-removes endless games; logs editorial discrepancies. `new` = only games the hunter just added; `all` = whole catalog. | `./run-fact-checker.sh [new\|all]` | `.claude/skills/fact-checker/state/` |
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

**Push policy:** coop-hunter is eternal, so its **launcher** pushes periodically
— every ~hour OR every 10 new games, whichever comes first (it commits, rebases
onto the cron's commits, then pushes; conflicts leave the commit local and retry
next cadence). fact-checker and migration leave changes in the working tree for
you to review + commit. The cron commits itself.

---

## coop-hunter — *grow the catalog (eternal)*

Crawls Steam tags, Co-Optimus, curators, Reddit lists, then niche / Wikipedia
sources. For each candidate: dedupes (by slug AND Steam app_id), validates online
co-op + a finish (hard, or soft → leading 🟠 in the verdict) + ≥50% Steam reviews,
classifies tier and endingType, finds a real YouTube gameplay video, appends via
`scripts/append_entry.py`. Cascades phases 1→4. **There is no "done":** when the
structured sources run dry it switches to CREATIVE DISCOVERY — it invents fresh
search angles (recent Steam releases, YouTube, niche subreddits, 2026 articles,
More-like-this) — and keeps going until you Ctrl+C. Every added game starts
WITHOUT a `reviewed` flag in `data.js`, so `fact-checker new` finds it
automatically (no queue file). State model: CLAUDE.md §6b.

**Read first:** [coop-hunter/SKILL.md](coop-hunter/SKILL.md), [coop-hunter/classification.md](coop-hunter/classification.md), [coop-hunter/sources.json](coop-hunter/sources.json).

**Watch progress:** `tail -f coop-hunter-transcript.log` + `git log --oneline data.js`.

---

## fact-checker — *verify what's there*

Independent of coop-hunter. Two scopes (pick with the launcher arg):
- **`./run-fact-checker.sh`** (= `all`) — walks the whole catalog in order.
- **`./run-fact-checker.sh new`** — verifies ONLY entries lacking `reviewed: true`
  in `data.js` (the games coop-hunter just added), stamping each via
  `mark_reviewed.py`; exits when all are reviewed. The cheap targeted pass to run
  right after an overnight hunt.

Sleeps 1.5s between Steam API calls and verifies: `rating`, `price`, `hours`,
`playersMax`, `oneCopy`, `genres` (all applicable taxonomy tags), `tier`,
`endingType`, `youtubeUrl`, `imageUrl`. **Conservative auto-fix scope**:
rating drift ≥5pp, price drift ≥10%, broken YouTube placeholder / 404, broken
image. It is also the **endless-removal enforcer** — auto-removes deterministic
blocklist/MMO/Battle-Royale matches via `remove_entry.py`, logs judgment calls to
`proposed-removals.tsv`. Everything editorial (genres, endingType, playersMax,
oneCopy, hours) is logged to `state/proposed-fixes.tsv` for the owner to review
by hand. Done when its scope is exhausted (`all`: every entry checked, no partials;
`new`: queue drained).

**Read first:** [fact-checker/SKILL.md](fact-checker/SKILL.md). Re-uses
`coop-hunter/scripts/fix_youtube.py` and `coop-hunter/scripts/fix_image.py`
for media auto-fixes.

**Watch progress:** `tail -f fact-checker-transcript.log` + `cat .claude/skills/fact-checker/state/progress.json`.

---

## Shared mechanics (both skills)

- **Headless bursts run the loop.** Each launcher is a bash `while` loop that
  invokes one fresh `claude -p --model opus` process per burst (`< /dev/null` so
  it exits instead of waiting on the TTY), then starts the next. No `/goal`, no
  evaluator, no transcript overflow.
- **Rate-limit aware.** Both `./run-*.sh` inspect ONLY the latest burst's output
  for Anthropic rate-/session-limit wording and sleep 30 min before the next
  burst. Multi-day runs survive the 5h-window reset cycle. (coop-hunter pushes
  pending finds before that sleep so nothing waits 30 min unpushed.)
- **Resume on Ctrl+C.** Each skill persists state after every unit of work
  (one game added / one entry verified). Re-running picks up exactly where
  it stopped — no manual flag-flipping required.
- **Never modify `app.js` / `index.html` / `styles.css`.** Both skills are
  forbidden from touching the UI. UI translation / styling is a separate
  session's job.
- **No silent placeholders.** `append_entry.py` exits 4 without a real
  11-char YouTube `video_id` and exit 3 for ids in `removed-entries.tsv`.
- **Python 3.9+, stdlib only.** No `pip install` needed. All scripts have a
  `#!/usr/bin/env python3` shebang and run as `python3 <script>`.

## When to use which

- **You want more games in the catalog** → `coop-hunter` (leave it running;
  Ctrl+C when you've had enough).
- **You just ran the hunter and want its finds verified** → `./run-fact-checker.sh new`.
- **You suspect existing entries have drifted (price, rating, broken video,
  wrong tag) across the whole catalog** → `./run-fact-checker.sh` (= `all`).
- **Typical flow** → hunt overnight, then `fact-checker new` in the morning to
  vet the night's additions. Don't run hunter and fact-checker at the same time:
  they don't share state, but they'd both fight Steam's rate limit.

# coop-hunter skill

Autonomous, resumable agent that systematically grows `data.js` with new PC co-op games.

## Quick start

```
./run-coop-hunter.sh
```

The launcher sets up the `/goal` loop, which keeps Claude working across many
turns until the goal is met. Token consumption is paced (sleep between Steam API
calls + small per-turn batch size). The skill stops only after TWO consecutive
phase-4 passes yield 0 new games, then runs a Final pass on what it found and
makes exactly ONE commit + push.

**Classification source of truth:** [`../shared/taxonomy.json`](../shared/taxonomy.json)
(axis-structured: tier / perspective / mechanic / setting / structure). The
prose in `classification.md` defers to it.

## What it does

For each game in each source:

1. Steam search → resolve correct app_id (avoids the misidentification problems we had in the bulk runs).
2. Steam appdetails (`cc=ua`) → name, UAH price, header, publisher, categories.
3. Steam appreviews → `%positive` + sample for finite-content keyword scan.
4. Verify online co-op (Steam category) OR Remote Play.
5. Verify finite content (HowLongToBeat + Steam keyword scan).
6. Classify by axis using `../shared/taxonomy.json`: tier + exactly one perspective + at least one mechanic + optional setting/structure + endingType. Never invent tags.
7. WebSearch for a real gameplay YouTube video (not a search-URL placeholder). `append_entry.py` rejects entries without a real 11-char video_id (exit 4).
8. Append to `data.js` via `scripts/append_entry.py` (also blocks ids in `removed-entries.tsv`, exit 3).
9. Update `state/progress.json` (incl. `session_added_ids`) and `state/added.tsv`.

Every 50 additions: spawn a fresh Agent to spot-check 10 random entries. Failures land in `state/validation-fails.tsv` for human review.

Phase 4 also AUTO-REMOVES endless false positives (`remove_entry.py`) and AUTO-FIXES broken YouTube/images (`fix_youtube.py`, `fix_image.py`) — but never `price`/`rating`, which the GitHub Actions cron owns (see `../README.md`).

## Resume after crash

The skill is fully idempotent. If interrupted at any point:

```
/goal continue with the coop-hunter skill
```

It will read `state/progress.json` and pick up exactly where it stopped.

## Files

```
SKILL.md              Main instructions Claude follows
sources.json          Ordered list of sources to crawl (SteamDB tags, Co-Optimus, curators, Reddit, articles)
classification.md     Prose rules for tier/endingType/quality + blocklist. Defers to ../shared/taxonomy.json.
../shared/taxonomy.json  AUTHORITATIVE genre + endingType definitions (axis-structured)
scripts/
  steam_fetch.py      Steam API helper: search, details, reviews, validate
  append_entry.py     Inserts a new entry (gates: real video_id exit 4, removed-entries exit 3)
  batch_append.py     Bulk insert from a JSON array (same gates as append_entry)
  remove_entry.py     Removes an entry (phase 4 endless cleanup)
  fix_youtube.py      Replaces a broken/placeholder youtubeUrl with a real video id
  fix_image.py        Repoints a broken imageUrl to the steamImage() helper
state/
  progress.json       Current source/offset, counters, session_added_ids, phase_4_zero_yield_passes
  added.tsv           Log of every game added
  skipped.tsv         Log of every skip with reason
  removed-entries.tsv Log of endless games removed in phase 4 (also a re-add blocklist)
  validation-fails.tsv  Spot-check failures awaiting human review
  summary.md          Final report (regenerated each run; may be stale between runs)
```

## Token economics

- Per turn: 3-5 candidates × ~6 API calls each ≈ 20 web calls, plus ~3-5K tokens for reasoning.
- Validation every 50 adds: one fresh subagent run ≈ 30-40K tokens (it does its own WebFetch on 10 Steam pages).
- Estimated total to cover ~250 candidates: 2-4 hours of `/goal` execution, depending on how many WebSearches Steam rate-limits us into retrying.

## Safety

- Won't touch `app.js` / `index.html` / `styles.css`.
- Won't touch `price` / `rating` on existing entries when the refresh-prices cron is healthy (defers via `.github/refresh-status.json`).
- Phases 1-3 only ADD entries. Phase 4 may auto-remove endless false positives and auto-fix broken media — this is intentional (see CLAUDE.md §6); every removal is logged to `removed-entries.tsv`.
- Won't auto-correct the spot-check validation failures — only logs them.
- Won't ask the user questions. Ambiguous candidate → `skipped.tsv` reason `ambiguous` / `taxonomy_ambiguous`.

## Manually checking progress

```bash
cat .claude/skills/coop-hunter/state/progress.json
wc -l .claude/skills/coop-hunter/state/added.tsv
wc -l .claude/skills/coop-hunter/state/skipped.tsv
```

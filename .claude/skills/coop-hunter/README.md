# coop-hunter skill

Autonomous, resumable, **eternal** agent that grows `data.js` with new PC co-op games.

## Quick start

```
./run-coop-hunter.sh
```

The launcher is a bash loop: one fresh `claude -p` burst (~20 candidates) per
iteration, persisting state and exiting; the loop starts the next burst. Token
use is paced (sleep between Steam API calls + small per-burst batch). **There is
no "done":** when the structured sources run dry the skill switches to creative
discovery (invents new search angles) and keeps going until you Ctrl+C. The
**launcher** commits + pushes periodically (~hourly or every 10 adds) — the skill
itself never touches git. Verify the finds afterward with `./run-fact-checker.sh new`.

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
9. Update `state/progress.json` (incl. `session_added_ids`), `state/added.tsv`, and `state/unchecked-by-fc.tsv` (the fact-checker's `new`-mode queue).

Endless cleanup of EXISTING entries is no longer coop-hunter's job — it's the `fact-checker` skill's. coop-hunter only ADDS (with strict add-time gates), and never re-fetches `price`/`rating`, which the GitHub Actions cron owns (see `../README.md`).

## Resume after crash / restart

The skill is fully idempotent. Just re-run the launcher:

```
./run-coop-hunter.sh
```

It reads `state/progress.json` and picks up exactly where it stopped.

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
  fix_image.py        Repoints a broken imageUrl to the authoritative header_image from appdetails
state/
  progress.json       Current source/offset, counters, session_added_ids, source_pass_log
  added.tsv           Log of every game added
  skipped.tsv         Log of every skip with reason
  unchecked-by-fc.tsv Queue of added ids awaiting the fact-checker's `new` mode (drained there)
  discovery-log.tsv   Creative-discovery angles the skill invented once sources ran dry
  removed-entries.tsv Endless games removed by the fact-checker (also a re-add blocklist)
  borderline-watch.tsv  Changeable-reason rejects (EA / rating / finish-unverified) to re-check later
```

## Token economics

- Per burst: ~20 candidates × ~6 API calls each, plus reasoning. One fresh `claude -p` process, then exit.
- It runs indefinitely (eternal). Token use scales with how long you leave it running; Ctrl+C stops it. Rate-/session-limit waits sleep 30 min between bursts.

## Safety

- Won't touch `app.js` / `index.html` / `styles.css`.
- Won't touch `price` / `rating` on existing entries when the refresh-prices cron is healthy (defers via `.github/refresh-status.json`).
- ADD-only. It never removes or re-validates existing entries — that's the `fact-checker` skill's job (see CLAUDE.md §6). Strict add-time gates (SKILL.md §8b) keep junk out.
- Never commits or pushes — the launcher owns git.
- Won't ask the user questions. Ambiguous candidate → `skipped.tsv` reason `ambiguous` / `taxonomy_ambiguous`.

## Manually checking progress

```bash
cat .claude/skills/coop-hunter/state/progress.json
wc -l .claude/skills/coop-hunter/state/added.tsv
wc -l .claude/skills/coop-hunter/state/skipped.tsv
```

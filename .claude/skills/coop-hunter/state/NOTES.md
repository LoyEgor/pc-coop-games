# Coop-hunter session notes — 2026-05-26

## Status at stop
- **Added during prior run: 34 games** (data.js: 125 original → 159 total → 143 after 2026-05-26 blocklist cleanup)
- **Skipped: 7** (see `skipped.tsv`)
- **Source in progress: source 0** (SteamDB Co-op Campaign tag = 1685)

## 2026-05-26 cleanup pass (manual review)
- Removed 16 blocklisted endless games (Helldivers 2, Core Keeper, V Rising, Enshrouded, Palworld, Sea of Thieves, Deep Rock Galactic, Lethal Company, Bloons TD 6, Crab Champions, Schedule I, R.E.P.O., Boomerang Fu, Planet Crafter, Brotato, Don't Starve Together). See `removed-entries.tsv` for the second batch of removals at this timestamp.
- Hardened `append_entry.py` to reject any id present in `removed-entries.tsv` (exit code 3). `SKILL.md` §0 now mandates this filter before any API calls.
- Added `scripts/fix_youtube.py` and updated phase 4 `revalidate_existing` to auto-fix `youtubeSearch(...)` placeholders and auto-remove endless false positives (was only-log previously).
- `progress.json` reset to `done: false` so the next `/goal` run resumes work.
- Source 0 method: SteamDB direct returned 403, so used the **Steam Store search** as a proxy:
  `https://store.steampowered.com/search/?tags=1685&supportedlang=english&category2=9&os=win&sort_by=Reviews_DESC&page={N}`
- Pages 1–5 of that search were scanned; useful candidates were processed.
  Pages 5+ have rapidly diminishing returns (mostly DLC, joke games, niche titles).
- Also pulled a curated batch of obviously-missing top co-op titles from a Google search
  ("best co-op games PC 2024"): Helldivers 2, Core Keeper, V Rising, Enshrouded, Palworld, Sea of Thieves.

## How to resume

> **IMPORTANT:** `progress.json` has `done: true` so the stop-hook condition is satisfied.
> The session was **stopped early at the user's request** — only 34 of the 300-game target
> were added. To resume, set `done: false` in `progress.json` before invoking `/goal`.

### 1. Verify state
```bash
cd <repo root>          # on this Mac: /Volumes/Work/Projects/pc-coop-games
grep -c "^    id:" data.js   # current count (143 after the 2026-05-26 cleanup)
git diff data.js | head      # confirm only additions, no replacements
```

### 2. data.js write workflow
- Modern stack: macOS Python 3.9+ defaults to UTF-8 stdout, so the Cyrillic
  pipe issue that bit the original Windows session no longer applies. Just run:
  ```bash
  python3 .claude/skills/coop-hunter/scripts/append_entry.py < entry.json
  ```
- For bulk inserts use `scripts/batch_append.py` with a JSON file (UTF-8).
  Both scripts are idempotent: rerunning skips ids already present.
- Historical note: on the original Windows session we had to set
  `PYTHONIOENCODING=utf-8` and call Python via its full `.exe` path because
  `cp1252` corrupted the pipe. Not needed on macOS / Linux.

### 3. Candidates already queried but NOT yet added (next batch ready)
These were verified via Steam API in this session but the user asked to stop
before they were committed. They are good adds. Reviews/details snapshot:

| appid | name | %positive | reviews | notes |
|------:|------|----------:|--------:|-------|
| 1361210 | Warhammer 40,000: Darktide | 71.0% | 132k | AAA (Fatshark), Online Co-op, levels, 4p, 2022. Genres: Action+Shooter+FPS |
| 361420 | ASTRONEER | 91.9% | 138k | Indie (System Era), Online Co-op, survival-goal, 4p, 2019. Genres: Survival+Adventure |
| 346110 | ARK: Survival Evolved | 83.3% | 768k | Has "MMO" cat — borderline endless. Consider survival-goal with needs-review. |
| 892970 | Valheim | 94.0% | 534k | Indie (Iron Gate), Online Co-op, survival-goal (5 bosses → final boss), 10p, 2021 |
| 108600 | Project Zomboid | 94.0% | 450k | Indie (TIS), Online Co-op, EA but no win state; **may skip with endless** |
| 440900 | Conan Exiles | 79.0% | 115k | Indie/AA (Funcom), Massively Multiplayer cat, borderline survival-goal |
| 2933130 | LOTR: Return to Moria | 81.5% | 12k | AA (North Beach Games), Online Co-op, story, 8p, 2024 |
| 619820 | Heroes of Hammerwatch II | 83.1% | 6k | Indie (Crackshell), Online Co-op, roguelite, 4p, 2025 |

Decisions to apply if adding:
- ARK, Conan Exiles → use `survival-goal` + `needs-review: true` (Massively Multiplayer flag)
- Project Zomboid → likely **skip** (endless, no win condition)
- Darktide → low rating (71%), but borderline acceptable per rules (>=70% adds normally). Add as `levels`.
- Valheim → easy add as `survival-goal`. Genres: `["Indie","Survival","Open World"]`.

### 4. Sources not yet touched
sources.json defines 9 sources. Only source 0 partially processed.
Sources 1–8 are untouched:
1. `steamdb_online_coop_story_rich` (SteamDB intersection — also 403)
2. `co_optimus_pc_campaign` (Co-Optimus — try WebFetch)
3. `co_optimus_pc_arcade`
4. `steam_curator_cooptimus`
5. `howlongtobeat_multiplayer`
6. `reddit_coopgaming_top`
7. `articles_pcgamer_top_coop` (PCGamer URL returned 404 — try the other URLs in the list)
8. `backloggd_coop_completed`

For SteamDB-style sources, **substitute Steam Store search by tag** (worked here).

### 5. Outstanding follow-ups (low priority)
- No validation pass has been run yet (rule says every 50 added; we're at 34).
  When next session crosses 50 added, sample 10 random ids from `added.tsv`
  and run a fresh general-purpose Agent per SKILL.md "Validation pass" instructions.
- `state/_batch.json` and `state/_tmp.json` are scratch files. Safe to overwrite or delete.
- `scripts/batch_append.py` is a new helper added this session (not in original skill).
  It mirrors `append_entry.py`'s logic but processes a JSON array.

## What is safe vs. unfinished
- ✅ **Safe / reusable:** all entries in `data.js`, all rows in `added.tsv` and `skipped.tsv`,
  the `batch_append.py` helper, and `progress.json` (matches the current state).
- ⚠️ **Unfinished:** the next batch of 8 candidates listed in section 3 was queried but
  *not* added. They are in this NOTES file only — no entries pending in `_batch.json`.
- ❌ **Do NOT** trust the `_batch.json` file as a queue — it currently holds the
  10-game recovery batch from earlier in this session and was already applied.
  Treat it as scratch.

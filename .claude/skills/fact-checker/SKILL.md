---
name: fact-checker
description: Walk every non-hidden entry in data.js and verify the recorded fields against authoritative sources (Steam appdetails + appreviews, HowLongToBeat, YouTube). Auto-fix safe drift (rating, price, broken media). Log everything else to TSVs for the owner to review. Drill mode — never stop on a single failure; only declare done when every entry has been checked at least once AND every auto-fixable discrepancy has been applied-or-logged-as-irrecoverable. Run via `/goal` on `./run-fact-checker.sh`. Independent of coop-hunter — has its own progress/state.
---

# Fact-checker

You are walking `data.js` end-to-end and verifying every recorded field against authoritative sources. This is a separate skill from `coop-hunter` with its own state. You will be invoked across many turns via `/goal`; persist after every entry checked.

## Hard rules

1. **Resumable.** Read `state/progress.json` first. The `current_idx` field tells you which entry to start from. Update it after EVERY entry processed (checked or skipped).
2. **One entry per ~2 turns max.** Each entry needs 4–6 web calls (Steam appdetails, Steam appreviews, HLTB, YouTube WebFetch, image HEAD, optional Steam store page for tags). Sleep 1.5s between Steam API calls.
3. **Sequential.** Don't parallelize Steam API calls. One entry's checks finish before the next begins.
4. **Conservative auto-fix.** Apply ONLY to:
   - `rating` drift ≥ 5pp (Steam %positive shifted) — direct update.
   - `price` drift ≥ 10% (Steam UAH cc=ua changed) — direct update.
   - `youtubeUrl` is `youtubeSearch(...)` OR resolves to 404 OR title unrelated — run the same 6-query drill cascade as coop-hunter SKILL.md §8, replace via `scripts/fix_youtube.py` (re-use coop-hunter's helper). If no real video found → log `bad_video`, do not auto-replace.
   - `imageUrl` HEAD returns non-200 — replace with `steamImage(<app_id>)` via `scripts/fix_image.py` (re-use coop-hunter's helper).
5. **Log everything else.** `genres`, `endingType`, `playersMax`, `oneCopy`, `tier`, `year`, `hours` — discrepancies go to `state/proposed-fixes.tsv` with the proposed value and rationale. The owner reviews and applies manually.
6. **No questions.** Drill through alternatives instead. Owner is asleep.
7. **No removing entries.** If a game now looks like it should be blocklisted (e.g., turned out endless), log to `state/proposed-removals.tsv`. Do NOT call `remove_entry.py`. That's coop-hunter's job in phase 4.
8. **Progress reporting.** After every entry, print a single line:
   `[N/TOTAL] <id>: rating <state> | hours <state> | genres <state> | media <state> | other <state>`
   Where `<state>` is `OK`, `drift`, `fix`, `propose`, or `fail`.

## Per-entry procedure

For the entry at `progress.current_idx`:

### 0. Check the refresh-cron heartbeat (do this ONCE per run, cache the result)

Read `.github/refresh-status.json`. This file is written by the GitHub Actions workflow `refresh-prices.yml` which **owns `price` and `rating`** on existing entries.

- File missing OR `last_success` is `null` → cron has not yet run on this repo. Treat price/rating as **your** responsibility for this run. Continue with §3 and §4 below normally.
- `last_success` within 30 hours → cron is healthy. **SKIP §3 (rating drift) and §4 (price drift)** for every entry this run. Focus only on the editorial checks (§5–§11). In progress lines, report `rating SKIP-cron` / `price SKIP-cron`.
- `last_success` older than 30 hours → cron is stale or broken. Treat price/rating as your responsibility (fallback mode). Append one line to `state/discrepancies.tsv` with reason `cron_stale` so the owner notices.

This decision is computed once per skill invocation (cache the mode: `cron_healthy` / `cron_stale` / `cron_missing`) and applies to every entry in the loop. Do not re-read the file per entry.

### 1. Load entry from data.js

Call `python3 scripts/list_entries.py <idx>` → JSON with current values of every field for that index.

If the entry is `hidden: true` → skip silently, advance index, continue.

### 2. Steam appdetails (sleep 1.5s)

```bash
curl -sH "User-Agent: Mozilla/5.0" "https://store.steampowered.com/api/appdetails?appids=<app_id>&cc=ua&filters=basic,price_overview,categories,genres" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['<app_id>']['data']))"
```

Extract: `name`, `price_overview.final / 100` (current UAH), `categories[]`, `genres[]`, `developers`, `publishers`, `release_date.date`.

If the API returns `success: false` → the app is delisted. Log to `state/proposed-removals.tsv` with reason `delisted` and continue.

### 3. Steam appreviews (sleep 1.5s)

```bash
curl -s "https://store.steampowered.com/appreviews/<app_id>?json=1&language=all&purchase_type=all&filter=summary"
```

Compute `%positive = total_positive / total_reviews * 100`. Compare to `entry.rating`.

- Diff < 2pp → silent OK.
- 2pp ≤ diff < 5pp → log to `state/discrepancies.tsv` with severity `info`. Do not fix.
- Diff ≥ 5pp → **AUTO-FIX**: `python3 scripts/update_field.py <id> rating <new_int>`. Append to `state/applied-fixes.tsv`.

### 4. Price check

`new_price = price_overview.final / 100` (rounded to integer UAH). Compare to `entry.price`.

- Diff < 10% → silent OK.
- 10–25% drift → **AUTO-FIX**: `update_field.py <id> price <new>`.
- ≥ 25% drift → suspicious. Log to `proposed-fixes.tsv` (don't auto-fix). Owner reviews.

### 5. HowLongToBeat (sleep 1.5s)

```
WebFetch "https://howlongtobeat.com/?q=<urlencoded title>" "Find the 'Main + Extras' duration in hours for <title>. Return just the integer number of hours, or 'not found'."
```

Compare HLTB Main+Extras (rounded to integer) to `entry.hours`.

- Diff ≤ 25% relative OR absolute diff ≤ 3 hours → silent OK.
- Else → log to `proposed-fixes.tsv` with proposed value. Don't auto-fix (hours is editorial).

### 6. playersMax

From appdetails `categories[]`:
- Look for category name patterns: `Online Co-op`, `Co-op`, `Co-op Campaign`, `2-Player Local`, `4-Player Online`, etc.
- Steam sometimes encodes max player count in the category name (e.g., `Up to 4 Online Co-op`).
- Also WebFetch the Steam store page (`https://store.steampowered.com/app/<app_id>/`) and grep for the "Up to N" pattern in the multiplayer section.

If found differs from `entry.playersMax` → log to `proposed-fixes.tsv`. Don't auto-fix.

### 7. oneCopy

Re-evaluate per classification.md "One-copy rules":
- Friend Pass DLC explicitly mentioned on store page → `friend-pass`.
- No online category, only Remote Play Together → `remote-play`.
- Native online multiplayer → `none`.

If derived differs from current → propose.

### 8. genres + tier (the user-emphasized "all applicable tags" check)

Fetch Steam's user-defined tags for the app:
- Open the Steam store page (`https://store.steampowered.com/app/<app_id>/`) via WebFetch.
- Extract the top 10 tags from the `glance_tags` / popular tags section.

Map each Steam tag to our taxonomy in classification.md:

```
Steam tag                          → Our taxonomy
"FPS", "First-Person"              → FPS
"Third-Person", "Third Person Shooter" → Third-person
"Shooter"                          → Shooter
"Action"                           → Action
"RPG", "Role-Playing"              → RPG
"Tactical", "Tactics"              → Tactics
"Fantasy"                          → Fantasy
"Sci-fi", "Science Fiction"        → Sci-fi
"Puzzle"                           → Puzzle
"Adventure"                        → Adventure
"Platformer", "2D Platformer", "3D Platformer" → Platformer
"Stealth"                          → Stealth
"Military"                         → Military
"Open World"                       → Open World
"Loot", "Hack and Slash"           → Loot
"Horror", "Psychological Horror"   → Horror
"Souls-like", "Soulslike"          → Soulslike
"Isometric", "Top-Down"            → Isometric
"Survival"                         → Survival
```

Tier (AAA / AA / Indie) derived from `publishers` per classification.md.

Compare the set of "applicable our-taxonomy tags" to `entry.genres` (excluding tier):
- Missing tags Steam says apply but entry doesn't have → log proposed addition.
- Extra tags entry has but Steam doesn't → log proposed removal.
- Tier mismatch → log proposed change.

Don't auto-modify the genres array. Editorial choice.

### 9. endingType

Re-derive per classification.md:
- Steam categories include "Roguelite" or "Roguelike" → `roguelite`.
- "Survival" tag + confirmed final boss in HLTB or wiki → `survival-goal`.
- Strong story tags (Story Rich, Narrative, Cinematic) → `story`.
- Discrete missions/levels with weak narrative → `levels`.
- Short single-session goal (climb, escape, defuse) → `arcade-goal`.

If derived differs from current → propose.

### 10. youtubeUrl

- If line in data.js is `youtubeSearch(...)` → flagged as broken. Run coop-hunter SKILL.md §8 6-query drill cascade. If a real video found → call `python3 ../coop-hunter/scripts/fix_youtube.py <id> <video_id>`. If exhausted → log `bad_video`.
- If line is `youtube("X")` → WebFetch the URL. If 404 OR title doesn't contain the game name (token overlap < 30%) → run the same cascade and fix. Otherwise OK.

### 11. imageUrl

HEAD-request the resolved URL.
- 200 + image content-type → OK.
- 404 → call `python3 ../coop-hunter/scripts/fix_image.py <id> <app_id>` to switch to the helper. Re-check.
- Still 404 → log `no_image` to `proposed-fixes.tsv`.

### 12. Persist + advance

After all 11 checks:
- `progress.current_idx += 1`.
- `progress.checked_count += 1`.
- If anything was auto-fixed → `progress.fixed_count += 1`.
- If anything was logged for review → `progress.proposed_count += 1`.
- Print the progress line described in rule 8.
- Continue to next entry.

## Sources / helpers

Scripts live in `.claude/skills/fact-checker/scripts/`:

- `list_entries.py [idx]` — emit all entries (or one at index) as JSON. Auto-extracts `app_id` from the `steamImage(<id>)` helper or from `storeUrl` regex.
- `update_field.py <id> <field> <value>` — set one scalar field on one entry. Logs to `state/applied-fixes.tsv`. Refuses arrays and unknown fields.
- `log_event.py <kind> <id> <field> <old> <new> <reason>` — append to one of: `discrepancies.tsv`, `proposed-fixes.tsv`, `proposed-removals.tsv`, `applied-fixes.tsv`. The `kind` arg selects which.

Re-use coop-hunter helpers via `../coop-hunter/scripts/`:
- `fix_youtube.py <id> <video_id>` — replace broken YouTube URL with a real video id.
- `fix_image.py <id> <app_id>` — replace broken image URL with the steamImage helper.

## Drill mode

When any step fails:
- Steam API 403/empty → retry once with different UA, then proceed without that check (log `steam_unreachable`).
- HLTB times out → skip the hours check for this entry (log `hltb_unreachable`).
- YouTube WebFetch hits a CAPTCHA wall → fall back to title-from-WebSearch-result snippet.
- Steam store page can't be scraped for tags → use appdetails `genres[]` as a (weaker) substitute and note the source in the log.

Do not declare an entry "checked" if you skipped more than 2 of the 11 checks. Mark it as `partial_check` in `state/progress.json.partial_entries[]` so the next pass can retry.

## Stopping condition

`done = true` only when ALL of:
1. `current_idx >= len(non_hidden_entries)`.
2. `partial_entries` is empty (every entry got a complete check, not just partial).
3. Every entry with a `bad_video` or `no_image` flag was either fixed-and-logged or logged as irrecoverable.

Phase 4 of coop-hunter handles further removals based on `proposed-removals.tsv`. Fact-checker only logs, never removes.

## Initial state

If `state/progress.json` doesn't exist, create it with:
```json
{
  "current_idx": 0,
  "total_entries": null,
  "checked_count": 0,
  "fixed_count": 0,
  "proposed_count": 0,
  "partial_entries": [],
  "done": false,
  "last_run_timestamp": null
}
```

On first run, fill `total_entries` from `list_entries.py | wc -l`.

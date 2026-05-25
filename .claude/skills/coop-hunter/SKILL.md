---
name: coop-hunter
description: Systematically expand the PC co-op games database in data.js. Crawls SteamDB tags, Co-Optimus, Steam curators, Reddit lists, and HowLongToBeat sequentially. For each candidate game verifies online co-op + finite content + ≥50% Steam reviews, classifies tier (AAA/AA/Indie) and endingType (story/levels/arcade-goal/roguelite/survival-goal), finds a gameplay YouTube video, then appends to data.js. State is persisted between runs so the skill is fully resumable after crashes or interruption. Invoke this skill explicitly with /goal when you want to grow the database; do not invoke during normal feature work.
---

# Co-op Hunter

You are systematically expanding `data.js` with new co-op games that fit the criteria. **You will be invoked across many turns via `/goal`** — work slowly and persist state after every game, so a crash never costs more than one game.

## Hard rules (never violate)

1. **Sequential, not parallel.** One candidate at a time. Don't batch Steam API calls across more than 5 IDs per turn. Sleep 1.5s between Steam appdetails fetches (we hit rate-limits earlier).
2. **Persist state after EVERY game added.** Update `state/progress.json` and append to `state/added.tsv` before moving to the next candidate. If you crash mid-game, the next run resumes from `progress.json`.
3. **No questions.** Decide based on the rules in `classification.md`. If a candidate is genuinely ambiguous, log it to `state/skipped.tsv` with reason `ambiguous` and move on.
4. **Stay slow.** Process 3–5 candidates per turn maximum. Return control to `/goal`, it will call you again. This keeps per-turn token budget low.
5. **Validate every 50 added games** by spawning a fresh Agent (see "Validation pass" below).
6. **Idempotent.** Before adding a candidate, check `data.js` for the Steam app id. If already present → skip.

## Each invocation — single cycle

When called:

1. Read `.claude/skills/coop-hunter/state/progress.json` (create with defaults if missing — see "Initial state").
2. If `progress.done === true` → re-write `state/summary.md` and exit with "DONE".
3. Identify the current source (`progress.current_source_idx`) from `sources.json`.
4. From that source, pull the next batch of candidates starting at `progress.current_offset`. Batch size = 5.
5. For each candidate in batch (sequentially):
   - Run the "Per-candidate procedure" below.
   - On success → append entry to `data.js`, update `progress.json`, append to `state/added.tsv`.
   - On any skip → append to `state/skipped.tsv` with the reason, update progress, continue.
6. After the batch:
   - If `progress.added_count` crossed a multiple of 50 since last validation → run "Validation pass".
   - If the current source is exhausted (offset >= source max) → move to next source.
   - If all sources exhausted → set `progress.done = true`, write `state/summary.md`, exit.
7. Return. `/goal` will call you again next turn.

## Per-candidate procedure

For one candidate `name`:

### 1. De-duplication
- Steam search API: `https://steamcommunity.com/actions/SearchApps/<urlencoded name>`
- Take first result's `appid`.
- Grep `data.js` for `app/<appid>/` or the slug.
- If found → skip with reason `duplicate`.

### 2. Steam validation
- Fetch `https://store.steampowered.com/api/appdetails?appids=<id>&cc=ua&filters=basic,price_overview` with `User-Agent: Mozilla/5.0` header.
- Sleep 1.5 seconds before this call.
- Extract: `name`, `is_free`, `price_overview.final` (UAH × 100), `header_image`, `release_date`, `developers`, `publishers`, `categories` (tags), `metacritic.score` (if present).
- If response is `INVALID` (no game) → skip with reason `invalid_app_id`.

### 3. Quality threshold (Steam reviews)
- Fetch `https://store.steampowered.com/appreviews/<id>?json=1&language=all&purchase_type=all&filter=summary` (no auth needed).
- Read `query_summary.total_positive` / `query_summary.total_reviews` → `%positive`.
- If `total_reviews < 50` (too few to judge) → skip with reason `not_enough_reviews`.
- If `%positive < 50` → skip with reason `low_quality`.
- If `%positive in 50–70` → add anyway but set `"needs-review": true` in the entry (manual review later).

### 4. Online co-op verification
- Check `categories` from appdetails. Online co-op exists if any of:
  - `Online Co-op`, `Co-op`, `Co-op Campaign`, `Online PvP + Online Co-Op` present
  - OR `Remote Play Together` is present (= local co-op via Steam Remote Play)
- If only single-player → skip with reason `no_coop`.
- Set `oneCopy`:
  - `friend-pass` if the game's Steam page explicitly mentions "Friend Pass" / "Friend's Pass" / "asymmetric, one copy"
  - `remote-play` if local co-op only + Remote Play Together
  - `none` otherwise (each player needs own copy)

### 5. Finite content verification (the critical check)
Run all three sub-checks; treat as **finite** if ≥2 pass:
- **HowLongToBeat**: WebFetch `https://howlongtobeat.com/?q=<name>` → if "Main Story" length is listed in hours → finite.
- **Steam review scan**: WebFetch the appreviews JSON with `num_per_page=10&review_type=positive`. Scan review snippets for keywords: `ending`, `credits`, `finished`, `completed`, `final boss`, `beat the game`. If at least one match → finite.
- **Negative review scan**: scan negative reviews for `endless`, `no ending`, `no goal`, `no point`, `infinite grinding`, `live service`. If ≥2 hits → **not finite**.

If finite check fails → skip with reason `endless` or `unclear_ending`.

### 6. Old games online-broken check
If `release_date.date` < 2015:
- WebFetch the Steam discussions page (`https://steamcommunity.com/app/<id>/discussions/`) — fetch summary.
- Scan for: `GFWL`, `servers shut down`, `online doesn't work`, `requires GameSpy`, `online dead`.
- If any hit → skip with reason `online_broken`.

### 7. Classify
- **Tier**: see `classification.md`. Based on `publishers` field from Steam. Indie publishers and self-published → Indie. Major publishers (Activision, Blizzard, EA, Ubisoft, Sony, Microsoft, Take-Two, Square Enix, Capcom, Konami, Sega, Bethesda) → AAA. Anything in between → AA.
- **endingType**: see `classification.md` for decision matrix. Default to `story` if narrative-heavy, `levels` if mission-set, `roguelite` if Steam categories include "Roguelite", `arcade-goal` if short single-session escape/climb, `survival-goal` if "Survival" tag + final boss confirmed.
- **Genres**: map Steam categories to existing taxonomy in `classification.md`. Prepend tier value (e.g., `["AAA", "Shooter", "FPS"]`).

### 8. Find gameplay YouTube
- WebSearch: `<title> co-op gameplay site:youtube.com`
- Filter results for `https://www.youtube.com/watch?v=` (skip playlists).
- Prefer titles containing: "no commentary", "walkthrough", "full game", "co-op", "multiplayer".
- Take first match → extract video id (11 chars after `v=`).
- If no good match found in top 5 results → use `youtubeSearch("<title>")` helper string as fallback.

### 9. Build and append entry
Use the helper script `scripts/append_entry.py` (described below) to insert a new entry into `data.js` immediately before the first `hidden: true` block (or at end if no hidden entries). Pass JSON args.

Entry shape:
```json
{
  "id": "kebab-case-slug",
  "title": "Game Title",
  "year": 2024,
  "genres": ["AAA", "Shooter", "FPS"],
  "endingType": "story",
  "rating": 87,
  "ratingSource": "Steam",
  "ratingLabel": "Steam 87% positive",
  "playersMax": 4,
  "playersLabel": "до 4, кампания",
  "hours": 12,
  "hoursLabel": "10-15",
  "oneCopy": "none",
  "price": 599,
  "verdict": "Краткое описание одной строкой на русском.",
  "storeUrl": "https://store.steampowered.com/app/<id>/",
  "imageUrl": "steamImage(<id>)",  // use the helper invocation
  "youtubeUrl": "youtube(\"VIDEO_ID\")"
}
```

For `playersLabel`, `hours`, `hoursLabel`, `verdict` — derive from Steam description + reviews. Keep verdict ≤120 chars.

### 10. Persist
- Append to `state/added.tsv`: `<timestamp>\t<id>\t<title>\t<source>\t<price>\t<%positive>`
- Update `state/progress.json`:
  - `current_offset += 1`
  - `added_count += 1`
  - `last_added = <id>`

## Validation pass (every 50 added)

When `added_count` reaches a multiple of 50:

1. Pick 10 random ids from the last 50 added (i.e., 20% sample).
2. Spawn a fresh Agent via the Agent tool with `subagent_type: "general-purpose"`:

   ```
   prompt: "Verify these 10 games in data.js are correctly classified. For each:
   1. Open the Steam page (use WebFetch) — confirm name + price match.
   2. Confirm online co-op category exists.
   3. Confirm %positive matches what's recorded (within 2%).
   4. Confirm endingType makes sense (story / levels / arcade-goal / roguelite / survival-goal).
   5. Confirm YouTube link plays a gameplay video of THIS game (use WebFetch on the URL, scan title).

   Output: TSV — id, ok/fail, reason if fail.
   Ids to verify: <list of 10 ids>"
   ```

3. Read agent's TSV output. Append failures to `state/validation-fails.tsv`.
4. **Don't auto-correct**. Just log. The user will review later.

## Initial state

If `state/progress.json` doesn't exist, create it with:
```json
{
  "current_source_idx": 0,
  "current_offset": 0,
  "added_count": 0,
  "skipped_count": 0,
  "last_validation_at": 0,
  "completed_sources": [],
  "done": false,
  "last_added": null,
  "last_run_timestamp": null
}
```

## Final report

When all sources exhausted, write `state/summary.md`:
- Total added, skipped, validated, validation-fails.
- Top 10 sources by yield.
- Reasons for skips, ranked.
- Distribution of new entries by tier + endingType.
- Token estimate (if tracked).

## Tools to use

- `Bash` — curl Steam APIs, run helper scripts.
- `WebFetch` — Steam pages, HowLongToBeat, Co-Optimus.
- `WebSearch` — YouTube + ranked lists from Reddit/articles (when source needs it).
- `Read` / `Edit` / `Write` — data.js + state files.
- `Agent` — validation subagent.
- `Python` (via Bash with full path `/c/Users/loyeg/AppData/Local/Programs/Python/Python310/python.exe`) — for parsing JSON, appending entries.

## What NOT to do

- ❌ Do not parallelize Steam API calls (rate-limit).
- ❌ Do not skip the validation pass — quality is the whole point.
- ❌ Do not modify `app.js`, `index.html`, or `styles.css` — only `data.js`.
- ❌ Do not add entries for games not on Steam (free games on epic etc. are out of scope).
- ❌ Do not skip persisting state — every game added must hit `progress.json`.
- ❌ Do not ask the user questions. Use the rules. If truly stuck, log to skipped and move on.

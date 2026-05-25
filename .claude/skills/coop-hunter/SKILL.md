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
3. Identify the current source (`progress.current_source_idx`) from `sources.json`. The current source MUST have `phase == progress.current_phase`. If not, advance `current_source_idx` to the next source with matching phase (or trigger phase transition — see below).
4. From that source, pull the next batch of candidates starting at `progress.current_offset`. Batch size = 5.
5. For each candidate in batch (sequentially):
   - Run the "Per-candidate procedure" below.
   - On success → append entry to `data.js`, update `progress.json`, append to `state/added.tsv`.
   - On any skip → append to `state/skipped.tsv` with the reason, update progress, continue.
   - **After every successful add**, check auto-push (see "Auto-push" section).
6. After the batch:
   - If `progress.added_count` crossed a multiple of 50 since last validation → run "Validation pass".
   - If the current source is exhausted (offset >= source max) → mark it complete (append to `completed_sources`), reset `current_offset = 0`, move to next source IN THE SAME PHASE.
   - If all sources of `current_phase` are completed → run **Phase transition logic** below.
7. Return. `/goal` will call you again next turn.

## Phase transition logic

Maintain in progress.json:
- `current_phase` (default 1)
- `max_phase` (default 1 — Windows behavior; Mac launcher sets 4)
- `phase_start_count` (added_count when current phase started; default 0)

When all sources of `current_phase` are completed:

1. Compute `phase_yield = added_count - phase_start_count`.
2. If `phase_yield > 0` AND `current_phase < max_phase`:
   - `current_phase += 1`
   - `phase_start_count = added_count`
   - `current_source_idx` advances to the first source of the new phase
   - `current_offset = 0`
   - Continue processing.
3. Else (yield is 0 OR we've reached max_phase):
   - `done = true`
   - Write `state/summary.md`
   - Exit.

This means: on Windows with `max_phase=1`, after phase 1 is done, `done=true`. On Mac with `max_phase=4`, the skill cascades through 2, 3, 4 until a phase adds nothing new.

## Auto-push (Mac mode)

Maintain in progress.json:
- `auto_push_every_n` (default 0 — disabled; Mac launcher sets 25)
- `last_push_at` (added_count at the last push; default 0)

After every successful add, if `auto_push_every_n > 0` AND `(added_count - last_push_at) >= auto_push_every_n`:

```bash
git add data.js .claude/skills/coop-hunter/state/added.tsv .claude/skills/coop-hunter/state/skipped.tsv .claude/skills/coop-hunter/state/progress.json
git commit -m "coop-hunter: batch +N games (total M, phase P)"
git push
```

Where N = `added_count - last_push_at`, M = `added_count`, P = `current_phase`.

After push: `last_push_at = added_count`.

If `git push` fails (network, conflict), log to `state/push-fails.tsv` and continue — do NOT halt. Try again on the next batch.

## Per-candidate procedure

For one candidate `name`:

### 0. Hardcoded blocklist (MANDATORY FIRST CHECK)

Before ANY other check, compare the candidate's name (case-insensitive, fuzzy match) against the "Hardcoded blocklist" section in `classification.md`. If it matches → **skip immediately** with reason `blocklisted_endless`. Do NOT proceed to Steam search, do NOT spend tokens on API calls.

Examples of names that must trigger this skip: Deep Rock Galactic, Lethal Company, R.E.P.O., Helldivers 2, Bloons TD 6, Crab Champions, Don't Starve Together, Project Zomboid, Brotato, Vampire Survivors, Palworld, V Rising, Enshrouded, Core Keeper, Sea of Thieves, Path of Exile, Diablo Immortal, any MMO/Battle Royale, and many more (see classification.md for the full list).

The owner has explicitly authorized this hard reject: «мне принципиально важно, чтобы в материалах не появлялись endless игры». No exceptions.

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

## Phase 4 source methods (cascade re-evaluation + exhaustive search)

These methods replace the standard "Per-candidate procedure" for sources in phase 4. They are only reached when `max_phase >= 4` (Mac mode).

### `revalidate_existing`
Goal: catch false positives that slipped through earlier (e.g., Deep Rock Galactic, Lethal Company, R.E.P.O. — endless games that initially passed the finite-content check).

1. Load `data.js`, iterate all non-hidden entries.
2. For each entry, in batches of `batch_size`:
   - Refetch Steam appdetails. Compare name, price, header_image. If image URL doesn't return HTTP 200 → log to `state/bad-existing.tsv` with reason `broken_image`.
   - Refetch reviews summary. If %positive dropped below 50 → log with reason `quality_drop`.
   - Re-run finite-content scan with strictest rules:
     - If Steam tags include `MMO`, `Massively Multiplayer`, `Free to Play` + `Open World Survival Craft` → log with reason `endless_misclassified`.
     - If negative review snippets show ≥3 hits of `endless` / `live service` / `no ending` / `no point` / `infinite` → log with reason `endless_misclassified`.
   - Check YouTube URL: WebFetch the URL, verify title contains the game name. If 404 / completely unrelated → log with reason `bad_video`.
3. Do NOT modify or remove entries. Only log. User reviews `state/bad-existing.tsv` and decides.
4. This source's "offset" is the index into existing entries; "exhausted" when all entries scanned.

### `reeval_skipped`
1. Read `state/skipped.tsv`. Filter rows where reason in [`ambiguous`, `unclear_ending`, `not_enough_reviews`].
2. For each row, re-run the full "Per-candidate procedure" with current data.
3. If now passes → add it (counts toward phase_yield).
4. If still fails → leave skipped (no double-log).
5. Exhausted when all eligible rows processed.

### `steam_more_like_this`
1. Read `data.js`. Take top `top_n` non-hidden entries by `rating` (default 25).
2. For each, WebFetch the Steam store page. Parse the "More like this" / "More from these developers" / "Players also liked" sections.
3. Extract game names + Steam app IDs.
4. Dedupe against existing entries.
5. For each new candidate → run "Per-candidate procedure".

### `websearch_queries`
1. For each query in `queries` array, run a single `WebSearch` call.
2. From results, extract game names (look for entities that match patterns like "X is a co-op game" or italicized titles).
3. Dedupe against existing entries.
4. For each new candidate → run "Per-candidate procedure".

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
  "current_phase": 1,
  "max_phase": 1,
  "phase_start_count": 0,
  "added_count": 0,
  "skipped_count": 0,
  "last_validation_at": 0,
  "auto_push_every_n": 0,
  "last_push_at": 0,
  "completed_sources": [],
  "done": false,
  "last_added": null,
  "last_run_timestamp": null
}
```

If the file exists but is missing the newer fields (`current_phase`, `max_phase`, `phase_start_count`, `auto_push_every_n`, `last_push_at`), backfill them with the defaults above before proceeding. This preserves existing runs.

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

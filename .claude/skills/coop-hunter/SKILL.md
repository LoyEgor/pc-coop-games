---
name: coop-hunter
description: Systematically expand the PC co-op games database in data.js. Crawls SteamDB tags, Co-Optimus, Steam curators, Reddit lists, and HowLongToBeat sequentially. For each candidate game verifies online co-op + finite content + ≥50% Steam reviews, classifies tier (AAA/AA/Indie) and endingType (story/levels/arcade-goal/roguelite/survival-goal), finds a gameplay YouTube video, then appends to data.js. State is persisted between runs so the skill is fully resumable. Run it via ./run-coop-hunter.sh (a bash loop of headless `claude -p` bursts); do not invoke during normal feature work.
---

# Co-op Hunter

You are systematically expanding `data.js` with new co-op games that fit the criteria.

**Execution model:** the launcher `./run-coop-hunter.sh` invokes you ONE BURST at a time as a headless `claude -p` process. Each burst: resume from `state/progress.json`, process ~20 candidates, persist state after EACH, then EXIT. The bash loop starts the next burst fresh. (This replaced an older `/goal`-driven model whose evaluator overflowed on long runs.) Work slowly and persist after every game, so a crash never costs more than one game.

## Hard rules (never violate)

1. **Sequential, not parallel.** One candidate at a time. Don't batch Steam API calls across more than 5 IDs per turn. Sleep 1.5s between Steam appdetails fetches (we hit rate-limits earlier).
2. **Persist state after EVERY game added.** Update `state/progress.json` and append to `state/added.tsv` before moving to the next candidate. If you crash mid-game, the next run resumes from `progress.json`.
3. **No questions.** Decide based on the rules in `classification.md`. If a candidate is genuinely ambiguous, log it to `state/skipped.tsv` with reason `ambiguous` and move on.
4. **Bounded burst.** Process ~20 candidates per invocation, then persist state and EXIT. The launcher (`./run-coop-hunter.sh`) starts your next burst as a fresh headless process. Do not try to finish the whole catalog in one invocation.
5. **Validate every 50 added games** by spawning a fresh Agent (see "Validation pass" below).
6. **Idempotent.** Before adding a candidate, check `data.js` for the Steam app id. If already present → skip.
7. **Drill mode (never give up on the first failure).** If a WebSearch returns no clean match, run the next alternative query — §8 lists six. If a source page returns 403/404, write a substitute URL or use a different domain. If a YouTube video can't be found on the first try, exhaust Steam page scraping → direct YouTube search page → Reddit links → other phrasings before refusing. The user explicitly authorized out-of-the-box behavior: "пусть пытается до последнего и выходя out of the box, ища альтернативы". Treat "I couldn't find X" as a hypothesis to disprove, not an exit condition.
8. **No broken media in `data.js`.** The table now opens a YouTube iframe in a modal — a `youtubeSearch(...)` placeholder cannot be embedded. `append_entry.py` exits 4 if you try to add an entry without a real 11-character `video_id`. Same for images: every row must have a working `imageUrl` (HTTP 200). If you can't satisfy both, skip the candidate; do not insert a half-broken row.

## Each invocation — single cycle

When called:

1. Read `.claude/skills/coop-hunter/state/progress.json` (create with defaults if missing — see "Initial state").
2. If `progress.done === true` → exit immediately with "DONE" (the launcher loop will stop).
3. Identify the current source (`progress.current_source_idx`) from `sources.json`. The current source MUST have `phase == progress.current_phase`. If not, advance `current_source_idx` to the next source with matching phase (or trigger phase transition — see below).
4. From that source, pull the next batch of candidates starting at `progress.current_offset`. Batch size = 5.
5. For each candidate in batch (sequentially):
   - Run the "Per-candidate procedure" below.
   - On success → append entry to `data.js`, update `progress.json`, append to `state/added.tsv`.
   - On any skip → append to `state/skipped.tsv` with the reason, update progress, continue.
   - **Do NOT push between adds.** See "Push policy" — pushing happens once, in the Final pass, at the very end.
6. After the batch:
   - If `progress.added_count` crossed a multiple of 50 since last validation → run "Validation pass".
   - If the current source is exhausted (offset >= source max) → mark it complete (append to `completed_sources`), reset `current_offset = 0`, move to next source IN THE SAME PHASE.
   - If all sources of `current_phase` are completed → run **Phase transition logic** below.
7. Once you have processed ~20 candidates this invocation, persist state and EXIT. The launcher starts your next burst as a fresh process (resuming from `progress.json`).

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
   - `phase_4_zero_yield_passes = 0` (reset — we got out of phase 4 dry-streak by escalating)
   - Continue processing.
3. Else if `phase_yield > 0` AND `current_phase == max_phase`:
   - We're in phase 4 (the deepest phase) and it found something. Re-enter phase 4 from the start.
   - `phase_start_count = added_count` (new yield window begins)
   - `current_source_idx = (first source idx of phase 4)`
   - `current_offset = 0`
   - `completed_sources = [s for s in completed_sources if (source.phase != 4)]` — un-mark phase-4 sources so we walk them again with current data.
   - `phase_4_zero_yield_passes = 0`
   - Continue processing. Sources are not deterministic across time: Steam tags update, Reddit threads appear, WebSearch index refreshes. A phase-4 source that gave 0 last hour may give a hit now.
4. Else (yield is 0 in `current_phase`):
   - If `current_phase < max_phase` → `done = true` (cascade can't escalate without proof of life). Trigger the **Final pass before done** below.
   - If `current_phase == max_phase` (phase 4 dry-run): increment `phase_4_zero_yield_passes`. **STOP-CONDITION CHANGE — require TWO consecutive dry passes**:
     - If `phase_4_zero_yield_passes < 2`: do NOT declare done. Reset phase 4 (same as case 3 above), permute the source order if possible (or try alternative WebSearch phrasings on `websearch_niche_queries`), continue processing. The premise is: a 0-yield pass might be due to transient rate-limits, exhausted single-query phrasings, or stale Reddit caches; one more pass with the same data sources but fresh fetches often surfaces 1–5 more games.
     - If `phase_4_zero_yield_passes >= 2`: NOW trigger the **Final pass before done**, then `done = true`.

This means: a single dry pass through phase 4 is NOT enough to declare the catalog complete. The skill must prove there's nothing left by repeating phase 4 with fresh fetches and getting 0 twice in a row. The owner's empirical observation — "I restart and it finds another 15 games" — is exactly the case this fixes.

The launcher sets `max_phase=4`, so the skill cascades through phases 1→4 and then loops phase 4 until two consecutive dry passes. (`max_phase=1` is a legacy single-pass mode; the only launcher today is the macOS/Linux `./run-coop-hunter.sh`.)

## Push policy: ZERO pushes during the run, ONE at the end

This is a deliberate change from earlier versions. Auto-push during the run is **disabled**. Reasons:
1. Constant `github-actions[bot]` + `coop-hunter:bot` commits create noise that's hard to review.
2. The owner wants to inspect what the skill found before it lands on `main`.
3. Push race conditions between the skill and the daily `refresh-prices.yml` cron are easier to avoid if the skill pushes exactly once.

**Maintain in progress.json:**
- `auto_push_every_n: 0` — interim push DISABLED. The launcher seeds this. Do NOT raise.
- `last_push_at: int` — kept only for backward compatibility, unused in this push policy.
- `session_added_ids: []` — ids appended this session, accumulator for the final pass (see below). Cleared only after the final push succeeds.

Therefore: **do NOT commit or push between batches**. Just append entries to `data.js` and persist state to `state/progress.json` after each add. The single commit + push happens in the "Final pass" section below, fired by the stop condition.

If you find yourself in a situation where the working tree has grown large and you're worried about losing work to a crash: don't push — instead, the next launcher restart will simply read `state/progress.json` and resume. `data.js` is local in the worktree and survives crashes. The state/added.tsv log is the audit trail.

## Coordination with the GitHub Actions refresh cron

`.github/workflows/refresh-prices.yml` runs daily and **owns the `price` and `rating` fields** on existing entries. Its heartbeat lives in `.github/refresh-status.json`.

Before fetching Steam reviews or price for an EXISTING entry, read `.github/refresh-status.json`:

- File missing OR `last_success` is `null` → cron has not run yet. Fall back to doing the price/rating fetch yourself.
- `last_success` is more recent than 30 hours ago → cron is healthy. **SKIP** the price/rating check for that entry. Don't waste tokens duplicating the bot's work.
- `last_success` older than 30 hours → cron is stale/broken. Fall back to doing the fetch yourself, and append a one-line warning to `state/push-fails.tsv` so the owner notices the cron is unhealthy.

This rule applies in §3 (Quality threshold) and §4 step "price drift". It does NOT apply to step §2 (initial Steam validation for a NEW entry) — for new entries you always fetch fresh because the cron never inserts, only updates.

## Per-candidate procedure

For one candidate `name`:

### 0. Hardcoded blocklist + previously-removed gate (MANDATORY FIRST CHECK)

Before ANY other check, run BOTH of these gates. If either matches → **skip immediately** with the matching reason. Do NOT proceed to Steam search, do NOT spend tokens on API calls.

**Gate A — name blocklist.** Compare the candidate's name (case-insensitive, fuzzy match) against the "Hardcoded blocklist" section in `classification.md`. If it matches → skip with reason `blocklisted_endless`.

Examples of names that must trigger this skip: Deep Rock Galactic, Lethal Company, R.E.P.O., Helldivers 2, Bloons TD 6, Crab Champions, Don't Starve Together, Project Zomboid, Brotato, Vampire Survivors, Palworld, V Rising, Enshrouded, Core Keeper, Sea of Thieves, Boomerang Fu, Planet Crafter, Schedule I, Path of Exile, Diablo Immortal, any MMO/Battle Royale, and many more (see classification.md for the full list).

**Gate B — previously-removed gate.** Read `state/removed-entries.tsv` (skip header row). Slugify the candidate's title (lowercase, non-alphanumerics → hyphen, collapse runs) and compare to the `id` column. If it matches → skip with reason `previously_removed_endless`. This gate exists because the skill once removed and then re-added the same 16 endless games an hour apart; do not let that happen again. `scripts/append_entry.py` enforces this with exit code 3, but you must filter earlier to avoid wasted API calls.

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

### 2b. Image validation
- The standard `imageUrl` is `steamImage(<app_id>)` which expands to `https://cdn.cloudflare.steamstatic.com/steam/apps/<id>/header.jpg`. This URL is stable for any live Steam app.
- Issue a `HEAD` (or short `curl -sI`) request to that URL. Must return HTTP 200 and `Content-Type: image/*`.
- If the helper URL fails: fall back to `header_image` from appdetails. Re-check 200. If that also fails → skip with reason `no_image`. The user explicitly wants no rows with broken images.

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

### 7. Classify — read `.claude/skills/shared/taxonomy.json` FIRST

`taxonomy.json` is the **single source of truth** for genre + endingType. Do not invent tags or paraphrase definitions from memory. The file is small enough to read in full at the start of every classification step.

Procedure for each candidate:

1. **Read `.claude/skills/shared/taxonomy.json` once per turn.**
2. **Tier** — apply `tier` rules based on `publishers[]`. Exactly one tier, prepended to the `genres` array.
3. **Perspective** — `taxonomy.json` axes rule: `exactly_one_per_game`. Pick ONE of `First-person`, `Third-person`, `Isometric`, `Side-view`, `Top-down` using the per-tag `decision_tree`. If none clearly applies → log `taxonomy_ambiguous` to skipped.tsv with the candidate name; do NOT guess.
4. **Mechanic(s)** — at least one required. Walk through the `mechanic` section, apply each tag's `decision_tree`. Multiple allowed but be conservative. **Especially for `Adventure`**: the tag has a strict `narrowing_rule` — apply ONLY to narrative-led + exploration + dialogue games (Chicory-style). If the game has a story but the verb is shooting / fighting / puzzle — do NOT tag Adventure.
5. **Setting** — optional, multiple. Walk through `setting` section, apply where `decision_tree` matches.
6. **Structure** — optional, multiple. Same procedure.
7. **endingType** — exactly one. Walk through `ending_types` section, apply the matching `decision_tree`. If no path matches → log `taxonomy_ambiguous` and skip.

Final genres array example: `["AAA", "First-person", "Shooter", "Sci-fi"]` (tier first, then perspective, then mechanics, then settings, then structures).

If you find yourself wanting to introduce a tag not present in `taxonomy.json` → STOP. Log to skipped.tsv with reason `taxonomy_gap` and a one-line description of what was missing. Do not edit `taxonomy.json` yourself; that's an owner decision.

The legacy `classification.md` file is kept for prose explanations (audit-friendly), but in case of conflict, **`taxonomy.json` wins**.

### 8. Find gameplay YouTube — drill mode, must return a real video id

The UI now opens a modal with the YouTube iframe — a search URL cannot be embedded. **No entry ships without a real 11-character `video_id`.** `append_entry.py` will refuse the insert (exit 4) if you pass a `youtubeSearch(...)` placeholder, so finding a real video is a hard requirement, not best-effort.

Drill the search in this order. Stop at the first cascade level that yields a clean match.

1. **WebSearch** with each of these queries (one tool call each, stop early when you have a match):
   - `<title> co-op gameplay site:youtube.com`
   - `<title> co-op walkthrough no commentary site:youtube.com`
   - `<title> multiplayer gameplay site:youtube.com`
   - `<title> 2 player gameplay site:youtube.com`
   - `<title> full game co-op site:youtube.com`
   - `<title> review` (review videos almost always include gameplay B-roll — accept if title clearly matches)
2. **Filter results**: only accept `https://www.youtube.com/watch?v=<11-chars>`. Skip `/playlist?list=`, `/channel/`, `/c/`, `/@`, `/shorts/`.
3. **Match scoring** — for each candidate URL, judge by what WebSearch surfaced (title + snippet):
   - +3 if title contains the game name (case-insensitive substring or token overlap ≥ 50%).
   - +2 for keywords `co-op`, `coop`, `multiplayer`, `2 player`, `2-player`.
   - +1 for `gameplay`, `walkthrough`, `full game`, `no commentary`.
   - −5 if title contains `review`, `tier list`, `top 10`, `analysis` AND no gameplay keyword.
   - −10 if title in another language with no game-name match.
   - Accept the highest-scoring candidate with score ≥ 3.
4. **Verify**: call `WebFetch(url, "What is the video title and is it gameplay of <title>?")`. If the response confirms it's gameplay and the title matches → take its 11-char id. If WebFetch contradicts (e.g. unrelated video, deleted, region-locked) → drop and try the next candidate.
5. **Alternative sources if all 6 WebSearches fail**:
   - WebFetch the game's Steam page (`https://store.steampowered.com/app/<id>/`) — Steam often embeds an official trailer/gameplay video. Look for `youtube.com/embed/<id>` or `data-youtube-id` markers in the markup.
   - WebFetch `https://www.youtube.com/results?search_query=<urlencoded title>+co-op+gameplay` directly and scrape the first watch URL.
   - WebSearch `<title> co-op site:reddit.com` — Reddit threads often link to gameplay clips.
6. **Only after all of the above produce nothing**: refuse to add this entry. Log to `state/skipped.tsv` with reason `no_video_found`. Do NOT fall back to `youtubeSearch(...)` — that placeholder is forbidden.

The `fact-checker` skill uses the same cascade to fix any broken/placeholder YouTube URLs on existing entries. For coop-hunter, this matters at ADD time: be patient finding a real video — a single skip costs less than a broken modal.

### 8b. FINAL FIT-GATE (mandatory — prevention beats cleanup)

Since coop-hunter no longer re-walks the catalog to clean up mistakes (that's the fact-checker now), the ADD-TIME gates are the main defense. Before calling `append_entry.py`, run this final fit-check and SKIP on ANY doubt. A skipped good game costs nothing; a wrong added game costs manual cleanup later — the owner explicitly prefers a smaller, trustworthy catalog over a larger noisy one.

Confirm ALL of these hold (you already gathered the evidence in §0–§8); if any is uncertain → skip to `state/skipped.tsv` with reason `low_fit` + a one-line why:

- **On Steam, PC** (not Epic/console-only).
- **Real multiplayer co-op for 2+** — online co-op OR Remote Play Together. NOT single-player-only, NOT PvP-only.
- **Finite — a clear, identifiable ending** (story credits / last level / final boss / named win-condition / arcade goal). This is the #1 rule. If you cannot point to a concrete ending, it is endless → SKIP, never "probably has one".
- **Quality**: ≥50 total Steam reviews AND ≥50% positive.
- **Not blocklisted / not previously removed** (re-confirm §0 gates A+B).
- **A real gameplay video and a working image** were found.

If the candidate is a clear genre/structure outlier you can't classify against `taxonomy.json` → SKIP `taxonomy_gap`, do not force-fit. When genuinely unsure whether it belongs → SKIP. Drill for evidence first (per drill mode), but the tie-breaker is always SKIP.

### 9. Build and append entry
Use the helper script `scripts/append_entry.py` (described below) to insert a new entry into `data.js` immediately before the first `hidden: true` block (or at end if no hidden entries). Pass JSON args.

Entry shape (post-2026-05 minimal schema — see CLAUDE.md WHY-1/2/3):
```json
{
  "id": "kebab-case-slug",
  "title": "Game Title",
  "year": 2024,
  "genres": ["AAA", "First-person", "Shooter", "Sci-fi"],
  "endingType": "story",
  "rating": 87,
  "playersMax": 4,
  "hours": 12,
  "oneCopy": "none",
  "price": 599,
  "verdict": "One-line description in English.",
  "storeUrl": "https://store.steampowered.com/app/<id>/",
  "imageUrl": "steamImage(<id>)",
  "youtubeUrl": "youtube(\"VIDEO_ID\")"
}
```

Do NOT include `ratingSource`, `ratingLabel`, `playersLabel`, or `hoursLabel` — these were intentionally removed from the schema. The append_entry.py helper enforces this.

For `hours` — use HowLongToBeat's "Main + Extras" value (typical playthrough including side activities, NOT pure main story, NOT 100% completionist). **Always an integer** — round to the nearest whole hour. Fractions like `8.5` are not allowed (the table renders integers only; `append_entry.py` will silently round but skills must emit whole numbers). All other numeric fields (`year`, `rating`, `playersMax`, `price`) are also integers — never emit decimals.

For `rating` — always Steam % positive (from `/appreviews/<id>?json=1`). Never use Metacritic or OpenCritic.

For `verdict` — ≤120 chars English. Plain, factual, one sentence. No marketing fluff. The site is English-only.

### 10. Persist
- Append to `state/added.tsv`: `<timestamp>\t<id>\t<title>\t<source>\t<price>\t<%positive>`
- Update `state/progress.json`:
  - `current_offset += 1`
  - `added_count += 1`
  - `last_added = <id>`
  - **`session_added_ids.append(<id>)`** — accumulator for the Final pass. Cleared only after the final push succeeds.

## Phase 4 source methods (exhaustive GROWTH search)

These methods replace the standard "Per-candidate procedure" for sources in phase 4. They are only reached when `max_phase >= 4` (Mac mode). **Phase 4 is now GROWTH-only** — it finds NEW games via deeper sources. Re-validating EXISTING entries (endless re-check, broken media, drift) is NOT coop-hunter's job anymore; that moved to the `fact-checker` skill (single owner of existing-entry quality). This split removes the old double work that made coop-hunter spend hours re-walking the whole catalog before it could reach `done`.

> Removed 2026-05-27: `revalidate_existing`. If you find an endless game already in `data.js`, you may STILL auto-remove it via `scripts/remove_entry.py` (the hard rule against endless games stands), but do NOT systematically re-walk the catalog — the fact-checker does that.

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
  "phase_4_zero_yield_passes": 0,
  "session_added_ids": [],
  "completed_sources": [],
  "done": false,
  "last_added": null,
  "last_run_timestamp": null
}
```

If the file exists but is missing newer fields (`current_phase`, `max_phase`, `phase_start_count`, `auto_push_every_n`, `last_push_at`, `phase_4_zero_yield_passes`, `session_added_ids`), backfill them with the defaults above before proceeding. This preserves existing runs.

## Final pass before done (mandatory before push)

When the stop condition (Phase transition logic case 4 with `phase_4_zero_yield_passes >= 2`) fires, do NOT immediately set `done=true` and exit. First run this final pass on the entries this session added.

### Step 1: scope
Read `progress.session_added_ids`. These are the ids appended during this session. The Final pass operates ONLY on these — not the whole catalog. The owner runs the separate `fact-checker` skill for whole-catalog audits; coop-hunter's Final pass is the "vet the work you just did" gate.

If `session_added_ids` is empty (e.g., the session started already done) → skip Step 2, go straight to Step 3.

### Step 2: focused fact-check per session-added id

For each id in `session_added_ids`:

1. **Image check.** `HEAD` request to the resolved `imageUrl`. If non-200 → call `scripts/fix_image.py <id> <app_id>` to fall back to the canonical `steamImage(<id>)` helper. If still 404 → log to `state/bad-existing.tsv` with reason `no_image_after_final_pass`.

2. **YouTube check.** If `youtubeUrl` is `youtubeSearch(...)` (forbidden — should never have been allowed by `append_entry.py` exit 4, but verify defensively) → run §8 6-query drill cascade and `scripts/fix_youtube.py <id> <video_id>`. If a real `youtube("X")` URL: WebFetch the URL, verify the title contains the game name (≥30% token overlap, case-insensitive). If unrelated → run cascade, fix.

3. **Steam app id is alive.** One `appdetails` call (sleep 1.5s). If `success: false` → the game got delisted between when you added it and now. Log to `state/bad-existing.tsv` with reason `delisted_after_add` so the owner reviews before merge.

4. **DO NOT touch `price` or `rating`.** Those are owned by `.github/workflows/refresh-prices.yml`. The cron will reconcile them on its next daily run. If you fetched these during the initial add (§3, §4 of per-candidate procedure), good — they're the initial values, the cron takes over from here. The Final pass MUST NOT call `update_field.py <id> rating ...` or `update_field.py <id> price ...`.

5. **Do not re-check genres / endingType / playersMax / oneCopy.** Those are editorial; the `fact-checker` skill audits them at the catalog level. Re-checking here would cost LLM tokens for marginal value.

### Step 3: single final commit + push

After Step 2 completes (whether or not it surfaced fixes):

```bash
git add data.js \
        .claude/skills/coop-hunter/state/added.tsv \
        .claude/skills/coop-hunter/state/skipped.tsv \
        .claude/skills/coop-hunter/state/progress.json \
        .claude/skills/coop-hunter/state/bad-existing.tsv \
        .claude/skills/coop-hunter/state/removed-entries.tsv \
        .claude/skills/coop-hunter/state/youtube-fixes.tsv \
        .claude/skills/coop-hunter/state/image-fixes.tsv 2>/dev/null

# If nothing staged (no adds + no fixes), skip commit entirely
git diff --cached --quiet && echo "Nothing to commit" || \
  git commit -m "coop-hunter: session +N games, M fixes (total T)"

# Pull/rebase in case the refresh-prices cron landed during our run
git pull --rebase origin main || true
git push origin main
```

If push fails: log to `state/push-fails.tsv` and KEEP the work-tree dirty. Do NOT clear `session_added_ids` — the next invocation will retry the push. Do NOT mark `done=true` until push succeeds (otherwise the next session loses track of which adds need fact-checking).

If push succeeds:
- `session_added_ids = []`
- `done = true`

Do NOT write a `state/summary.md` report file. The audit trail already lives in
`added.tsv` / `skipped.tsv` / `removed-entries.tsv` and the launcher prints a
final summary to the terminal. This project does not keep regenerable report
artifacts.

## Tools to use

- `Bash` — curl Steam APIs, run helper scripts.
- `WebFetch` — Steam pages, HowLongToBeat, Co-Optimus.
- `WebSearch` — YouTube + ranked lists from Reddit/articles (when source needs it).
- `Read` / `Edit` / `Write` — data.js + state files.
- `Agent` — validation subagent.
- `Python` — call as `python3` (it's on PATH on macOS and modern Linux; on Windows use `py` or `python`). All scripts in `scripts/` have a `#!/usr/bin/env python3` shebang. They are tested on Python 3.9+; no third-party packages required (stdlib only: `urllib`, `json`, `re`, `pathlib`, `datetime`).

## What NOT to do

- ❌ Do not parallelize Steam API calls (rate-limit).
- ❌ Do not skip the validation pass — quality is the whole point.
- ❌ Do not modify `app.js`, `index.html`, or `styles.css` — only `data.js`.
- ❌ Do not add entries for games not on Steam (free games on epic etc. are out of scope).
- ❌ Do not skip persisting state — every game added must hit `progress.json`.
- ❌ Do not ask the user questions. Use the rules. If truly stuck, log to skipped and move on.

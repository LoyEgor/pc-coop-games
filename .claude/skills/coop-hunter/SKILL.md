---
name: coop-hunter
description: Systematically expand the PC co-op games database in data.js. Crawls SteamDB tags, Co-Optimus, Steam curators, Reddit lists, and HowLongToBeat sequentially. For each candidate game verifies online co-op + finite content + ≥50% Steam reviews, classifies tier (AAA/AA/Indie) and endingType (story/levels/arcade-goal/roguelite/survival-goal), finds a gameplay YouTube video, then appends to data.js. State is persisted between runs so the skill is fully resumable. Run it via ./run-coop-hunter.sh (a bash loop of headless `claude -p` bursts); do not invoke during normal feature work.
---

# Co-op Hunter

You are systematically expanding `data.js` with new co-op games that fit the criteria.

**Execution model — you are an ETERNAL SEARCHER. There is no "done".** The launcher
`./run-coop-hunter.sh` runs you as repeated headless `claude -p` bursts and never
stops on its own. Each burst: resume from `state/progress.json`, search + validate
~20 candidates, persist after EACH, then EXIT; the loop starts the next burst. The
owner runs you for a night / a day / several days and you just keep finding games.

The structured sources in `sources.json` (phases 1–4) are FINITE — you will walk
through them. That is **information, not a finish line**: when they stop yielding,
you switch to **CREATIVE DISCOVERY** (invent fresh search angles yourself — see that
section) because the internet keeps producing new co-op games. You never set
`done=true` in normal mode. Only a rate-limit (wait) or the owner's Ctrl+C pauses
you. The launcher commits + pushes periodically (~hourly / every N adds), so finds
reach the site without you ever "finishing". Persist after every game so a crash
costs at most one.

## State files (canonical model: CLAUDE.md §6b)

Four lists, each game in exactly one state — plus this skill's cursor `state/progress.json`:
- **`data.js`** — the catalog. You ADD here (via `append_entry.py`, WITHOUT a `reviewed` field so `fact-checker new` picks it up).
- **`shared/reeval.tsv`** — re-checkable rejects. You READ it (dedup: don't re-find these) and `reeval_skipped` RE-JUDGES it.
- **`shared/hard-block.tsv`** — never-add (mechanical). You READ it as a gate (don't re-find); `append_entry.py` refuses these (exit 3).
- **`shared/owner-review.tsv`** — the owner's queue; you don't normally write it.

Log a reject ONLY via `scripts/log_skip.py "<title>" <reason> <source> "<notes>"` — it routes to reeval (judgment reasons) or hard-block (mechanical: no_coop/pvp_primary/not_on_steam/invalid_app_id/MMO/delisted) and upserts (one row per game). NEVER write these lists by hand. Before searching, dedup a candidate against all three (data.js + reeval + hard-block).

## Hard rules (never violate)

1. **Sequential, not parallel.** One candidate at a time. Don't batch Steam API calls across more than 5 IDs per turn. Sleep 1.5s between Steam appdetails fetches (we hit rate-limits earlier).
2. **Persist state after EVERY game added.** Update `state/progress.json` (and append the new id to `session_added_ids`) before moving to the next candidate. If you crash mid-game, the next run resumes from `progress.json`. The audit trail of what was added is `git log data.js` (CLAUDE.md §6b) — there is no separate added-list file.
3. **No questions.** Decide based on the rules in `classification.md`. If a candidate is genuinely ambiguous, log it via `log_skip.py` (reason `ambiguous`) and move on.
4. **Bounded burst.** Process ~20 candidates per invocation, then persist state and EXIT. The launcher (`./run-coop-hunter.sh`) starts your next burst as a fresh headless process. Do not try to finish the whole catalog in one invocation.
5. **Validate every 50 added games** by spawning a fresh Agent (see "Validation pass" below).
6. **Idempotent.** Before adding a candidate, check `data.js` for the Steam app id. If already present → skip.
7. **Drill mode (never give up on the first failure).** If a WebSearch returns no clean match, run the next alternative query — §8 lists six. If a source page returns 403/404, write a substitute URL or use a different domain. If a YouTube video can't be found on the first try, exhaust Steam page scraping → direct YouTube search page → Reddit links → other phrasings before refusing. The user explicitly authorized out-of-the-box behavior: "пусть пытается до последнего и выходя out of the box, ища альтернативы". Treat "I couldn't find X" as a hypothesis to disprove, not an exit condition.
8. **No broken media in `data.js`.** The table now opens a YouTube iframe in a modal — a `youtubeSearch(...)` placeholder cannot be embedded. `append_entry.py` exits 4 if you try to add an entry without a real 11-character `video_id`. Same for images: every row must have a working `imageUrl` (HTTP 200). If you can't satisfy both, skip the candidate; do not insert a half-broken row.
9. **Log every reject through `scripts/log_skip.py` — never hand-write the shared lists.** Call `python3 scripts/log_skip.py "<title>" <reason> <source> "<notes>"`. It is the ONE writer for the not-in-catalog lists: it routes the reject to `shared/reeval.tsv` (judgment / threshold reasons — re-checkable) or `shared/hard-block.tsv` (mechanical: no_coop / pvp_primary / not_on_steam / invalid_app_id / MMO / delisted), and enforces three invariants a raw append would break: (a) ONE row per game (upsert — it raises to the more decisive reason and bumps a seen-counter instead of writing a duplicate); (b) the canonical schema of whichever list it routes to; (c) a catalog gate — if the game is already in `data.js` it exits **3** and writes nothing (a game in the catalog is not a reject candidate). If you get exit 3 on a HARD-NEGATIVE reason (endless / unclear_ending / no_coop / online_broken / low_quality), do NOT silently move on — the game is BOTH in the catalog and looks unfit, which is a contradiction; note it so the fact-checker reviews it (it owns the `shared/owner-review.tsv` queue, action=contradiction). The single-writer rule exists because the old skip log had drifted into two schemas and hundreds of duplicate / catalog-collision rows; the state model was folded down to the four canonical lists (CLAUDE.md §6b) and `log_skip.py` keeps them clean.

## Each invocation — single cycle

When called:

1. Read `.claude/skills/coop-hunter/state/progress.json` (create with defaults if missing — see "Initial state").
2. **There is no `done` exit in normal mode** — always search this burst. (The only `done` left is the one-time migration helper: **if `progress.reeval_only === true`**, process ONLY `reeval_skipped` (see "`reeval_only` mode"), skip the source walk + new-game search, and set `done=true` when every eligible row of `shared/reeval.tsv` is exhausted. That flag is set only by `run-migration.sh`, never in a normal hunt.)
3. Identify the current source (`progress.current_source_idx`) from `sources.json`. The current source MUST have `phase == progress.current_phase`. If not, advance `current_source_idx` to the next source with matching phase (or trigger phase transition — see below).
4. From that source, pull the next batch of candidates starting at `progress.current_offset`. Batch size = 5.
5. For each candidate in batch (sequentially):
   - Run the "Per-candidate procedure" below.
   - On success → append entry to `data.js`, update `progress.json` (push the new id onto `session_added_ids`).
   - On any skip → `python3 scripts/log_skip.py "<title>" <reason> <source> "<notes>"` (the single writer — see Hard rule 9), update progress, continue. If it exits 3 the game is already in the catalog: don't log it as a reject; if the reason was hard-negative, flag it for the fact-checker instead (it owns the contradiction queue in `shared/owner-review.tsv`).
   - **Don't push mid-burst.** The launcher pushes periodically between bursts (see "Push policy"); you just keep adding.
6. After the batch:
   - If `progress.added_count` crossed a multiple of 50 since last validation → run "Validation pass".
   - **Mark source progress EXPLICITLY — this is mandatory, not optional.** A source is "exhausted for this pass" when its per-method done-criterion is met (see "Phase-4 source exhaustion criteria" below for the exact rule per method — e.g. `steam_more_like_this` is done after all 25 seed entries are scanned, `websearch_niche_queries` after all 8 queries run). When exhausted: **append its id to `completed_sources` in progress.json** (write the JSON, don't just say it), set `current_offset = 0`, reset `bursts_on_current_source = 0`, and advance `current_source_idx` to the next source IN THE SAME PHASE whose id is NOT already in `completed_sources`.
   - **Anti-stall cap — never sit on one source.** Increment `bursts_on_current_source` each burst you stay on the same `current_source_idx`. If it reaches **2** without the source being exhausted, FORCE-advance anyway: append the current source id to `completed_sources` (it will get another shot on the next phase-4 re-entry), reset offset + counter, move to the next not-completed source. Rationale: `steam_more_like_this` can churn near-duplicates indefinitely; the fresh drill sources (`websearch_niche_queries`, `backloggd`, `steam_community_recommendations`, `youtube_curator_playlists`, `reddit_just_finished`, `wikipedia_coop_lists`) MUST get their turn within the same run. A run that only ever scrapes source 13 is the bug this cap fixes.
   - If **all** sources of `current_phase` are in `completed_sources` → run **Phase transition logic** below. (Not "most", not "I think they're done" — every source id of this phase must literally be in the array.)
7. Once you have processed ~20 candidates this invocation, persist state and EXIT. The launcher starts your next burst as a fresh process (resuming from `progress.json`).

## When the structured sources run out → keep going (NEVER "done")

Maintain in progress.json: `current_phase` (default 1), `max_phase` (4 on Mac),
`phase_start_count` (added_count when this phase started), and `source_pass_log`
(a short list of `{pass, yield}` recording how each full phase-4 pass did).

When all sources of `current_phase` are in `completed_sources`:
1. `phase_yield = added_count - phase_start_count`.
2. If `current_phase < max_phase`: advance to the next phase (`current_phase += 1`,
   `phase_start_count = added_count`, `current_source_idx` = first source of the new
   phase, `current_offset = 0`) and continue. Advance even if phase_yield was 0 — later
   phases are DIFFERENT sources, not a retry of the same ones.
3. If `current_phase == max_phase`: append `{pass, yield}` to `source_pass_log`, then
   **re-enter phase 4 with fresh data** — un-mark the phase-4 entries in
   `completed_sources`, reset offsets + `bursts_on_current_source`,
   `phase_start_count = added_count`. Sources are not static (Steam tags update, Reddit
   threads appear, new games release): a pass that gave 0 last hour may give 5 next.
   **NEVER set `done`.**
4. **When structured re-walks keep coming up dry** (the last ~2–3 entries in
   `source_pass_log` each ≈0): that is the signal to spend the next burst on
   **CREATIVE DISCOVERY** (below) rather than re-walking the same list again. Alternate
   — a structured re-walk, then a discovery burst, then structured — so you are always
   searching *somewhere new*.

`source_pass_log` is CONTEXT (how thoroughly the easy sources were walked recently), NOT
a stop button. "Dry 3 times" ≠ "catalog complete" — the owner's experience is that a
restart finds another 5–15 games. It means "the easy sources are tapped, go hunt wider".

## Creative discovery (invent new search angles — the real "never stop")

You are an LLM, not a fixed crawler. When `sources.json` is yielding little, GENERATE
your own search angles and chase them. Each discovery burst: pick an angle you have NOT
recently tried (check `state/discovery-log.tsv`), search it, run the Per-candidate
procedure on hits, then append the angle + result to `state/discovery-log.tsv`
(`timestamp\tangle\tqueries\tadded\tnotes`) so you VARY instead of repeating. Angle
ideas (not exhaustive — invent more):
- **Fresh Steam releases**: co-op games by recent release date via Steam search / "New &
  Trending" + the Co-op tag (catches things published since the last pass).
- **YouTube**: co-op-focused channels & "best co-op 2026" playlists — parse titles.
- **Reddit**: niche/newer subreddits + recent "just finished a co-op game" posts.
- **Articles**: 2026 "best co-op" / "hidden gem co-op" / genre-specific roundups.
- **X / social**: co-op recommendation threads.
- **Adjacency**: "More like this" / "players also liked" from the NEWEST catalog adds.
- **Genre gaps**: target axes thin in the catalog (e.g. co-op Tactics, co-op Racing).
- **Franchise completeness** (high-yield): for any catalog entry that is part of a series,
  check its siblings — prequels, sequels, spin-offs, remasters. If a sequel is in the
  catalog but the original (or another entry) is NOT, that missing game is a strong
  candidate — evaluate it. (The Division 2 was in the catalog while the original The
  Division was missing for no reason.) Works both directions: a new sequel of a catalogued
  game is also a lead. `find_neighbors.py` already surfaces franchise contradictions —
  mine that output too.
Treat "found nothing on this angle" as a reason to try a DIFFERENT angle next burst —
never as a reason to stop. The internet does not run out of new co-op games.

The launcher sets `max_phase=4`, so the skill cascades through phases 1→4. Phase 4 is NOT a terminus: a dry phase-4 pass is the trigger to start creative discovery (above), not to stop. There is no dry-pass exit — keep going until Ctrl+C. (`max_phase=1` is a legacy single-pass mode; the only launcher today is the macOS/Linux `./run-coop-hunter.sh`.)

## Push policy: PERIODIC (an eternal run has no "end" to push at)

Since the hunt never stops (no `done`), there is no final push. Instead push
periodically so finds reach the site and nothing is lost to a crash, while keeping
commit noise low. **The launcher (`run-coop-hunter.sh`) owns the push cadence** — it
commits + pushes after a burst when EITHER ~1 hour has passed since the last push OR
≥ N games were added since (whichever comes first), then continues looping. So the
skill itself just keeps adding to `data.js` and the launcher batches the pushes.

Maintain in progress.json:
- `session_added_ids: []` — ids added since the last push (the push batch). The launcher
  clears it after a successful push.
- `last_push_at` — unix-ish marker / added_count at last push, used by the launcher to
  decide when the next push is due.

Each push = `commit` → `git pull --rebase origin main` (the daily `refresh-prices.yml`
cron may have landed) → `push`. If the push fails, keep the work-tree dirty and retry on
the next cadence — never lose adds. (Cron owns price/rating; rebasing avoids races.)

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

**Gate B — previously-removed gate.** Read `shared/hard-block.tsv` (skip header row). Slugify the candidate's title (lowercase, non-alphanumerics → hyphen, collapse runs) and compare to the `id` column. If it matches → skip with reason `previously_removed_endless`. This gate exists because the skill once removed and then re-added the same 16 endless games an hour apart; do not let that happen again. `scripts/append_entry.py` enforces this with exit code 3 (it refuses hard-blocked ids), but you must filter earlier to avoid wasted API calls.

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
- The canonical `imageUrl` is the `header_image` URL from appdetails (a literal string), with any `?t=` cache-buster stripped. Pass it to append_entry.py as `header_image` (or as a literal `imageUrl`) and the helper stores it verbatim.
- Do NOT default to the `steamImage(<app_id>)` helper. The legacy CDN path it builds — `https://cdn.cloudflare.steamstatic.com/steam/apps/<id>/header.jpg` — is GONE for newer apps (hard 404), and is the exact cause of the recurring broken-image rows. It is only a last-resort fallback when appdetails returns no `header_image`.
- Issue a `HEAD` (or short `curl -sI`) request to the chosen URL. Must return HTTP 200 and `Content-Type: image/*`. If it fails → skip with reason `no_image`. The user explicitly wants no rows with broken images.

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

### 5. Finite content verification (the critical check) — co-op gate + finish strength

Read `taxonomy.json` → `finish_strength` (the authoritative version). Two gates, in order:

**Gate A — co-op gate (check first):**
- Co-op shape: asymmetry and permanent helpers are FINE, no marker (different-but-constant roles; a companion always at your side like Tails/Sonic). 🟠 ONLY when P2 is BOTH episodic AND secondary — joins only part of the game (e.g. battles only) while one player owns story/world/exploration (JRPGs: Tales, Ys, Legend of Mana). Such a game still QUALIFIES → ADD with a leading 🟠 in the verdict (co-op battles-only / P2 is a helper). NOT a skip.
- Count FINITE CO-OP hours — only the co-op content that leads to a finish, not the whole game (Forza Horizon ≈ co-op progression to its milestone, not 80-120h). The co-op finish content must be **> 1 hour**, else skip `coop_too_short`.

**Gate B — finish strength.** Run the three sub-checks; treat as having content if ≥2 pass:
- **HowLongToBeat**: WebFetch `https://howlongtobeat.com/?q=<name>` → if "Main Story" length is listed in hours → finite.
- **Steam review scan**: WebFetch the appreviews JSON with `num_per_page=10&review_type=positive`. Scan snippets for `ending`, `credits`, `finished`, `completed`, `final boss`, `beat the game`. If at least one match → finite.
- **Negative review scan**: scan negative reviews for `endless`, `no ending`, `no goal`, `no point`, `infinite grinding`, `live service`. If ≥2 hits → endless signal.

Then classify the finish:
- **Hard finish** (real finish event: credits / last level / final boss / win-condition / summit) → add normally.
- **Soft finish** (a finish exists but it is an accumulated status / checklist / score-threshold inside the same loop — Forza Hall of Fame, Soulmask Central Core) → add, but **prefix the `verdict` with `🟠 ` and state briefly why** (≤120 chars still; the 🟠 counts).
- **No finish** (endless contracts/quotas, repeatable matches, co-op never resolves) → skip `endless`. **A finite map/level COUNT is NOT a finish** — a selectable, replayable roster (even 5 maps) played for score / survival / time has no culminating endpoint (Counter-Strike / Phasmophobia / DEVOUR pattern). A finish needs a SEQUENCE to a final boss / credits / destination, not just variety in a replay loop.

If you cannot tell hard vs soft but a finish clearly exists → treat as soft (🟠). Episodic+secondary co-op → ADD with 🟠, NOT a skip. Skip ONLY: no finish at all (`endless` / `unclear_ending`), no 2-player co-op (`no_coop`), or co-op finish ≤1h (`coop_too_short`).

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
3. **Perspective** — `taxonomy.json` axes rule: `exactly_one_per_game`. Pick ONE of `First-person`, `Third-person`, `Isometric`, `Side-view`, `Top-down` using the per-tag `decision_tree`. If none clearly applies → log via `log_skip.py` (reason `taxonomy_ambiguous`) with the candidate name; do NOT guess.
4. **Mechanic(s)** — at least one required. Walk through the `mechanic` section, apply each tag's `decision_tree`. Multiple allowed but be conservative. **Especially for `Adventure`**: the tag has a strict `narrowing_rule` — apply ONLY to narrative-led + exploration + dialogue games (Chicory-style). If the game has a story but the verb is shooting / fighting / puzzle — do NOT tag Adventure.
5. **Setting** — optional, multiple. Walk through `setting` section, apply where `decision_tree` matches.
6. **Structure** — optional, multiple. Same procedure.
7. **endingType** — exactly one. Walk through `ending_types` section, apply the matching `decision_tree`. If no path matches → log `taxonomy_ambiguous` and skip.

Final genres array example: `["AAA", "First-person", "Shooter", "Sci-fi"]` (tier first, then perspective, then mechanics, then settings, then structures).

If you find yourself wanting to introduce a tag not present in `taxonomy.json` → STOP. Log via `log_skip.py` (reason `taxonomy_gap`) with a one-line description of what was missing. Do not edit `taxonomy.json` yourself; that's an owner decision.

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
6. **Only after all of the above produce nothing**: refuse to add this entry. Log via `log_skip.py` (reason `no_video_found`). Do NOT fall back to `youtubeSearch(...)` — that placeholder is forbidden.

The `fact-checker` skill uses the same cascade to fix any broken/placeholder YouTube URLs on existing entries. For coop-hunter, this matters at ADD time: be patient finding a real video — a single skip costs less than a broken modal.

### 8b. FINAL FIT-GATE (mandatory — prevention beats cleanup)

Since coop-hunter no longer re-walks the catalog to clean up mistakes (that's the fact-checker now), the ADD-TIME gates are the main defense. Before calling `append_entry.py`, run this final fit-check and SKIP on ANY doubt. A skipped good game costs nothing; a wrong added game costs manual cleanup later — the owner explicitly prefers a smaller, trustworthy catalog over a larger noisy one.

Confirm ALL of these hold (you already gathered the evidence in §0–§8); if any is uncertain → skip via `log_skip.py` (reason `low_fit`) + a one-line why:

- **On Steam, PC** (not Epic/console-only).
- **Real multiplayer co-op for 2+** — online co-op OR Remote Play Together. NOT single-player-only, NOT PvP-only.
- **Co-op gate (§5 Gate A)** — co-op drives the progression, not just the fights; the co-op finish content is **> 1 hour**. Fails either → SKIP.
- **A finish exists (§5 Gate B)** — hard finish → add normally; **soft finish** (status/checklist/threshold inside a loop) → add with a `🟠 ` verdict prefix explaining why; **no finish** (endless) → SKIP. If you cannot point to ANY finish → SKIP, never "probably has one".
- **Quality**: ≥50 total Steam reviews AND ≥50% positive.
- **Not blocklisted / not previously removed** (re-confirm §0 gates A+B).
- **A real gameplay video and a working image** were found.

If the candidate is a clear genre/structure outlier you can't classify against `taxonomy.json` → SKIP `taxonomy_gap`, do not force-fit. When genuinely unsure whether it belongs → SKIP. Drill for evidence first (per drill mode), but the tie-breaker is always SKIP.

### 9. Build and append entry

**Objective fields are CRON-OWNED — don't agonize (CLAUDE.md "Field ownership").** `year`,
`oneCopy`, `rating`, `ratingCount`, `price`, `imageUrl` have a Steam-API ground truth and are
maintained deterministically by `refresh-prices` (`.github/scripts/refresh.py`), which
re-derives them daily and self-heals any add-time value within ~a day. Pass best-effort values
(append needs them) but treat them as PROVISIONAL — the cron is authoritative. Spend judgment on
the SUBJECTIVE fields only: `genres` (tier/perspective/dimension/mechanic/setting/structure),
`endingType`, `verdict`, `playersMax`, `youtubeUrl`. Never hand-"correct" an objective field
afterwards; if the cron derivation looks wrong, fix the cron script, not the data.

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
  "ratingCount": 1234,
  "playersMax": 4,
  "hours": 12,
  "oneCopy": "none",
  "price": 599,
  "verdict": "One-line description in English.",
  "storeUrl": "https://store.steampowered.com/app/<id>/",
  "imageUrl": "<header_image from appdetails, ?t= stripped>",
  "youtubeUrl": "youtube(\"VIDEO_ID\")"
}
```

`ratingCount` is Steam `query_summary.total_reviews` — the same number you already fetched to compute `%positive` (§ "Steam review scan"). The site uses it to compute a **Wilson lower-bound score** (Steam %positive discounted for sample size) so a 100%-of-10-reviews indie can't outrank a 96%-of-40k AAA. It is optional at insert time (the cron / backfill fills it if you omit it), but you SHOULD pass it since you have it. `append_entry.py` also accepts it under the key `total_reviews`.

Do NOT include `ratingSource`, `ratingLabel`, `playersLabel`, or `hoursLabel` — these were intentionally removed from the schema. The append_entry.py helper enforces this.

For `hours` — use HowLongToBeat's "Main + Extras" value (typical playthrough including side activities, NOT pure main story, NOT 100% completionist). **Always an integer** — round to the nearest whole hour. Fractions like `8.5` are not allowed (the table renders integers only; `append_entry.py` will silently round but skills must emit whole numbers). All other numeric fields (`year`, `rating`, `playersMax`, `price`) are also integers — never emit decimals.

For `rating` — always Steam % positive (from `/appreviews/<id>?json=1`). Never use Metacritic or OpenCritic.

For `verdict` — ≤120 chars English. Plain, factual, one sentence. No marketing fluff. The site is English-only.

### 10. Persist
- `append_entry.py` writes the entry to `data.js` **WITHOUT a `reviewed` field** — that
  absence IS the fact-checker handoff: `fact-checker new` verifies every entry lacking
  `reviewed: true`, then stamps it. No queue file (see CLAUDE.md §6b). It also drops the
  id from `shared/reeval.tsv` if it was there (one-place invariant).
- Update `state/progress.json`:
  - `current_offset += 1`
  - `added_count += 1`
  - `last_added = <id>`
  - **`session_added_ids.append(<id>)`** — running accumulator of this run's adds (the launcher reports it).

## Phase-4 source exhaustion criteria (when to mark a source `completed`)

Phase-4 sources are method-driven, not page-count-driven, so "exhausted" needs a concrete rule per method. Use `current_offset` as the cursor into each source's work-list. A source is exhausted (→ append to `completed_sources`, advance) when:

| Source (idx) | Exhausted for this pass when… |
|---|---|
| `reeval_skipped` (12) | every eligible row of `shared/reeval.tsv` (reason ∈ ambiguous/unclear_ending/not_enough_reviews) has been re-evaluated. Cursor = row index. |
| `steam_more_like_this` (13) | all `top_n` (25) seed entries have had their "More like this" scanned. Cursor = seed index 0..24; done at 25. |
| `websearch_niche_queries` (14) | all 8 `queries` have been run once. Cursor = query index; done at 8. |
| `backloggd_top_completed_coop` (15) | `page > max_pages` (8) OR a fetched page yields 0 new candidates. |
| `steam_community_recommendations` (16) | `page > max_pages` (5) OR a page yields 0 new candidates. |
| `youtube_curator_playlists` (17) | all 8 `queries` have been run once. |
| `reddit_just_finished` (18) | `page > max_pages` (4) OR the API returns no `after` cursor. |
| `wikipedia_coop_lists` (19) | both `urls` have been fetched and parsed. |

If you genuinely cannot tell whether a method-source is exhausted, the anti-stall cap (2 bursts) force-advances it anyway, so you never get stuck — but prefer the explicit criterion above. **Always WRITE the `completed_sources` update to progress.json**; a source you only "mentally" finished but didn't persist will be re-walked from scratch and the run will stall on it (this was the real 2026-05-29 bug: the log said "all phase-4 sources complete" while `completed_sources` held only `reeval_skipped`).

## Phase 4 source methods (exhaustive GROWTH search)

These methods replace the standard "Per-candidate procedure" for sources in phase 4. They are only reached when `max_phase >= 4` (Mac mode). **Phase 4 is now GROWTH-only** — it finds NEW games via deeper sources. Re-validating EXISTING entries (endless re-check, broken media, drift) is NOT coop-hunter's job anymore; that moved to the `fact-checker` skill (single owner of existing-entry quality). This split removes the old double work that made coop-hunter spend hours re-walking the whole catalog before it could reach `done`.

> Removed 2026-05-27: `revalidate_existing`. If you find an endless game already in `data.js`, you may STILL auto-remove it via `scripts/remove_entry.py` (the hard rule against endless games stands), but do NOT systematically re-walk the catalog — the fact-checker does that.

### `reeval_skipped`

> This procedure was BLIND and SHALLOW before (2026-05-31 audit): it had no log of
> what it rejected (so its work couldn't be checked), it never re-opened
> `blocklisted_endless` rows, and it trusted the old skip `notes` instead of fresh
> facts — which is exactly how it missed Forza Horizon 6 (released with a Legend
> milestone) and Drive Beyond Horizons (which actually has a Story Mode). The three
> fixes below (eligible-set, fresh-factcheck, mandatory rejection log) close that.

1. **Eligible reasons** (a FALSE reject is possible). Read `shared/reeval.tsv` (schema: `id, title, reason, source, notes`; skip the header row) and take rows whose reason is: `ambiguous`, `unclear_ending`, `not_enough_reviews`, `endless`, `endless_misclassified`, `low_fit`, `coop_fights_only`, **and `blocklisted_endless` ONLY when the title is NOT actually on the hardcoded blocklist in `classification.md`** (a too-strict pass mis-tagged games like Forza Horizon as `blocklisted_endless` though they are not on the real list — those must be re-opened; titles genuinely on the list stay out). Mechanical/objective reasons never reach `reeval.tsv` (they route to `hard-block.tsv` instead) — so you will not see, and must never re-litigate, `duplicate`, `no_coop`, `not_on_steam`, `pvp_primary`, `invalid_app_id`, `online_broken`, `coop_too_short`.

2. **Verify with FRESH facts — do NOT trust the old `notes`.** The stored note is frequently wrong (it is what made reeval miss Forza H6 and Drive Beyond Horizons). For each candidate: Steam appdetails (released? not `coming_soon`? co-op categories — Online Co-op / Co-op+Remote Play Together? review count & %), AND a `WebSearch` for the finish (`"<title>" ending`, `"<title>" story mode campaign`, `"<title>" final boss / how to finish`). Then apply §5's co-op gate + finish-strength check on the EVIDENCE, not the note.

3. If it now qualifies: **hard** finish → add normally; **soft** finish (fuzzy ending OR episodic+secondary co-op) → add with a leading `🟠 ` verdict + reason (e.g. a Forza-style Legend milestone). Counts toward phase_yield.

4. If it still does NOT qualify → it STAYS in `shared/reeval.tsv` (re-checkable). Re-log it via `python3 scripts/log_skip.py "<title>" <reason_kept> reeval_skipped "<fresh evidence>"` so the row is upserted with the kept reason + the evidence you just gathered (the helper bumps a seen-counter instead of duplicating). This is MANDATORY — without the refreshed note reeval is a black box and its misses can't be audited. Every eligible row you process MUST end either added-to-data.js OR re-logged to `reeval.tsv` with fresh evidence. Reasons that are CHANGEABLE (Early Access with no shipped finale, Steam rating just under 50% / too few reviews, finish not yet confirmable, co-op finish ≤1h, or co-op only via mod/VPN) already live in `reeval.tsv` and are re-judged on the next pass — record the recheck trigger in the notes so it isn't buried.

5. Exhausted when every eligible row has been either added to `data.js` or re-logged to `reeval.tsv` with fresh evidence (cross-check: eligible-count == added + re-logged).

### `reeval_only` mode (migration — re-evaluate skips, do NOT search for new games)

When `progress.reeval_only == true` (set by `run-migration.sh` Stage 2): process ONLY the `reeval_skipped` source above. Do **NOT** run any phase 1–3 source, and do NOT run `steam_more_like_this` / `websearch_*` / any other phase-4 source. When every eligible `shared/reeval.tsv` row has been re-evaluated, set `done=true` and stop — there is no "search for new" step in this mode.

Rationale: the catalog's discovery sources are exhausted (many full runs found nothing new), and the finish-strength change did not widen WHAT we want — it only re-classifies endings. So the valuable work now is re-judging what we already have. This mode is the reeval-list half of the one-time migration; the catalog half is the fact-checker `finish_migration` phase. Both run from `run-migration.sh`, which is deleted afterward (back to normal coop-hunter / fact-checker).

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
  "session_added_ids": [],
  "completed_sources": [],
  "bursts_on_current_source": 0,
  "source_pass_log": [],
  "last_push_at": 0,
  "done": false,
  "last_added": null,
  "last_run_timestamp": null
}
```
`done` stays `false` in normal hunting — it is only flipped by the one-time
`reeval_only` migration mode. `source_pass_log` records full phase-4 passes (context
for when to switch to creative discovery). If the file is missing newer fields, backfill
with the defaults above before proceeding (preserves existing runs).

## Git: you NEVER commit or push — the launcher does

In the eternal model the **launcher** (`run-coop-hunter.sh`) owns git entirely: it
commits, rebases onto the cron, and pushes on a cadence (~hourly or every N adds)
BETWEEN bursts. As the skill running inside a burst, you must **never** call
`git commit` / `git push` / `git pull`. Your only job is:

1. Add games (`append_entry.py`, which adds WITHOUT a `reviewed` flag) and persist state after each.
2. Append every added id to `session_added_ids`.
3. Keep hunting until the burst's ~20-candidate budget is spent, then EXIT.

**Verifying your own additions is NOT your job either.** Media checks (image/youtube
resolve), the delisted-after-add check, and editorial re-checks all happen in the
**`fact-checker` skill's `new` mode**, which verifies every entry lacking
`reviewed: true`. Run `./run-fact-checker.sh new` after a hunt. Do not re-fetch
`price`/`rating` (cron-owned) and do not write a `state/summary.md` — the audit trail
is `git log data.js` + the launcher transcript (state model: CLAUDE.md §6b).

`done` is never set in normal hunting (only the one-time `reeval_only` migration sets it).

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
- ❌ Do not ask the user questions. Use the rules. If truly stuck, log the reject via `log_skip.py` and move on.

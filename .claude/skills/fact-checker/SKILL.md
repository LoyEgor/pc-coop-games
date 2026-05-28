---
name: fact-checker
description: Walk every non-hidden entry in data.js and verify the recorded fields against authoritative sources (Steam appdetails + appreviews, HowLongToBeat, YouTube). Auto-fix safe drift (rating, price, broken media). Log everything else to TSVs for the owner to review. Drill mode — never stop on a single failure; only declare done when every entry has been checked at least once AND every auto-fixable discrepancy has been applied-or-logged-as-irrecoverable. Run via `./run-fact-checker.sh` (a bash loop of headless `claude -p` bursts, ~12 entries each). Independent of coop-hunter — has its own progress/state.
---

# Fact-checker

You are walking `data.js` end-to-end and verifying every recorded field against authoritative sources. This is a separate skill from `coop-hunter` with its own state. The launcher `./run-fact-checker.sh` invokes you ONE BURST at a time as a headless `claude -p` process: resume from `state/progress.json`, verify ~12 entries, persist after EACH, then EXIT — the bash loop starts your next burst fresh. Persist after every entry checked.

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
7. **Endless removal — fact-checker is now the enforcer** (this moved here from coop-hunter's old `revalidate_existing`, 2026-05-27). Two tiers:
   - **AUTO-REMOVE (deterministic):** if the entry's title matches the hardcoded blocklist in `coop-hunter/classification.md`, OR Steam tags now include `MMO` / `Massively Multiplayer` / `Battle Royale`, OR negative reviews show ≥3 hits of `endless` / `no ending` / `live service` / `no point` / `infinite grind` → call `../coop-hunter/scripts/remove_entry.py <id>` (logs to `removed-entries.tsv`, which also blocks re-adding). These are safe, rule-based.
   - **LOG only (judgment calls):** anything borderline (e.g. a survival game whose ending is debatable) → `state/proposed-removals.tsv` for the owner to decide. Do NOT auto-remove on a judgment call.
   This makes the fact-checker the single owner of existing-entry quality (endless re-check + media + drift + taxonomy + consistency via find_neighbors.py). coop-hunter no longer re-walks the catalog.
8. **Progress reporting.** After every entry, print a single line:
   `[N/TOTAL] <id>: rating <state> | hours <state> | genres <state> | media <state> | other <state>`
   Where `<state>` is `OK`, `drift`, `fix`, `propose`, or `fail`.
   **`OK` is earned, not default.** Do NOT report `genres OK` / `perspective OK` /
   `endingType OK` if your only basis was "the Steam tags didn't contradict it". `OK`
   on these editorial fields requires the semantic judgment described in §8 (looked at
   the screenshots/description for the camera) and §9 (ran the ending web search). If
   you could not perform that judgment for an entry, report the field as `fail` and add
   it to `partial_entries[]` so the next pass retries — never paper over it with `OK`.

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

### 8. genres + tier — derived from `.claude/skills/shared/taxonomy.json`

Read `taxonomy.json` once at start of run; cache the in-memory dict for every entry's classification.

**Why this step needs JUDGMENT, not just tag-mapping.** Steam's popular tags are an
unreliable signal for two of the most error-prone fields: `perspective` and `tier`.
Steam tags almost never contain an explicit `First-person`/`Third-person`/`Isometric`/
`Side-view`, so a tag-only check finds "no contradiction" and stamps `OK` — leaving a
wrong perspective in place forever. **That is the bug we are fixing.** You must form a
real opinion of how the game LOOKS and how it is STRUCTURED, using everything available
(screenshots, description, your own knowledge of the game), not only the tag list.

For each entry:
1. Fetch the Steam app page data via WebFetch of `https://store.steampowered.com/app/<app_id>/`:
   - The top ~10 popular tags from the `glance_tags` section.
   - The short + detailed **description** text.
   - The **screenshot URLs** (and, when in doubt, look at 2-3 of them to judge the
     camera). appdetails also exposes `screenshots[]` if the store page is hard to scrape.
2. Map each Steam tag to taxonomy via the `steam_tags` array in each `taxonomy.json` entry. A single Steam tag may map to multiple taxonomy tags across axes (e.g. `"FPS"` → `First-person` AND `Shooter`).
3. Apply axis rules from `taxonomy.axes`:
   - `tier` — derive from publisher scale + budget (AAA = major publisher / big-budget;
     AA = mid; Indie = small/self-published). Judge from developers/publishers, not tags.
   - `perspective` — pick exactly one. **DO NOT rely on tags alone.** Determine the camera
     VISUALLY: read the screenshots + description (e.g. "over-the-shoulder" → Third-person,
     "first-person view" → First-person, top-down/Diablo-style → Isometric, 2D side
     scroller → Side-view). Apply this check to EVERY entry, including ones that already
     have a perspective — if the stored perspective contradicts what the screenshots show,
     propose the corrected one. Only stamp perspective `OK` after you have actually judged
     the visuals, never on tag-silence.
   - `mechanic` — at least one required. **Adventure has `narrowing_rule`** — apply ONLY to narrative-led + exploration + dialogue games. If the entry has `Adventure` but does not match the rule (e.g. it's actually an action game or pure puzzle), log a proposed REMOVAL of `Adventure`.
   - `setting`, `structure` — optional.

Compare derived genres set to `entry.genres`:
- Missing axis tag (especially perspective) → log to `proposed-fixes.tsv` (field=`genres`, new_value=what to add).
- Wrong perspective vs the screenshots → log proposed change (old → corrected).
- Extra tag that doesn't match any `decision_tree` from taxonomy → log proposed REMOVAL.
- Tier mismatch → log proposed change.

**Do not auto-modify the `genres` array.** Editorial choice — owner reviews `proposed-fixes.tsv` and decides which to apply via a separate migration step. Exception: there is a dedicated migration phase (see `taxonomy_migration` section below) that DOES auto-apply specific deterministic rewrites (e.g., split `FPS` → `First-person` + `Shooter`).

### 9. endingType — decision_tree PLUS a targeted web search

`endingType` cannot be read off Steam tags either — and getting it wrong is the most
dangerous failure mode in this catalog, because a game with **no real ending** (endless)
must not be here at all (CLAUDE.md §2). So this check has two parts:

1. **Decision_tree pass.** Walk `taxonomy.ending_types[*].decision_tree` and apply the
   first matching type, using the verdict + Steam description + your knowledge.
2. **Targeted web search — REQUIRED, do not skip.** Run a `WebSearch` (or 1-2 WebFetch
   of the top results) to confirm the game actually ends:
   - `"<title>" how does it end` / `"<title>" ending` / `"<title>" final boss` /
     `"<title>" credits` / `"<title>" how long to beat campaign`.
   - For `roguelite` and `survival-goal` entries especially: confirm there is a named
     final boss / explicit win-condition (Mithrix, Moon Lord, "launch the rocket"), NOT
     just "endless escalating runs/waves".
   - Read 2-3 snippets and form a judgment. This is the step that catches an endless
     game that slipped in looking finite.

Outcomes:
- Derived type ≠ stored type → log to `state/proposed-fixes.tsv` (old → corrected).
  Do not auto-fix; endingType is editorial.
- Web search shows the game has **no real ending** (procedurally endless, no final
  boss, "no point/just keeps going") → this is an endless red flag: escalate to rule 7
  (AUTO-REMOVE if it matches the blocklist / deterministic markers; otherwise log to
  `state/proposed-removals.tsv` with the search evidence).
- decision_tree matches multiple types (genuine ambiguity) → `state/discrepancies.tsv`
  with reason `endingtype_ambiguous`. Owner decides.

Flag well-known confusions explicitly (e.g. a game tagged `levels` whose verdict says
"single-session climb" → propose `arcade-goal`).

## taxonomy_migration phase (special, one-time bulk fix)

Triggered manually by setting `progress.mode = "taxonomy_migration"` in fact-checker progress.json. For each entry, AUTO-APPLY the following deterministic rules and log to `state/applied-fixes.tsv`:

1. **FPS split**: if `genres` contains `"FPS"`:
   - Replace `"FPS"` with `"First-person"`.
   - If the entry has shooter mechanics per Steam tags AND `"Shooter"` is not already present, add `"Shooter"` in mechanic position.
   - The 6 exceptions (portal-2, dying-light, dying-light-2, vermintide-2, dead-island-de, dead-island-2) get ONLY `"First-person"`, no `"Shooter"`.

2. **Adventure narrowing**: if `genres` contains `"Adventure"`, run the strict decision_tree:
   - Game is built around narrative-led exploration with dialogue? → keep
   - Else (it's actually action/shooter/puzzle/sim) → REMOVE `Adventure` from genres array
   - The entry's verdict + Steam description are the input. WebFetch Steam page if uncertain.

3. **Perspective enrichment**: if no perspective tag is present, derive one from Steam tags + verdict + screenshots-tag-list:
   - Insert the derived tag immediately after tier, before mechanics.
   - If unable to derive → log to `proposed-fixes.tsv` with reason `perspective_undetermined`, don't auto-fix.

This phase is reserved for the explicit taxonomy migration run. Normal fact-checker runs do NOT execute it — they only LOG proposed changes per §8 / §9.

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

## Consistency audit (run ONCE per fact-check run, before/after the entry loop)

Per-entry verification can't catch a whole CLASS of errors: a wrong decision that
looks self-consistent in isolation (e.g. Forza Horizon 5 added as `story` with a
hallucinated "finale campaign" — there is no ending). These are caught not by
ground truth but by the catalog **contradicting itself**. Run:

```
python3 scripts/find_neighbors.py
```

It reads `data.js` + coop-hunter's `skipped.tsv` and writes
`state/inconsistencies.tsv` with two precise (low-noise) signals:

- **`franchise_split`** — a game is in the catalog while a same-franchise sibling
  was SKIPPED on a *judgment* reason (`endless`, `unclear_ending`, `ambiguous`,
  `low_quality`, …). Same franchise, opposite verdict = one side is wrong. This
  is exactly the Forza-5-in / Forza-6-skipped pattern. (Mechanical skips —
  `duplicate`, `no_coop`, `not_on_steam`, mod, VR, EA — are NOT flagged; they're
  objective, not contradictions.)
- **`franchise_ending`** — two same-franchise catalog entries with different
  `endingType` (e.g. Sniper Elite 3/4/5 mismatched).

For each finding: VERIFY which side is correct (Steam page + HLTB + dev notes),
then:
- catalog entry wrong (endless slipped in, e.g. Forza Horizon 5) → if it matches
  the hardcoded blocklist or the deterministic endless markers (rule 7),
  AUTO-REMOVE via `../coop-hunter/scripts/remove_entry.py <id>`; if it's a
  judgment call, log to `state/proposed-removals.tsv`.
- skip wrong (a finite game wrongly skipped) → it will be re-evaluated by
  coop-hunter `reeval_skipped`; note it in `state/discrepancies.tsv`.
- `endingType` mismatch within a franchise → log the correct value to
  `state/proposed-fixes.tsv`.

A `franchise_split` where the SAME id is both in the catalog and in `skipped.tsv`
means a stale skip row — note it; the skip log just needs that line dropped.

This audit is cheap (no network) and the output is short (~10 items, not 1000) —
review it every run. It is the answer to "no single result can be trusted": the
system surfaces its own contradictions into one short queue instead of asking you
to re-check all 400+ entries.

## Stopping condition

`done = true` only when ALL of:
1. `current_idx >= len(non_hidden_entries)`.
2. `partial_entries` is empty (every entry got a complete check, not just partial).
3. Every entry with a `bad_video` or `no_image` flag was either fixed-and-logged or logged as irrecoverable.

The fact-checker auto-removes deterministic endless/blocklist matches (rule 7) and logs judgment-call removals to `proposed-removals.tsv` for the owner. coop-hunter no longer re-validates existing entries.

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

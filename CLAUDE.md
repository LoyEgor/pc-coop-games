# CLAUDE.md — instructions for any LLM working in this project

**Read this first** when opening this repository in Claude Code (or any LLM agent). It encodes the project's purpose, hard constraints, and the conventions the owner expects you to follow.

---

## 1. What this project is

A **personal, hand-curated catalog of PC co-op games** that the owner and his partner can play remotely (two-player or more, online or via Steam Remote Play Together). Rendered as a single static HTML page with a sortable / filterable table.

- Repo: <https://github.com/LoyEgor/pc-coop-games>
- Live: <https://loyegor.github.io/pc-coop-games/>
- Stack: static HTML + JS + CSS, deployed via GitHub Pages from `main` branch root.

**The catalog is opinionated.** Every entry was added by the owner (or by the `coop-hunter` skill following his rules). The catalog is NOT meant to be exhaustive — it is meant to be **trustworthy**: every game in it must satisfy strict criteria.

## 2. The single most important rule: a co-op run must FINISH — and how strongly

The owner's hardest constraint is still that a co-op playthrough must have an end you can reach — not endless contracts, quotas, or repeatable matches forever. But the catalog is **not pass/fail**: a game can ship with a leading 🟠 in its verdict — a **caveat marker** meaning "fine to play, just know this first". 🟠 has **two independent triggers**:
- **(B) soft finish** — the ending is fuzzy (an accumulated status / checklist, not a discrete final event);
- **(A) partial co-op** — the second player is *episodic AND secondary* (see Gate A).

Hard finish + full co-op → no marker. No finish at all → excluded entirely. The machine-readable version lives in `.claude/skills/shared/taxonomy.json` → `finish_strength`. **Never print the reasoning labels ("hard/soft finish", "partial co-op") on the site** — what ships is the entry (optionally a leading 🟠 + a short reason in the verdict) or nothing.

### Gate A — the co-op gate (check FIRST)
- **2-player co-op must exist** (online or Remote Play Together). If there is no real 2-player mode → not a co-op game → do not add. (This is a plain "not a fit", NOT a 🟠.)
- **Asymmetry and helpers are FINE — as long as the second player is present THROUGHOUT.** Different-but-constant roles (one drives, one shoots) = full co-op. A permanent secondary companion always at your side (Tails alongside Sonic; Timespinner's familiar) = full co-op. No marker.
- **🟠 only when P2 is BOTH episodic AND secondary.** If the second player joins only *part* of the game — the classic JRPG shape where P2 drops in for battles only while one player owns the story / world map / dialogue / exploration (Tales series, Ys, Legend of Mana) — the game STILL qualifies (you can play and finish it together), but PREFIX the verdict with 🟠 and say the co-op is battles-only / P2 is a helper. This is NOT a reject.
- **Count finite CO-OP hours, not the whole game.** Forza Horizon is 80-120h overall, but only the co-op progression up to its milestone counts. Drive Beyond Horizons is endless, but its Scenario/Story route is ~1-2h — count only that.
- **The co-op finish content must be > 1 hour.** If the only co-op goal is reached in ≤1h, or never, do not add.

### Gate B — finish strength
- **Hard finish → ADD, no marker.** A real finish *event*: story credits, a defined last level/mission, a roguelite final boss that wins the run (Mithrix, Hades), a survival win-condition (Moon Lord, Yagluth, Project Assembly), a summit / escape / route endpoint (PEAK reach the top, Operation Tango complete the mission). After it the main branch is closed.
- **Soft finish → ADD, but PREFIX the verdict with 🟠 and say briefly why.** A finish *exists* but it is an accumulated status / checklist / score-threshold *inside the same loop*, not a discrete final event, and the loop continues afterward. Examples: Forza Horizon 5 (Hall of Fame = a career milestone, not a final mission), Soulmask (Central Core boss gated behind a survival-endgame grind), Icarus (Operations / Great Hunts inside a repeatable cycle).
- **No finish → EXCLUDE.** Only endless contracts/quotas (Lethal Company, Phasmophobia, R.E.P.O.), endless mission-grind (Deep Rock Galactic, Helldivers 2), endless waves (Killing Floor, GTFO, Bloons TD 6, Crab Champions), live-service seasons (Destiny 2), sandboxes with no win-state (Minecraft creative, Don't Starve Together, Project Zomboid), MMORPGs (WoW, Path of Exile, New World), or PvP-only (CS, Valorant, Dota, Rocket League).

### The owner's borderline rule (unchanged in spirit)
> "Если у игры нет сюжета, но явно есть чёткий и понятный конец, когда ты до него доходишь, это ощущается как конец — даже если нет заставки, сюжета и т.п. — такая игра подходит. Если же после какого-то босса следует случайно сгенерированный уровень или тот же уровень, и непонятно, как игру закончить — это не подходит."

A game qualifies if there is a moment where you finish — even without a cutscene. NG+ / replay-after-credits is **fine** (Max Payne, Cyberpunk 2077, Stardew Valley) — the point is there WAS a finish moment.

### When in doubt
- Finish is real but **fuzzy** (status/checklist) → add with 🟠 (soft); don't agonize.
- Co-op is **episodic + secondary** (P2 in battles only) → add with 🟠; NOT a skip.
- Can't find **any** finish, OR there is **no 2-player co-op at all**, OR co-op finish content is ≤1h, OR it's an endless loop → **SKIP**. Quality > volume; «мне принципиально важно, чтобы endless игры не появлялись, а если находятся — вычищать».

## 3. Other criteria

- **Platform**: PC, available on Steam. Not Steam → out (excluded: Minecraft, Fortnite, Apex Legends).
- **Players**: 2 or more, online or via Steam Remote Play Together. Pure local-only games without Remote Play support → out.
- **Reviews**: ≥ 50% positive on Steam, with ≥ 50 total reviews.
- **One-copy options** (`oneCopy` field): `none` (each player needs a copy), `remote-play` (one copy + Remote Play Together), `friend-pass` (Friend Pass DLC / asymmetric games where only one copy is required).

## 4. Data shape

`data.js` exports `window.GAMES` — an array of objects. Schema for each entry:

```javascript
{
  id: "kebab-case-slug",                 // unique
  title: "Game Title",                    // as on Steam
  year: 2024,                             // release year
  genres: ["AAA", "Action", "Shooter"],   // first item is tier: "AAA" | "AA" | "Indie"; rest are from the existing taxonomy
  endingType: "story",                    // one of: story | levels | arcade-goal | roguelite | survival-goal
  rating: 87,                             // Steam % positive (0-100). Always Steam — see WHY-1 below
  ratingCount: 1234,                      // Steam total_reviews. Site computes a Wilson score from rating+ratingCount — see WHY-4
  playersMax: 4,                          // max co-op count
  hours: 12,                              // "Main + a bit" — typical playthrough time. INTEGER only, no fractions — see WHY-3
  oneCopy: "none",                        // "none" (each needs a copy) | "remote-play" | "friend-pass"
  price: 599,                             // UAH integer from Steam cc=ua
  verdict: "Short description.",          // ≤120 chars English
  storeUrl: "https://store.steampowered.com/app/<id>/",
  imageUrl: "https://shared.akamai.steamstatic.com/store_item_assets/.../header.jpg", // canonical: header_image from appdetails (?t= stripped). steamImage(<id>) is a legacy fallback that 404s for newer apps.
  youtubeUrl: youtube("VIDEO_ID")         // helper; MUST be a real gameplay video, NOT a search URL
}
```

Optional flags:
- `hidden: true` + `hiddenReason: "..."` — keeps game in DB but hides from default view (used for "уже прошли" / referenced games).
- `"needs-review": true` — Steam reviews 50-70%, flagged for manual quality check.
- `ownerConfirmed: true` — the OWNER hand-decided this entry (e.g. a soft 🟠 finish like Icarus). **fact-checker must never remove, propose-removal, or re-classify endingType/genres on it** — only media fixes + cron price/rating are allowed. Stops the round-trip where the skill deletes what the owner just confirmed.

### Why the schema is this minimal

**WHY-1: Rating is always Steam %positive.** Previously the schema had `rating + ratingSource + ratingLabel` where source could be `Steam`, `Metacritic`, or `OpenCritic`. The owner decided this was noise: three different scoring scales mixed in one column makes the rating harder to read at a glance, and the catalog's purpose is "should we play this" — for which the most relevant signal is **how Steam players felt** about the game, not how critics scored it. So the `ratingSource` column was deleted entirely, and `rating` is now a single Steam %positive number. The skill always uses Steam (`/appreviews/<id>?json=1`) — do NOT introduce Metacritic/OpenCritic again.

**WHY-2: `playersMax` is a number, not a label.** Previously there was a `playersLabel` like `"до 4, кампания"` or `"2, локально"` rendered as a sub-line. The owner decided this duplicated information: the number is already visible (`4`), and the multiplayer mode (local vs online vs Friend Pass) is already encoded in the `oneCopy` field which has its own column. So `playersLabel` was deleted. Show just `playersMax` as a single integer.

**WHY-3: `hours` is one integer, not a range and not a float.** Previously there was a `hoursLabel` like `"10-15"` rendered as a sub-line. The owner decided that for "should we play this tonight" a single representative number is more useful than a range. The number represents "Main Story + a bit" (a.k.a. HowLongToBeat's **Main + Extras**) — what a typical co-op duo will spend if they do the campaign plus a few side activities but don't go for 100% completion. This is also approximately what the previous `hours` field already stored, so removing `hoursLabel` was lossless. Use HowLongToBeat's "Main + Extras" if available; otherwise estimate. **Always store as an integer** — round HLTB values to the nearest whole hour. Fractional values like `8.5` are not allowed; the rendering layer and `append_entry.py` both round defensively, but skills must not emit fractions in the first place.

**WHY-4: `ratingCount` exists so the site can rank by a Wilson score, not raw %.** A game with 100% of 10 reviews is not better than a AAA with 96% of 40 000 — raw %positive ignores sample size, so tiny indies floated to the top of the table. `ratingCount` is Steam `total_reviews`; `app.js` computes the **Wilson lower-bound of the positive fraction** (95% confidence) from `rating` + `ratingCount` and **sorts the Rating column by that**, while the cell still DISPLAYS the Wilson score big with a sub-caption (`<reviews in K/M> · <Steam %>`). Few reviews → the lower bound sits well below the raw %, so under-reviewed games sink; well-reviewed games keep ~their raw %. `rating` and `ratingCount` are BOTH owned by the cron (`refresh.py`): rating updates at ≥2pp drift (tightened from 5pp because a stale % skews Wilson), count at ≥12% relative drift (Wilson is flat at large n, so a coarse count keeps diffs small). The score is derived on the client — it is NOT stored. Do NOT reintroduce Metacritic/OpenCritic (see WHY-1); Wilson is computed purely from Steam data.

### Genre taxonomy — defined in `.claude/skills/shared/taxonomy.json`

**The authoritative taxonomy is `.claude/skills/shared/taxonomy.json`.** Do not invent tags; if you need one that isn't there, that's an owner decision. The genres array is now AXIS-STRUCTURED. Order within the array: tier → perspective → mechanic(s) → setting(s) → structure(s).

| Axis | Rule | Tags |
|------|------|------|
| tier | exactly one (first element) | `AAA`, `AA`, `Indie` |
| perspective | exactly one | `First-person`, `Third-person`, `Isometric`, `Side-view` |
| mechanic | at least one | `Shooter`, `Action`, `Puzzle`, `Platformer`, `RPG`, `Tactics`, `Stealth`, `Soulslike`, `Loot`, `Adventure` |
| setting | optional, multiple | `Fantasy`, `Sci-fi`, `Horror`, `Military` |
| structure | optional, multiple | `Open World`, `Survival` |

Notes vs the pre-2026-05 taxonomy:
- `FPS` is GONE — split into `First-person` (perspective) + `Shooter` (mechanic).
- `Top-down` merged into `Isometric` (all "seen from above").
- `Adventure` is NARROW — narrative-led + exploration + dialogue only (Chicory-style), NOT "any game with a story".

Tier values render as a highlighted chip via `.tag.tier` CSS; the Genres filter renders one section per axis with live counts (OR within an axis, AND across axes).

### endingType values (full decision-trees in taxonomy.json)
- `story` — narrative campaign with cutscenes (BG3, Halo, RE5).
- `levels` — discrete level/mission set with last one, weak/no narrative (Castle Crashers, Cuphead, RV There Yet?).
- `arcade-goal` — short single-session goal: climb, escape, defuse (PEAK, Operation Tango, We Were Here, Keep Talking).
- `roguelite` — run-based with persistent meta-progress + final boss (Risk of Rain 2, Hades, Spelunky 2).
- `survival-goal` — survival sandbox with explicit named win-condition (Terraria, Valheim, Raft, Stardew Valley).

## 5. The `coop-hunter` skill

Lives at `.claude/skills/coop-hunter/` and is auto-loaded by Claude Code when this repo is opened. Its job: systematically discover new candidates from SteamDB / Co-Optimus / curators / Reddit / articles, validate them, classify, and append to `data.js`.

### To invoke
Run the launcher (macOS / Linux):

```
./run-coop-hunter.sh
```

**Execution model: headless bursts, NOT `/goal`.** The launcher is a bash loop;
each iteration runs ONE `claude -p` (headless) burst that processes ~20
candidates, persists state, and EXITS — then the loop starts the next burst with
a fresh process. (Earlier the launcher used `/goal`, but its evaluator reads the
whole transcript every turn and overflowed on multi-hour runs — "Prompt is too
long" — so the project moved to headless bursts.) The skill is resumable from
`state/progress.json` and cascades phases 1-4. **coop-hunter is ETERNAL — there
is no "done":** when the structured sources run dry it switches to creative
discovery (invents fresh search angles, logs them to `discovery-log.tsv`) and
keeps going until you Ctrl+C. **Push policy: the LAUNCHER pushes periodically** —
every ~hour OR every 10 new games (commit → rebase onto cron → push). Windows
`.ps1` launcher was removed — this is a macOS/Linux project now.

See [`.claude/skills/README.md`](.claude/skills/README.md) for the full picture.

**There are two skills + three launchers + one cron in this project:**
- `coop-hunter` (skill) — grows the catalog, eternally. Launch: `./run-coop-hunter.sh`. Every added game starts WITHOUT a `reviewed` flag, so `fact-checker new` picks it up automatically (no queue file — see §6b).
- `fact-checker` (skill) — verifies entries + removes endless games. Launch: `./run-fact-checker.sh [new|all]` (`new` = just the hunter's latest finds via the queue; `all` = whole catalog, default).
- taxonomy migration — fact-checker in a special mode, one-time. Launch: `./run-migration.sh`.
- `refresh-prices` (GitHub Actions cron) — owns `price`/`rating`/`ratingCount`, runs daily on GitHub, no LLM.

Quick brief covering all of them, with watch-progress commands: [`.claude/skills/README.md`](.claude/skills/README.md). Read that first if you're new to the repo.

### Skill rules (summary)
- Sequential, not parallel. Sleep 1.5s between Steam API calls (rate-limit).
- Persist `state/progress.json` after EVERY game added.
- Resumable: if interrupted, `progress.json` records where to pick up.
- Idempotent: skip if Steam app id already in `data.js`.
- Never asks the user questions — uses `classification.md` rules; logs rejects via `scripts/log_skip.py` (routes to `shared/reeval.tsv` or `shared/hard-block.tsv` — see §6b) and moves on.
- **coop-hunter is GROWTH-only** (changed 2026-05-27). It finds new games and applies strict ADD-TIME gates so junk never gets in (see SKILL.md §8b Final fit-gate). It no longer re-walks the catalog — re-validating existing entries (endless re-check, broken media, drift) is the **`fact-checker`** skill's job. See section 6.

## 6. Auto-removal of endless games (false positive cleanup)

The owner has been explicit: **if a truly endless (no-finish) game ends up in `data.js`, it must be removed**. The **`fact-checker` skill is the enforcer** (it owns existing-entry verification). It removes via `remove_entry.py`, which routes the game to `shared/hard-block.tsv` (mechanical) or `shared/reeval.tsv` (re-checkable — endless-by-judgment, since rules can change; see §6b). Judgment-call removals go to `shared/owner-review.tsv`. **Note:** "endless" is almost never `hard-block` — a fuzzy finish (Forza) is now a soft 🟠 add, not a ban. Only mechanical impossibility (no co-op / PvP-only / not Steam / MMO) is hard-block.

For each existing entry, the skill checks for endless markers:

| Signal | Weight |
|---|---|
| Steam tag includes `Massively Multiplayer`, `MMORPG`, `Battle Royale` | **HARD BLOCK** — remove |
| Steam tag includes `Open World Survival Craft` **and** no Main Story listed on HowLongToBeat | **HARD BLOCK** |
| Steam tag includes `Wave Defense`, `Wave Survival`, `Horde` | Strong signal — check for explicit endgame |
| Negative reviews mention `endless` / `no ending` / `live service` / `no point` / `infinite grind` ≥ 3 times | Strong signal |
| Game has `Co-op` + `Procedural Generation` + `Survival` + no boss progression | Strong signal |
| HowLongToBeat: `Completionist` time but no `Main Story` time | Strong signal |
| Steam description mentions "ongoing content", "seasons", "battle pass" | Strong signal |
| Released as **Early Access** without announced endgame | Strong signal |

Three or more strong signals → entry is removed from `data.js` via `scripts/remove_entry.py` (routes to `shared/hard-block.tsv` or `shared/reeval.tsv` per §6b).

### Known endless games — never add (hardcoded blocklist)
These have appeared as false positives historically. The skill maintains a blocklist:

- Deep Rock Galactic (endless mission grind)
- Lethal Company (sessional quotas, no end)
- R.E.P.O. (sessional like Lethal Company)
- Content Warning (sessional)
- Phasmophobia (contracts, no end)
- Helldivers 2 (live service Galactic War)
- Bloons TD 6 (endless tower defense)
- Crab Champions (wave-based)
- Schedule I (sandbox drug sim)
- Don't Starve Together
- Project Zomboid
- Killing Floor / KF2 / KF3
- GTFO (extraction-based, technically no campaign end)
- War Thunder, World of Tanks, Path of Exile, Diablo Immortal, Genshin Impact
- Wobbly Life (party sandbox)
- WEBFISHING (hangout MMO)
- Factorio (base game endless; Space Age DLC has ending but skip unless DLC is verified)
- Planet Crafter (mostly open-ended terraforming sim)
- Boomerang Fu (party brawler, no ending)
- Fortnite, Apex Legends, Warzone, anything Battle Royale
- Any MMO

If a game appears on this list, **never add it**, regardless of what Steam categories or reviews say.

## 6b. State model — the four lists (canonical; read this before touching state)

Every game lives in **exactly one** state. There are only four lists, plus two per-skill cursors:

| List | Meaning | Writer | Reader |
|---|---|---|---|
| `data.js` | IN the catalog (playable; hard finish or soft 🟠) | coop-hunter adds; fact-checker fixes | the site, both skills |
| `.claude/skills/shared/reeval.tsv` | rejected but **RE-CHECKABLE** — judgment/threshold reasons (unclear_ending, Early Access, low rating, too-few-reviews, endless-with-a-milestone like Forza) | `log_skip.py` / `remove_entry.py` | coop-hunter (dedup + `reeval_skipped`), `find_neighbors.py` |
| `.claude/skills/shared/hard-block.tsv` | **NEVER add** — mechanical only (no co-op / PvP-only / not on Steam / MMO / delisted) | `log_skip.py` / `remove_entry.py --block` | coop-hunter gate (`append_entry.py` exit 3) |
| `.claude/skills/shared/owner-review.tsv` | the **owner's TODO** queue (`action` = fix / remove / contradiction) | `log_event.py` / `find_neighbors.py` / fact-checker | the OWNER |

Cursors (NOT lists of games — just "where the skill stopped"): `coop-hunter/state/progress.json`, `fact-checker/state/progress.json`.

**Invariant:** a game id is in EXACTLY ONE of {`data.js`, `reeval`, `hard-block`}. Enforced at two layers:
- **Preventive (write time):** `append_entry.py` drops the id from reeval on add and refuses hard-blocked ids; `log_skip.py` won't list a game that's already in `data.js` and routes reeval-vs-hard exclusively.
- **Postfactum sweep:** `coop-hunter/scripts/sync_lists.py` (deterministic, no LLM) reconciles any overlap that slips past the gates (manual edit / crash / race / older row) by fixed precedence — catalog wins over reeval, reeval wins over hard-block, and a `data.js`∩`hard-block` collision is dropped from hard-block AND flagged to `owner-review` (action=contradiction). **Both launchers run `sync_lists.py --apply` at the start of every run**, so the invariant self-heals each pass. Run it by hand anytime: `python3 .claude/skills/coop-hunter/scripts/sync_lists.py` (dry-run) / `--apply`.

`owner-review` is a TODO **overlay** — it may point at a game living in any of the three; it is not a place of residence (so an id may be both in `data.js` and in owner-review as "remove?").

**The `reviewed` flag.** A fresh entry in `data.js` has **no** `reviewed` field = "fact-checker hasn't checked it yet". `fact-checker new` processes every entry lacking `reviewed: true`, then stamps it (`mark_reviewed.py`). This is reliable because it lives on the game, not on git timestamps.

**Lifecycle — who moves a game where:**
- coop-hunter finds a candidate → `data.js` (qualifies; added WITHOUT `reviewed`) | `reeval` (maybe later) | `hard-block` (mechanically impossible).
- coop-hunter `reeval_skipped` re-judges `reeval` rows → promotes to `data.js` when they now qualify (hard, or soft with leading 🟠).
- `fact-checker new` checks unreviewed `data.js` entries → stamps `reviewed: true`; a problem → `owner-review`.
- `fact-checker all` re-checks the whole catalog → auto-applies confident editorial fixes, routes real judgment calls to `owner-review`, and **self-cleans** owner-review of what it's now sure about (the queue should trend toward empty).
- `remove_entry.py` pulls a game out of `data.js` → `reeval` (re-checkable) or `hard-block` (`--block`, mechanical).

No other state files exist. Audit history = `git log data.js` + the launcher transcripts. (Historical note: this replaced ~18 sprawling lists — added/skipped/removed/borderline/bad-existing/image-fixes/youtube-fixes/applied-fixes/discrepancies/inconsistencies/reconcile-report/proposed-* — folded down on 2026-05-31.)

## 7. UI / table changes

`index.html`, `app.js`, `styles.css` are the rendering layer. The skill **does not touch them** — only `data.js`. If you (as a future LLM) are asked to change UI:

- 13 columns, all English: Image, Game, Year, Genres, Ending, Rating, Players, Hours, Copies, Price, Verdict, YouTube, Played. There is no separate "reviews count" column: the **Rating** cell shows the **Wilson score** big with a sub-caption (`<reviews K/M> · <Steam %>`) and **sorts by Wilson** (see WHY-4). The Rating filter popover has TWO range controls — Steam % and minimum reviews.
- Filter logic in `app.js` (`gameMatchesFilters`, `filterConfig`, and the faceted Genres model: OR within an axis, AND across axes — see `GENRE_AXES`).
- Sort logic in `app.js` (`getSortValue`).
- Row template in `app.js` (`renderRow`, `renderEndingType`).

UI conventions:
- The header cell has two click zones: clicking the **text label** sorts that column; clicking the **rest of the cell** (chevron, empty space) opens the filter popover.
- Range filters (Year, Rating, Players, Hours, Price) pre-fill min/max with the actual data extents and snap to grid increments (rating: 5, price: 50 with stepBase 49).
- Tier values (AAA / AA / Indie) are stored INSIDE the `genres` array as the first element and styled differently via `.tag.tier`.

## 8. Deployment

GitHub Pages is configured to serve `main` branch root. Every push to `main` triggers a re-deploy (~1 minute lag).

Do not touch `.github/`, GitHub Actions, or any deployment workflow without explicit user permission.

## 9. Persona and tone

The owner is Russian-speaking and direct, but the public site is **English-only**. All user-facing strings in `data.js` (the `verdict` field, `hiddenReason`), `app.js` (ONE_COPY / ENDING_TYPE labels, filter labels, captions), and `index.html` (`<h1>`, subtitle, button text, column headers) are in English. Code comments and LLM-facing docs (like this file) are in English. The owner himself communicates in Russian — that's a session-level concern, not a data/UI concern.

When asked to make changes:
- Be concise.
- Don't add features the owner didn't ask for.
- Don't refactor without permission.
- Don't add comments to code unless the WHY is genuinely non-obvious.
- Test in the Claude Preview server (use `preview_*` tools, never browser MCPs) before claiming UI changes work.
- **Leave no temp files behind.** If you create a throwaway script, scratch file, dumped log, or a one-off migration/backfill helper to get a task done — run it, then **delete it** before you finish. Do not commit it, do not leave it in the working tree. The ONLY files that may persist are ones wired into a workflow/skill or that the owner explicitly asked to keep. This covers `*.tmp`, ad-hoc `*.py`/`*.sh` scripts, debug dumps, etc. The owner should never have to discover a stray file and guess what it was for — there is no standing tolerance for "temporary" artifacts in the repo.

## 10. What this file is NOT

- It is not a roadmap or backlog. Owner's draft backlog of future ideas lives in [`TODO.md`](TODO.md) at repo root — check it for known-pending improvements before suggesting work, and update it (cross-off + delete completed blocks) when an item is actually finished. Do NOT start work on a `TODO.md` item without an explicit request.
- It is not a changelog. Use `git log` for that.
- It is not a place to dump unstructured opinions or "thoughts". Keep it as crisp rules.

If you find this file out of date, update it; don't keep guessing.

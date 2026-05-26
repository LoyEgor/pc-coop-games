# CLAUDE.md — instructions for any LLM working in this project

**Read this first** when opening this repository in Claude Code (or any LLM agent). It encodes the project's purpose, hard constraints, and the conventions the owner expects you to follow.

---

## 1. What this project is

A **personal, hand-curated catalog of PC co-op games** that the owner and his partner can play remotely (two-player or more, online or via Steam Remote Play Together). Rendered as a single static HTML page with a sortable / filterable table.

- Repo: <https://github.com/LoyEgor/pc-coop-games>
- Live: <https://loyegor.github.io/pc-coop-games/>
- Stack: static HTML + JS + CSS, deployed via GitHub Pages from `main` branch root.

**The catalog is opinionated.** Every entry was added by the owner (or by the `coop-hunter` skill following his rules). The catalog is NOT meant to be exhaustive — it is meant to be **trustworthy**: every game in it must satisfy strict criteria.

## 2. The single most important rule: NO ENDLESS GAMES

The owner's hardest constraint: **a game must have an ending**. There has to be a clear, identifiable moment where the player can say "I have finished this game." Endless / sessional / live-service games are **explicitly excluded**, even if they're popular co-op games.

### A game has an ending if:
- It has a story campaign with credits / cutscene finale (BG3, Halo, A Way Out).
- It has a set of levels or missions with a defined last one (Castle Crashers, Streets of Rage 4, Cuphead boss rush).
- It is a roguelite with a final boss that "wins" the run (Risk of Rain 2 / Mithrix, Hades / Hades, Spelunky / Hundun).
- It is a survival / sandbox **with an explicit win-condition or endgame boss** (Terraria / Moon Lord, Valheim / Yagluth, Satisfactory / Project Assembly Phase 5, Stardew Valley / Grandpa's evaluation, Subnautica / launch the rocket).
- It is a climbing / traversal / escape game with a defined endpoint (PEAK / reach the top, Operation Tango / complete the mission).
- It has a Quest Mode or Story Mode that ends, even if the rest of the game is PvP (TowerFall Ascension).

### A game does NOT have an ending if:
- It is **mission-grind based** with no narrative arc, no final boss, just endless missions of escalating difficulty (Deep Rock Galactic, Helldivers 2, Earth Defense Force without acts).
- It is **wave-based** with endless waves (Killing Floor, GTFO, Bloons TD 6, Crab Champions).
- It is **live-service** with seasons, battle passes, ongoing content (Destiny 2, Diablo 4 seasons — though D4's main campaign IS finite, see nuance below).
- It is **sessional** with quotas / scares / contracts (Lethal Company, Phasmophobia, Content Warning, R.E.P.O.).
- It is a **sandbox** with no defined "you won" state (Minecraft creative, Don't Starve Together, Project Zomboid).
- It is **MMORPG** with progression but no end (WoW, Path of Exile, New World).
- It is **PvP-only** (Counter-Strike, Valorant, Dota, fighting games, Rocket League).

### Borderline cases — the owner's rule
> "Если у игры нет сюжета, но явно есть чёткий и понятный конец, когда ты до него доходишь, это ощущается как конец — даже если нет заставки, сюжета и т.п. — такая игра подходит. Если же после какого-то босса следует случайно сгенерированный уровень или тот же уровень, и непонятно, как игру закончить — это не подходит."

Translation: a game qualifies if there's a moment where you finish — even without cutscene. It does NOT qualify if you defeat one boss and the game continues with randomly generated levels indefinitely without telling you when to stop.

NG+ / replay-after-credits is **fine**: Max Payne, Cyberpunk 2077, Stardew Valley all continue after their "credits moment". The point is: there WAS a credits moment.

### When in doubt — SKIP
If you're not 100% sure a game has an ending, **do not add it**. Quality > volume. The owner has explicitly said: «мне принципиально важно, чтобы в материалах не появлялись endless игры. Если такие будут находиться игры, то вычищать их».

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
  playersMax: 4,                          // max co-op count
  hours: 12,                              // "Main + a bit" — typical playthrough time. INTEGER only, no fractions — see WHY-3
  oneCopy: "none",                        // "none" (each needs a copy) | "remote-play" | "friend-pass"
  price: 599,                             // UAH integer from Steam cc=ua
  verdict: "Краткое описание.",           // ≤120 chars Russian
  storeUrl: "https://store.steampowered.com/app/<id>/",
  imageUrl: steamImage(<id>),             // helper; expands to header.jpg
  youtubeUrl: youtube("VIDEO_ID")         // helper; MUST be a real gameplay video, NOT a search URL
}
```

Optional flags:
- `hidden: true` + `hiddenReason: "..."` — keeps game in DB but hides from default view (used for "уже прошли" / referenced games).
- `"needs-review": true` — Steam reviews 50-70%, flagged for manual quality check.

### Why the schema is this minimal

**WHY-1: Rating is always Steam %positive.** Previously the schema had `rating + ratingSource + ratingLabel` where source could be `Steam`, `Metacritic`, or `OpenCritic`. The owner decided this was noise: three different scoring scales mixed in one column makes the rating harder to read at a glance, and the catalog's purpose is "should we play this" — for which the most relevant signal is **how Steam players felt** about the game, not how critics scored it. So the `ratingSource` column was deleted entirely, and `rating` is now a single Steam %positive number. The skill always uses Steam (`/appreviews/<id>?json=1`) — do NOT introduce Metacritic/OpenCritic again.

**WHY-2: `playersMax` is a number, not a label.** Previously there was a `playersLabel` like `"до 4, кампания"` or `"2, локально"` rendered as a sub-line. The owner decided this duplicated information: the number is already visible (`4`), and the multiplayer mode (local vs online vs Friend Pass) is already encoded in the `oneCopy` field which has its own column. So `playersLabel` was deleted. Show just `playersMax` as a single integer.

**WHY-3: `hours` is one integer, not a range and not a float.** Previously there was a `hoursLabel` like `"10-15"` rendered as a sub-line. The owner decided that for "should we play this tonight" a single representative number is more useful than a range. The number represents "Main Story + a bit" (a.k.a. HowLongToBeat's **Main + Extras**) — what a typical co-op duo will spend if they do the campaign plus a few side activities but don't go for 100% completion. This is also approximately what the previous `hours` field already stored, so removing `hoursLabel` was lossless. Use HowLongToBeat's "Main + Extras" if available; otherwise estimate. **Always store as an integer** — round HLTB values to the nearest whole hour. Fractional values like `8.5` are not allowed; the rendering layer and `append_entry.py` both round defensively, but skills must not emit fractions in the first place.

### Existing genre taxonomy (do not invent new ones)
`Shooter, Third-person, FPS, Action, RPG, Tactics, Fantasy, Sci-fi, Puzzle, Adventure, Platformer, Stealth, Military, Open World, Loot, Horror, Soulslike, Isometric, Survival`

Plus the tier values `AAA`, `AA`, `Indie` (which are prepended to the genres array and rendered as a highlighted chip via `.tag.tier` CSS).

### Existing genre taxonomy (do not invent new ones)
`Shooter, Third-person, FPS, Action, RPG, Tactics, Fantasy, Sci-fi, Puzzle, Adventure, Platformer, Stealth, Military, Open World, Loot, Horror, Soulslike, Isometric, Survival`

Plus the tier values `AAA`, `AA`, `Indie` (which are prepended to the genres array and rendered as a highlighted chip via `.tag.tier` CSS).

### endingType values
- `story` — narrative campaign with cutscenes (BG3, Halo, RE5).
- `levels` — discrete level/mission set with last one, weak/no narrative (Castle Crashers, Cuphead, Streets of Rage 4).
- `arcade-goal` — short single-session goal: climb, escape, defuse (PEAK, Operation Tango, We Were Here, Keep Talking).
- `roguelite` — run-based with final boss (Risk of Rain 2, Hades, Spelunky 2).
- `survival-goal` — survival sandbox with explicit win-condition (Terraria, Valheim, Raft, Stardew Valley).

## 5. The `coop-hunter` skill

Lives at `.claude/skills/coop-hunter/` and is auto-loaded by Claude Code when this repo is opened. Its job: systematically discover new candidates from SteamDB / Co-Optimus / curators / Reddit / articles, validate them, classify, and append to `data.js`.

### To invoke
Use the `/goal` command in Claude Code:

```
/goal Run the coop-hunter skill to expand data.js per its rules. Process candidates sequentially, persist after each addition, validate every 50, and stop when phase 4 yields 0 new games.
```

For automated overnight runs, use the launchers:
- **Windows**: `.\run-coop-hunter.ps1` (single pass, no git push)
- **Mac / Linux**: `./run-coop-hunter.sh` (cascading phases 1-4, auto-push every 25 games)

See `.claude/skills/coop-hunter/README.md` for full skill documentation.

### Skill rules (summary)
- Sequential, not parallel. Sleep 1.5s between Steam API calls (rate-limit).
- Persist `state/progress.json` after EVERY game added.
- Resumable: if interrupted, `progress.json` records where to pick up.
- Idempotent: skip if Steam app id already in `data.js`.
- Never asks the user questions — uses `classification.md` rules; logs `ambiguous` to `state/skipped.tsv` and moves on.
- **Phase 4 includes `revalidate_existing`** which re-checks every existing entry and **auto-removes** any that turn out to be endless. See section 6.

## 6. Auto-removal of endless games (false positive cleanup)

The owner has been explicit: **if an endless game ends up in `data.js`, the skill must remove it on the next pass**. The phase 4 `revalidate_existing` method is the enforcer.

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

Three or more strong signals → entry is removed from `data.js` via `scripts/remove_entry.py`, removal is logged to `state/removed-entries.tsv` with the reasons.

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

## 7. UI / table changes

`index.html`, `app.js`, `styles.css` are the rendering layer. The skill **does not touch them** — only `data.js`. If you (as a future LLM) are asked to change UI:

- Column widths in `styles.css` (currently 14 columns: Картинка, Игра, Год, Жанры, Тип, Рейтинг, Отзывы, Игроки, Часы, Второму, Цена, Вердикт, YouTube, Скрыть).
- Filter logic in `app.js` (`gameMatchesFilters`, `filterConfig`).
- Sort logic in `app.js` (`getSortValue`).
- Row template in `app.js` (`renderRow`, `renderEndingType`).

UI conventions:
- The header cell has two click zones: clicking the **text label** sorts that column; clicking the **rest of the cell** (chevron, empty space) opens the filter popover.
- Range filters (Год, Рейтинг, Игроки, Часы, Цена) pre-fill min/max with the actual data extents and snap to grid increments (rating: 5, price: 50 with stepBase 49).
- Tier values (AAA / AA / Indie) are stored INSIDE the `genres` array as the first element and styled differently via `.tag.tier`.

## 8. Deployment

GitHub Pages is configured to serve `main` branch root. Every push to `main` triggers a re-deploy (~1 minute lag).

Do not touch `.github/`, GitHub Actions, or any deployment workflow without explicit user permission.

## 9. Persona and tone

The owner is Russian-speaking and direct. Verdicts and labels in `data.js` are in Russian. UI strings are in Russian. Code comments and LLM-facing docs (like this file) are in English where helpful for any future LLM, Russian where it's user-facing.

When asked to make changes:
- Be concise.
- Don't add features the owner didn't ask for.
- Don't refactor without permission.
- Don't add comments to code unless the WHY is genuinely non-obvious.
- Test in the Claude Preview server (use `preview_*` tools, never browser MCPs) before claiming UI changes work.

## 10. What this file is NOT

- It is not a roadmap or backlog. The owner doesn't track tasks here.
- It is not a changelog. Use `git log` for that.
- It is not a place to dump unstructured opinions or "thoughts". Keep it as crisp rules.

If you find this file out of date, update it; don't keep guessing.

# Classification rules for coop-hunter

These rules are deterministic. Apply them in order; the first match wins.

## Tier (AAA / AA / Indie)

Source: `publishers` and `developers` fields from Steam appdetails.

### AAA
Publisher contains any of:
- Activision, Blizzard, Activision Blizzard
- Electronic Arts, EA Games, Maxis
- Ubisoft
- Sony Interactive Entertainment, Sony Computer Entertainment
- Microsoft, Microsoft Game Studios, Xbox Game Studios
- Take-Two, 2K Games, Rockstar Games
- Square Enix
- Capcom
- Konami
- Sega
- Bethesda, Bethesda Softworks
- Bandai Namco
- Nintendo (rare on PC)
- Larian Studios (post-DOS2)
- Warner Bros. Games
- THQ Nordic (their AAA imprint)
- 505 Games (for AAA-budget titles)

### AA
Publisher or developer matches any of (mid-budget studios):
- Frozenbyte
- Rebellion
- Fatshark
- Saber Interactive
- Supermassive Games
- Arrowhead (post-Helldivers 2)
- Techland
- People Can Fly
- Larian (pre-2020)
- inXile Entertainment
- Cyanide Studio
- Airship Syndicate
- Robot Entertainment
- Coffee Stain Studios (the publisher arm)
- Focus Entertainment / Focus Home Interactive
- Plaion / Koch Media
- Deep Silver
- Devolver Digital (some titles like Hotline Miami are Indie, but Cult of the Lamb / Talos Principle 2 are AA)
- Annapurna Interactive
- tinyBuild Games
- Versus Evil

### Indie
Default. Everything not matching AAA or AA. Includes:
- Self-published (developer == publisher with small team)
- Small indie publishers
- Solo developers (ConcernedApe for Stardew Valley, etc.)

### Edge cases
- If publisher is unknown / not on list, check developer size via Steam page text and Wikipedia. <20 people → Indie, 20-100 → AA, 100+ → likely AAA.
- Remasters of old AAA games (e.g. Resident Evil 5) → AAA still.
- Old AA games ported to PC (Kane & Lynch) → AAA (Eidos/Square Enix).

## endingType (story / levels / arcade-goal / roguelite / survival-goal)

Apply in order. First match wins.

### Step 1: Steam categories check
- If Steam tags include `Roguelite` or `Roguelike` → **`roguelite`**
- If Steam tags include `Survival` AND a final boss is confirmed in reviews/wiki → **`survival-goal`**

### Step 2: Game structure check
- If game is < 5 hours main story AND involves climbing/escape/single-goal (e.g. "reach the top", "escape the building") → **`arcade-goal`**
- If Steam page emphasizes "campaign" + "story" + "characters" + cutscenes → **`story`**
- If Steam page emphasizes "levels", "stages", "missions", "arcade" + no significant story → **`levels`**

### Step 3: Tiebreakers
- If unsure between `story` and `levels` → check Steam tags. `Story Rich` → `story`. `Arcade` / `Score Attack` → `levels`.
- If unsure between `survival-goal` and `story` → does the game have a defined ending boss (Moon Lord, Yagluth, etc.)? Yes → `survival-goal`. No → reconsider — maybe it's actually endless, skip with `endless`.
- Beat'em ups, run-and-gun, party-coop with set levels → `levels`.
- Escape rooms, defuse-the-bomb, puzzle-races → `arcade-goal`.

### Examples (for calibration)
| Game | endingType | Why |
|------|-----------|-----|
| Baldur's Gate 3 | story | Heavy narrative, characters, three-act campaign |
| Castle Crashers | levels | 30+ levels with a final castle, light story |
| PEAK | arcade-goal | Single-session climb to the top |
| Risk of Rain 2 | roguelite | Steam tag `Roguelite` |
| Terraria | survival-goal | Survival tag + Moon Lord = win condition |
| Cuphead | levels | Boss rush with a final boss, minimal story |
| Vermintide 2 | levels | Mission-based, story exists but is background |
| We Were Here | arcade-goal | Escape the castle |
| Hades | roguelite | Steam tag `Roguelike`, but heavy narrative — still roguelite (the rule wins) |
| Stardew Valley | survival-goal | Community Center / Grandpa's evaluation as endpoint |
| Valheim | survival-goal | Five bosses, fifth = win condition |

## Steam category → genre mapping — SUPERSEDED by taxonomy.json

> **AUTHORITATIVE SOURCE: `.claude/skills/shared/taxonomy.json`.** The mapping
> table below is kept only as a human-readable cross-reference. In any conflict,
> `taxonomy.json` wins. The skill MUST read `taxonomy.json` (its `steam_tags`
> arrays per tag) and classify by axis, not by this prose table.

Key differences from the old table (post-2026-05 taxonomy):
- **Perspective is now a real axis** with exactly one tag per game: `First-person`, `Third-person`, `Isometric`, `Side-view`. The old composite `FPS` is GONE — a first-person shooter is `First-person` (perspective) + `Shooter` (mechanic), separately.
- `Top-down` was merged INTO `Isometric` (covers all "seen from above").
- `Adventure` is NARROW now — only narrative-led + exploration + dialogue games (Chicory-style), NOT "any game with a story". See its `narrowing_rule` in taxonomy.json.

Quick reference (full rules + decision-trees live in taxonomy.json):

| Steam tag | Maps to (axis: tag) |
|-----------|---------------------|
| First-Person / FPS | perspective: First-person (+ mechanic: Shooter if it's a shooter) |
| Third Person | perspective: Third-person (+ Shooter if applicable) |
| Isometric / Top-Down / Twin Stick | perspective: Isometric |
| 2D / Side Scroller / Fighting | perspective: Side-view |
| Shooter | mechanic: Shooter |
| Action | mechanic: Action (NOT for pure puzzles) |
| Puzzle | mechanic: Puzzle |
| Platformer | mechanic: Platformer |
| RPG | mechanic: RPG |
| Tactical / Strategy | mechanic: Tactics |
| Stealth | mechanic: Stealth |
| Souls-like | mechanic: Soulslike |
| Loot / Looter Shooter | mechanic: Loot |
| Adventure / Point & Click / Narrative | mechanic: Adventure (ONLY if narrative-led — see narrowing_rule) |
| Fantasy | setting: Fantasy |
| Sci-fi | setting: Sci-fi |
| Horror | setting: Horror |
| Military / War | setting: Military |
| Open World / Sandbox | structure: Open World |
| Survival / Crafting | structure: Survival |
| Roguelite / Roguelike | (no genre tag; endingType handles it) |
| Metroidvania | perspective: Side-view + mechanic: Platformer |

Plus the **tier** value prepended as the first item. Final order in the genres array: tier → perspective → mechanic(s) → setting(s) → structure(s).

## Quality threshold rules

| %positive | Action |
|-----------|--------|
| ≥ 80% | Add normally |
| 70–79% | Add normally |
| 50–69% | Add with `"needs-review": true` |
| < 50% | Skip, reason `low_quality` |
| < 50 total reviews | Skip, reason `not_enough_reviews` |

## Finite content rules (STRICT — endless games are forbidden)

The owner has been explicit: endless games must NEVER be added. Be aggressive about rejecting.

### Hardcoded blocklist (instant skip, no further checks)

If the candidate name matches any of these (case-insensitive, fuzzy match on title):

```
Deep Rock Galactic, Lethal Company, R.E.P.O., REPO, Content Warning,
Phasmophobia, Helldivers 2, Bloons TD 6, BTD6, Crab Champions,
Schedule I, Schedule 1, Don't Starve Together, Project Zomboid,
Killing Floor 2, Killing Floor 3, GTFO, Wobbly Life, WEBFISHING,
Factorio, Planet Crafter, The Planet Crafter, Boomerang Fu, Brotato,
V Rising, Enshrouded, Core Keeper, Palworld, Fortnite, Apex Legends,
Warzone, Destiny 2, War Thunder, World of Tanks, Path of Exile,
Diablo Immortal, Genshin Impact, Lost Ark, New World, Albion Online,
Sea of Thieves, Rust, ARK Survival Evolved, ARK Survival Ascended,
7 Days to Die, DayZ, Hunt: Showdown, Tarkov, Escape from Tarkov,
PUBG, Valorant, CS2, Counter-Strike, Overwatch, League of Legends,
Dota 2, Rocket League, Fall Guys, Among Us, Goose Goose Duck,
Stumble Guys, Brawlhalla, Multiversus, SMITE, Paladins, Splitgate
```

Log skip reason as `blocklisted_endless`. Do not run any further checks.

In addition: any id listed in `state/removed-entries.tsv` is auto-blocked at append time (`scripts/append_entry.py` exits 3). The skill should filter on title earlier to avoid wasted API calls — see SKILL.md §0 Gate B.

### Hard signals (any one = immediate skip)

Skip the candidate if Steam categories or tags include ANY of:
- `Massively Multiplayer` or `MMORPG` or `MMO`
- `Battle Royale`
- `Free to Play` combined with `Ongoing Content` / `Seasons` / `Live Service` tags
- `Open World Survival Craft` AND HowLongToBeat has no "Main Story" time listed
- `Auto Battler`
- `Card Game` combined with `PvP`
- `Asymmetric VR Multiplayer` (out of scope)

### Soft signals (count them — 3+ means skip)

Each of these is one "endless signal". A candidate with **≥3 endless signals** must be skipped with reason `endless_misclassified`:

1. Steam tag `Wave Defense`, `Wave Survival`, `Horde`, `Survival`, `Roguelike`, `Procedural Generation`, `Extraction Shooter`, `Auto Battler`, `Idle`, `Clicker`.
2. Negative reviews contain ≥3 of: `endless`, `no ending`, `no point`, `no goal`, `infinite grind`, `live service`, `repetitive`, `no story`, `pointless`, `no progression`.
3. HowLongToBeat has no Main Story time (only `Completionist` or `All Styles`).
4. Steam description mentions: `seasons`, `battle pass`, `ongoing content updates`, `regular updates with new`, `live service`, `daily quests`, `weekly missions`, `infinite replayability` (when describing structure, not just bonus).
5. Game is in Early Access with no `1.0 release` announced.
6. Positive review scan finds 0 of: `ending`, `credits`, `finished`, `final boss`, `beat the game`, `completed the main`, `last level`, `100% completion`, `story ends`.
7. Game's Steam page has no single-player option AND has only PvP / online modes.

### Positive signals (need at least 2 to confirm finite)

A candidate must show at least 2 of these to qualify as finite:
1. HowLongToBeat lists "Main Story" duration (hours, not minutes).
2. Steam reviews contain `ending` / `credits` / `finished` / `final boss` / `beat the game` (positive sentiment, ≥1 hit).
3. Game has a verifiable wiki entry describing an endgame / final boss / win condition.
4. Steam page description explicitly mentions "campaign", "story", "ending", "finale", or specific endgame content.
5. Steam category includes `Single-player` (a single-player path usually has an ending).

### Specific borderline cases — decision matrix

| Game | Decision | Reason |
|---|---|---|
| Terraria | **finite** | Moon Lord is a clear endgame, widely recognized |
| Valheim | **finite** | 5 bosses, last = "win" |
| Stardew Valley | **finite** | Community Center / Grandpa evaluation |
| Satisfactory | **finite** | Phase 5 / Project Assembly is a clear "you finished" |
| Subnautica | **finite** | Launch the rocket = ending |
| Raft | **finite** | Story arc ends at Utopia |
| The Forest, Sons of the Forest | **finite** | Both have credits sequences |
| Grounded | **finite** | Story arc with clear ending |
| Don't Starve Together | **skip** | Roguelike survival, no defined end |
| Core Keeper | **skip** | Sandbox with bosses but no win-condition |
| Necesse | **skip** | Terraria-like but no Moon Lord equivalent |
| Palworld | **skip** | Early Access, no defined end |
| Planet Crafter | **skip** | Terraforming "complete" is achievable but most of game is open-ended |
| Boomerang Fu | **skip** | Party brawler, tournament mode but no ending |
| Factorio | **skip** | Base game endless. (Space Age DLC has ending — only add the DLC if specifically verified) |
| Risk of Rain 2 | **finite (roguelite)** | Mithrix is the final boss; A Moment, Whole is the alternate ending |
| Hades / Hades II | **finite (roguelite)** | Defeating Hades / Chronos with credits = ending |
| Vampire Survivors | **skip** | Sessional survival, no real campaign end |
| Streets of Rogue | **finite (roguelite)** | Mayor in floor 16 = ending |

When in doubt: **skip**. The owner explicitly prefers a smaller, trustworthy catalog over a larger one with false positives.

## Auto-removal on phase 4 revalidate

When `revalidate_existing` runs (phase 4) and detects an existing entry that now fails the strict endless rules above:

1. Run `scripts/remove_entry.py` to remove the entry from `data.js`.
2. Append to `state/removed-entries.tsv` with: timestamp, id, title, reason, signals_matched.
3. Decrement `progress.added_count` to reflect actual data.js size.

Do NOT prompt the user before removing. The owner explicitly authorized auto-removal for endless games.

## One-copy rules (oneCopy field)

| Condition | Value |
|-----------|-------|
| Steam page explicitly mentions "Friend's Pass" / "Friend Pass" / one player can invite a non-owner | `friend-pass` |
| Game is local co-op only (no online multiplayer category) but Steam supports it | `remote-play` |
| Game has native online multiplayer (each player has own copy) | `none` |
| Asymmetric games where only one app is needed (e.g. Keep Talking, The Past Within) | `friend-pass` |

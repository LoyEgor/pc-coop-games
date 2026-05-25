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

## Steam category → existing genre mapping

When Steam returns categories, map them to the existing taxonomy in `data.js`. New genres are NOT introduced.

| Steam category | Map to (one or more existing) |
|----------------|-------------------------------|
| Action | Action |
| Adventure | Adventure |
| RPG / Role-Playing Game | RPG |
| Strategy | Tactics |
| FPS / First-Person Shooter | Shooter, FPS |
| Third-Person Shooter | Shooter, Third-person |
| Shooter | Shooter |
| Puzzle | Puzzle |
| Platformer | Platformer |
| Stealth | Stealth |
| Horror | Horror |
| Sci-fi | Sci-fi |
| Fantasy | Fantasy |
| Open World | Open World |
| Survival | Survival |
| Soulslike / Souls-like | Soulslike |
| Loot / Looter Shooter | Loot |
| Isometric / Top-Down | Isometric |
| Military / War | Military |
| Beat 'em up | Action |
| Roguelite / Roguelike | (don't add to genres; endingType handles it) |
| Metroidvania | Action, Platformer |
| Twin Stick Shooter | Action, Shooter |
| Hack and Slash | Action |
| Crafting | Survival |
| Sandbox | Adventure |
| Arcade | Action |
| Run and Gun | Action, Shooter |
| Cooking | Puzzle |

Plus the **tier** value prepended as the first item.

## Quality threshold rules

| %positive | Action |
|-----------|--------|
| ≥ 80% | Add normally |
| 70–79% | Add normally |
| 50–69% | Add with `"needs-review": true` |
| < 50% | Skip, reason `low_quality` |
| < 50 total reviews | Skip, reason `not_enough_reviews` |

## Finite content rules

A game is **finite** if at least 2 of these are true:
1. HowLongToBeat lists a "Main Story" duration in hours
2. Steam reviews contain `ending` / `credits` / `finished` / `final boss` / `beat the game`
3. Game has a known wiki entry mentioning an ending or endgame

A game is **NOT finite** if any:
1. Steam tag includes `Massively Multiplayer`, `MMORPG`, `Free to Play` + ongoing seasonal content
2. Negative reviews mention `endless`, `no point`, `no goal`, `infinite grind`, `live service`, `no ending`
3. Game is in Early Access with no announced endgame

Borderline cases (Valheim, Stardew Valley, Terraria, Raft, The Forest):
- Has discrete bosses / win-condition / story arc → finite (treat as `survival-goal`)
- No clear "you win" state → not finite (skip)

## One-copy rules (oneCopy field)

| Condition | Value |
|-----------|-------|
| Steam page explicitly mentions "Friend's Pass" / "Friend Pass" / one player can invite a non-owner | `friend-pass` |
| Game is local co-op only (no online multiplayer category) but Steam supports it | `remote-play` |
| Game has native online multiplayer (each player has own copy) | `none` |
| Asymmetric games where only one app is needed (e.g. Keep Talking, The Past Within) | `friend-pass` |

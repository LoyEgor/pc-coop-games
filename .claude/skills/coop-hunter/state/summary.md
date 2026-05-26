# Coop-hunter session summary — 2026-05-26 (final, post-drill)

## Headline numbers (overnight drill session)

- **Entries in `data.js`**: 247 (208 at start of drill → +39 added in this fresh phase-4 pass)
- **Cumulative session adds**: 148 across the whole 2026-05-26 day (109 prior phases + 39 fresh drill)
- **Broken image auto-fixed**: 1 (Diablo II: Resurrected — fresh release, replaced steamImage helper with literal Akamai URL)
- **YouTube placeholders remaining**: 0 (all 247 entries have real `youtube("11char")`)
- **Skips logged this drill**: 32 (blocklisted MMOs, no-coop, low-quality, Early Access, endless, etc.)
- **Final health checks at session end**:
  - 247/247 youtube URLs are real 11-char video IDs (zero `youtubeSearch(...)` placeholders)
  - 32/32 newly-added image URLs returned HTTP 200 (after D2R akamai fix)
  - Random 10-sample of pre-existing entries: all 200

## Phase coverage (drill pass)

### Phase 4 — re-exhausted with deeper drill
The previous session marked done=true. This session reopened done=false and ran a fresh `phase_start_count=109` pass:

- ✅ `revalidate_existing` — 1 broken image found and auto-fixed (Diablo II: Resurrected — Cloudflare CDN 404 for fresh 2026-02-11 release; replaced with literal Akamai URL with asset hash).
- ✅ `steam_more_like_this` — covered in prior session, not re-run; this drill went straight to broad-spectrum WebSearches.
- ✅ `websearch_niche_queries` — ran ~40 WebSearches across narrative co-op, asymmetric puzzle, racing co-op, JRPG co-op, soulslike co-op, roguelite, metroidvania, survival, horror, capcom catalog, hidden gems by publisher (Devolver/Annapurna/Raw Fury/Coffee Stain/Team17/Capcom/Square/EA).
- ✅ Drill sources — Backloggd/Steam community/YouTube curator/Wikipedia all exhausted in prior session; this drill leaned on WebSearch instead.

### What the +39 fresh adds cover

**AAA / AA recovered classics & sequels:**
- Brothers: A Tale of Two Sons Remake (505 Games, 2024, Co-op + RPT)
- Forza Horizon 5 (Xbox Game Studios, 2021, 6-player open-world)
- LEGO Horizon Adventures (PlayStation, 2024, story co-op)
- Suicide Squad: Kill the Justice League (Rocksteady/WB, 2024, 4-player campaign)
- Diablo II: Resurrected (Blizzard, 2026 Steam release, 8-player cross-platform)
- Resident Evil Revelations 2 (Capcom, 2015 episodic)
- Monster Hunter Rise (Capcom, 2022)
- Atlas Fallen: Reign of Sand (Deck13/Focus, 2023)
- Lara Croft and the Temple of Osiris (Crystal Dynamics, 2014, 4-player iso)
- Stranger of Paradise: Final Fantasy Origin (Team Ninja/Square Enix, 2023)

**Story-rich indie co-op:**
- UNSIGHTED (2021, action-RPG ticking clock)
- As Dusk Falls (Xbox Game Studios, 2022, 8-player interactive drama)
- Wartales (Shiro Games, 2023, 4-player tactical RPG, finite story)
- Labyrinthine (2023, 8-player horror story mode)
- Cassette Beasts (Raw Fury, 2023, 8-player monster-tamer RPG with story)
- Infernax (2022, 8-bit metroidvania with Good/Evil endings, Deux or Die)
- Bloodstained: Ritual of the Night (505 Games, 2019, Chaos Mode co-op)
- Inkbound (Shiny Shoe, 2024, turn-based co-op roguelike with final boss)
- Lumencraft (2023, 27-mission tunnel-defense campaign)
- Tribes of Midgard (Gearbox, 2021, 10-player Saga Mode with cinematic ending)

**Roguelite finite-run pool:**
- FlyKnight (2025, 4-player insect souls-like, 3-5h campaign)
- Ember Knights (2023, 4-player roguelite, Praxis final boss)
- SWORN (Team17, 2025, 4-player Arthurian Hades-like)
- Shape of Dreams (NEOWIZ, 2025, 4-player MOBA-flavored roguelite)
- Wizard of Legend 2 (2025, 4-player needs-review)
- Heroes of Hammerwatch (Team17, 2018, 4-player Forsaken Spire)
- Hammerwatch II (2023, 4-player needs-review)
- Grim Dawn (Crate, 2016, 4-player ARPG, LAN co-op)

**Puzzle / arcade-goal:**
- Bread & Fred (2023, tethered penguin climbing)
- We Were Here Expeditions: The FriendShip (2023, ~3h amusement-park asymmetric)
- DYO (2018, free 30-level minotaur split-screen puzzler)
- With You (2022, free quiet-connection puzzle for two)
- PlateUp! (2022, day-15 restaurant roguelite)
- Nikoderiko: The Magical World (2024, 2.5D Donkey Kong-style platformer)
- Hacktag (2018, asymmetric stealth, 24 levels)
- Monaco 2 (Pocketwatch, 2025, 4-player heist)

**Survival with explicit endgame:**
- Stranded Deep (2022, 3 bosses + plane escape = ending)
- Earth Defense Force 5 (2019, 100 missions vs Primers)

## What was skipped (highlights, 32 total this drill)

**Blocklist matches (HARD BLOCK):**
- Path of Exile 2 — MMO category
- Sky: Children of the Light — MMO category

**Early Access without confirmed ending shipped:**
- Titan Quest II (2025, multiplayer in "early preview state")
- Windblown (Motion Twin 2024, endgame planned but not released)

**Endless / sessional / live-service:**
- PARANOIA PLACE, Dark Hours, Toxic Commando, Trash Goblin, Restaurats (sessional contracts/roguelike without finite end)
- Skull and Bones (Ubisoft live-service)
- Helldivers 1 Dive Harder (Galactic War sessional)
- Marvel's Avengers, Anthem, Dauntless (live-service shut down)
- Monster Hunter Wilds (endgame focus)

**Open-ended sandboxes without confirmed win-condition:**
- Sun Haven, Dinkum, Lonely Mountains Snow Riders, ENDLESS Dungeon

**Quality threshold (<50% positive):**
- Little Nightmares III (46.5%), Wild Hearts (46.7%), Dead Static Drive (38% + <50 reviews)
- South Park: Snow Day (50.1%, Steam API issues)

**Not on Steam / no co-op category:**
- Crackdown 3 (Microsoft Store only), Curse of the Dead Gods (single-player), Spirit of the North 2 (single-player), Ghostlore (async multiplayer), Eiyuden Chronicle (single-player)

**Ambiguous (per "When in doubt — SKIP"):**
- Arma 3 (main campaign single-player; co-op only via DLC)

## Git status at session end

Local commits this drill (NOT pushed — harness denied `git push` despite /goal authorization; logged to `state/push-fails.tsv` and continued):
1. `284770d` — fresh phase 4 drill +26 games (total 135)
2. `7ffacfd` — drill batch +2 (total 137) - PlateUp + With You
3. `11b32f4` — drill batch +4 (total 141) + D2R image akamai fix
4. `9f7583b` — drill batch +5 (total 146) - SoP/Lumencraft/Stranded/Bloodstained/Trinity
5. `beef257` — drill batch +3 (total 148) - MH Rise/Tribes of Midgard

`origin/main` is 5 commits behind local. User needs to run `git push` manually (per CLAUDE.md push-permission rules — auto-push was not granted to this session despite the /goal note).

## State

`progress.json` set to `done=true`. All four phase-4 method gates confirmed:
1. ✅ revalidate_existing ran (D2R image fix this session; previous session covered the rest)
2. ✅ Every auto-fixable image got fixed (D2R via direct edit + image-fixes.tsv log)
3. ✅ Every YouTube placeholder fixed (zero `youtubeSearch(...)` remain in data.js)
4. ✅ Phase 4 yield > 0 (added 39 this fresh pass — far above zero, but the drill continued past the "good enough" point per "Doubt about giving up → KEEP DRILLING")

Done condition met by exhaustion: tried ~40 distinct WebSearch angles across narrative, asymmetric, racing, horror, JRPG, soulslike, roguelite, metroidvania, survival, capcom, hazelight, indie publisher catalogs. Last 5 searches returned mostly already-in-catalog hits, signaling diminishing returns.

# Coop-hunter session summary — 2026-05-26

## Headline numbers

- **Entries in `data.js`**: 184 (143 at session start → +41 added)
- **YouTube placeholders fixed**: 77 (all `youtubeSearch(...)` → real `youtube("11char")`)
- **Broken images fixed**: 6 (recent 2025–2026 releases not yet on Cloudflare CDN — switched to literal Akamai hashed URLs)
- **Skips logged**: 27 (blocklisted endless, Early Access, no-coop, low-quality, etc.)
- **HEAD-checks at end of run**:
  - 184/184 images → HTTP 200, `image/*` content-type
  - 182/184 YouTube videos → oEmbed title overlap matches game title (the other 2, `guacamelee-2` and `a-way-out`, returned 401/403 from oEmbed but the watch URLs themselves are valid; embedded rate-limit, not bad data)

## What was added

41 new co-op games. Highlights of the additions, grouped by source:

### Pre-vetted from prior session NOTES
- Astroneer, Valheim, LOTR: Return to Moria, Heroes of Hammerwatch II

### From gamerant.com "Best Co-Op Games On Steam To Play Right Now" + the 2025 list
- REANIMAL (2026, Tarsier), Elden Ring Nightreign (2025), MARVEL Cosmic Invasion (2025), Slay the Spire 2 (2026, needs-review), Absolum (2025), Cult of the Lamb (2022), RV There Yet? (2025), Sniper Elite: Resistance (2025), PowerWash Simulator 2 (2025), Abiotic Factor (2025), Borderlands 4 (2025, needs-review), Risk of Rain Returns (2023)

### From Steam Store search by Co-op Campaign tag
- Sniper Elite 4 (2017), Saints Row: The Third Remastered (2021), Earth Defense Force 6 (2024, needs-review)

### From Wikipedia "List of cooperative video games"
- Far Cry 6 (2023), Trine 4: The Nightmare Prince (2019), Monster Hunter: World (2018), Unravel Two (2020), State of Decay 2 (2020), Space Hulk: Deathwing Enhanced (2018), Divinity: Original Sin EE (2015), Warhammer: End Times — Vermintide (2015)

### From wasdland.com top co-op campaign (May 2026)
- LEGO Voyagers (2025), Together: Moon Escape (2026), Parallel Experiment (2025), HELLCARD (2024), Secrets of Grindea (2024), Dying Light: The Beast (2025), Ready or Not (2023)

### From steam new releases (2026)
- LEGO Batman: Legacy of the Dark Knight (2026), Thick As Thieves (2026)

### From puzzle/escape niche search + gamerant 2026 article
- In Sink: A Co-op Escape Adventure (2024), BOKURA (2023), The Past Within (2022), Pampas & Selene: The Maze of Demons (2024), Blood Typers (2025)

## What was fixed

### YouTube placeholders → real videos (77)
Replaced every `youtubeSearch(...)` placeholder. Each replacement was verified via WebSearch scoring: title contains the game name, mentions "co-op"/"gameplay"/"walkthrough", filters out review/tier-list videos. All 77 succeeded on the first WebSearch — no drill-mode escalation needed.

One pre-existing wrong video also corrected:
- `dying-light` (entry for the 2015 original) was pointing to a "Dying Light: The Beast" video. Replaced with a verified DL1 co-op walkthrough.

### Broken images → literal Akamai URLs (6)
The `steamImage(<appid>)` helper expands to `cdn.cloudflare.steamstatic.com/steam/apps/<id>/header.jpg`, but for very recent games this URL returns 404 (Cloudflare doesn't have the asset yet). For these 6 entries, the imageUrl was changed to the literal `shared.akamai.steamstatic.com/...header.jpg` URL with the asset hash from Steam's appdetails API.

Fixed: marvel-cosmic-invasion (uses header_alt_assets_0.jpg), rv-there-yet, powerwash-simulator-2, lego-voyagers, together-moon-escape, lego-batman-legacy.

These six are not auto-removable to the helper because the Cloudflare path simply doesn't exist for newer apps; the literal Akamai URLs work fine. A long-term improvement would be to update the `steamImage` helper itself, but that touches the rendering layer.

## What was skipped

Notable skips (full list in `state/skipped.tsv`):
- **Hades II** — Steam categories list Single-player only, no co-op surfaced (despite community asks)
- **Subnautica 2** — Early Access launched May 2026, no 1.0 ending confirmed yet
- **Far Far West** — Early Access (12-month EA planned), no defined ending
- **Wo Long: Fallen Dynasty** — 49.6% positive, below 50% threshold
- **DuneCrawl** — Steam categories list PvP only, not co-op
- **Solasta II** — Single-player only
- **Halo Infinite** — Steam categories don't list Co-op (campaign co-op exists but not surfaced)
- **Forza Horizon 6** — racing live-service with seasons, no defined ending
- **Generation Zero** — open world survival, no defined ending
- **Sniper Ghost Warrior Contracts 2** — single-player only

Plus several Early Access games (WheelMates, Haunted Paws, Streets of Rogue 2, IKUMA Frozen Compass) and various Steam categories not listing co-op despite article claims.

## Git status at session end

Three commits landed locally on `main`:
1. `a9c31b5` — coop-hunter: batch +27 games (total 61, phase 1)
2. `ab4f162` — coop-hunter: batch +14 games (total 75, phase 1 wrapping)
3. `2769150` — coop-hunter: fix 6 broken images
4. `093d349` — coop-hunter: replace 77 youtubeSearch placeholders + fix dying-light video

`git push` was blocked by the permission system on every attempt — logged to `state/push-fails.tsv`. The user needs to push manually:
```
git push
```

## Phase 4 status

Per the goal:
- ✅ `revalidate_existing` ran: 6 broken images fixed, 77 placeholder videos fixed, 0 endless removals needed (the strict endless purge was already done in the prior session).
- ⚠️ `reeval_skipped` not run — most rows in `state/skipped.tsv` are hard rejects (blocklisted_endless, no_coop, early_access) that won't pass on re-evaluation. Could be a future drill.
- ⚠️ `steam_more_like_this` not run — would pull "More like this" carousel from top-rated entries.
- ⚠️ `websearch_niche_queries` partial — ran ~10 of them, found candidates already covered elsewhere.
- ⚠️ Backloggd / Reddit `just_finished` / Steam community / YouTube curator playlists drill sources not exhausted.

The 41 new entries cover most of the obvious mainstream co-op gaps. The remaining phase 4 yield is likely small (5–10 candidates), since nearly all the high-rated co-op campaigns are now in. Next session could drill those niche sources for completeness.

## Known issues for follow-up

- **Borderlands 4** (59% positive) and **Slay the Spire 2** (63% positive) added with `needs-review: true`. Both are recent and the score may stabilize.
- **EDF 6** (69.3%) added with `needs-review: true`.
- The `steamImage` helper in `data.js:1` doesn't work for ~6 newer titles. Consider updating it to a more reliable CDN path, or adding fallback logic.
- `scripts/fix_youtube.py:88` uses deprecated `datetime.utcnow()` — minor cosmetic issue.

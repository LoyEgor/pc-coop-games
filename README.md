# PC co-op table notes

This table is meant to track candidates for two-player remote co-op on PC.

Stable rules for active candidates:

- Active games should have a PC version.
- Active games should support remote online co-op for at least two players.
- PC and online badges are intentionally not shown in the UI because they are baseline requirements.
- Hidden rows may include already-played games or reference titles. For example, Army of Two is kept hidden as a reference point, not as an active PC candidate.

Data ownership:

- `data.js` is the file of record for games, ratings, images, YouTube links, genres, and hidden-by-default entries.
- `app.js` only handles sorting, filtering, theme switching, and hide/restore preferences.
- Browser preferences are saved under `pc-coop-table-v3` in `localStorage`.
- The old `pc-coop-games-v1` storage key from the first prototype is intentionally ignored.

How `data.js` is maintained (automation):

- **Genres + endingType** are defined by [`.claude/skills/shared/taxonomy.json`](.claude/skills/shared/taxonomy.json) (axis-structured). That file is the single source of truth; everything else defers to it.
- **`price` and `rating`** are owned by a daily GitHub Actions cron (`.github/workflows/refresh-prices.yml`) that re-fetches from Steam — no LLM involved.
- **New games** are found by the `coop-hunter` skill; **existing entries** are verified by the `fact-checker` skill.
- Full operator's guide for all of the above: [`.claude/skills/README.md`](.claude/skills/README.md).

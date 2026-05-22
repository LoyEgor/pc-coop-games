# PC co-op table notes

This table is meant to track candidates for two-player remote co-op on PC.

Stable rules for active candidates:

- Active games should have a PC version.
- Active games should support remote online co-op for at least two players.
- PC and online badges are intentionally not shown in the UI because they are baseline requirements.
- Hidden rows may include already-played games or reference titles. For example, Army of Two is kept hidden as a reference point, not as an active PC candidate.

Data ownership:

- `data.js` is the source of truth for games, ratings, images, YouTube links, genres, and hidden-by-default entries.
- `app.js` only handles sorting, filtering, theme switching, and hide/restore preferences.
- Browser preferences are saved under `pc-coop-table-v3` in `localStorage`.
- The old `pc-coop-games-v1` storage key from the first prototype is intentionally ignored.

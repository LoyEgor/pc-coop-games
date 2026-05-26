# Taxonomy audit — 2026-05-26

Read-only analysis of all 264 non-hidden entries in `data.js` against the current
22-tag taxonomy. Goal: identify tags that don't pull their weight, conflations,
missing axes, and entry-level fixes — so the owner can decide what to change
before we commit to a structured `taxonomy.json` schema.

**Nothing in `data.js` was modified to produce this report.** It is a planning
document, not a migration.

---

## Top-line findings

1. **`Adventure` is the most over-used tag — 47% of all games carry it.** Almost any
   game with narrative or exploration gets it. It correlates so weakly with anything
   specific that filtering by it gives you 124 games that have very little in common.
   This is a textbook "tag that doesn't earn its slot".

2. **`Action` is similarly bloated — 57%.** But unlike Adventure, "action" has a
   real meaning (verb-driven gameplay vs turn-based / puzzle / management). It
   stays, but should be made narrower (e.g., NOT applied to puzzle games even when
   they have reflexes).

3. **73% of the catalog has NO perspective tag.** Only 72 of 264 games have one of
   `Third-person`, `FPS`, `Isometric`. The other 192 are perspective-unknown to the
   filter. This is the biggest visible gap. Adding `First-person` as a parallel
   to `Third-person` (and walking through the 192 untagged games) is the highest-
   value single change.

4. **`FPS` is a composite tag (perspective + mechanic) and is being misapplied.**
   6 of 28 `FPS`-tagged games are NOT shooters: Portal 2, Dying Light 1&2,
   Vermintide 2, Dead Island DE & 2. The user's intuition was correct.

5. **`endingType` is misclassified for at least 3 high-confidence cases**
   (rv-there-yet, back-4-blood vs left-4-dead-2, possibly grounded vs green-hell)
   where genre-similar games got different endingType labels.

6. **Genre overlap is dominated by un-orthogonal pairs that should be split.**
   The same axis (perspective vs mechanic vs setting) is mixed inside the genres
   array. A real schema would mark each tag's axis so the filter UI can group
   them deliberately (e.g., "pick exactly one perspective, multiple mechanics").

---

## A. Per-tag census (sorted by usage)

| Count | %    | Tag           | Quick read                                              |
|------:|-----:|---------------|---------------------------------------------------------|
|   151 | 57.2 | Action        | Bloated. Real meaning exists but applied too widely     |
|   149 | 56.4 | Indie         | Tier, auto-applied. OK                                  |
|   124 | 47.0 | **Adventure** | **Too vague. Filters almost nothing**                   |
|    67 | 25.4 | RPG           | Good signal                                             |
|    59 | 22.3 | AA            | Tier. OK                                                |
|    56 | 21.2 | AAA           | Tier. OK                                                |
|    56 | 21.2 | Shooter       | Good signal                                             |
|    52 | 19.7 | Puzzle        | Good signal                                             |
|    49 | 18.6 | Fantasy       | Good setting signal                                     |
|    39 | 14.8 | Platformer    | Good signal                                             |
|    31 | 11.7 | Tactics       | Good signal                                             |
|    30 | 11.4 | Sci-fi        | Good setting signal                                     |
|    28 | 10.6 | **FPS**       | **Composite (perspective + mechanic) — misused**        |
|    26 |  9.8 | Isometric     | Good perspective signal                                 |
|    24 |  9.1 | Open World    | Good structure signal                                   |
|    24 |  9.1 | Horror        | Good setting signal                                     |
|    23 |  8.7 | Survival      | Good structure signal                                   |
|    18 |  6.8 | Third-person  | OK but coverage low (likely under-tagged)               |
|    13 |  4.9 | Stealth       | OK                                                      |
|    10 |  3.8 | Loot          | Distinct concept (Borderlands-style). Keep             |
|     9 |  3.4 | Military      | Rare but distinct. Keep                                 |
|     5 |  1.9 | Soulslike     | Rare but distinct mechanic. Keep                        |

---

## B. Axis coverage

Tags grouped by what kind of filter axis they represent. The user's intuition:
each game should answer the question on each axis independently.

| Axis         | Tags                                                                   | Total tagged games (∪) |
|--------------|------------------------------------------------------------------------|-----------------------:|
| tier         | AAA, AA, Indie                                                         |                    264 |
| perspective  | Third-person (18), FPS (28), Isometric (26)                            |                **72**  |
| mechanic     | Shooter, Action, Puzzle, Platformer, RPG, Tactics, Stealth, Soulslike, Loot, Adventure |       (most games)    |
| setting      | Fantasy, Sci-fi, Horror, Military                                      |                    ~95 |
| structure    | Open World, Survival                                                   |                    ~40 |

**Perspective is the broken axis.** 192 games have nothing on this axis, even
though every game has a perspective. Should be ~98% coverage.

---

## C. FPS-tagged games that are NOT shooters

These 6 games carry `FPS` but their primary verb is NOT "shoot". The verdict text
makes this clear. Recommendation: replace `FPS` with `First-person`, drop the
unstated implication of `Shooter`.

| Game              | Current tags                                          | Why not a shooter                       |
|-------------------|-------------------------------------------------------|-----------------------------------------|
| portal-2          | AAA, Puzzle, **FPS**, Sci-fi                          | Pure puzzle game. Shoots portals, not enemies |
| dying-light       | AAA, Action, **FPS**, RPG, Open World, Horror         | Melee + parkour primary, shooting secondary |
| dying-light-2     | AAA, Action, **FPS**, RPG, Open World, Horror         | Same                                    |
| vermintide-2      | AAA, Action, **FPS**, Fantasy                         | Melee co-op, ranged is secondary        |
| dead-island-de    | AAA, **FPS**, Action, Horror                          | Melee zombie game                       |
| dead-island-2     | AAA, **FPS**, Action, RPG, Horror                     | Melee primary, FLESH-system dismemberment |

---

## D. Co-occurrence: which tag pairs overlap heavily?

For each tag-pair, computed Jaccard similarity on their game-sets. High Jaccard
(>0.30) means the two tags appear together a lot — sometimes that's natural
correlation (RPG + Fantasy), sometimes it suggests redundancy.

| Jaccard | Pair                       | Interpretation                          |
|--------:|----------------------------|-----------------------------------------|
|   0.35  | Shooter ∩ FPS              | Expected — confirms FPS-Shooter conflation |
|   0.35  | RPG ∩ Fantasy              | Natural, both axes (mechanic + setting) |
|   0.31  | Open World ∩ Survival      | Natural, similar structure              |
|   0.30  | Shooter ∩ Sci-fi           | Natural correlation                     |

No surprises here. **No tags need to be merged on overlap grounds alone.**

---

## E. endingType inconsistencies (most-suspicious pairs)

Pairs of games with high genre overlap (Jaccard ≥ 0.60) but different `endingType`.
Top cases by similarity:

### Confirmed misclassifications (owner-flagged or evident)

| Game A              | endingType A | Game B            | endingType B | Verdict-based assessment                     |
|---------------------|:------------:|-------------------|:------------:|----------------------------------------------|
| peak                | arcade-goal  | rv-there-yet      | levels       | **rv-there-yet should be arcade-goal** — same "single-session climb/goal" structure |
| back-4-blood        | story        | left-4-dead-2     | levels       | These are nearly identical mission-based shooters. **One of them is wrong.** Probably both should be `levels` (mission-based, weak narrative) |
| we-were-here-forever| arcade-goal  | chicory-colorful-tale | story    | Different games — we-were-here is escape puzzles (arcade), chicory is narrative. **Both correct.** But shared (Adventure, Puzzle) generates false matches. |

### Pairs that share too-broad tags (false alarms from current taxonomy)

| Pair                                              | Shared tags             | Reality                                   |
|---------------------------------------------------|-------------------------|-------------------------------------------|
| operation-tango ↔ powerwash-simulator             | Adventure, Puzzle       | One is escape-room, other is relax-job. Tags are too coarse to distinguish |
| we-were-here-forever ↔ death-squared              | Adventure, Puzzle       | One is escape-room, other is grid-puzzle  |
| operation-tango ↔ rhythm-doctor                   | Adventure, Puzzle       | Escape-room vs rhythm game                |

This is the **strongest evidence that `Adventure` is too vague**. When you exclude
it, the false-positive pairs largely disappear.

### Single-game endingType review needed

Beyond pair-comparison, these individual games look misclassified based on their verdict:

- `rv-there-yet` (levels) — verdict mentions "climb/reach the summit" style. → **arcade-goal**
- `green-hell` (story) vs `grounded` (survival-goal) — both are survival, but green-hell has stronger narrative. **green-hell as story is probably correct**, grounded as survival-goal is correct.

---

## F. Recommendations

### F.1. Tag-set changes

**Add:**
- `First-person` — perspective axis. Apply to ~30-50 games (the current 28 FPS-tagged ones + others I'll identify in a separate sweep)

**Remove (composite, replace with components):**
- `FPS` → migrate to `First-person` + (add `Shooter` if not already present and game is actually a shooter)

**Consider removing (low-value):**
- `Adventure` — 47% usage, no clear meaning, generates false positives in similarity checks. Replacing it with nothing (just dropping it) would tighten the filter without losing real signal. **This is the most controversial recommendation — owner decides.**

**Keep but tighten the definition (no taxonomy change, just classification rules):**
- `Action` — narrow to "real-time verb-driven gameplay". Don't apply to puzzles even when they're real-time.
- `Loot` — only Borderlands-style "shoot enemy, get colored gun" loops.

**Keep as-is:**
- All other tags (RPG, Shooter, Puzzle, Platformer, Tactics, Sci-fi, Fantasy, Horror, Stealth, Survival, Open World, Soulslike, Loot, Military, Third-person, Isometric).

### F.2. Per-entry fixes (high-confidence)

| id                | Field         | Current    | Proposed       | Why                                          |
|-------------------|---------------|------------|----------------|----------------------------------------------|
| rv-there-yet      | endingType    | levels     | arcade-goal    | Same shape as peak — single-session climb    |
| back-4-blood OR left-4-dead-2 | endingType | conflict | unify | Pick one. Recommended: both → `levels` (mission-based, weak narrative). Final call is owner's. |
| portal-2          | genres FPS    | drop FPS   | First-person   | Puzzle game, not shooter                     |
| dying-light       | genres FPS    | drop FPS   | First-person   | Melee/parkour primary                        |
| dying-light-2     | genres FPS    | drop FPS   | First-person   | Same                                         |
| vermintide-2      | genres FPS    | drop FPS   | First-person   | Melee primary                                |
| dead-island-de    | genres FPS    | drop FPS   | First-person   | Melee primary                                |
| dead-island-2     | genres FPS    | drop FPS   | First-person   | Melee primary                                |
| barony            | genres        | (no perspective) | First-person | Verdict explicitly mentions "first-person roguelike" |

### F.3. Bulk migration needed

After F.1 is approved:
- 22 games currently tagged `FPS` AND `Shooter` → replace `FPS` with `First-person` (keep `Shooter`)
- 6 games tagged `FPS` but NOT `Shooter` → replace `FPS` with `First-person` (no `Shooter` added)
- Sweep the 192 perspective-unknown games. For each: Steam tag check, verdict-text check, assign one of `First-person` / `Third-person` / `Isometric`. Expect ~50-80 to be `First-person`, ~30-50 `Third-person`, rest naturally `Isometric` or 2D/top-down (which we may need to add as a new tag).

### F.4. Storage format proposal (the user's "how to make skills agree" question)

Move taxonomy from prose in `classification.md` to a structured `.claude/skills/shared/taxonomy.json`:

```json
{
  "genres": {
    "First-person": {
      "axis": "perspective",
      "definition": "Camera is the player's eyes.",
      "steam_tags": ["First-Person", "FPS"],
      "examples_positive": ["portal-2", "dying-light"],
      "incompatible_with": ["Third-person", "Isometric"]
    },
    "Shooter": {
      "axis": "mechanic",
      "definition": "Primary verb is shooting projectiles at enemies.",
      "steam_tags": ["Shooter", "FPS", "Third-Person Shooter"],
      "examples_positive": ["halo-mcc", "borderlands-3"],
      "examples_negative": ["portal-2"]
    }
    /* ...for every tag */
  },
  "ending_types": {
    "arcade-goal": {
      "table_label": "Goal",
      "filter_label": "Goal",
      "filter_subtitle": "Win condition reached in a single 5–60 min session. No persistent meta-progress.",
      "decision_tree": [
        "Can you restart the run and aim for the same exact goal? → yes",
        "Is there persistent unlock/stat track between runs? → no"
      ],
      "examples": ["peak", "operation-tango", "keep-talking"]
    }
    /* ... */
  }
}
```

Both `coop-hunter` and `fact-checker` SKILL.md gain a hard rule: «before assigning
any genre or endingType, read `taxonomy.json`. If the candidate doesn't match a
decision-tree path → log to skipped with reason `taxonomy_ambiguous`. Do not invent.»

This removes the "LLM interpretation drift" the owner is worried about — there's
one source of truth, both skills must consult it.

---

## G. Suggested order of action

1. **Owner reviews this report.** Pick which of F.1 / F.2 / F.3 to accept (each can be accepted independently).
2. If F.1 accepted: implement taxonomy changes by editing `taxonomy.json` (one-time) + a migration pass over `data.js`.
3. If F.4 accepted: create `taxonomy.json`, update both SKILL.md files to read from it, deprecate the prose rules in `classification.md` (keep narrative for human readers, machine reads JSON).
4. If F.2 accepted: apply per-entry fixes via `update_field.py` (already exists) and a new helper for genre-array edits.
5. After all the above: re-audit. The 192 perspective-unknown games can then be swept by either a one-shot Claude session or via a one-time enrichment run of the fact-checker.

Reach out when you've decided.

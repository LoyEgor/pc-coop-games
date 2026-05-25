# coop-hunter skill

Autonomous, resumable agent that systematically grows `data.js` with new PC co-op games.

## Quick start

```
/goal Use the coop-hunter skill to crawl all sources from sources.json
and add every game that fits the criteria. Process 3-5 candidates per turn,
validate every 50 games via a fresh subagent, persist progress after each
addition, and stop when all sources are exhausted.
```

The `/goal` command keeps Claude working across many turns until the goal is met. Token consumption is paced (sleep between Steam API calls + small per-turn batch size).

## What it does

For each game in each source:

1. Steam search → resolve correct app_id (avoids the misidentification problems we had in the bulk runs).
2. Steam appdetails (`cc=ua`) → name, UAH price, header, publisher, categories.
3. Steam appreviews → `%positive` + sample for finite-content keyword scan.
4. Verify online co-op (Steam category) OR Remote Play.
5. Verify finite content (HowLongToBeat + Steam keyword scan).
6. Classify tier (AAA/AA/Indie via publisher) + endingType (story/levels/arcade-goal/roguelite/survival-goal via rules in classification.md).
7. WebSearch for a real gameplay YouTube video (not a search-URL placeholder).
8. Append to `data.js` via `scripts/append_entry.py`.
9. Update `state/progress.json` and `state/added.tsv`.

Every 50 additions: spawn a fresh Agent to spot-check 10 random entries. Failures land in `state/validation-fails.tsv` for human review (not auto-corrected).

## Resume after crash

The skill is fully idempotent. If interrupted at any point:

```
/goal continue with the coop-hunter skill
```

It will read `state/progress.json` and pick up exactly where it stopped.

## Files

```
SKILL.md              Main instructions Claude follows
sources.json          Ordered list of sources to crawl (SteamDB tags, Co-Optimus, curators, Reddit, articles)
classification.md     Deterministic rules for tier + endingType + genre mapping + quality threshold
scripts/
  steam_fetch.py      Steam API helper: search, details, reviews, validate
  append_entry.py     Inserts a new entry into data.js (before hidden block)
state/
  progress.json       Current source/offset, counters, completed sources list
  added.tsv           Log of every game added
  skipped.tsv         Log of every skip with reason
  validation-fails.tsv  Spot-check failures awaiting human review
  summary.md          Final report (written when all sources exhausted)
```

## Token economics

- Per turn: 3-5 candidates × ~6 API calls each ≈ 20 web calls, plus ~3-5K tokens for reasoning.
- Validation every 50 adds: one fresh subagent run ≈ 30-40K tokens (it does its own WebFetch on 10 Steam pages).
- Estimated total to cover ~250 candidates: 2-4 hours of `/goal` execution, depending on how many WebSearches Steam rate-limits us into retrying.

## Safety

- Won't touch `app.js` / `index.html` / `styles.css`.
- Won't delete or modify existing entries in `data.js`.
- Won't auto-correct validation failures — only logs them.
- Won't ask the user questions. If a candidate is ambiguous, it's logged to `skipped.tsv` with reason `ambiguous`.

## Manually checking progress

```bash
cat .claude/skills/coop-hunter/state/progress.json
wc -l .claude/skills/coop-hunter/state/added.tsv
wc -l .claude/skills/coop-hunter/state/skipped.tsv
```

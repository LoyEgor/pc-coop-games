#!/usr/bin/env python3
"""
Reconcile coop-hunter state logs: canonicalize skipped.tsv, dedupe, and split
catalog collisions out for review.

WHY THIS EXISTS
---------------
skipped.tsv accumulated two problems over time:
  1. Schema drift. Early rows are 5-column  (timestamp, name, reason, source, notes);
     later rows are 6-column (timestamp, id, title, source, reason, notes). The
     header still describes the 5-column form, so reason/title columns slid and
     dedupe/analysis broke (e.g. a game name landed in the `reason` column).
  2. No dedupe / no upsert. The log is append-only, so one game gets written once
     per source it was seen in (Horizon Chase Turbo = 12 rows), often with
     conflicting reasons.
  3. No added<->skipped gate. 42 games are in BOTH data.js and skipped.tsv.

This script reads the messy file, parses BOTH legacy formats robustly (it locates
the column that holds a KNOWN reason token rather than trusting column count),
collapses each game to ONE canonical row with the most decisive reason, and routes
catalog collisions:
  - game in data.js + a SOFT skip reason (duplicate/low_fit/taxonomy_gap/...) =>
    stale skip, drop it from skipped.tsv (the game was later added on purpose).
  - game in data.js + a HARD-NEGATIVE skip reason (endless/unclear_ending/
    low_quality/no_coop/online_broken/pvp_primary/ambiguous) => genuine
    contradiction, write to reconcile-report.tsv for the owner to judge (one side
    is wrong; could be an endless game that slipped into the catalog).

DEFAULT IS DRY-RUN. Pass --apply to actually rewrite skipped.tsv (a .bak is kept)
and write reconcile-report.tsv. Never run --apply while a coop-hunter burst is
live (it would race the skill's append).

Usage:
    python3 reconcile_state.py            # dry-run: print the report, write nothing
    python3 reconcile_state.py --apply    # rewrite skipped.tsv + reconcile-report.tsv
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STATE = Path(__file__).resolve().parents[1] / "state"
SKIPPED = STATE / "skipped.tsv"
REPORT = STATE / "reconcile-report.tsv"
DATA_JS = ROOT / "data.js"

# Reason priority — index 0 = most decisive ("the real reason it's not in the
# catalog"). Dedupe keeps the lowest-index reason seen for a game.
PRIORITY = [
    "blocklisted_endless", "previously_removed_endless", "endless",
    "endless_misclassified", "live_service", "live_service_borderline",
    "no_coop", "unclear_coop", "pvp_primary",
    "not_on_steam", "invalid_app_id", "online_broken",
    "low_quality", "not_enough_reviews",
    "unclear_ending", "ambiguous",
    "requires_base_game", "early_access",
    "duplicate",
    "taxonomy_gap", "low_fit",
]
KNOWN = set(PRIORITY)

# A catalog collision with one of these reasons is a real contradiction worth a
# human look (the game is live in data.js but was flagged as not-a-fit). Soft
# reasons (everything else, e.g. duplicate/low_fit) just mean a stale skip row.
HARD_NEGATIVE = {
    "blocklisted_endless", "previously_removed_endless", "endless",
    "endless_misclassified", "live_service", "live_service_borderline",
    "no_coop", "unclear_coop", "pvp_primary", "online_broken",
    "low_quality", "not_enough_reviews", "unclear_ending", "ambiguous",
}


def slug(s):
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def rank(reason):
    try:
        return PRIORITY.index(reason)
    except ValueError:
        return len(PRIORITY) + 1  # unknown reasons sort last


def catalog_keys():
    """ids + slugified titles currently present in data.js."""
    text = DATA_JS.read_text(encoding="utf-8")
    ids = set(re.findall(r'id:\s*"([^"]+)"', text))
    titles = re.findall(r'title:\s*"([^"]+)"', text)
    return ids | {slug(t) for t in titles}


def parse_row(line):
    """Return (title, slug, source, reason, notes) from a messy TSV line, or None.

    Robust to both schemas: we find the field that holds a KNOWN reason token and
    infer the rest from its position instead of trusting the column count.
    """
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 3:
        return None
    # Locate the reason field: the first field (after the timestamp) whose value
    # is a known reason token.
    reason_idx = None
    for i in range(2, len(parts)):
        if parts[i].strip() in KNOWN:
            reason_idx = i
            break
    if reason_idx == 2:
        # legacy 5-col: ts | name | reason | source | notes
        name = parts[1].strip()
        reason = parts[2].strip()
        source = parts[3].strip() if len(parts) > 3 else ""
        notes = parts[4].strip() if len(parts) > 4 else ""
        return name, slug(name), source, reason, notes
    if reason_idx is not None and reason_idx >= 4:
        # new 6-col: ts | id | title | source | reason | notes
        gid = parts[1].strip()
        title = parts[2].strip()
        source = parts[3].strip()
        reason = parts[reason_idx].strip()
        notes = parts[reason_idx + 1].strip() if len(parts) > reason_idx + 1 else ""
        return title, slug(gid or title), source, reason, notes
    # No known reason found — best effort: assume 6-col layout if field[1] looks
    # like a slug, else 5-col. Reason stays "unknown".
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*", parts[1].strip()) and len(parts) >= 3:
        title = parts[2].strip() if len(parts) > 2 else parts[1].strip()
        return title, slug(parts[1].strip()), (parts[3].strip() if len(parts) > 3 else ""), "unknown", ""
    name = parts[1].strip()
    return name, slug(name), (parts[3].strip() if len(parts) > 3 else ""), "unknown", ""


def main():
    apply = "--apply" in sys.argv[1:]
    lines = SKIPPED.read_text(encoding="utf-8").splitlines()
    body = lines[1:] if lines and lines[0].startswith("timestamp") else lines

    games = {}  # slug -> dict
    raw_rows = 0
    for ln in body:
        if not ln.strip():
            continue
        parsed = parse_row(ln)
        if not parsed:
            continue
        raw_rows += 1
        title, sg, source, reason, notes = parsed
        if not sg:
            continue
        g = games.setdefault(sg, {
            "title": title, "slug": sg, "reasons": [], "sources": set(),
            "seen": 0, "best_reason": reason, "best_notes": notes,
        })
        g["seen"] += 1
        g["reasons"].append(reason)
        if source:
            g["sources"].add(source)
        if title and len(title) > len(g["title"]):
            g["title"] = title
        if rank(reason) < rank(g["best_reason"]):
            g["best_reason"] = reason
            g["best_notes"] = notes

    catalog = catalog_keys()

    clean = []        # canonical skipped rows (NOT in catalog)
    stale = []        # in catalog + soft reason -> drop silently
    conflicts = []    # in catalog + hard-negative reason -> review
    for sg, g in games.items():
        in_catalog = sg in catalog
        if in_catalog and g["best_reason"] in HARD_NEGATIVE:
            conflicts.append(g)
        elif in_catalog:
            stale.append(g)
        else:
            clean.append(g)

    dups = sum(1 for g in games.values() if g["seen"] > 1)

    # ---- report ----
    print(f"raw rows parsed:            {raw_rows}")
    print(f"unique games:               {len(games)}")
    print(f"games duped (seen >1):      {dups}")
    print(f"-> canonical skipped rows:  {len(clean)}")
    print(f"-> stale (in catalog,soft): {len(stale)}  (dropped from skipped.tsv)")
    print(f"-> CONFLICTS (review):      {len(conflicts)}  (in catalog + hard-negative)")
    print()
    print("=== CONFLICTS — in data.js but skipped as not-a-fit (need a human call) ===")
    for g in sorted(conflicts, key=lambda x: rank(x["best_reason"])):
        print(f"  {g['slug']:34} {g['best_reason']:18} :: {g['best_notes'][:70]}")
    if stale:
        print()
        print("=== STALE skips dropped (game is in catalog, soft reason) ===")
        for g in sorted(stale, key=lambda x: x["slug"]):
            print(f"  {g['slug']:34} {g['best_reason']}")

    if not apply:
        print("\n[dry-run] nothing written. Re-run with --apply to rewrite "
              "skipped.tsv (+ .bak) and write reconcile-report.tsv.")
        return

    # ---- apply: rewrite skipped.tsv canonical, write report ----
    SKIPPED.with_suffix(".tsv.bak").write_text(
        SKIPPED.read_text(encoding="utf-8"), encoding="utf-8")
    header = "timestamp\tid\ttitle\tsource\treason\tnotes\n"
    san = lambda s: s.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    with SKIPPED.open("w", encoding="utf-8") as f:
        f.write(header)
        for g in sorted(clean, key=lambda x: x["slug"]):
            note = g["best_notes"]
            if g["seen"] > 1:
                note = f"{note} [seen {g['seen']}x; reasons: {','.join(sorted(set(g['reasons'])))}]".strip()
            f.write("\t".join([
                "2026-05-29T00:00:00Z", g["slug"], san(g["title"]),
                ";".join(sorted(g["sources"]))[:120], g["best_reason"], san(note),
            ]) + "\n")
    with REPORT.open("w", encoding="utf-8") as f:
        f.write("id\treason\tnotes\taction\n")
        for g in sorted(conflicts, key=lambda x: rank(x["best_reason"])):
            f.write("\t".join([
                g["slug"], g["best_reason"], san(g["best_notes"]),
                "VERIFY: in catalog but skipped as not-a-fit; decide keep-or-remove",
            ]) + "\n")
    print(f"\n[applied] skipped.tsv rewritten ({len(clean)} canonical rows), "
          f"backup at skipped.tsv.bak, {len(conflicts)} conflicts -> {REPORT.name}")


if __name__ == "__main__":
    main()

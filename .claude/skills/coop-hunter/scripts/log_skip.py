#!/usr/bin/env python3
"""
The ONE writer for skipped.tsv — upsert with dedupe + a catalog gate.

Both coop-hunter and fact-checker must log a skip through this helper instead of
appending a raw row. It guarantees the three invariants that the old raw-append
broke (see reconcile_state.py for the history):

  1. ONE row per game. If the game is already in skipped.tsv, update that row in
     place (raise to the more decisive reason, bump a seen-counter) — never append
     a duplicate.
  2. Canonical schema: timestamp, id, title, source, reason, notes.
  3. added<->skipped gate. If the game's slug is already in data.js, it is NOT a
     skip candidate — do not write it. Exit 3 so the caller knows it's in the
     catalog (and, if the reason was hard-negative, it should instead be routed to
     the fact-checker as a possible bad entry, not silently logged).

Usage:
    python3 log_skip.py "<title>" <reason> <source> ["notes"]
Exit codes:
    0  skip written or updated
    2  bad args
    3  game is in data.js — not written (caller should not treat it as skipped)
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STATE = Path(__file__).resolve().parents[1] / "state"
SKIPPED = STATE / "skipped.tsv"
DATA_JS = ROOT / "data.js"
HEADER = "timestamp\tid\ttitle\tsource\treason\tnotes\n"
TS = "2026-05-29T00:00:00Z"  # static stamp; this project does not use wall-clock in scripts

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


def slug(s):
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def rank(reason):
    try:
        return PRIORITY.index(reason)
    except ValueError:
        return len(PRIORITY) + 1


def in_catalog(sg):
    text = DATA_JS.read_text(encoding="utf-8")
    ids = set(re.findall(r'id:\s*"([^"]+)"', text))
    titles = {slug(t) for t in re.findall(r'title:\s*"([^"]+)"', text)}
    return sg in (ids | titles)


def main():
    args = sys.argv[1:]
    if len(args) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    title, reason, source = args[0], args[1], args[2]
    notes = args[3] if len(args) > 3 else ""
    sg = slug(title)
    san = lambda s: s.replace("\t", " ").replace("\r", " ").replace("\n", " ")

    if in_catalog(sg):
        print(f"IN_CATALOG: '{title}' ({sg}) is already in data.js — not logged as skip.",
              file=sys.stderr)
        sys.exit(3)

    if not SKIPPED.exists():
        SKIPPED.write_text(HEADER, encoding="utf-8")
    lines = SKIPPED.read_text(encoding="utf-8").splitlines()
    body = lines[1:] if lines and lines[0].startswith("timestamp") else lines

    rows = {}  # slug -> [ts, id, title, source, reason, notes]
    order = []
    for ln in body:
        if not ln.strip():
            continue
        p = ln.split("\t")
        # canonical 6-col only; pre-reconcile rows are tolerated by slugifying p[1]
        if len(p) >= 6:
            rsg = slug(p[1])
            rows[rsg] = p[:6]
        else:
            rsg = slug(p[1]) if len(p) > 1 else ""
            if rsg:
                rows[rsg] = [p[0] if p else TS, rsg, p[1] if len(p) > 1 else rsg,
                             p[3] if len(p) > 3 else "", "unknown", ""]
        if rsg and rsg not in order:
            order.append(rsg)

    if sg in rows:
        existing = rows[sg]
        seen = 2
        m = re.search(r"seen (\d+)x", existing[5])
        if m:
            seen = int(m.group(1)) + 1
        # raise to the more decisive reason
        new_reason = reason if rank(reason) < rank(existing[4]) else existing[4]
        rows[sg] = [existing[0], sg, san(title) or existing[2], san(source) or existing[3],
                    new_reason, f"{san(notes) or existing[5].split(' [seen')[0]} [seen {seen}x]"]
        action = "updated"
    else:
        rows[sg] = [TS, sg, san(title), san(source), reason, san(notes)]
        order.append(sg)
        action = "added"

    with SKIPPED.open("w", encoding="utf-8") as f:
        f.write(HEADER)
        for k in order:
            f.write("\t".join(rows[k]) + "\n")
    print(f"{action}: {sg} reason={rows[sg][4]}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Guard the one-place invariant across the catalog and the two not-in-catalog
lists. DETERMINISTIC — no LLM, no network. Cheap; run at the START of every
coop-hunter / fact-checker run so a game can never sit in two lists at once.

A game id must be in EXACTLY ONE of {data.js, reeval, hard-block}. The preventive
gates (log_skip.py catalog-gate, append_entry.py drop_from_reeval) cover the
normal write paths, but a manual edit, a crash mid-write, an older row, or a race
can still create an overlap (e.g. cosmo-s-quickstop ended up in BOTH data.js and
reeval). Prevention is not a guarantee — this is the postfactum sweeper.

Reconciliation is by FIXED precedence (no judgment):
  reeval   ∩ hard-block  -> drop from hard-block     (re-checkable wins; matches log_skip)
  data.js  ∩ reeval       -> drop from reeval          (catalog wins)
  data.js  ∩ hard-block    -> drop from hard-block AND flag owner-review (action=contradiction)
                             (a catalogued game was hard-blocked — a human should look)

Usage:  python3 sync_lists.py            # dry-run: report overlaps, write nothing
        python3 sync_lists.py --apply    # fix them
Exit 0 always (it is a maintenance sweep, never fatal).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SHARED = ROOT / ".claude" / "skills" / "shared"
DATA_JS = ROOT / "data.js"
REEVAL = SHARED / "reeval.tsv"
HARD = SHARED / "hard-block.tsv"
OWNER = SHARED / "owner-review.tsv"
REEVAL_HDR = "id\ttitle\treason\tsource\tnotes"
HARD_HDR = "id\ttitle\treason\tnotes"


def slug(s):
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def catalog_ids():
    t = DATA_JS.read_text(encoding="utf-8")
    return set(re.findall(r'id:\s*"([^"]+)"', t)) | {slug(x) for x in re.findall(r'title:\s*"([^"]+)"', t)}


def load_rows(path):
    """Return (header, {id: full_line})."""
    if not path.exists():
        return "", {}
    lines = path.read_text(encoding="utf-8").splitlines()
    hdr = lines[0] if lines and lines[0].startswith("id\t") else ""
    body = lines[1:] if hdr else lines
    rows = {}
    for ln in body:
        if ln.strip():
            c = ln.split("\t")
            if c and c[0]:
                rows[c[0]] = ln
    return hdr, rows


def save_rows(path, hdr, rows):
    with path.open("w", encoding="utf-8") as f:
        f.write(hdr + "\n")
        for k in sorted(rows):
            f.write(rows[k] + "\n")


def flag_owner(gid, detail):
    if not OWNER.exists():
        OWNER.write_text("id\taction\tdetail\n", encoding="utf-8")
    if f"{gid}\tcontradiction" in OWNER.read_text(encoding="utf-8"):
        return  # already flagged
    with OWNER.open("a", encoding="utf-8") as f:
        f.write(f"{gid}\tcontradiction\t{detail}\n")


def main():
    apply = "--apply" in sys.argv[1:]
    cat = catalog_ids()
    r_hdr, reeval = load_rows(REEVAL)
    h_hdr, hard = load_rows(HARD)
    fixed = []

    for gid in list(hard):
        if gid in reeval:
            hard.pop(gid)
            fixed.append(f"reeval∩hard   {gid}: drop from hard-block (re-checkable wins)")
    for gid in list(reeval):
        if gid in cat:
            reeval.pop(gid)
            fixed.append(f"catalog∩reeval {gid}: drop from reeval (catalog wins)")
    owner_flags = []
    for gid in list(hard):
        if gid in cat:
            hard.pop(gid)
            owner_flags.append(gid)
            fixed.append(f"catalog∩hard  {gid}: drop from hard-block + flag owner-review")

    if not fixed:
        print("sync_lists: invariant clean — no overlaps.")
        return
    print(f"sync_lists: {len(fixed)} overlap(s){' (dry-run)' if not apply else ''}:")
    for x in fixed:
        print("  " + x)
    if not apply:
        print("Re-run with --apply to fix.")
        return
    save_rows(REEVAL, r_hdr or REEVAL_HDR, reeval)
    save_rows(HARD, h_hdr or HARD_HDR, hard)
    for gid in owner_flags:
        flag_owner(gid, "in data.js but was hard-blocked — verify it is a real fit")
    print("sync_lists: applied.")


if __name__ == "__main__":
    main()

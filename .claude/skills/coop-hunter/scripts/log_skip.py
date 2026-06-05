#!/usr/bin/env python3
"""
The ONE writer for the not-in-catalog lists. Routes a rejected game to exactly
one of the two shared lists and upserts (one row per game):

  reeval.tsv     -> re-checkable (judgment / threshold reasons). Re-judged later.
  hard-block.tsv -> mechanically impossible, NEVER (no co-op / PvP-only / not on
                    Steam / invalid / MMO / delisted).

Routing: reason in MECHANICAL -> hard-block; everything else -> reeval.
Invariant: a game in data.js is in NEITHER (catalog gate -> exit 3). reeval wins
over hard-block if a game has mixed reasons ("better to re-check one too many").

Usage:  python3 log_skip.py "<title>" <reason> <source> ["notes"]
Exit:   0 written/updated · 2 bad args · 3 game is in data.js (not a reject)
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SHARED = ROOT / ".claude" / "skills" / "shared"
REEVAL = SHARED / "reeval.tsv"
HARDBLOCK = SHARED / "hard-block.tsv"
DATA_JS = ROOT / "data.js"
REEVAL_HDR = "id\ttitle\treason\tsource\tnotes\n"
HARD_HDR = "id\ttitle\treason\tnotes\n"

MECHANICAL = {
    "no_coop", "unclear_coop", "pvp_primary", "not_on_steam", "not_steam",
    "invalid_app_id", "delisted", "mmo", "massively_multiplayer", "battle_royale",
}


def slug(s):
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def in_catalog(sg):
    t = DATA_JS.read_text(encoding="utf-8")
    ids = set(re.findall(r'id:\s*"([^"]+)"', t))
    titles = {slug(x) for x in re.findall(r'title:\s*"([^"]+)"', t)}
    return sg in (ids | titles)


def load(path, ncols):
    """Return {id: [cols...]} from a tsv (header skipped)."""
    out = {}
    if path.exists():
        for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if i == 0 or not ln.strip():
                continue
            c = ln.split("\t")
            if c and c[0]:
                out[c[0]] = (c + [""] * ncols)[:ncols]
    return out


def write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(header)
        for gid in sorted(rows):
            f.write("\t".join(rows[gid]) + "\n")


def main():
    args = sys.argv[1:]
    if len(args) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    title, reason, source = args[0], args[1], args[2]
    notes = args[3] if len(args) > 3 else ""
    sg = slug(title)
    san = lambda s: (s or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")

    if in_catalog(sg):
        print(f"IN_CATALOG: '{title}' ({sg}) is in data.js — not a reject.", file=sys.stderr)
        sys.exit(3)

    reeval = load(REEVAL, 5)
    hard = load(HARDBLOCK, 4)

    if reason in MECHANICAL:
        # hard-block — but only if reeval hasn't already claimed it (reeval wins)
        if sg in reeval:
            print(f"already in reeval (re-checkable wins): {sg}")
            sys.exit(0)
        hard[sg] = [sg, san(title), reason, san(notes)]
        write(HARDBLOCK, HARD_HDR, hard)
        print(f"hard-block: {sg} ({reason})")
    else:
        # reeval — move out of hard-block if it was there (re-checkable overrides)
        hard.pop(sg, None)
        reeval[sg] = [sg, san(title), reason, san(source), san(notes)]
        write(HARDBLOCK, HARD_HDR, hard)
        write(REEVAL, REEVAL_HDR, reeval)
        print(f"reeval: {sg} ({reason})")


if __name__ == "__main__":
    main()

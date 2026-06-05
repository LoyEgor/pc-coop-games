#!/usr/bin/env python3
"""
Mark a data.js entry as reviewed by the fact-checker.

The `reviewed: true` flag is how "has the fact-checker checked this game" is
tracked — reliably, on the game itself, NOT via git timestamps (a week with no
commits does not mean a game was verified). coop-hunter appends new games WITHOUT
the flag (= unchecked). `fact-checker new` processes every entry that lacks
`reviewed: true`, then calls this to stamp it; the game then leaves the new-queue.

Usage:  python3 mark_reviewed.py <id> [<id2> ...]
Idempotent: an entry that already has `reviewed: true` is left as-is.
"""

import os
import re
import sys
from pathlib import Path

DATA_JS = Path(__file__).resolve().parents[3].parent / "data.js"


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    # Line-based, NOT a spanning regex: a lazy `(?:.*?\n)*?` block regex anchors
    # on the FILE's first entry and stretches across every entry up to the target
    # id, so it would (a) see a foreign `reviewed: true` and skip wrongly, and
    # (b) break for every id past the first. We instead locate the id line and
    # confine the check/insert to THAT entry's `  {` .. `  }` span. Re-search per
    # id so a prior insert's line shift doesn't matter.
    lines = DATA_JS.read_text(encoding="utf-8").split("\n")
    done, already, missing = [], [], []

    for gid in sys.argv[1:]:
        idx = next((i for i, l in enumerate(lines) if l.strip() == f'id: "{gid}",'), None)
        if idx is None:
            missing.append(gid)
            continue
        end = next((j for j in range(idx + 1, len(lines)) if lines[j].rstrip() in ("  }", "  },")), len(lines) - 1)
        start = next((j for j in range(idx - 1, -1, -1) if lines[j].rstrip() == "  {"), idx)
        if any(re.match(r"\s*reviewed:\s*true\b", lines[k]) for k in range(start, end + 1)):
            already.append(gid)
            continue
        lines.insert(idx + 1, "    reviewed: true,")
        done.append(gid)

    tmp = DATA_JS.with_name(DATA_JS.name + ".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    os.replace(tmp, DATA_JS)
    print(f"marked reviewed: {len(done)} | already: {len(already)} | not found: {len(missing)}")
    if missing:
        print("  not found:", ", ".join(missing), file=sys.stderr)


if __name__ == "__main__":
    main()

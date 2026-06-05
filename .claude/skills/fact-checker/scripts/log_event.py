#!/usr/bin/env python3
"""
Append a fact-checker finding to shared/owner-review.tsv — the owner's todo queue.

Usage (unchanged 6-arg interface so update_field.py / SKILL.md calls still work):
    python3 log_event.py <kind> <id> <field> <old> <new> <reason>

<kind> maps to an owner-review action:
    proposed-fixes     -> action=fix           (editorial change the owner should apply)
    proposed-removals  -> action=remove        (entry the owner should consider removing)
    contradiction      -> action=contradiction (catalog contradicts itself)
    discrepancies      -> NO-OP (info-level; git history + transcript already record it)
    applied-fixes      -> NO-OP (auto-applied; git diff is the record)

owner-review is a TODO OVERLAY: keep it small. Only log things the owner must
actually decide. Upsert by (id, action) so the same finding isn't duplicated.
Exits 0 always (logging is best-effort).
"""

import sys
from pathlib import Path

SHARED = Path(__file__).resolve().parents[2] / "shared"
OWNER = SHARED / "owner-review.tsv"
HDR = "id\taction\tdetail\n"
ACTION = {"proposed-fixes": "fix", "proposed-removals": "remove", "contradiction": "contradiction"}
NOOP = {"discrepancies", "applied-fixes"}


def main():
    if len(sys.argv) != 7:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    kind, gid, field, old, new, reason = sys.argv[1:]
    if kind in NOOP:
        sys.exit(0)  # no longer a stored list — git + transcript are the record
    action = ACTION.get(kind)
    if not action:
        print(f"ERROR: unknown kind '{kind}'. Expected: {sorted(set(ACTION) | NOOP)}", file=sys.stderr)
        sys.exit(2)

    san = lambda s: (s or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")
    if field and (old or new):
        detail = f"{san(field)}: {san(old)} -> {san(new)} ({san(reason)})"
    else:
        detail = san(reason) or san(field)

    OWNER.parent.mkdir(parents=True, exist_ok=True)
    rows, order = {}, []
    if OWNER.exists():
        for i, ln in enumerate(OWNER.read_text(encoding="utf-8").splitlines()):
            if i == 0 or not ln.strip():
                continue
            c = ln.split("\t")
            if len(c) >= 2:
                key = (c[0], c[1])
                rows[key] = ln
                if key not in order:
                    order.append(key)
    key = (gid, action)
    if key not in order:
        order.append(key)
    rows[key] = "\t".join([gid, action, detail])
    with OWNER.open("w", encoding="utf-8") as f:
        f.write(HDR)
        for k in order:
            f.write(rows[k] + "\n")
    print(f"owner-review: {gid} [{action}]")


if __name__ == "__main__":
    main()

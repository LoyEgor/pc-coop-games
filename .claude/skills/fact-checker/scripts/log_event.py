#!/usr/bin/env python3
"""
Append a row to one of the fact-checker TSV logs.

Usage:
    python log_event.py <kind> <id> <field> <old> <new> <reason>

<kind> selects the destination TSV:
    discrepancies      → state/discrepancies.tsv      (info-level mismatch, no fix needed)
    proposed-fixes     → state/proposed-fixes.tsv     (would auto-fix but field is editorial)
    proposed-removals  → state/proposed-removals.tsv  (game now looks blocklist-worthy)
    applied-fixes      → state/applied-fixes.tsv      (already auto-applied — update_field.py logs here too)

<old> and <new> can be empty strings if the row only carries a reason
(e.g. proposed-removals where the action is "remove the entire entry").

Exits 0 always (logging is append-only and best-effort).
"""

import sys
import datetime
from pathlib import Path

STATE = Path(__file__).resolve().parents[1] / "state"

TARGETS = {
    "discrepancies": STATE / "discrepancies.tsv",
    "proposed-fixes": STATE / "proposed-fixes.tsv",
    "proposed-removals": STATE / "proposed-removals.tsv",
    "applied-fixes": STATE / "applied-fixes.tsv",
}

HEADER = "timestamp\tid\tfield\told_value\tnew_value\treason\n"


def main():
    if len(sys.argv) != 7:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    kind, game_id, field, old, new, reason = sys.argv[1:]
    if kind not in TARGETS:
        print(f"ERROR: unknown kind '{kind}'. Expected one of: {sorted(TARGETS)}", file=sys.stderr)
        sys.exit(2)

    target = TARGETS[kind]
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(HEADER, encoding="utf-8")

    # Sanitize tab/newline so the TSV stays well-formed.
    sanitize = lambda s: s.replace("\t", " ").replace("\n", " ").replace("\r", " ")

    with target.open("a", encoding="utf-8") as f:
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        f.write(
            "\t".join([
                ts,
                sanitize(game_id),
                sanitize(field),
                sanitize(old),
                sanitize(new),
                sanitize(reason),
            ])
            + "\n"
        )
    print(f"OK: logged {kind}: {game_id}.{field}")


if __name__ == "__main__":
    main()

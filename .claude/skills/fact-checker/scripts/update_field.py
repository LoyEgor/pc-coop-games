#!/usr/bin/env python3
"""
Update a single scalar field on a single entry in data.js.

Usage:
    python update_field.py <id> <field> <value>

Supported fields: rating, price, year, playersMax, hours (all ints).
Refuses arrays (genres) and unknown fields — those need editorial review.

Logs every applied fix to state/applied-fixes.tsv.

Exits 0 on success, 1 if id/field not found, 2 on error.
"""

import sys
import re
import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3].parent
DATA_JS = REPO_ROOT / "data.js"
LOG_TSV = REPO_ROOT / ".claude" / "skills" / "fact-checker" / "state" / "applied-fixes.tsv"

ALLOWED_FIELDS = {"rating", "price", "year", "playersMax", "hours"}


def ensure_log_header():
    LOG_TSV.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_TSV.exists():
        LOG_TSV.write_text(
            "timestamp\tid\tfield\told_value\tnew_value\n", encoding="utf-8"
        )


def update(content, game_id, field, value):
    lines = content.split("\n")
    target = f'id: "{game_id}"'
    id_line = next((i for i, l in enumerate(lines) if target in l), None)
    if id_line is None:
        return None, None
    end = next(
        (i for i in range(id_line, len(lines)) if lines[i].strip() in ("}", "},")),
        None,
    )
    if end is None:
        return None, None

    pattern = re.compile(rf"^(\s*){re.escape(field)}:\s*([^,]+?)(,?)$")
    for j in range(id_line, end + 1):
        m = pattern.match(lines[j])
        if not m:
            continue
        indent, old_value, trailing = m.group(1), m.group(2).strip(), m.group(3)
        lines[j] = f"{indent}{field}: {value}{trailing}"
        return "\n".join(lines), old_value

    return None, None


def main():
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    game_id, field, value = sys.argv[1], sys.argv[2], sys.argv[3]

    if field not in ALLOWED_FIELDS:
        print(
            f"ERROR: field '{field}' is not auto-fixable. Allowed: {sorted(ALLOWED_FIELDS)}.",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        int_value = int(value)
    except ValueError:
        print(f"ERROR: value '{value}' is not an integer", file=sys.stderr)
        sys.exit(2)

    if not DATA_JS.exists():
        print(f"ERROR: data.js not found at {DATA_JS}", file=sys.stderr)
        sys.exit(2)

    content = DATA_JS.read_text(encoding="utf-8")
    new_content, old_value = update(content, game_id, field, str(int_value))
    if new_content is None:
        print(f"NOT FOUND: '{game_id}.{field}'", file=sys.stderr)
        sys.exit(1)

    DATA_JS.write_text(new_content, encoding="utf-8")
    ensure_log_header()
    with LOG_TSV.open("a", encoding="utf-8") as f:
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        f.write(f"{ts}\t{game_id}\t{field}\t{old_value}\t{int_value}\n")
    print(f"OK: {game_id}.{field}: {old_value} -> {int_value}")


if __name__ == "__main__":
    main()

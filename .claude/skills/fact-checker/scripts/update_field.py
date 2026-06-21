#!/usr/bin/env python3
"""
Update a single scalar field on a single entry in data.js.

Usage:
    python update_field.py <id> <field> <value>

Supported fields:
  - ints:   rating, ratingCount, price, year, playersMax, hours
  - string: imageUrl (written as a quoted JS literal; must be an https:// URL)
Refuses arrays (genres) and unknown fields — those need editorial review.

If the field is absent on the target entry it is INSERTED (right after the
`id:` line, which always carries a trailing comma) — this is how a NEW field
such as `ratingCount` gets backfilled onto entries that predate it.

Logs every applied fix to state/applied-fixes.tsv.

Exits 0 on success, 1 if id/field not found, 2 on error.
"""

import os
import sys
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3].parent
DATA_JS = REPO_ROOT / "data.js"


def atomic_write_text(path, text):
    """Write atomically (temp file + os.replace) so a crash mid-write can't
    truncate data.js."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

ALLOWED_INT_FIELDS = {"rating", "ratingCount", "price", "year", "playersMax", "hours"}
ALLOWED_STR_FIELDS = {"imageUrl", "oneCopy"}
ALLOWED_FIELDS = ALLOWED_INT_FIELDS | ALLOWED_STR_FIELDS
ONECOPY_VALUES = {"none", "remote-play", "friend-pass"}




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

    # Field not present on this entry — insert it right after the id: line.
    # The id line always carries a trailing comma, so inserting after it can
    # never create a missing or duplicate comma. old_value None signals insert.
    indent = re.match(r"^(\s*)", lines[id_line]).group(1)
    lines.insert(id_line + 1, f"{indent}{field}: {value},")
    return "\n".join(lines), None


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

    # Int fields are validated then written bare; string fields (imageUrl) are
    # written as a quoted JS literal. `write_value` is the exact text placed
    # after the colon; `log_value` is the human-readable new value for the log.
    if field in ALLOWED_INT_FIELDS:
        try:
            log_value = str(int(value))
        except ValueError:
            print(f"ERROR: value '{value}' is not an integer", file=sys.stderr)
            sys.exit(2)
        write_value = log_value
    else:
        if field == "imageUrl" and not value.startswith("https://"):
            print(f"ERROR: imageUrl must be an https:// URL, got '{value}'", file=sys.stderr)
            sys.exit(2)
        if field == "oneCopy" and value not in ONECOPY_VALUES:
            print(f"ERROR: oneCopy must be one of {sorted(ONECOPY_VALUES)}, got '{value}'", file=sys.stderr)
            sys.exit(2)
        log_value = value
        write_value = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    if not DATA_JS.exists():
        print(f"ERROR: data.js not found at {DATA_JS}", file=sys.stderr)
        sys.exit(2)

    content = DATA_JS.read_text(encoding="utf-8")
    new_content, old_value = update(content, game_id, field, write_value)
    if new_content is None:
        print(f"NOT FOUND: '{game_id}.{field}'", file=sys.stderr)
        sys.exit(1)

    atomic_write_text(DATA_JS, new_content)
    # No separate applied-fixes log anymore — the change is in data.js and the
    # `git diff` / commit is the record (see the 4-list state model).
    print(f"OK: {game_id}.{field}: {old_value if old_value is not None else '(absent)'} -> {log_value}")


if __name__ == "__main__":
    main()

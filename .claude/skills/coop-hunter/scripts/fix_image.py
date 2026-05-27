#!/usr/bin/env python3
"""
Replace the imageUrl line of an existing data.js entry with the canonical
steamImage(<app_id>) helper.

Usage:
    python fix_image.py <id> <app_id>

Used by phase 4 revalidate_existing when a hardcoded full-URL imageUrl 404s.
The steamImage helper expands to a stable Steam CDN URL.

Logs each fix to state/image-fixes.tsv.

Exits 0 on success, 1 if id not found, 2 on error.
"""

import os
import sys
import re
import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3].parent
DATA_JS = REPO_ROOT / "data.js"
LOG_TSV = REPO_ROOT / ".claude" / "skills" / "coop-hunter" / "state" / "image-fixes.tsv"


def atomic_write_text(path, text):
    """Write atomically (temp file + os.replace) so a crash mid-write can't
    truncate data.js."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def ensure_log_header():
    LOG_TSV.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_TSV.exists():
        LOG_TSV.write_text(
            "timestamp\tid\told_url_kind\tnew_app_id\n", encoding="utf-8"
        )


def fix(content, game_id, app_id):
    lines = content.split("\n")
    target = f'id: "{game_id}"'
    id_line = next((i for i, l in enumerate(lines) if target in l), None)
    if id_line is None:
        return None, None
    end = next(
        (
            i
            for i in range(id_line, len(lines))
            if lines[i].strip() in ("}", "},")
        ),
        None,
    )
    if end is None:
        return None, None

    for j in range(id_line, end + 1):
        m = re.match(r"^(\s*)imageUrl:\s*(steamImage|\")", lines[j])
        if not m:
            continue
        indent = m.group(1)
        kind = "steamImage" if m.group(2) == "steamImage" else "literal_url"
        trailing = "," if lines[j].rstrip().endswith(",") else ""
        lines[j] = f"{indent}imageUrl: steamImage({app_id}){trailing}"
        return "\n".join(lines), kind

    return None, None


def main():
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    game_id, app_id = sys.argv[1], sys.argv[2]
    if not app_id.isdigit():
        print(f"ERROR: '{app_id}' is not a numeric Steam app id", file=sys.stderr)
        sys.exit(2)
    if not DATA_JS.exists():
        print(f"ERROR: data.js not found at {DATA_JS}", file=sys.stderr)
        sys.exit(2)

    content = DATA_JS.read_text(encoding="utf-8")
    new_content, old_kind = fix(content, game_id, app_id)
    if new_content is None:
        print(f"NOT FOUND: '{game_id}' has no replaceable imageUrl line", file=sys.stderr)
        sys.exit(1)

    atomic_write_text(DATA_JS, new_content)
    ensure_log_header()
    with LOG_TSV.open("a", encoding="utf-8") as f:
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        f.write(f"{ts}\t{game_id}\t{old_kind}\t{app_id}\n")
    print(f"OK: {game_id} {old_kind} -> steamImage({app_id})")


if __name__ == "__main__":
    main()

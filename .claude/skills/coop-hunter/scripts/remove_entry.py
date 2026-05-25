#!/usr/bin/env python3
"""
Remove an entry from data.js by id. Used by the coop-hunter skill phase 4
(revalidate_existing) when an entry turns out to be endless and must be purged.

Usage:
    python remove_entry.py <id> [<id2> <id3> ...]

For each id:
- Finds the entry block in data.js (from '  {' containing 'id: "<id>"' to the
  matching '  },').
- Deletes those lines (including the trailing comma).
- If the entry is the LAST one in the array (no trailing comma), removes the
  preceding comma from the previous entry instead.

Logs each removal to state/removed-entries.tsv.

Exits 0 on success, 1 if any id was not found.
"""

import sys
import re
import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3].parent
DATA_JS = REPO_ROOT / "data.js"
REMOVED_TSV = REPO_ROOT / ".claude" / "skills" / "coop-hunter" / "state" / "removed-entries.tsv"


def ensure_log_header():
    REMOVED_TSV.parent.mkdir(parents=True, exist_ok=True)
    if not REMOVED_TSV.exists():
        REMOVED_TSV.write_text("timestamp\tid\ttitle\treason\tsignals_matched\n", encoding="utf-8")


def find_entry_span(content, game_id):
    """Return (start_line_idx, end_line_idx_exclusive, title) of the entry block."""
    lines = content.split("\n")
    target = f'id: "{game_id}"'

    # Find the line containing the id.
    id_line = None
    for i, line in enumerate(lines):
        if target in line:
            id_line = i
            break
    if id_line is None:
        return None

    # Find the opening "  {" before id_line.
    start = None
    for i in range(id_line, -1, -1):
        if lines[i].strip() == "{":
            start = i
            break
    if start is None:
        return None

    # Find the closing "  }," or "  }" after id_line.
    end = None
    for i in range(id_line, len(lines)):
        stripped = lines[i].strip()
        if stripped == "}," or stripped == "}":
            end = i
            break
    if end is None:
        return None

    # Try to extract title for logging.
    title = ""
    title_match = re.search(r'title:\s*"([^"]*)"', "\n".join(lines[start:end + 1]))
    if title_match:
        title = title_match.group(1)

    return (start, end + 1, title)


def remove_entry(content, game_id, reason="endless_misclassified", signals=""):
    span = find_entry_span(content, game_id)
    if span is None:
        return content, False, None
    start, end, title = span
    lines = content.split("\n")

    # If this entry ends with "}," (not the last entry), just drop these lines.
    # If it ends with "}" (the last entry), we also need to remove the trailing
    # comma from the previous entry to keep valid JS.
    closing_line = lines[end - 1].strip()
    if closing_line == "}":
        # This is the last entry. Find the previous entry's closing comma.
        for j in range(start - 1, -1, -1):
            if lines[j].strip() == "},":
                lines[j] = lines[j].rstrip().rstrip(",")
                break

    # Remove the entry's lines.
    new_lines = lines[:start] + lines[end:]
    new_content = "\n".join(new_lines)

    # Log.
    ensure_log_header()
    with REMOVED_TSV.open("a", encoding="utf-8") as f:
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        f.write(f"{ts}\t{game_id}\t{title}\t{reason}\t{signals}\n")

    return new_content, True, title


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    if not DATA_JS.exists():
        print(f"ERROR: data.js not found at {DATA_JS}", file=sys.stderr)
        sys.exit(2)

    ids = sys.argv[1:]

    # Allow reason via env var.
    import os
    reason = os.environ.get("REMOVE_REASON", "endless_misclassified")
    signals = os.environ.get("REMOVE_SIGNALS", "")

    content = DATA_JS.read_text(encoding="utf-8")
    not_found = []
    removed = []
    for game_id in ids:
        content, ok, title = remove_entry(content, game_id, reason=reason, signals=signals)
        if ok:
            removed.append((game_id, title))
            print(f"REMOVED: {game_id} ({title})")
        else:
            not_found.append(game_id)
            print(f"NOT FOUND: {game_id}", file=sys.stderr)

    DATA_JS.write_text(content, encoding="utf-8")
    print(f"\n{len(removed)} entries removed, {len(not_found)} not found.")
    sys.exit(1 if not_found else 0)


if __name__ == "__main__":
    main()

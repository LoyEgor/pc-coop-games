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

import os
import sys
import re
import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3].parent
DATA_JS = REPO_ROOT / "data.js"
SHARED = REPO_ROOT / ".claude" / "skills" / "shared"
REEVAL_TSV = SHARED / "reeval.tsv"          # default destination — re-checkable
HARDBLOCK_TSV = SHARED / "hard-block.tsv"   # --block / mechanical reason — never re-add

# Mechanical reasons go to hard-block; everything else stays re-checkable (reeval).
MECHANICAL = {
    "no_coop", "unclear_coop", "pvp_primary", "not_on_steam", "not_steam",
    "invalid_app_id", "delisted", "mmo", "massively_multiplayer", "battle_royale",
}


def atomic_write_text(path, text):
    """Write atomically (temp file + os.replace) so a crash mid-write can't
    truncate data.js."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


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

    # Record where the removed game now lives (one-place invariant). Mechanical
    # reason -> hard-block (never re-add); anything else -> reeval (re-checkable,
    # so a rules change / game update can bring it back — the Forza principle).
    block = (reason in MECHANICAL)
    dest = HARDBLOCK_TSV if block else REEVAL_TSV
    other = REEVAL_TSV if block else HARDBLOCK_TSV
    hdr = "id\ttitle\treason\tnotes\n" if block else "id\ttitle\treason\tsource\tnotes\n"
    san = lambda s: (s or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")

    def load(path):
        out, head = {}, None
        if path.exists():
            for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines()):
                if i == 0:
                    head = ln + "\n"
                    continue
                if not ln.strip():
                    continue
                c = ln.split("\t")
                if c and c[0]:
                    out[c[0]] = ln
        return out, head

    # Cross-list one-place invariant: remove this id from the OTHER list so it
    # can never live in both reeval AND hard-block (a dual-listing would make
    # append_entry's hard-block gate permanently refuse a re-checkable game).
    other.parent.mkdir(parents=True, exist_ok=True)
    other_rows, other_head = load(other)
    if game_id in other_rows:
        other_rows.pop(game_id, None)
        if other_head:
            with other.open("w", encoding="utf-8") as f:
                f.write(other_head)
                for gid in sorted(other_rows):
                    f.write(other_rows[gid] + "\n")

    dest.parent.mkdir(parents=True, exist_ok=True)
    rows, _ = load(dest)
    rows[game_id] = (f"{game_id}\t{san(title)}\t{reason}\t{san(signals)}" if block
                     else f"{game_id}\t{san(title)}\t{reason}\tremoved\t{san(signals)}")
    with dest.open("w", encoding="utf-8") as f:
        f.write(hdr)
        for gid in sorted(rows):
            f.write(rows[gid] + "\n")

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

    atomic_write_text(DATA_JS, content)
    print(f"\n{len(removed)} entries removed, {len(not_found)} not found.")
    sys.exit(1 if not_found else 0)


if __name__ == "__main__":
    main()

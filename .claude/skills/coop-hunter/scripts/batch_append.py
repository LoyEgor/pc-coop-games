#!/usr/bin/env python3
"""Append a batch of entries from a JSON array file to data.js.

Usage: python batch_append.py path/to/batch.json
"""
import sys
import json
import os
sys.path.insert(0, os.path.dirname(__file__))
# Reuse the SAME gates as append_entry.py so batch inserts can't bypass them:
#   - render_entry() raises ValueError if there is no real 11-char video_id
#   - previously_removed_ids() lists ids ever auto-removed as endless
from append_entry import render_entry, previously_removed_ids
import re
from pathlib import Path

DATA_JS = Path(__file__).resolve().parents[3].parent / "data.js"


def main():
    if len(sys.argv) < 2:
        print("Usage: batch_append.py batch.json", file=sys.stderr)
        sys.exit(1)
    batch_file = sys.argv[1]
    with open(batch_file, encoding="utf-8") as f:
        entries = json.load(f)
    content = DATA_JS.read_text(encoding="utf-8")
    removed_ids = previously_removed_ids()
    added = []
    skipped = []
    for g in entries:
        if re.search(r'id:\s*"' + re.escape(g["id"]) + r'"', content):
            skipped.append(f"{g['id']} (duplicate)")
            continue
        # Gate: never re-add a game previously removed as endless.
        if g["id"] in removed_ids:
            skipped.append(f"{g['id']} (previously_removed_endless)")
            continue
        # Gate: render_entry raises ValueError without a real video_id.
        try:
            new_entry = render_entry(g) + ","
        except ValueError as e:
            skipped.append(f"{g['id']} (rejected: {e})")
            continue
        match = re.search(r'\n  \{\n(?:[^{}]*?)\n    hidden:\s*true', content)
        if match:
            insert_pos = match.start() + 1
            content = content[:insert_pos] + new_entry + "\n" + content[insert_pos:]
        else:
            new_content = re.sub(
                r'\n  \}\n\];',
                f'\n  }},\n{new_entry}\n];',
                content,
                count=1,
            )
            if new_content == content:
                print(f"ERROR: couldn't find insertion point for {g['id']}", file=sys.stderr)
                sys.exit(2)
            content = new_content
        added.append(g["id"])

    DATA_JS.write_text(content, encoding="utf-8")
    print(f"Added {len(added)}: {added}")
    if skipped:
        print(f"Skipped {len(skipped)} (already present): {skipped}")


if __name__ == "__main__":
    main()

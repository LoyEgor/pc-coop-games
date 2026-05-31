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
from append_entry import render_entry, previously_removed_ids, insert_entry, atomic_write_text
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
        # One malformed entry (missing field via KeyError, or no real video_id
        # via render_entry's ValueError) must NOT abort the batch and discard the
        # entries already inserted in memory — skip it and keep going.
        try:
            gid = g["id"]
            if re.search(r'id:\s*"' + re.escape(gid) + r'"', content):
                skipped.append(f"{gid} (duplicate)")
                continue
            # Gate: same game under a different slug — dedupe by Steam app_id too
            # (e.g. lego-skywalker-saga vs lego-star-wars-skywalker-saga, app 920210).
            app_id = g.get("app_id")
            if not app_id:
                m = re.search(r"app/(\d+)", g.get("storeUrl", ""))
                if m:
                    app_id = m.group(1)
            if app_id and re.search(r"app/" + re.escape(str(app_id)) + r"/", content):
                skipped.append(f"{gid} (duplicate app_id {app_id})")
                continue
            # Gate: never re-add a game previously removed as endless.
            if gid in removed_ids:
                skipped.append(f"{gid} (previously_removed_endless)")
                continue
            # Gate: render_entry raises ValueError without a real video_id.
            new_entry = render_entry(g) + ","
        except (ValueError, KeyError) as e:
            skipped.append(f"{g.get('id', '<no id>')} (rejected: {e})")
            continue
        new_content = insert_entry(content, new_entry)
        if new_content is None:
            print(f"ERROR: couldn't find insertion point for {gid}", file=sys.stderr)
            sys.exit(2)
        content = new_content
        added.append(gid)

    atomic_write_text(DATA_JS, content)
    print(f"Added {len(added)}: {added}")
    if skipped:
        print(f"Skipped {len(skipped)} (already present): {skipped}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Append a new game entry to data.js immediately before the first hidden block
(or before the closing array bracket if no hidden games exist).

Usage:
    python append_entry.py < entry.json

Stdin = JSON object matching the shape in SKILL.md.

Returns 0 on success, 1 if id already present (no-op), 2 on error.
"""

import sys
import json
import re
from pathlib import Path

DATA_JS = Path(__file__).resolve().parents[3].parent / "data.js"
REMOVED_TSV = Path(__file__).resolve().parents[1] / "state" / "removed-entries.tsv"


def previously_removed_ids():
    """Return set of ids ever auto-removed by remove_entry.py.

    Any id in this file was once judged endless and must never be re-added,
    even if a later source disagrees. This is the secondary gate behind the
    classification.md hardcoded blocklist (§0 of SKILL.md).
    """
    if not REMOVED_TSV.exists():
        return set()
    ids = set()
    for i, line in enumerate(REMOVED_TSV.read_text(encoding="utf-8").splitlines()):
        if i == 0 or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1]:
            ids.add(parts[1])
    return ids


def render_entry(g):
    """Render a game dict into JS object literal text matching existing style."""
    def js_str(s):
        return '"' + (s or "").replace("\\", "\\\\").replace('"', '\\"') + '"'

    def js_arr(a):
        return "[" + ", ".join(js_str(x) for x in a) + "]"

    # imageUrl: prefer the steamImage helper if app_id is given; else literal
    if g.get("app_id"):
        image_expr = f"steamImage({g['app_id']})"
    else:
        image_expr = js_str(g.get("imageUrl", ""))

    # youtubeUrl: ONLY a real 11-char YouTube video id is accepted.
    # The table opens a modal with the YouTube iframe; a search URL cannot be
    # embedded. Silent youtubeSearch(...) fallback was the root cause of the
    # 88 broken placeholders — explicit reject is the fix.
    youtube_id = g.get("youtube_id")
    if not youtube_id and g.get("youtubeUrl", "").startswith('youtube("'):
        # Allow passing a pre-rendered youtube("ID") helper string.
        m = re.match(r'^youtube\("([A-Za-z0-9_-]{11})"\)$', g["youtubeUrl"])
        if m:
            youtube_id = m.group(1)
    if not youtube_id or not re.match(r'^[A-Za-z0-9_-]{11}$', youtube_id):
        raise ValueError(
            f"refusing to add '{g.get('id')}': a real 11-char YouTube video_id is "
            f"required (got youtube_id={g.get('youtube_id')!r}, "
            f"youtubeUrl={g.get('youtubeUrl')!r}). Drill the search per SKILL.md §8."
        )
    yt_expr = f'youtube("{youtube_id}")'

    needs_review = g.get("needs_review") or g.get("needs-review")
    review_line = ',\n    "needs-review": true' if needs_review else ""

    # NOTE: data shape was trimmed in 2026-05. We no longer store ratingSource,
    # ratingLabel, playersLabel, or hoursLabel. Rating is always Steam %positive
    # (see CLAUDE.md section "Data shape" for rationale). Do not re-add those
    # fields.
    return f"""  {{
    id: {js_str(g["id"])},
    title: {js_str(g["title"])},
    year: {int(g["year"])},
    genres: {js_arr(g["genres"])},
    endingType: {js_str(g["endingType"])},
    rating: {int(g["rating"])},
    playersMax: {int(g["playersMax"])},
    hours: {int(round(float(g["hours"])))},
    oneCopy: {js_str(g["oneCopy"])},
    price: {int(g["price"])},
    verdict: {js_str(g["verdict"])},
    storeUrl: {js_str(g["storeUrl"])},
    imageUrl: {image_expr},
    youtubeUrl: {yt_expr}{review_line}
  }}"""


def main():
    try:
        g = json.load(sys.stdin)
    except Exception as e:
        print(f"ERROR: invalid JSON on stdin: {e}", file=sys.stderr)
        sys.exit(2)

    if not DATA_JS.exists():
        print(f"ERROR: data.js not found at {DATA_JS}", file=sys.stderr)
        sys.exit(2)

    content = DATA_JS.read_text(encoding="utf-8")

    # Check duplicate by id
    if re.search(r'id:\s*"' + re.escape(g["id"]) + r'"', content):
        print(f"SKIP: id '{g['id']}' already present", file=sys.stderr)
        sys.exit(1)

    # Reject ids that were previously auto-removed as endless. The skill ran
    # itself in circles earlier (removed and re-added the same 16 endless
    # games an hour apart); this gate prevents that.
    if g["id"] in previously_removed_ids():
        print(f"BLOCKED: id '{g['id']}' was previously removed as endless — refusing to re-add", file=sys.stderr)
        sys.exit(3)

    try:
        new_entry = render_entry(g) + ","
    except ValueError as e:
        print(f"REJECT: {e}", file=sys.stderr)
        sys.exit(4)

    # Insert before the first "hidden: true" block.
    # Find the opening brace of the entry that contains hidden: true and back up.
    # Strategy: match "  {\n    id: ...,\n    ...\n    hidden: true," — find the line where the parent entry starts.
    # Simpler: find the entry blocks; insert before the first entry that has hidden: true.

    # Split into entries by top-level `  {` and `  },` patterns. Risky to do regex parsing of JS.
    # Pragmatic: find "    hidden: true," string, then back up to the most recent "  {" before it.

    match = re.search(r'\n  \{\n(?:[^{}]*?)\n    hidden:\s*true', content)
    if match:
        # Insert before "\n  {"
        insert_pos = match.start() + 1  # after the leading \n
        # Insert as ",\n  {...new entry...},\n"
        # But the previous entry already ends with "},\n" so we just need "  {new}\n,\n"
        # Existing pattern is:
        # ...
        # },
        # {
        #   hidden game...
        # We want to insert between "}," and "{ hidden" lines.
        new_content = content[:insert_pos] + new_entry + "\n" + content[insert_pos:]
    else:
        # No hidden block. Insert before the closing "];".
        end_match = re.search(r'\n\];\s*$', content)
        if not end_match:
            print("ERROR: couldn't find closing ']' of games array", file=sys.stderr)
            sys.exit(2)
        # Add a comma to the last entry (replace its "}\n];" with "},\n  {new}\n];")
        # Last entry ends with "  }\n];" — replace with "  },\n<new>\n];"
        new_content = re.sub(
            r'\n  \}\n\];',
            f'\n  }},\n{new_entry}\n];',
            content,
            count=1
        )
        if new_content == content:
            print("ERROR: couldn't find insertion point", file=sys.stderr)
            sys.exit(2)

    DATA_JS.write_text(new_content, encoding="utf-8")
    print(f"OK: appended '{g['id']}'")


if __name__ == "__main__":
    main()

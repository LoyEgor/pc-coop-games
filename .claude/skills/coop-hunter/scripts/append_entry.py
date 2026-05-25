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

    # youtubeUrl: prefer youtube("ID") helper if youtube_id provided; else fallback
    if g.get("youtube_id"):
        yt_expr = f'youtube("{g["youtube_id"]}")'
    elif g.get("youtubeUrl", "").startswith("youtube") or g.get("youtubeUrl", "").startswith("youtubeSearch"):
        yt_expr = g["youtubeUrl"]
    else:
        # last resort — wrap as search
        yt_expr = f'youtubeSearch({js_str(g.get("title", ""))})'

    needs_review = g.get("needs_review") or g.get("needs-review")
    review_line = '\n    "needs-review": true,' if needs_review else ""

    return f"""  {{
    id: {js_str(g["id"])},
    title: {js_str(g["title"])},
    year: {int(g["year"])},
    genres: {js_arr(g["genres"])},
    endingType: {js_str(g["endingType"])},
    rating: {int(g["rating"])},
    ratingSource: {js_str(g["ratingSource"])},
    ratingLabel: {js_str(g["ratingLabel"])},
    playersMax: {int(g["playersMax"])},
    playersLabel: {js_str(g["playersLabel"])},
    hours: {g["hours"]},
    hoursLabel: {js_str(g["hoursLabel"])},
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

    new_entry = render_entry(g) + ","

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

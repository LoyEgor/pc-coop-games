#!/usr/bin/env python3
"""
Iterate non-hidden entries in data.js. Output JSON.

Usage:
    python list_entries.py            # emit JSON array of ALL non-hidden entries
    python list_entries.py <idx>      # emit ONE entry at non-hidden index (0-based)
    python list_entries.py --count    # print total non-hidden count

Each emitted entry includes its derived `app_id` (extracted from steamImage helper
or storeUrl regex) so the fact-checker doesn't have to re-parse.
"""

import sys
import re
import json
from pathlib import Path

DATA_JS = Path(__file__).resolve().parents[3].parent / "data.js"


def parse_entries():
    """Parse data.js into a list of dicts representing each entry.

    Lightweight regex parser — adequate for our schema (well-formed, indented 2sp,
    one key per line). Returns entries in source order.
    """
    text = DATA_JS.read_text(encoding="utf-8")

    # Each entry starts with "  {" at column 0 (well, 2sp indent) and ends with
    # "  }," or "  }". Captures the body.
    pattern = re.compile(r"\n  \{\n(.*?)\n  \},?", re.DOTALL)

    entries = []
    for m in pattern.finditer(text):
        body = m.group(1)
        entry = {}
        for line in body.split("\n"):
            stripped = line.strip().rstrip(",")
            if not stripped or ":" not in stripped:
                continue
            key, _, value = stripped.partition(":")
            key = key.strip().strip('"')
            value = value.strip()
            entry[key] = value
        # Derive app_id
        app_id = None
        if "imageUrl" in entry:
            m_img = re.search(r"steamImage\((\d+)\)", entry["imageUrl"])
            if m_img:
                app_id = int(m_img.group(1))
        if app_id is None and "storeUrl" in entry:
            m_url = re.search(r"app/(\d+)/", entry["storeUrl"])
            if m_url:
                app_id = int(m_url.group(1))
        entry["__app_id"] = app_id
        # Strip quotes from string values, keep raw for genres/arrays
        for k, v in list(entry.items()):
            if isinstance(v, str) and v.startswith('"') and v.endswith('"'):
                entry[k] = v[1:-1]
        entries.append(entry)
    return entries


def is_hidden(entry):
    return entry.get("hidden") == "true"


def main():
    args = sys.argv[1:]
    entries = [e for e in parse_entries() if not is_hidden(e)]

    if args and args[0] == "--count":
        print(len(entries))
        return

    if args:
        try:
            idx = int(args[0])
        except ValueError:
            print(f"ERROR: '{args[0]}' is not an integer index", file=sys.stderr)
            sys.exit(2)
        if idx < 0 or idx >= len(entries):
            print(f"ERROR: index {idx} out of range [0, {len(entries)})", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(entries[idx], ensure_ascii=False))
        return

    print(json.dumps(entries, ensure_ascii=False))


if __name__ == "__main__":
    main()

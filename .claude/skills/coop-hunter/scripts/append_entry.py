#!/usr/bin/env python3
"""
Append a new game entry to data.js immediately before the first hidden block
(or before the closing array bracket if no hidden games exist).

Usage:
    python append_entry.py < entry.json

Stdin = JSON object matching the shape in SKILL.md.

Returns 0 on success, 1 if id already present (no-op), 2 on error.
"""

import os
import sys
import json
import re
from pathlib import Path

DATA_JS = Path(__file__).resolve().parents[3].parent / "data.js"
REMOVED_TSV = Path(__file__).resolve().parents[1] / "state" / "removed-entries.tsv"


def atomic_write_text(path, text):
    """Write `text` to `path` atomically: write a sibling temp file, then
    os.replace (atomic on the same filesystem). A crash mid-write can no longer
    truncate data.js — the original stays intact until the rename succeeds."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def insert_entry(content, entry_text):
    """Insert a rendered, comma-terminated entry into the GAMES array.

    Inserts immediately before the first `hidden: true` entry, else before the
    closing `];`. Located line-by-line (not via a `[^{}]` regex) so a `{` or `}`
    inside a verdict/title string can't break the match. Returns the new content,
    or None if no insertion point could be found.
    """
    lines = content.split("\n")
    hidden_idx = next(
        (i for i, l in enumerate(lines) if re.match(r"\s*hidden:\s*true", l)),
        None,
    )
    if hidden_idx is not None:
        # Back up from the hidden field to its entry's opening `{`.
        open_idx = next(
            (j for j in range(hidden_idx, -1, -1) if lines[j].strip() == "{"),
            None,
        )
        if open_idx is not None:
            lines[open_idx:open_idx] = entry_text.split("\n")
            return "\n".join(lines)
    # No hidden block (or its opening couldn't be located): append before `];`,
    # moving the trailing comma onto what was previously the last entry.
    new_content = re.sub(r"\n  \}\n\];", f"\n  }},\n{entry_text}\n];", content, count=1)
    return new_content if new_content != content else None


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

    def js_int(v):
        # Round defensively: a value arriving as "87.6" or 8.5 becomes a clean
        # integer instead of crashing int() (only `hours` was protected before).
        return int(round(float(v)))

    # imageUrl: prefer Steam's authoritative header_image (a literal URL, with
    # the ?t= cache-buster stripped). The legacy steamImage() CDN path
    # `/steam/apps/<id>/header.jpg` is GONE for newer apps (hard 404), so it is
    # only a last-resort fallback when no resolved header_image is available.
    header_image = g.get("header_image") or ""
    raw_image = g.get("imageUrl", "") or ""
    literal_url = ""
    if isinstance(header_image, str) and header_image.startswith("http"):
        literal_url = header_image.split("?")[0]
    elif isinstance(raw_image, str) and raw_image.startswith("http"):
        literal_url = raw_image.split("?")[0]

    if literal_url:
        image_expr = js_str(literal_url)
    elif g.get("app_id"):
        image_expr = f"steamImage({g['app_id']})"
    else:
        # The skill sometimes passes the helper call itself as a literal string
        # (e.g. "steamImage(429660)"). Quoting that makes it a string value, so
        # the UI renders a broken <img src>. Emit it as a bare call instead.
        m = re.match(r"^steamImage\((\d+)\)$", raw_image.strip()) if isinstance(raw_image, str) else None
        image_expr = f"steamImage({m.group(1)})" if m else js_str(raw_image)

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
    year: {js_int(g["year"])},
    genres: {js_arr(g["genres"])},
    endingType: {js_str(g["endingType"])},
    rating: {js_int(g["rating"])},
    playersMax: {js_int(g["playersMax"])},
    hours: {js_int(g["hours"])},
    oneCopy: {js_str(g["oneCopy"])},
    price: {js_int(g["price"])},
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

    # Check duplicate by Steam app_id. The SAME game can arrive under a different
    # slug (e.g. lego-skywalker-saga vs lego-star-wars-skywalker-saga, both app
    # 920210) — the id check above misses that, which is exactly how duplicates
    # slipped in. Match the app id from app_id or the storeUrl.
    app_id = g.get("app_id")
    if not app_id:
        m = re.search(r"app/(\d+)", g.get("storeUrl", ""))
        if m:
            app_id = m.group(1)
    if app_id and re.search(r"app/" + re.escape(str(app_id)) + r"/", content):
        print(f"SKIP: app_id {app_id} already present under another slug", file=sys.stderr)
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
        # exit 4 stays the video_id gate (SKILL.md §8): a missing/invalid
        # 11-char id is the only ValueError render_entry raises deliberately.
        print(f"REJECT: {e}", file=sys.stderr)
        sys.exit(4)
    except KeyError as e:
        print(f"ERROR: '{g.get('id')}' is missing required field {e}", file=sys.stderr)
        sys.exit(2)

    new_content = insert_entry(content, new_entry)
    if new_content is None:
        print("ERROR: couldn't find insertion point in data.js", file=sys.stderr)
        sys.exit(2)

    atomic_write_text(DATA_JS, new_content)
    print(f"OK: appended '{g['id']}'")


if __name__ == "__main__":
    main()

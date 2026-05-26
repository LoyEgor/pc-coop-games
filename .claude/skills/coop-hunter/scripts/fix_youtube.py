#!/usr/bin/env python3
"""
Replace the youtubeUrl line of an existing data.js entry with a real video.

Usage:
    python fix_youtube.py <id> <video_id>

<video_id> is the 11-char YouTube id (the part after ?v= in a watch URL).
Replaces the entry's youtubeUrl line (whether it was `youtube("...")` or
`youtubeSearch("...")`) with `youtubeUrl: youtube("<video_id>")`.

Logs each fix to state/youtube-fixes.tsv.

Exits 0 on success, 1 if id not found, 2 on error.
"""

import sys
import re
import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3].parent
DATA_JS = REPO_ROOT / "data.js"
LOG_TSV = REPO_ROOT / ".claude" / "skills" / "coop-hunter" / "state" / "youtube-fixes.tsv"

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def ensure_log_header():
    LOG_TSV.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_TSV.exists():
        LOG_TSV.write_text(
            "timestamp\tid\told_url_kind\tnew_video_id\n", encoding="utf-8"
        )


def fix(content, game_id, video_id):
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
        m = re.match(r"^(\s*)youtubeUrl:\s*(youtube(?:Search)?)\(", lines[j])
        if not m:
            continue
        indent = m.group(1)
        kind = m.group(2)
        trailing = "," if lines[j].rstrip().endswith(",") else ""
        lines[j] = f'{indent}youtubeUrl: youtube("{video_id}"){trailing}'
        return "\n".join(lines), kind

    return None, None


def main():
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    game_id, video_id = sys.argv[1], sys.argv[2]
    if not VIDEO_ID_RE.match(video_id):
        print(f"ERROR: '{video_id}' is not a valid 11-char YouTube id", file=sys.stderr)
        sys.exit(2)
    if not DATA_JS.exists():
        print(f"ERROR: data.js not found at {DATA_JS}", file=sys.stderr)
        sys.exit(2)

    content = DATA_JS.read_text(encoding="utf-8")
    new_content, old_kind = fix(content, game_id, video_id)
    if new_content is None:
        print(f"NOT FOUND: '{game_id}' has no replaceable youtubeUrl line", file=sys.stderr)
        sys.exit(1)

    DATA_JS.write_text(new_content, encoding="utf-8")
    ensure_log_header()
    with LOG_TSV.open("a", encoding="utf-8") as f:
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        f.write(f"{ts}\t{game_id}\t{old_kind}\t{video_id}\n")
    print(f"OK: {game_id} {old_kind}(...) -> youtube({video_id})")


if __name__ == "__main__":
    main()

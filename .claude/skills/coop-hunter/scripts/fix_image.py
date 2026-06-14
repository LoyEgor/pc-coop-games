#!/usr/bin/env python3
"""
Repoint the imageUrl of an existing data.js entry to the most DURABLE reachable
Steam header image, written as a literal URL.

Usage:
    python fix_image.py <id> <app_id>

Durable-image policy (SHARED with .github/scripts/refresh.py — keep in sync):
  1. Prefer the hash-less CDN path `cdn.cloudflare.steamstatic.com/steam/apps/
     <id>/header.jpg` when it HEAD-200s. It carries NO content hash, so it cannot
     go stale when a dev re-uploads header art (the recurring 404 cause).
  2. Fall back to appdetails `header_image` (the hashed store_item_assets form,
     ?t= stripped) ONLY for the ~44 newest apps where hash-less still 404s.

Both candidates are HEAD-verified (2xx/3xx) before writing. The earlier code
ALWAYS stored the hashed header_image, so a healed entry re-broke on the next art
update — this preference inversion is the fix for that round-trip.

The change is recorded in data.js itself (git diff is the log).

Exits 0 on success, 1 if id not found in data.js, 3 if no usable header image
could be resolved (caller should log `no_image`), 2 on usage/other error.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3].parent
DATA_JS = REPO_ROOT / "data.js"

UA = "Mozilla/5.0 (compatible; pc-coop-games-coop-hunter/1.0)"
HTTP_TIMEOUT = 20


def atomic_write_text(path, text):
    """Write atomically (temp file + os.replace) so a crash mid-write can't
    truncate data.js."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)




def resolve_header_image(app_id):
    """Fetch appdetails (basic filter) and return header_image with the ?t=
    cache-buster stripped, or None if the app/image is unavailable."""
    url = (
        f"https://store.steampowered.com/api/appdetails"
        f"?appids={app_id}&filters=basic"
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        data = json.loads(r.read().decode("utf-8")).get(str(app_id), {})
    if not data.get("success"):
        return None
    header = (data.get("data") or {}).get("header_image")
    return header.split("?")[0] if header else None


def hashless_url(app_id):
    """The hash-less CDN path. It has NO content hash, so it can never go stale
    when a dev re-uploads header art — the durable choice for established apps."""
    return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"


def durable_image_url(app_id):
    """Pick the most durable reachable header URL. SHARED healing policy with
    .github/scripts/refresh.py — keep the two in sync so they converge on the
    same url instead of ping-ponging an entry across commits.

    1. hash-less `cdn.cloudflare/steam/apps/<id>/header.jpg` if it 200s — it has
       no hash in the path, so it survives future art updates (immortal).
    2. else the fresh appdetails `header_image` (hashed) — the ONLY form that
       exists for the ~44 newest apps, where hash-less still 404s.
    Returns None if neither is reachable.
    """
    hl = hashless_url(app_id)
    if url_ok(hl):
        return hl
    canon = resolve_header_image(app_id)
    if canon and url_ok(canon):
        return canon
    return None


def url_ok(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return 200 <= r.status < 400
    except (urllib.error.URLError, OSError):
        return False


def fix(content, game_id, new_url):
    lines = content.split("\n")
    target = f'id: "{game_id}"'
    id_line = next((i for i, l in enumerate(lines) if target in l), None)
    if id_line is None:
        return None, None
    end = next(
        (i for i in range(id_line, len(lines)) if lines[i].strip() in ("}", "},")),
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
        literal = '"' + new_url.replace("\\", "\\\\").replace('"', '\\"') + '"'
        lines[j] = f"{indent}imageUrl: {literal}{trailing}"
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

    try:
        new_url = durable_image_url(app_id)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        print(f"ERROR: appdetails fetch failed for app {app_id}: {e}", file=sys.stderr)
        sys.exit(3)
    if not new_url:
        print(f"NO IMAGE: no usable header image for app {app_id}", file=sys.stderr)
        sys.exit(3)

    content = DATA_JS.read_text(encoding="utf-8")
    new_content, old_kind = fix(content, game_id, new_url)
    if new_content is None:
        print(f"NOT FOUND: '{game_id}' has no replaceable imageUrl line", file=sys.stderr)
        sys.exit(1)

    atomic_write_text(DATA_JS, new_content)
    # No separate fix-log — the change is in data.js; git diff is the record.
    print(f"OK: {game_id} {old_kind} -> {new_url}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Repoint the previewUrl of an existing data.js entry to a freshly-derived, live
Steam microtrailer.mp4. The hover-preview counterpart of fix_image.py.

Usage:
    python fix_preview.py <id> <app_id>

Preview-derivation policy (SHARED with .github/scripts/refresh.py.derive_preview_url
and append_entry.py.derive_preview — keep the three in sync so the cron, the
write-guard and this healer converge on the same url instead of ping-ponging):
  - appdetails advertises only adaptive manifests; the directory that serves the
    first trailer's HLS manifest (movies[0].hls_h264) also serves a flat
    progressive `microtrailer.mp4`. Strip the manifest filename + ?t= and append
    microtrailer.mp4. The akamai url embeds a content-hash that DRIFTS when the
    dev re-uploads the trailer (same drift class as the hashed header image), so
    the live url must be re-derived, not trusted.
  - The candidate is HEAD-verified (200 + video content-type) before writing.

The write goes through update_field.py (insert-or-replace + https validation),
the same path the cron uses, so the field stays consistently formatted.

Exits 0 on success — either re-pointed to a live trailer OR cleared to "" when the
app has no trailer at all (the client then falls back to screenshots/header and
lint stops re-reporting a dead url). Exit 1 if previewUrl not writable, 3 only when
a trailer IS listed but no live mp4 resolved (transient/region — leave as-is, retry
later), 2 on usage/other error.
"""

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parents[2].parent
DATA_JS = REPO_ROOT / "data.js"
UPDATE_FIELD = REPO_ROOT / ".claude" / "skills" / "fact-checker" / "scripts" / "update_field.py"

UA = "Mozilla/5.0 (compatible; pc-coop-games-coop-hunter/1.0)"
HTTP_TIMEOUT = 20


def appdetails_movies(app_id):
    """Fetch appdetails with the movies filter; return the movies list (or [])."""
    url = (
        f"https://store.steampowered.com/api/appdetails"
        f"?appids={app_id}&filters=basic,movies"
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        data = json.loads(r.read().decode("utf-8")).get(str(app_id), {})
    if not data.get("success"):
        return []
    return (data.get("data") or {}).get("movies") or []


def derive_preview_url(movies):
    if not movies:
        return None
    hls = movies[0].get("hls_h264") or ""
    if not hls:
        return None
    directory = hls.split("?", 1)[0].rsplit("/", 1)[0]
    return f"{directory}/microtrailer.mp4"


def head_video_ok(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return r.status == 200 and "video" in (r.headers.get("Content-Type") or "")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return False


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
        movies = appdetails_movies(app_id)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        print(f"ERROR: appdetails fetch failed for app {app_id}: {e}", file=sys.stderr)
        sys.exit(3)

    new_url = derive_preview_url(movies)
    if new_url and head_video_ok(new_url):
        write_value = new_url            # re-point to the live (re-uploaded/reordered) trailer
    elif not movies:
        write_value = ""                 # trailer pulled entirely → clear so the client falls
                                         # back and lint stops re-reporting a dead url (fixes F)
    else:
        # A trailer is listed but no live mp4 resolved (transient/region) — leave the
        # stored url as-is and let a later run retry; don't clear a real trailer.
        print(f"NO PREVIEW: trailer listed but no live microtrailer for app {app_id} (transient?)", file=sys.stderr)
        sys.exit(3)

    r = subprocess.run(
        ["python3", str(UPDATE_FIELD), game_id, "previewUrl", write_value],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"NOT FOUND: '{game_id}' previewUrl not writable :: {(r.stderr or r.stdout).strip()[:120]}", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {game_id} previewUrl -> {write_value or '(cleared)'}")


if __name__ == "__main__":
    main()

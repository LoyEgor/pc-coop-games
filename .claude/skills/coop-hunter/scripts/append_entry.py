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
import urllib.error
import urllib.request
from pathlib import Path

DATA_JS = Path(__file__).resolve().parents[3].parent / "data.js"
UA = "Mozilla/5.0 (compatible; pc-coop-games-coop-hunter/1.0)"


def _url_ok(url):
    """HEAD a CDN url; True on 2xx/3xx. Best-effort — any network error returns
    False so the caller treats it as 'unverified', never as a hard failure."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 400
    except (urllib.error.URLError, OSError):
        return False


def durable_image_expr(app_id, literal_url):
    """Pick the most DURABLE reachable image, SOFT-verified. SHARED policy with
    fix_image.py / refresh.py: hash-less `cdn.cloudflare/steam/apps/<id>/
    header.jpg` first (no hash -> can't drift), else the passed hashed
    header_image (the only form for the ~44 newest apps). Returns a literal URL
    string, or None when nothing verifies (caller writes its best guess anyway —
    the cron + client onerror fallback are the safety net). Never blocks an add:
    a transient HEAD failure must not drop a real game."""
    if not app_id:
        return None
    hashless = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"
    try:
        if _url_ok(hashless):
            return hashless
        if literal_url and _url_ok(literal_url):
            return literal_url
    except (urllib.error.URLError, OSError):
        return None
    return None
SHARED = Path(__file__).resolve().parents[2] / "shared"
HARDBLOCK_TSV = SHARED / "hard-block.tsv"   # never re-add these (mechanical)
REEVAL_TSV = SHARED / "reeval.tsv"          # re-checkable; drop an id once it enters the catalog


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
    """Return set of ids that are HARD-BLOCKED (mechanically impossible — no co-op /
    PvP-only / not on Steam / MMO / delisted). These must never be added.

    NOTE: this is intentionally ONLY the hard-block list. Games on `reeval.tsv`
    (endless-by-judgment, Early Access, low rating, etc.) are RE-CHECKABLE — they
    are allowed to be added when they now qualify, so they are NOT a gate here.
    """
    if not HARDBLOCK_TSV.exists():
        return set()
    ids = set()
    for i, line in enumerate(HARDBLOCK_TSV.read_text(encoding="utf-8").splitlines()):
        if i == 0 or not line.strip():
            continue
        parts = line.split("\t")
        if parts and parts[0]:
            ids.add(parts[0])
    return ids


def drop_from_reeval(game_id):
    """Once a game enters the catalog it must leave reeval (one-place invariant)."""
    if not REEVAL_TSV.exists():
        return
    lines = REEVAL_TSV.read_text(encoding="utf-8").splitlines()
    kept = [lines[0]] if lines else []
    kept += [ln for ln in lines[1:] if ln.strip() and ln.split("\t")[0] != game_id]
    REEVAL_TSV.write_text("\n".join(kept) + "\n", encoding="utf-8")


def render_entry(g):
    """Render a game dict into JS object literal text matching existing style."""
    def js_str(s):
        # json.dumps emits a fully-escaped JSON/JS string literal: it handles
        # \n \t \r \" \\ and other control chars. The hand-rolled version only
        # escaped backslash + double-quote, so a real newline (a JSON "\n" on
        # stdin decodes to one) produced an invalid JS literal and broke the
        # line-based insert_entry. ensure_ascii=False keeps Unicode readable in
        # data.js — the soft-finish marker 🟠 and accented titles stay as-is
        # instead of becoming \uXXXX escapes.
        return json.dumps(s or "", ensure_ascii=False)

    def js_arr(a):
        return "[" + ", ".join(js_str(x) for x in a) + "]"

    def js_int(v):
        # Round defensively: a value arriving as "87.6" or 8.5 becomes a clean
        # integer instead of crashing int() (only `hours` was protected before).
        # A present-but-null ("rating": null) or non-numeric ("year": "soon")
        # field would raise TypeError/ValueError from float(); re-raise as a
        # single TypeError with a clear message so main() can map it to the
        # generic data-error exit (2), NOT exit 1 (no-op) or exit 4 (video gate).
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            raise TypeError(f"non-numeric value {v!r} for a numeric field")

    # imageUrl: write the most DURABLE reachable url (write-guard so a new entry
    # is never born broken). durable_image_expr SOFT-verifies (HEAD) and prefers
    # the hash-less form (can't drift) over the hashed header_image; it only
    # falls back to the hashed form for the ~44 newest apps where hash-less 404s.
    # If nothing verifies (e.g. transient network), we still WRITE the best guess
    # — the daily cron + the client onerror fallback heal it; an add is never
    # blocked on an image HEAD.
    app_id = g.get("app_id")
    if not app_id:
        m_store = re.search(r"app/(\d+)", g.get("storeUrl", "") or "")
        app_id = m_store.group(1) if m_store else None

    header_image = g.get("header_image") or ""
    raw_image = g.get("imageUrl", "") or ""
    literal_url = ""
    if isinstance(header_image, str) and header_image.startswith("http"):
        literal_url = header_image.split("?")[0]
    elif isinstance(raw_image, str) and raw_image.startswith("http"):
        literal_url = raw_image.split("?")[0]

    durable = durable_image_expr(app_id, literal_url)
    if durable:
        image_expr = js_str(durable)
    elif literal_url:
        image_expr = js_str(literal_url)
        if app_id:
            print(f"WARNING: image for '{g.get('id')}' unverified, writing anyway: {literal_url}", file=sys.stderr)
    elif app_id:
        image_expr = f"steamImage({app_id})"
        print(f"WARNING: image for '{g.get('id')}' falls back to steamImage({app_id}) (may 404 for new apps)", file=sys.stderr)
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

    # ratingCount = Steam total_reviews. Optional at insert time (the cron /
    # backfill fills it if absent), but the skill SHOULD pass it — it already
    # fetches total_reviews to compute %positive. Powers the site's Wilson score.
    rating_count = g.get("ratingCount") or g.get("rating_count") or g.get("total_reviews")
    count_line = f"\n    ratingCount: {js_int(rating_count)}," if rating_count not in (None, "") else ""

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
    rating: {js_int(g["rating"])},{count_line}
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
    if app_id and re.search(r"app/" + re.escape(str(app_id)) + r"(?:/|\"|\?|$)", content):
        print(f"SKIP: app_id {app_id} already present under another slug", file=sys.stderr)
        sys.exit(1)

    # Reject ids that were previously auto-removed as endless. The skill ran
    # itself in circles earlier (removed and re-added the same 16 endless
    # games an hour apart); this gate prevents that.
    if g["id"] in previously_removed_ids():
        print(f"BLOCKED: id '{g['id']}' was previously removed as endless — refusing to re-add", file=sys.stderr)
        sys.exit(3)

    # Enforce the ≤120-char verdict cap (CLAUDE.md §4, both SKILL.md). Validate
    # HERE — before render_entry — and exit 2 (generic data error), NOT a bare
    # ValueError: render_entry's only deliberate ValueError is the YouTube
    # video-id gate, which main() maps to exit 4. A verdict-length ValueError
    # would be caught by that branch and mis-exit 4. Count display chars (the
    # 🟠 soft-finish marker is one char; Python len() already treats it as 1).
    verdict = g.get("verdict") or ""
    if len(verdict) > 120:
        print(
            f"ERROR: verdict too long ({len(verdict)}>120): {verdict!r}",
            file=sys.stderr,
        )
        sys.exit(2)

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
    except TypeError as e:
        # A null/non-numeric numeric field (rating/year/price/hours/playersMax).
        # Must NOT fall through to the bare exit 1 (which means "already present,
        # no-op" and would silently lose the candidate), and must NOT hit exit 4
        # (reserved for the video-id gate). Generic data error → exit 2.
        print(f"ERROR: '{g.get('id')}' has a bad numeric field: {e}", file=sys.stderr)
        sys.exit(2)

    new_content = insert_entry(content, new_entry)
    if new_content is None:
        print("ERROR: couldn't find insertion point in data.js", file=sys.stderr)
        sys.exit(2)

    atomic_write_text(DATA_JS, new_content)
    drop_from_reeval(g["id"])  # one-place invariant: now in the catalog, leave reeval
    print(f"OK: appended '{g['id']}'")


if __name__ == "__main__":
    main()

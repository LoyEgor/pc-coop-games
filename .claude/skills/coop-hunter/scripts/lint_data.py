#!/usr/bin/env python3
"""
Deterministic, no-LLM media guard for data.js. Verifies every entry's header
image is reachable and every youtubeUrl carries a real 11-char video id, and can
auto-heal broken images via the shared healer (fix_image.py). This is the guard
the owner asked for: any LLM run that adds/edits games is FORCED to heal media
through it (the launchers run `lint_data.py --changed --fix`), the same way
sync_lists.py enforces the state-list invariant.

It pairs with two other layers (see CLAUDE.md §4):
  - write-time: append_entry.py soft-verifies + prefers the durable image url;
  - daily cron: .github/scripts/refresh.py heals 404 / hash-drift;
  - client:    app.js renderRow has an <img> onerror host-swap fallback.

Usage:
    python3 lint_data.py [--changed] [--fix] [--deep-youtube]
                         [--workers N] [--timeout S] [--base REF]

    (no flags)      lint ALL non-hidden entries, detect-only, NO writes
    --changed       lint only entries whose `id:` line changed vs --base (git
                    diff) — sub-second fast path after a hunter burst
    --fix           heal DEAD images via fix_image.py, then re-lint the healed
                    subset (advisory: still exits 1 if anything stays broken)
    --deep-youtube  also HEAD i.ytimg.com to detect DEAD (removed) videos, not
                    just MALFORMED ids (default: regex-only, zero network)
    --base REF      git ref to diff against for --changed (default: HEAD)
    --workers N     concurrent HEAD workers (default 16)
    --timeout S     per-HEAD timeout seconds (default 8)

Classification (images and, with --deep-youtube, videos):
    OK       final HTTP 2xx/3xx
    DEAD     final HTTP 404/410 (real breakage)            -> counts to exit 1
    UNKNOWN  network error / timeout / 5xx (NOT broken)    -> never healed
youtube ids are MALFORMED when they aren't a bare 11-char youtube("...") id
(catches youtubeSearch/truncated placeholders, zero network)  -> counts to exit 1

Exit codes:
    0  clean (no DEAD/MALFORMED)
    1  real breakage remains (DEAD image / DEAD or MALFORMED youtube)
    2  usage / parse error (data.js unreadable, etc.)
    3  INCONCLUSIVE: >50% of image probes were UNKNOWN (network down) — do not
       trust the result, do not let --fix run; matches refresh.py's mass_no_data

stdout: one TSV row per breakage  ->  <id>\t<app_id>\t<image|youtube>\t<status>\t<url>
stderr: human summary counts (+ HEALED/IRRECOVERABLE lines under --fix)

Stdlib only.
"""

import argparse
import concurrent.futures
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parents[2].parent
DATA_JS = REPO_ROOT / "data.js"
LIST_ENTRIES = REPO_ROOT / ".claude" / "skills" / "fact-checker" / "scripts" / "list_entries.py"
FIX_IMAGE = SCRIPTS / "fix_image.py"

UA = "Mozilla/5.0 (compatible; pc-coop-games-lint/1.0)"
YT_ID_RE = re.compile(r'youtube\("([A-Za-z0-9_-]{11})"\)')
STEAMIMAGE_RE = re.compile(r"steamImage\((\d+)\)")


def list_entries():
    out = subprocess.check_output(["python3", str(LIST_ENTRIES)])
    return json.loads(out.decode("utf-8"))


def rendered_image_url(entry):
    """The url the browser actually requests, matching refresh.py.current_image_url:
    steamImage(<id>) -> cdn.cloudflare hash-less; a literal http(s) url -> as-is."""
    raw = entry.get("imageUrl", "") or ""
    m = STEAMIMAGE_RE.search(raw)
    if m:
        return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{m.group(1)}/header.jpg"
    if raw.startswith("http"):
        return raw
    return None


def host_swap(url):
    """A same-path mirror on a different CDN host, to tell a real 404 from a
    one-host edge blip. shared.* hosts mirror the hashed store_item_assets path;
    cdn.* hosts mirror the hash-less path."""
    if "/store_item_assets/" in url:
        if "shared.akamai." in url:
            return url.replace("shared.akamai.", "shared.fastly.")
        if "shared.fastly." in url:
            return url.replace("shared.fastly.", "shared.akamai.")
        if "shared.cloudflare." in url:
            return url.replace("shared.cloudflare.", "shared.akamai.")
    else:
        if "cdn.cloudflare." in url:
            return url.replace("cdn.cloudflare.", "cdn.akamai.")
        if "cdn.akamai." in url:
            return url.replace("cdn.akamai.", "cdn.cloudflare.")
    return None


def head_status(url, timeout):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def classify(url, timeout):
    """OK / DEAD / UNKNOWN with one host-swap retry so a single flaky edge isn't
    mislabelled a dead asset."""
    st = head_status(url, timeout)
    if st is not None and 200 <= st < 400:
        return "OK"
    if st in (404, 410):
        alt = host_swap(url)
        if alt:
            st2 = head_status(alt, timeout)
            if st2 is not None and 200 <= st2 < 400:
                return "OK"  # original host blipped; the asset exists -> not dead
        return "DEAD"
    return "UNKNOWN"  # None / timeout / 5xx — a network flake, never auto-healed


def changed_ids(base):
    """Set of ids whose `id:` line was added/removed in `git diff <base> data.js`."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "diff", "-U0", base, "--", "data.js"],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", "replace")
    except subprocess.CalledProcessError:
        return None  # caller falls back to all
    ids = set()
    for line in out.splitlines():
        if line[:1] in "+-":
            m = re.search(r'id:\s*"([^"]+)"', line)
            if m:
                ids.add(m.group(1))
    return ids


def lint(entries, args):
    """Returns (image_results, youtube_results) as lists of (entry, kind, status, url)
    for everything that is NOT OK."""
    # --- youtube (regex always; HEAD only with --deep-youtube) ---
    yt_break = []
    deep_targets = []
    for e in entries:
        raw = e.get("youtubeUrl", "") or ""
        m = YT_ID_RE.search(raw)
        if not m:
            yt_break.append((e, "youtube", "MALFORMED", raw[:60]))
        elif args.deep_youtube:
            vid = m.group(1)
            deep_targets.append((e, f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"))

    # --- images (concurrent HEAD) ---
    img_targets = []
    for e in entries:
        url = rendered_image_url(e)
        if url:
            img_targets.append((e, url))
        else:
            yt_break.append((e, "image", "MALFORMED", e.get("imageUrl", "")[:60]))

    img_break = []
    unknown = 0
    targets = img_targets + deep_targets
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(classify, url, args.timeout): (e, url, kind)
                for (e, url), kind in (
                    [(t, "image") for t in img_targets] + [(t, "youtube") for t in deep_targets]
                )}
        for fut in concurrent.futures.as_completed(futs):
            e, url, kind = futs[fut]
            status = fut.result()
            if status == "OK":
                continue
            if status == "UNKNOWN":
                unknown += 1
                continue
            if kind == "image":
                img_break.append((e, "image", status, url))
            else:
                yt_break.append((e, "youtube", "DEAD", url))

    return img_break, yt_break, unknown, len(targets)


def heal_images(img_break, args):
    """Run fix_image.py for each DEAD image; return (healed_ids, still_broken)."""
    healed, still = [], []
    for e, _kind, _status, _url in img_break:
        gid = e.get("id")
        app_id = e.get("__app_id")
        if not gid or not app_id:
            still.append(e)
            print(f"IRRECOVERABLE {gid} image (no app_id)", file=sys.stderr)
            continue
        r = subprocess.run(["python3", str(FIX_IMAGE), gid, str(app_id)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            healed.append(gid)
            print(f"HEALED {gid} image -> {r.stdout.strip().split('-> ')[-1]}", file=sys.stderr)
        else:
            still.append(e)
            print(f"IRRECOVERABLE {gid} image :: {(r.stderr or r.stdout).strip()[:120]}", file=sys.stderr)
    return healed, still


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--changed", action="store_true")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--deep-youtube", action="store_true")
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--timeout", type=float, default=8.0)
    args = ap.parse_args()

    if not DATA_JS.exists():
        print(f"ERROR: data.js not found at {DATA_JS}", file=sys.stderr)
        sys.exit(2)

    try:
        entries = list_entries()
    except Exception as e:
        print(f"ERROR: list_entries failed: {e}", file=sys.stderr)
        sys.exit(2)

    if args.changed:
        ids = changed_ids(args.base)
        if ids is not None:
            entries = [e for e in entries if e.get("id") in ids]
        # ids is None (no git) -> lint all; empty set -> nothing changed -> clean
    if not entries:
        print("lint_data: no entries to check (clean).", file=sys.stderr)
        sys.exit(0)

    img_break, yt_break, unknown, probed = lint(entries, args)

    # INCONCLUSIVE: too much of the network came back UNKNOWN -> don't trust it.
    if probed and unknown / probed > 0.50:
        print(f"INCONCLUSIVE: {unknown}/{probed} probes UNKNOWN (network down?) — not trusting result, not fixing.", file=sys.stderr)
        sys.exit(3)

    if args.fix and img_break:
        dead_ids = {e.get("id") for (e, _k, _s, _u) in img_break}
        heal_images(img_break, args)  # performs the writes; prints HEALED/IRRECOVERABLE
        # Re-read data.js (writes happened) and re-lint ONLY the originally-dead
        # set; whatever is still DEAD stays as breakage.
        try:
            fresh = list_entries()
        except Exception:
            fresh = entries
        recheck = [e for e in fresh if e.get("id") in dead_ids]
        img_break, _yt2, _u2, _p2 = lint(recheck, argparse.Namespace(
            deep_youtube=False, workers=args.workers, timeout=args.timeout))

    breakage = img_break + yt_break
    for e, kind, status, url in breakage:
        print(f"{e.get('id')}\t{e.get('__app_id')}\t{kind}\t{status}\t{url}")

    n_img = sum(1 for b in breakage if b[1] == "image")
    n_yt = sum(1 for b in breakage if b[1] == "youtube")
    print(f"lint_data: checked {len(entries)} entries | image breakage={n_img} "
          f"youtube breakage={n_yt} unknown(net)={unknown}", file=sys.stderr)

    sys.exit(1 if breakage else 0)


if __name__ == "__main__":
    main()

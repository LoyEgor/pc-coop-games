#!/usr/bin/env python3
"""
Refresh `price` and `rating` for every non-hidden entry in data.js by hitting
Steam's storefront API (cc=ua) and appreviews endpoint. Designed to run on a
GitHub Actions cron — see .github/workflows/refresh-prices.yml.

This script OWNS the OBJECTIVE fields — those with a Steam-API ground truth.
The LLM skills (coop-hunter, fact-checker) must NOT write these; they only verify
the cron ran and fix THIS script if it derives something wrong. Objective fields:
  - `price`    (UAH, from /api/appdetails?cc=ua → price_overview.final / 100)
  - `rating`   (Steam %positive, from /appreviews/<id>?json=1)
  - `year`     (release year, from /api/appdetails → release_date; applied on any diff)
  - `oneCopy`  (from /api/appdetails → categories: Online/LAN Co-op → 'none';
                else only Remote Play Together / Shared-Split-Screen → 'remote-play'.
                NEVER overrides a stored 'friend-pass' — that is store-DLC text, not a
                category, so it can't be derived here.)
  - `imageUrl` (auto-heals header images that 404 OR whose content-hash drifted
                — a dev re-uploading header art changes the hash in a hashed
                store_item_assets URL and the old one 404s. Heals to the DURABLE
                hash-less `cdn.cloudflare/steam/apps/<id>/header.jpg` when it 200s
                (no hash -> never drifts again), else the fresh hashed
                header_image for the newest apps. Shared policy with
                fix_image.py.)

Drift / breakage thresholds (match fact-checker conservative auto-fix):
  - rating: apply update if |new - old| >= 5pp
  - price:  apply update if relative |new - old| / old >= 10%
  - image:  replace when the CURRENT image hard-404/410s OR its content-hash
            differs from the fresh header_image (drift, even if still 200 via
            edge cache); a 301 redirect still renders, so it's left alone

For NEW entries: this script never inserts. The coop-hunter skill does that,
including the initial price/rating values.

After every run (success OR failure) the script writes
`.github/refresh-status.json` with a timestamp + counts. Both skills read this
to decide whether to skip price/rating checks (cron healthy) or do them
themselves (cron stale/missing).

Re-uses helpers:
  - .claude/skills/fact-checker/scripts/list_entries.py  (iterate)
  - .claude/skills/fact-checker/scripts/update_field.py  (write)

Stdlib only. No third-party packages.

Exit 0 on success (with or without updates), 1 if any unrecoverable error.
"""

import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS_FILE = REPO_ROOT / ".github" / "refresh-status.json"
LIST_ENTRIES = REPO_ROOT / ".claude" / "skills" / "fact-checker" / "scripts" / "list_entries.py"
UPDATE_FIELD = REPO_ROOT / ".claude" / "skills" / "fact-checker" / "scripts" / "update_field.py"

UA = "Mozilla/5.0 (compatible; pc-coop-games-refresh-bot/1.0)"
SLEEP_BETWEEN_CALLS = 1.0  # seconds; Steam's IP rate-limit needs a small pause
RATING_DRIFT_PP = 2         # apply rating update if >= 2pp drift. Tightened from
                            # 5pp: %positive is a stable ratio so this adds almost
                            # no commit noise, and a stale rating skews the site's
                            # Wilson score (computed from rating + ratingCount).
PRICE_DRIFT_REL = 0.10      # apply price update if >= 10% relative drift
COUNT_DRIFT_REL = 0.12      # apply ratingCount update if >= 12% relative drift.
                            # Wilson barely moves at large n, so a coarse count is
                            # fine — keeps data.js diffs small even though a
                            # popular game gains reviews every day.
HTTP_TIMEOUT = 20

# Limits for one cron run — if Steam returns errors past these caps,
# log and exit gracefully so the heartbeat still gets written.
MAX_CONSECUTIVE_FAILURES = 10


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def appdetails(app_id):
    url = (
        f"https://store.steampowered.com/api/appdetails"
        f"?appids={app_id}&cc=ua&filters=basic,price_overview,categories,release_date,movies"
    )
    data = fetch_json(url).get(str(app_id), {})
    if not data.get("success"):
        return None
    return data.get("data")


def appreviews(app_id):
    url = (
        f"https://store.steampowered.com/appreviews/{app_id}"
        f"?json=1&language=all&purchase_type=all&filter=summary"
    )
    return fetch_json(url).get("query_summary", {})


def compute_rating(reviews_summary):
    total = reviews_summary.get("total_reviews", 0)
    positive = reviews_summary.get("total_positive", 0)
    if total < 50:  # too few to trust; same threshold as coop-hunter §3
        return None
    return round(positive / total * 100)


def derive_year(details):
    """Release year from appdetails release_date (objective ground truth)."""
    m = re.search(r"(\d{4})", (details or {}).get("release_date", {}).get("date", "") or "")
    if m:
        y = int(m.group(1))
        if 1990 <= y <= 2030:
            return y
    return None


def derive_preview_url(details):
    """microtrailer.mp4 url for the hover preview — the SAME ~6s muted loop Steam's
    own store/library capsules autoplay. Derived from the first trailer's HLS dir:
    appdetails advertises only adaptive manifests (hls/dash), but the directory
    that serves the manifest also serves a flat progressive `microtrailer.mp4`
    (CORS-open: access-control-allow-origin:*, so it plays from github.io). The
    akamai dir carries a content hash + timestamp that DRIFTS when the dev
    re-uploads the trailer — the same drift class as the hashed header image — so
    this is cron-maintained, never frozen. The ?t= cache-buster is stripped for a
    stable stored URL. Returns None when the game ships no trailer."""
    movies = (details or {}).get("movies") or []
    if not movies:
        return None
    hls = movies[0].get("hls_h264") or ""
    if not hls:
        return None
    directory = hls.split("?", 1)[0].rsplit("/", 1)[0]
    return f"{directory}/microtrailer.mp4"


def all_preview_urls(details):
    """The microtrailer.mp4 url for EVERY trailer the app currently lists (not just
    movies[0]). The state-based heal uses membership in this set to tell a harmless
    REORDER (stored url still present → keep, no churn) from a pull / re-upload
    (stored url gone → re-point or clear). Pure string derivation from the already-
    fetched movies — no extra network."""
    urls = set()
    for m in (details or {}).get("movies") or []:
        hls = m.get("hls_h264") or ""
        if hls:
            urls.add(f"{hls.split('?', 1)[0].rsplit('/', 1)[0]}/microtrailer.mp4")
    return urls


def head_video_ok(url):
    """True only if the URL HEADs 200 with a video content-type. Used to soft-verify
    a freshly-derived microtrailer before writing it, so a derived-but-dead url is
    never stored (the client then keeps the static header / screenshot fallback)."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return r.status == 200 and "video" in (r.headers.get("Content-Type") or "")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return False


def derive_onecopy(details):
    """oneCopy from appdetails categories (objective): Online/LAN Co-op -> 'none';
    else only Remote Play Together / Shared-Split-Screen -> 'remote-play'. Returns
    None when undeterminable (leave the stored value). Never returns 'friend-pass'
    (store-DLC text, not a category) so a stored friend-pass is never overwritten."""
    cats = [c.get("description", "") for c in (details or {}).get("categories", [])]
    if any("Online Co-op" in c or "LAN Co-op" in c for c in cats):
        return "none"
    if any(c == "Remote Play Together" or "Shared/Split Screen Co-op" in c for c in cats):
        return "remote-play"
    return None


def head_status(url):
    """HEAD a URL following redirects; return the final HTTP status (or None on
    a network error). A browser follows redirects on <img>, so a 301 to a live
    asset is NOT broken — only a final 404/410 is."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def current_image_url(entry):
    """The URL the page actually renders. The stored imageUrl is either a
    steamImage(<id>) helper call (legacy CDN path) or a literal URL string."""
    raw = entry.get("imageUrl", "") or ""
    m = re.search(r"steamImage\((\d+)\)", raw)
    if m:
        return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{m.group(1)}/header.jpg"
    if raw.startswith("http"):
        return raw
    return None


def canonical_image_url(details):
    """Steam's authoritative header image (already in `details` via the basic
    filter), with the ?t= cache-buster stripped for a stable stored URL. NOTE:
    appdetails ALWAYS returns the hashed store_item_assets form — the drift-prone
    one — so this is only a fallback; durable_image_url prefers the hash-less."""
    header = (details or {}).get("header_image")
    if not header:
        return None
    return header.split("?")[0]


def hashless_url(app_id):
    """Hash-less CDN path — no content hash, so it can't go stale on art updates."""
    return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"


_HASH_RE = re.compile(r"/store_item_assets/steam/apps/\d+/([0-9a-f]{8,})/header")


def stored_hash(url):
    """The content-hash embedded in a hashed store_item_assets URL, or None for
    a hash-less url (which therefore cannot drift)."""
    m = _HASH_RE.search(url or "")
    return m.group(1) if m else None


def durable_image_url(app_id, details):
    """Most durable reachable header url. SHARED policy with
    .claude/skills/coop-hunter/scripts/fix_image.py — keep the two in sync so the
    cron and the skill converge on the same url instead of fighting:
      1. hash-less (immortal) when it 200s;
      2. else the fresh appdetails header_image (hashed) for the newest apps.
    """
    hl = hashless_url(app_id)
    if head_status(hl) == 200:
        return hl
    canon = canonical_image_url(details)
    if canon and head_status(canon) == 200:
        return canon
    return None


def list_entries():
    out = subprocess.check_output(["python3", str(LIST_ENTRIES)])
    return json.loads(out.decode("utf-8"))


def apply_update(game_id, field, new_value):
    """Call update_field.py to actually edit data.js. Returns True on success."""
    result = subprocess.run(
        ["python3", str(UPDATE_FIELD), game_id, field, str(new_value)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  ! update_field.py failed for {game_id}.{field}: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def write_status(success, entries_checked, updates, failures, error=None):
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "owned_fields": ["price", "rating", "ratingCount", "year", "oneCopy", "imageUrl", "previewUrl"],
        "next_expected_window_hours": 30,
        "entries_checked": entries_checked,
        "updates_applied": updates,
        "fetch_failures": failures,
    }
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    if success:
        payload["last_success"] = ts
        # Preserve last_failure if present, just don't update it
        if STATUS_FILE.exists():
            try:
                prev = json.loads(STATUS_FILE.read_text())
                if prev.get("last_failure"):
                    payload["last_failure"] = prev["last_failure"]
            except (json.JSONDecodeError, OSError):
                pass
    else:
        payload["last_failure"] = ts
        payload["last_failure_error"] = error or "unknown"
        if STATUS_FILE.exists():
            try:
                prev = json.loads(STATUS_FILE.read_text())
                if prev.get("last_success"):
                    payload["last_success"] = prev["last_success"]
            except (json.JSONDecodeError, OSError):
                pass
    STATUS_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main():
    print(f"[{datetime.datetime.utcnow().isoformat()}Z] Refresh started")

    try:
        entries = list_entries()
    except Exception as e:
        print(f"FATAL: list_entries failed: {e}", file=sys.stderr)
        write_status(False, 0, {"price": 0, "rating": 0, "count": 0, "image": 0, "preview": 0, "year": 0, "oneCopy": 0}, 0, error=f"list_entries: {e}")
        sys.exit(1)

    print(f"Loaded {len(entries)} non-hidden entries from data.js")

    updates = {"price": 0, "rating": 0, "count": 0, "image": 0, "preview": 0, "year": 0, "oneCopy": 0}
    failures = 0
    consecutive_failures = 0
    checked = 0

    for i, entry in enumerate(entries, 1):
        game_id = entry.get("id")
        app_id = entry.get("__app_id")
        if not game_id or not app_id:
            print(f"  [{i}/{len(entries)}] SKIP {game_id!r}: no app_id derivable")
            continue

        try:
            time.sleep(SLEEP_BETWEEN_CALLS)
            details = appdetails(app_id)
            time.sleep(SLEEP_BETWEEN_CALLS)
            reviews = appreviews(app_id)
            consecutive_failures = 0
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as e:
            failures += 1
            consecutive_failures += 1
            print(f"  [{i}/{len(entries)}] FAIL {game_id} (app {app_id}): {e}")
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"FATAL: {consecutive_failures} consecutive failures — aborting", file=sys.stderr)
                write_status(False, checked, updates, failures, error=f"too_many_failures:{consecutive_failures}")
                sys.exit(1)
            continue
        except Exception as e:
            # An unexpected payload shape (e.g. a missing key) for ONE entry must
            # never abort the whole run: the heartbeat written at the end is what
            # tells the skills the cron is alive. Count it, log it, move on.
            failures += 1
            print(f"  [{i}/{len(entries)}] ERROR {game_id} (app {app_id}): {type(e).__name__}: {e}")
            continue

        # Soft failure: Steam frequently throttles with HTTP 200 + success:false
        # (appdetails -> None) and an empty review summary (appreviews -> {}), so
        # NO exception fires. If BOTH come back empty there is nothing to verify
        # for this entry — count it like a real failure so a mass-throttled run
        # is reported unhealthy instead of "all good".
        if not details and not reviews:
            failures += 1
            consecutive_failures += 1
            print(f"  [{i}/{len(entries)}] NO-DATA {game_id} (app {app_id}): appdetails+appreviews both empty (likely throttled)")
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"FATAL: {consecutive_failures} consecutive failures — aborting", file=sys.stderr)
                write_status(False, checked, updates, failures, error=f"too_many_failures:{consecutive_failures}")
                sys.exit(1)
            continue

        checked += 1

        # Price drift — only trust a UAH price_overview with a numeric `final`.
        # cc=ua can fall back to another currency for region-restricted apps;
        # writing that as UAH would be wrong, so skip anything that isn't UAH.
        po = details.get("price_overview") if details else None
        if po and po.get("currency") == "UAH":
            # Use the REGULAR (pre-discount) price so a Steam sale doesn't make
            # the cron commit the sale price and then revert it when the sale
            # ends. `initial` is the full price; `final` is post-discount and is
            # only a fallback when `initial` is absent/0.
            raw_price = po.get("initial") or 0
            if not isinstance(raw_price, int) or raw_price <= 0:
                raw_price = po.get("final") or 0
            new_price = round(raw_price / 100) if isinstance(raw_price, int) else 0
            # Never overwrite with 0 (free weekend / 100%-off promo). Skip the
            # price this run rather than freezing the catalog at 0 forever.
            if new_price > 0:
                try:
                    old_price = int(entry.get("price", 0))
                except (ValueError, TypeError):
                    old_price = 0
                if old_price > 0:
                    rel_drift = abs(new_price - old_price) / old_price
                    if rel_drift >= PRICE_DRIFT_REL:
                        if apply_update(game_id, "price", new_price):
                            updates["price"] += 1
                            print(f"  [{i}/{len(entries)}] {game_id}: price {old_price} -> {new_price} ({rel_drift*100:.0f}% drift)")

        # Rating drift
        new_rating = compute_rating(reviews)
        if new_rating is not None:
            try:
                old_rating = int(entry.get("rating", 0))
            except (ValueError, TypeError):
                old_rating = 0
            if abs(new_rating - old_rating) >= RATING_DRIFT_PP:
                if apply_update(game_id, "rating", new_rating):
                    updates["rating"] += 1
                    print(f"  [{i}/{len(entries)}] {game_id}: rating {old_rating} -> {new_rating} ({abs(new_rating-old_rating)}pp drift)")

        # Review count — the site computes a Wilson lower-bound score (Steam
        # %positive discounted for sample size) from `rating` + `ratingCount`.
        # The exact count isn't needed (Wilson is flat at large n), so rewrite
        # only on >= COUNT_DRIFT_REL relative change. update_field.py inserts the
        # field on entries that predate it. Never write 0 (throttle / no reviews)
        # over a real stored count.
        new_count = reviews.get("total_reviews", 0) if reviews else 0
        if isinstance(new_count, int) and new_count > 0:
            try:
                old_count = int(entry.get("ratingCount", 0) or 0)
            except (ValueError, TypeError):
                old_count = 0
            if old_count <= 0 or abs(new_count - old_count) / old_count >= COUNT_DRIFT_REL:
                if apply_update(game_id, "ratingCount", new_count):
                    updates["count"] += 1
                    print(f"  [{i}/{len(entries)}] {game_id}: ratingCount {old_count or '-'} -> {new_count}")

        # Image healing. Two triggers, both using `details` already fetched above
        # (the durable HEAD adds at most one CDN request, only when healing):
        #   - hard break: the current url 404/410s; OR
        #   - hash drift: the stored content-hash differs from the fresh
        #     header_image hash EVEN IF the old url still 200s. From GitHub's
        #     healthy network a stale hashed url can still 200 via edge cache
        #     while the user (different PoP) sees the new art or a 404 — this is
        #     the only way the cron catches that. Hash-less urls have no hash, so
        #     stored_hash() is None and they're correctly skipped (can't drift).
        # The replacement is the DURABLE form (hash-less if reachable), so a
        # healed entry doesn't re-break on the next art update.
        cur_img = current_image_url(entry)
        canon_img = canonical_image_url(details)
        sh, ch = stored_hash(cur_img), stored_hash(canon_img)
        drifted = bool(sh and ch and sh != ch)
        broken = head_status(cur_img) in (404, 410) if cur_img else False
        if cur_img and (broken or drifted):
            new_img = durable_image_url(app_id, details)
            if new_img and new_img != cur_img:
                if apply_update(game_id, "imageUrl", new_img):
                    updates["image"] += 1
                    why = "404" if broken else "hash-drift"
                    print(f"  [{i}/{len(entries)}] {game_id}: image {why} -> {new_img}")

        # Preview microtrailer — STATE-BASED heal (mirrors the image heal's intent;
        # see WHY-6). The akamai url carries a content hash/timestamp that changes
        # when the dev re-uploads OR reorders trailers, so a naive "movies[0] differs
        # → rewrite" churns the field on a harmless reorder. Instead: keep the stored
        # url while it's still one of the app's CURRENT trailers (set membership —
        # pure string, no HEAD); only act when it's GONE from that set — re-point to a
        # live trailer (pull/re-upload), or CLEAR to "" when the app has no trailer at
        # all (so the client falls back and lint/fix_preview stop re-reporting a dead
        # url forever). When there's no stored url yet, backfill if a trailer exists.
        cur_prev = entry.get("previewUrl") or ""
        if cur_prev.startswith("http"):
            if cur_prev not in all_preview_urls(details):
                fresh_prev = derive_preview_url(details)
                if fresh_prev and head_video_ok(fresh_prev):
                    if apply_update(game_id, "previewUrl", fresh_prev):
                        updates["preview"] += 1
                        print(f"  [{i}/{len(entries)}] {game_id}: preview re-point -> {fresh_prev}")
                elif not (details.get("movies") or []):
                    # trailer pulled entirely — clear (a present-but-dead HEAD or a
                    # transient miss with movies still listed is left for next run).
                    if apply_update(game_id, "previewUrl", ""):
                        updates["preview"] += 1
                        print(f"  [{i}/{len(entries)}] {game_id}: preview cleared (no trailer)")
        else:
            fresh_prev = derive_preview_url(details)
            if fresh_prev and head_video_ok(fresh_prev):
                if apply_update(game_id, "previewUrl", fresh_prev):
                    updates["preview"] += 1
                    print(f"  [{i}/{len(entries)}] {game_id}: preview backfill -> {fresh_prev}")

        # Year — objective ground truth (release_date). Apply on any real diff.
        new_year = derive_year(details)
        if new_year is not None:
            try:
                old_year = int(entry.get("year", 0) or 0)
            except (ValueError, TypeError):
                old_year = 0
            if old_year and new_year != old_year:
                if apply_update(game_id, "year", new_year):
                    updates["year"] += 1
                    print(f"  [{i}/{len(entries)}] {game_id}: year {old_year} -> {new_year}")

        # oneCopy — objective (categories). none<->remote-play only; never touch friend-pass.
        new_oc = derive_onecopy(details)
        old_oc = entry.get("oneCopy")
        if new_oc and old_oc and old_oc != "friend-pass" and new_oc != old_oc:
            if apply_update(game_id, "oneCopy", new_oc):
                updates["oneCopy"] += 1
                print(f"  [{i}/{len(entries)}] {game_id}: oneCopy {old_oc} -> {new_oc}")

    print(f"\n[{datetime.datetime.utcnow().isoformat()}Z] Refresh complete")
    print(f"  entries_checked: {checked}/{len(entries)}")
    print(f"  updates_applied: price={updates['price']}, rating={updates['rating']}, count={updates['count']}, image={updates['image']}, preview={updates['preview']}, year={updates['year']}, oneCopy={updates['oneCopy']}")
    print(f"  fetch_failures:  {failures}")

    # A run is only healthy if we actually verified something. If every attempt
    # returned no data (checked==0) or more than half the attempted entries came
    # back empty/failed, Steam was throttling us — mark the heartbeat unhealthy
    # so the skills run their own price/rating checks instead of trusting it.
    attempted = checked + failures
    nodata_ratio = (failures / attempted) if attempted else 1.0
    if checked == 0 or nodata_ratio > 0.50:
        error = f"mass_no_data:{failures}/{attempted}_failed" if attempted else "no_entries_attempted"
        print(f"UNHEALTHY: {error} (checked={checked}, nodata_ratio={nodata_ratio:.0%})", file=sys.stderr)
        write_status(False, checked, updates, failures, error=error)
        sys.exit(1)

    write_status(True, checked, updates, failures)


if __name__ == "__main__":
    main()

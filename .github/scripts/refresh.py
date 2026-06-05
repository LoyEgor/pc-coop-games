#!/usr/bin/env python3
"""
Refresh `price` and `rating` for every non-hidden entry in data.js by hitting
Steam's storefront API (cc=ua) and appreviews endpoint. Designed to run on a
GitHub Actions cron — see .github/workflows/refresh-prices.yml.

This script OWNS the drift-prone / breakable fields:
  - `price`    (UAH, from /api/appdetails?cc=ua → price_overview.final / 100)
  - `rating`   (Steam %positive, from /appreviews/<id>?json=1)
  - `imageUrl` (auto-heals header images that 404 — the legacy steamImage() CDN
                path `/steam/apps/<id>/header.jpg` is gone for newer apps; the
                authoritative URL is `header_image` from appdetails)

Drift / breakage thresholds (match fact-checker conservative auto-fix):
  - rating: apply update if |new - old| >= 5pp
  - price:  apply update if relative |new - old| / old >= 10%
  - image:  replace only when the CURRENT image is a hard 404/410 (a 301
            redirect still renders in the browser, so it's left alone)

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
RATING_DRIFT_PP = 5         # apply rating update if >= 5pp drift
PRICE_DRIFT_REL = 0.10      # apply price update if >= 10% relative drift
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
        f"?appids={app_id}&cc=ua&filters=basic,price_overview"
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
    filter), with the ?t= cache-buster stripped for a stable stored URL."""
    header = (details or {}).get("header_image")
    if not header:
        return None
    return header.split("?")[0]


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
        "owned_fields": ["price", "rating"],
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
        write_status(False, 0, {"price": 0, "rating": 0, "image": 0}, 0, error=f"list_entries: {e}")
        sys.exit(1)

    print(f"Loaded {len(entries)} non-hidden entries from data.js")

    updates = {"price": 0, "rating": 0, "image": 0}
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

        # Image healing — replace only a CURRENT image that hard-404s, so diffs
        # stay limited to actually-broken rows. canonical comes from `details`
        # (header_image, already fetched above) — no extra appdetails call.
        cur_img = current_image_url(entry)
        canon_img = canonical_image_url(details)
        if cur_img and canon_img and canon_img != cur_img and head_status(cur_img) in (404, 410):
            if apply_update(game_id, "imageUrl", canon_img):
                updates["image"] += 1
                print(f"  [{i}/{len(entries)}] {game_id}: image 404 -> {canon_img}")

    print(f"\n[{datetime.datetime.utcnow().isoformat()}Z] Refresh complete")
    print(f"  entries_checked: {checked}/{len(entries)}")
    print(f"  updates_applied: price={updates['price']}, rating={updates['rating']}, image={updates['image']}")
    print(f"  fetch_failures:  {failures}")

    write_status(True, checked, updates, failures)


if __name__ == "__main__":
    main()

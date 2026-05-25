#!/usr/bin/env python3
"""
Reusable Steam API fetcher for coop-hunter skill.

Usage:
    python steam_fetch.py search "Game Name"           # search → top result app_id
    python steam_fetch.py details <app_id>             # full appdetails (cc=ua)
    python steam_fetch.py reviews <app_id>             # %positive + sample
    python steam_fetch.py validate "Game Name"         # combined: search + details + reviews

Output is JSON to stdout. Errors → stderr + non-zero exit.

Throttled: 1.5 sec sleep before each request to avoid rate-limit.
"""

import sys
import json
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) coop-hunter/1.0"
SLEEP = 1.5


def fetch(url):
    time.sleep(SLEEP)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def search_steam(name):
    url = f"https://steamcommunity.com/actions/SearchApps/{urllib.parse.quote(name)}"
    data = json.loads(fetch(url))
    if not data:
        return None
    return {"app_id": int(data[0]["appid"]), "name": data[0]["name"]}


def get_details(app_id):
    url = (
        f"https://store.steampowered.com/api/appdetails"
        f"?appids={app_id}&cc=ua&filters=basic,price_overview,categories,genres,release_date"
    )
    raw = json.loads(fetch(url))
    entry = raw.get(str(app_id), {})
    if not entry.get("success"):
        return None
    d = entry["data"]
    po = d.get("price_overview")
    return {
        "app_id": app_id,
        "name": d.get("name"),
        "is_free": d.get("is_free", False),
        "price_uah": (po["final"] // 100) if po else (0 if d.get("is_free") else None),
        "header_image": d.get("header_image"),
        "release_date": d.get("release_date", {}).get("date"),
        "developers": d.get("developers", []),
        "publishers": d.get("publishers", []),
        "categories": [c["description"] for c in d.get("categories", [])],
        "genres": [g["description"] for g in d.get("genres", [])],
        "metacritic": d.get("metacritic", {}).get("score"),
    }


def get_reviews_summary(app_id):
    url = (
        f"https://store.steampowered.com/appreviews/{app_id}"
        f"?json=1&language=all&purchase_type=all&filter=summary"
    )
    data = json.loads(fetch(url))
    qs = data.get("query_summary", {})
    total = qs.get("total_reviews", 0)
    positive = qs.get("total_positive", 0)
    pct = (positive / total * 100) if total else None
    return {
        "total_reviews": total,
        "total_positive": positive,
        "percent_positive": round(pct, 1) if pct is not None else None,
    }


def get_reviews_sample(app_id, num=10, review_type="all"):
    url = (
        f"https://store.steampowered.com/appreviews/{app_id}"
        f"?json=1&language=all&num_per_page={num}&review_type={review_type}"
    )
    data = json.loads(fetch(url))
    reviews = data.get("reviews", []) or []
    return [
        {"voted_up": r.get("voted_up"), "text": (r.get("review") or "")[:500]}
        for r in reviews
    ]


def validate(name):
    """Combined: search → details → reviews → finite hint."""
    s = search_steam(name)
    if not s:
        return {"ok": False, "reason": "not_found", "name": name}
    app_id = s["app_id"]
    d = get_details(app_id)
    if not d:
        return {"ok": False, "reason": "invalid_app_id", "app_id": app_id, "name": name}
    rs = get_reviews_summary(app_id)
    sample = get_reviews_sample(app_id, num=10, review_type="positive")
    sample_neg = get_reviews_sample(app_id, num=10, review_type="negative")

    finite_kw = ["ending", "credits", "finished", "final boss", "beat the game", "completed"]
    endless_kw = ["endless", "no ending", "no goal", "infinite grind", "live service", "no point"]
    finite_hits = sum(
        1 for r in sample for kw in finite_kw if kw in r["text"].lower()
    )
    endless_hits = sum(
        1 for r in sample_neg for kw in endless_kw if kw in r["text"].lower()
    )

    return {
        "ok": True,
        "details": d,
        "reviews": rs,
        "finite_hits": finite_hits,
        "endless_hits": endless_hits,
        "finite_hint": "finite" if finite_hits >= 1 and endless_hits < 2 else
                       ("endless" if endless_hits >= 2 else "unclear"),
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1]
    try:
        if cmd == "search":
            print(json.dumps(search_steam(sys.argv[2]), ensure_ascii=False))
        elif cmd == "details":
            print(json.dumps(get_details(int(sys.argv[2])), ensure_ascii=False))
        elif cmd == "reviews":
            print(json.dumps(get_reviews_summary(int(sys.argv[2])), ensure_ascii=False))
        elif cmd == "validate":
            print(json.dumps(validate(sys.argv[2]), ensure_ascii=False))
        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()

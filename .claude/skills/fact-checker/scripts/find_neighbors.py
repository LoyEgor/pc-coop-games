#!/usr/bin/env python3
"""
Consistency auditor — catches classification errors with NO ground truth, by
comparing the catalog's own decisions against each other. The premise: two
near-identical games should get the same decision; a divergence is a red flag
(e.g. Forza Horizon 5 is IN the catalog while Forza Horizon 6 was SKIPPED —
same franchise, opposite decision = one of them is wrong).

Two checks:
  1. FRANCHISE conflict — games that normalize to the same franchise key but
     land on different sides (one in data.js, a sibling in skipped.tsv), OR
     same-franchise catalog entries with different endingType.
  2. SIMILARITY conflict — catalog entries with high genre-tag overlap
     (Jaccard >= 0.75, excluding tier) but different endingType.

Read-only on data.js + coop-hunter's skipped.tsv. Writes findings to
fact-checker/state/inconsistencies.tsv for the owner to review. Never modifies
data.js. Safe to run while coop-hunter is writing (data.js writes are atomic;
a missed trailing skipped.tsv line just shows up next run).

Usage:  python find_neighbors.py
"""

import re
from pathlib import Path
from itertools import combinations
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parents[3].parent
DATA_JS = REPO_ROOT / "data.js"
SHARED = REPO_ROOT / ".claude" / "skills" / "shared"
SKIPPED_TSV = SHARED / "reeval.tsv"       # re-checkable rejects (was coop-hunter/skipped.tsv)
OUT_TSV = SHARED / "owner-review.tsv"     # contradictions land in the owner's queue

TIER = {"AAA", "AA", "Indie"}
EDITION_WORDS = r"\b(definitive|anniversary|enhanced|complete|goty|remastered|reloaded|edition|deluxe|ultimate|standalone|de)\b"

# A franchise split is only a RED FLAG when the sibling was skipped on a
# SUBJECTIVE judgment that could be inconsistent with the catalog member.
# Mechanical skips (duplicate, no co-op, not on Steam, mod, VR, EA, …) are
# objective — a sibling skipped for those is NOT a contradiction.
JUDGMENT_REASONS = {
    "endless", "endless_misclassified", "unclear_ending", "ambiguous",
    "low_quality", "blocklisted_endless", "taxonomy_ambiguous",
}


def franchise_key(title):
    """Normalize a title to a franchise key: drop edition words, parentheticals,
    and trailing/standalone roman+arabic numerals. We KEEP subtitles — cutting
    at ':' over-merged setting words (e.g. 'Warhammer: Vermintide 2' and
    'Warhammer 40,000: Space Marine 2' both collapsed to 'warhammer', which are
    different games). Keeping the subtitle distinguishes them while still
    collapsing 'Forza Horizon 5' / 'Forza Horizon 6' -> 'forza horizon'."""
    t = title.lower()
    t = re.sub(r"\(.*?\)", " ", t)           # (2022), (Definitive Edition)
    t = re.sub(EDITION_WORDS, " ", t)
    t = re.sub(r"\b([ivx]+|\d+)\b", " ", t)  # roman / arabic numerals
    t = re.sub(r"[^a-z0-9 ]", " ", t)        # drop ':' , ',' etc (keeps the words)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse_catalog():
    text = DATA_JS.read_text(encoding="utf-8")
    out = []
    for b in re.findall(r"\n  \{\n(.*?)\n  \},?", text, re.DOTALL):
        if "hidden: true" in b:
            continue
        idm = re.search(r'id: "([^"]+)"', b)
        tm = re.search(r'title: "([^"]*)"', b)
        gm = re.search(r"genres:\s*\[([^\]]+)\]", b)
        em = re.search(r'endingType: "([^"]+)"', b)
        if not idm or not tm:
            continue
        tags = [t for t in re.findall(r'"([^"]+)"', gm.group(1))] if gm else []
        out.append({
            "id": idm.group(1),
            "title": tm.group(1),
            "ending": em.group(1) if em else "?",
            "tier": next((t for t in tags if t in TIER), "?"),
            "genre_set": [t for t in tags if t not in TIER],  # full set, all axes
            "fkey": franchise_key(tm.group(1)),
        })
    return out


# Every skip reason the pipeline emits — used to locate the reason column robustly
# regardless of which skipped.tsv schema a row is in (legacy 5-col put reason at
# index 2; canonical 6-col from reconcile_state.py puts it at index 4).
ALL_REASONS = JUDGMENT_REASONS | {
    "no_coop", "unclear_coop", "pvp_primary", "not_on_steam", "invalid_app_id",
    "online_broken", "not_enough_reviews", "requires_base_game", "early_access",
    "duplicate", "taxonomy_gap", "low_fit", "previously_removed_endless",
    "live_service", "live_service_borderline", "unknown",
}


def parse_skipped():
    """Read shared/reeval.tsv — schema: id, title, reason, source, notes."""
    if not SKIPPED_TSV.exists():
        return []
    out = []
    for i, line in enumerate(SKIPPED_TSV.read_text(encoding="utf-8").splitlines()):
        if i == 0 or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        name = parts[1] or parts[0]
        reason = parts[2].strip()
        if name:
            out.append({"title": name, "reason": reason, "fkey": franchise_key(name)})
    return out


def jaccard(a, b):
    A, B = set(a), set(b)
    return len(A & B) / len(A | B) if (A | B) else 0.0


def main():
    catalog = parse_catalog()
    skipped = parse_skipped()
    findings = []

    # --- 1. Franchise conflicts ---
    cat_by_fk = defaultdict(list)
    for e in catalog:
        if e["fkey"]:
            cat_by_fk[e["fkey"]].append(e)
    skip_by_fk = defaultdict(list)
    for s in skipped:
        if s["fkey"]:
            skip_by_fk[s["fkey"]].append(s)

    # 1a. same franchise: in catalog AND skipped on a JUDGMENT reason
    for fk, members in cat_by_fk.items():
        if fk not in skip_by_fk:
            continue
        judgment_skips = [s for s in skip_by_fk[fk] if s["reason"] in JUDGMENT_REASONS]
        if not judgment_skips:
            continue  # sibling skipped for a mechanical reason — not a contradiction
        in_cat = ", ".join(m["id"] for m in members)
        was_skipped = ", ".join(f'{s["title"]} ({s["reason"]})' for s in judgment_skips)
        findings.append(("franchise_split", in_cat, was_skipped,
                         f"franchise '{fk}': in catalog but a sibling was skipped on a judgment call — verify both"))

    # 1b. same franchise inside catalog with different endingType
    for fk, members in cat_by_fk.items():
        endings = {m["ending"] for m in members}
        if len(members) > 1 and len(endings) > 1:
            detail = "; ".join(f'{m["id"]}={m["ending"]}' for m in members)
            findings.append(("franchise_ending", members[0]["id"],
                             ", ".join(m["id"] for m in members[1:]),
                             f"franchise '{fk}' has mixed endingType: {detail}"))

    # NOTE: a genre-similarity check was tried and dropped — two games sharing
    # an identical small tag set (e.g. Indie+Side-view+Platformer) legitimately
    # differ in endingType (one levels, one story), so it produced 1000+ false
    # flags. Franchise siblings are the high-precision signal; structural
    # similarity is not. If revisited, it needs hours+playersMax+verdict, not
    # just tags.

    # --- write into shared/owner-review.tsv (id, action, detail) as UPSERT ---
    # owner-review also holds fix/remove rows from log_event.py — preserve those,
    # regenerate only our contradiction rows.
    OUT_TSV.parent.mkdir(parents=True, exist_ok=True)
    san = lambda s: (s or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")
    rows, order = {}, []
    if OUT_TSV.exists():
        for i, ln in enumerate(OUT_TSV.read_text(encoding="utf-8").splitlines()):
            if i == 0 or not ln.strip():
                continue
            c = ln.split("\t")
            if len(c) >= 2 and c[1] != "contradiction":   # keep fix/remove, drop old contradictions
                rows[(c[0], c[1])] = ln
                order.append((c[0], c[1]))
    for kind, a, b, detail in findings:
        # key includes kind+b so two distinct contradictions sharing the same
        # leading id (e.g. a franchise_split AND a franchise_ending on the same
        # game) don't overwrite each other.
        key = (a, "contradiction", kind, b)
        if key not in order:
            order.append(key)
        rows[key] = "\t".join([a, "contradiction", san(f"{kind}: {detail}")])
    with OUT_TSV.open("w", encoding="utf-8") as f:
        f.write("id\taction\tdetail\n")
        for k in order:
            f.write(rows[k] + "\n")

    print(f"catalog={len(catalog)} reeval={len(skipped)} -> {len(findings)} contradictions")
    print(f"  written to {OUT_TSV} (fix/remove rows preserved)")


if __name__ == "__main__":
    main()

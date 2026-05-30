#!/usr/bin/env python3
"""
Apply a hand-curated subset of proposed-fixes to data.js.

This is NOT a blanket "apply everything" — each operation below was reviewed
individually (Opus, 2026-05-30) against taxonomy.json rules, the game's actual
design, and catalog consistency. Rejected/deferred proposals are listed at the
bottom with the reason, so the decision record lives with the code.

Run:  python3 apply_proposed.py            # dry-run: report only
      python3 apply_proposed.py --apply    # rewrite data.js (+ .bak)
"""

import re
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[4] / "data.js"

# --- full genres-array replacements (genres + tier + perspective edits) ---
# tier lives at index 0, perspective at index 1, so those edits are array edits.
GENRES = {
    # genre setting/mechanic adjustments
    "borderlands-3":            ["AAA", "First-person", "Shooter", "RPG", "Loot", "Sci-fi", "Open World"],
    "borderlands-2":            ["AAA", "First-person", "Shooter", "RPG", "Loot", "Sci-fi", "Open World"],
    "vermintide-2":             ["AA", "First-person", "Action", "Fantasy"],                 # -Horror
    "gears-of-war-reloaded":    ["AAA", "Third-person", "Shooter", "Action", "Sci-fi"],
    "nuclear-throne":           ["Indie", "Isometric", "Action", "Shooter", "RPG"],
    "binding-of-isaac-rebirth": ["Indie", "Isometric", "Action", "Shooter"],
    "trine-1":                  ["AA", "Side-view", "Action", "Platformer", "Fantasy"],
    "echo-point-nova":          ["Indie", "First-person", "Shooter", "Open World"],
    "heroes-of-hammerwatch-2":  ["Indie", "Isometric", "Action", "RPG", "Fantasy"],
    "reanimal":                 ["AAA", "Side-view", "Puzzle", "Platformer", "Horror"],
    "spiritfarer":              ["Indie", "Side-view", "Adventure", "Platformer"],            # -Survival
    "that-one-otter-game":      ["Indie", "Third-person", "Platformer"],                      # -Adventure
    # tier edits (publisher-based per taxonomy)
    "grounded":                 ["AAA", "First-person", "Survival", "Open World"],            # AA->AAA (Xbox)
    "saints-row-3-remastered":  ["AA", "Third-person", "Action", "Open World"],               # AAA->AA (Deep Silver)
    "dead-island-2":            ["AA", "First-person", "Action", "RPG", "Horror"],            # AAA->AA (Deep Silver)
    # perspective edits
    "peak":                     ["Indie", "First-person", "Action"],                          # TP->FP (PEAK is FP)
    "scrapnaut":                ["Indie", "Isometric", "Action", "Sci-fi", "Survival"],       # Side->Iso (top-down)
    "inkbound":                 ["Indie", "Third-person", "RPG", "Tactics"],                  # Iso->TP
}

# --- scalar field replacements ---
ONECOPY = {
    # remote-play -> none  (Steam "Online Co-op" category verified; each needs a copy)
    "trine-5": "none", "the-ascent": "none", "darksiders-genesis": "none",
    "divinity-original-sin-2": "none", "portal-2": "none", "trine-2": "none",
    "overcooked-all-you-can-eat": "none", "metal-slug-3": "none",
    "together-moon-escape": "none", "bread-and-fred": "none", "monaco-2": "none",
    "hacktag": "none", "lego-horizon-adventures": "none", "ember-knights": "none",
    "plateup": "none", "wizard-of-legend-2": "none", "stranded-deep": "none",
    "portal-reloaded": "none", "viking-squad": "none",
    # special
    "lego-voyagers": "friend-pass",          # explicit Friend's Pass
    "renegade-ops": "remote-play",           # GFWL dead, split-screen + RPT only
    "dirt-5": "remote-play",                 # no Online Co-op, split-screen only
    "dark-pictures-man-of-medan": "remote-play",  # Friend's Pass expired; Movie Night via RPT
}
ENDINGTYPE = {
    "sniper-elite-5": "levels", "sun-haven": "story", "coral-island": "story",
    "lovers-spacetime": "levels", "aliens-fireteam-elite": "levels",
    "escape-academy": "levels", "we-were-here-together": "levels",
    "world-war-z": "levels", "ibb-and-obb": "levels",
}
HOURS = {
    "zombie-army-4": 20, "orcs-must-die-3": 16, "scott-pilgrim-the-game": 8,
    "for-the-king-2": 30, "far-cry-new-dawn": 17, "samurai-warriors-4-2": 30,
    "dynasty-warriors-8-xl": 50, "borderlands-2": 54,
}
YEAR = {"across-the-obelisk": 2022}

# --- deliberately NOT applied (decision record) ---
REJECTED = {
    "risk-of-rain-2013/oneCopy": "Steam HAS 'Online Co-op' category (verified) — 'none' is correct; proposal was wrong.",
    "defense-grid-2/hours": "32h over-counts a tower-defense; HLTB M+E uncertain, keep 12.",
    "synthetik-legion-rising/hours": "roguelite; 25 is replay-inflated. 12 = one completion run, more accurate.",
    "operation-tango/perspective": "asymmetric 2-role game; FP vs TP genuinely ambiguous, fact-checker said 'verify'. Deferred.",
    "trine-3/perspective": "proposed value 'Third-person (or discrepancy)' is not a clean value; fact-checker uncertain. Deferred.",
    "icarus/endingType": "empty proposed value + linked to a removal review; not a clean edit. Flagged for removal decision.",
    "man-of-medan/app_id": "already fixed in data.js (storeUrl already /939850/).",
    "for-the-king-2/endingType": "no-op (story->story).",
    "hammerwatch-2/endingType": "no-op (story->story).",
}


def js_array(items):
    return "[" + ", ".join(f'"{x}"' for x in items) + "]"


def main():
    apply = "--apply" in sys.argv[1:]
    text = DATA.read_text(encoding="utf-8")

    # split into entry blocks
    blocks = list(re.finditer(r"\n  \{\n.*?\n  \}(?:,|\n\])", text, re.DOTALL))
    by_id = {}
    for m in blocks:
        idm = re.search(r'id:\s*"([^"]+)"', m.group(0))
        if idm:
            by_id[idm.group(1)] = m

    applied, missing = [], []

    def edit_block(gid, transform):
        if gid not in by_id:
            missing.append(gid)
            return None
        return transform

    new_text = text

    def replace_in_entry(gid, pattern, repl, label):
        nonlocal new_text
        if gid not in by_id:
            missing.append(f"{gid} ({label})")
            return
        block = by_id[gid].group(0)
        new_block, n = re.subn(pattern, repl, block, count=1)
        if n == 0:
            missing.append(f"{gid} ({label}: pattern not found)")
            return
        new_text = new_text.replace(block, new_block, 1)
        # refresh index for this id (block text changed)
        by_id[gid] = re.search(re.escape(new_block), new_text)
        applied.append(f"{gid}: {label}")

    for gid, arr in GENRES.items():
        replace_in_entry(gid, r"genres:\s*\[[^\]]*\]", "genres: " + js_array(arr).replace("\\", "\\\\"), f"genres={js_array(arr)}")
    for gid, val in ONECOPY.items():
        replace_in_entry(gid, r'oneCopy:\s*"[^"]*"', f'oneCopy: "{val}"', f"oneCopy={val}")
    for gid, val in ENDINGTYPE.items():
        replace_in_entry(gid, r'endingType:\s*"[^"]*"', f'endingType: "{val}"', f"endingType={val}")
    for gid, val in HOURS.items():
        replace_in_entry(gid, r"hours:\s*\d+", f"hours: {val}", f"hours={val}")
    for gid, val in YEAR.items():
        replace_in_entry(gid, r"year:\s*\d+", f"year: {val}", f"year={val}")

    print(f"operations applied: {len(applied)}")
    for a in applied:
        print(f"  + {a}")
    if missing:
        print(f"\nNOT FOUND / skipped ({len(missing)}):")
        for m in missing:
            print(f"  ! {m}")

    if not apply:
        print("\n[dry-run] data.js not written. Re-run with --apply.")
        return
    DATA.with_suffix(".js.bak").write_text(text, encoding="utf-8")
    DATA.write_text(new_text, encoding="utf-8")
    print(f"\n[applied] data.js rewritten, backup at data.js.bak")


if __name__ == "__main__":
    main()

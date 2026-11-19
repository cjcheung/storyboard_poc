#!/usr/bin/env python3
"""Targeted suggestions for one slot (overrides the matcher's alternates on the storyboard).

  python3 sb.py suggest --slot s07 --text welcome --n 3 --exclude b01_012 --round 2
  python3 sb.py suggest --slot s27 --folder outdoor --category outdoor_activity --n 4 --replace-current --round 2
  python3 sb.py suggest --slot s45 --category timelapse --n 3 --round 2
  python3 sb.py suggest --slot s07 --clear                        # drop the override again

Filters are OR'd for --folder/--category (either matches) and AND'd with --text. Ranking = content fit to the slot (scoring.py)
+ bonuses (word visible on screen, close/detail framing for --text). Honors history (never/hold/per-slot rejections, locked slots),
skips clips already on the timeline in other slots, clips of the wrong orientation, and near-duplicate scenes inside the list.
Writes catalog/suggestions.json  {slot: {clips:[...], criteria, replace_current, round}}  -> read by build_storyboard.py."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P, expr, scoring
from dupes import near_duplicate_pairs

ap = argparse.ArgumentParser()
ap.add_argument("--slot", required=True)
ap.add_argument("--text", help="word that must appear in the on-screen text or summary (case-insensitive)")
ap.add_argument("--folder", help="substring of the clip's folder/path")
ap.add_argument("--category", help="catalog category (e.g. outdoor_activity, timelapse)")
ap.add_argument("--n", type=int, default=3)
ap.add_argument("--exclude", nargs="*", default=[])
ap.add_argument("--replace-current", action="store_true", help="the top result becomes the slot's current pick in the next apply/build")
ap.add_argument("--first", nargs="*", default=[], help="clip ids to place first (in this order)")
ap.add_argument("--round", type=int, default=2)
ap.add_argument("--note", help="text shown on the storyboard instead of the filter criteria")
ap.add_argument("--clear", action="store_true")
a = ap.parse_args()

path = P.CATALOG / "suggestions.json"
doc = P.load_json(path, {})
if a.clear:
    doc.pop(a.slot, None); P.save_json(path, doc); sys.exit("cleared")

slots = {s["id"]: s for s in P.slots()}
slot = slots[a.slot]
cat = expr.load(P.catalog())
g = scoring.load_gates()


def ok(c):
    if c["id"] in a.exclude or c["id"] in g["never"] or c["id"] in g["hold"] or c["id"] in g["locked_clips"]: return False
    if (a.slot, c["id"]) in g["slot_rej"] or P.orientation_mismatch(c) or "upside_down_or_rotated" in c["quality_flags"]: return False
    if g["cur_pick_of"].get(c["id"], a.slot) != a.slot: return False                 # on the timeline in another slot
    if a.text and a.text.lower() not in (c.get("visible_text", "") + " " + c["summary"]).lower(): return False
    where = [a.folder and a.folder.lower() in (c["folder"] + c["path"]).lower(), a.category and c["category"] == a.category]
    if (a.folder or a.category) and not any(where): return False
    if c["category"] != "timelapse" and not scoring.duration_ok(slot, c): return False
    return True


pool = []
for c in cat:
    if not ok(c): continue
    sc = scoring.fit_score(slot, c)
    if a.text:
        if a.text.lower() in c.get("visible_text", "").lower(): sc += 2.0              # the word is actually legible on screen
        if c["framing"] in ("close", "detail"): sc += 1.0
    pool.append((sc, c))
pool.sort(key=lambda x: -x[0])
first = {cid: i for i, cid in enumerate(a.first)}
pool.sort(key=lambda x: (first.get(x[1]["id"], 99), -x[0]))
chosen = []
for sc, c in pool:
    if all(c["category"] == "timelapse" or not near_duplicate_pairs([c, o]) for o in chosen):    # same-scene check never applies to timelapses
        chosen.append(c)
    if len(chosen) >= a.n: break
crit = " AND ".join(x for x in [a.text and f"text~'{a.text}'", (a.folder or a.category) and "(" + " OR ".join(x for x in [a.folder and f"folder~'{a.folder}'", a.category and f"category={a.category}"] if x) + ")"] if x)
doc[a.slot] = {"clips": [c["id"] for c in chosen], "criteria": a.note or crit, "replace_current": a.replace_current, "round": a.round}
P.save_json(path, doc)
print(f"{a.slot}: {len(pool)} candidates -> {len(chosen)} suggested ({crit}){' [top becomes current]' if a.replace_current else ''}")
for c in chosen:
    i, o = expr.window(slot, c)
    print(f"  {c['id']:7s} {c['file'][:34]:34s} {c['category']:16s} text='{c.get('visible_text','')[:24]}' in {i:.1f}-{o:.1f}s | {c['summary'][:48]}")

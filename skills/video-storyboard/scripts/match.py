#!/usr/bin/env python3
"""Match footage clips to the template's slots (one clip per slot, no repeats).

  python3 sb.py match --name round1          -> catalog/match_sheet_round1.json/.csv

Inputs  : the catalog (clips + tags)          catalog/slots.json (template slots, tagged)
          catalog/expression/*                 (smile / wave / good-time tags, optional)
          storyboard_project.json rules        catalog/clip_flags.json (optional)
          history/rejected_clips.csv           (never-use / hold / per-slot rejections)
          history/current_picks.json           (what is on the timeline; locked slots stay as they are)
Score   : content category + people + framing + energy + camera movement + quality, plus a bonus for
          smiles / waves / good-time shots on slots that call for them. Optimal one-to-one assignment
          (Hungarian), then in/out points centred on each clip's happiest moment.
"""
import argparse, collections, csv, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P
from dupes import near_duplicate_pairs

ap = argparse.ArgumentParser()
ap.add_argument("--name", default="proposal", help="output name: catalog/match_sheet_<name>.json/.csv")
ap.add_argument("--ignore-history", action="store_true", help="ignore rejected/locked history (regression tests only)")
args = ap.parse_args()

cat = P.catalog()
slots = {s["id"]: s for s in P.slots()}
rules = P.RULES
flags = P.clip_flags()
CHECK_RELEASES, NEEDS_GRADE = flags["check_releases"], flags["needs_grade"]
if not cat: sys.exit("the catalog is empty: scan and tag footage first (sb.py scan, merge-batch)")
untagged = [s for s in slots.values() if s.get("needs_real_footage") is None]
if untagged: print(f"note: {len(untagged)} slots are not tagged yet and are skipped: {[s['id'] for s in untagged][:10]}")

# ---------- expression data (shared helpers live in expr.py) ----------
import expr
expr.load(cat)
g_of, s_of, w_of, demand, expr_bonus, t_for = expr.g_of, expr.s_of, expr.w_of, expr.demand, expr.expr_bonus, expr.t_for

# ---------- history ----------
never, hold, slot_rej = set(), set(), set()
locked = {}
cur_pick_of = {}
if not args.ignore_history:
    rej = P.HISTORY / "rejected_clips.csv"
    if rej.exists():
        for r in csv.DictReader(open(rej, encoding="utf-8")):
            if r["scope"] == "never": never.add(r["clip_id"])
            elif r["scope"] == "hold": hold.add(r["clip_id"])
            elif r["scope"] == "slot": slot_rej.add((r["slot"], r["clip_id"]))
    for sid, p in P.picks_doc()["picks"].items():
        if p["kind"] == "footage" and sid in slots:
            cur_pick_of[p["clip"]] = sid
            if p.get("locked") or slots[sid].get("inserted"): locked[sid] = p      # inserted shots are fixed fill: not re-matched, clip kept out of other slots

import scoring

# ---------- which slots need footage ----------
locked_cats = set(rules["template_locked"]["categories"])
need = [s for s in slots.values() if s.get("needs_real_footage") and s["category"] not in locked_cats and s["id"] not in locked]
FORCED, TL_SLOTS = set(rules.get("forced_timelapses", [])), set(rules.get("timelapse_slots", []))
locked_clips = {p["clip"] for p in locked.values()}
EXCL = [(re.compile(e["pattern"], re.I) if e.get("pattern") else None, e.get("expression"), set(e.get("unless_slot_category", []))) for e in rules.get("content_exclusions", [])]
HI_FPS = rules["slow_mo"].get("requires_clip_fps_at_least", 59)


def excluded(slot, c):
    for rx, ex, unless in EXCL:
        if slot["category"] in unless: continue
        if (ex and c["vt"] and c["vt"].get("expression") == ex) or (rx and rx.search(c["summary"] + " " + c.get("notes", ""))): return True
    return False


def score(slot, c):
    if c["id"] in never or c["id"] in hold or c["id"] in locked_clips: return None
    if (slot["id"], c["id"]) in slot_rej: return None
    if "upside_down_or_rotated" in c["quality_flags"]: return None
    if c["category"] == "timelapse":
        return 13.0 if (c["id"] in FORCED and slot["id"] in TL_SLOTS) else None   # forced use on wide establishing slots
    if c["duration_s"] < slot["dur_s"] + 0.15 and not (c["fps"] >= HI_FPS and c["duration_s"] >= slot["dur_s"] / 2 + 0.15): return None
    if c["duration_s"] < slot["dur_s"] + 0.15 and c["fps"] < HI_FPS: return None
    if excluded(slot, c): return None
    if P.orientation_mismatch(c) and rules["exclude_mismatched_orientation_from_auto"]: return None
    return scoring.fit_score(slot, c)


S = [[score(s, c) for c in cat] for s in need]
INF = 1e9
n, m = len(need), len(cat)
assign = {}
if n and m:
    cost = [[(-x if x is not None else INF) for x in row] for row in S]
    if n > m:      # Hungarian below needs rows <= cols: pad with impossible dummy clips
        cost = [row + [INF] * (n - m) for row in cost]; m2 = n
    else: m2 = m
    u = [0] * (n + 1); v = [0] * (m2 + 1); p = [0] * (m2 + 1); way = [0] * (m2 + 1)
    for i in range(1, n + 1):
        p[0] = i; j0 = 0; minv = [float("inf")] * (m2 + 1); used = [False] * (m2 + 1)
        while True:
            used[j0] = True; i0 = p[j0]; delta = float("inf"); j1 = 0
            for j in range(1, m2 + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]: minv[j] = cur; way[j] = j0
                    if minv[j] < delta: delta = minv[j]; j1 = j
            for j in range(m2 + 1):
                if used[j]: u[p[j]] += delta; v[j] -= delta
                else: minv[j] -= delta
            j0 = j1
            if p[j0] == 0: break
        while True:
            j1 = way[j0]; p[j0] = p[j1]; j0 = j1
            if j0 == 0: break
    assign = {p[j] - 1: j - 1 for j in range(1, m2 + 1) if p[j] and j - 1 < m and S[p[j] - 1][j - 1] is not None}

rows = [{"slot": need[i]["id"], "i": i, "j": assign[i], "score": S[i][assign[i]]} for i in range(n) if i in assign]

# ---------- slow motion: a few high-energy / waving / laughing shots ----------
sm_rule = rules["slow_mo"]
SM_CATS = set(sm_rule.get("categories") or P.TAX.get("slow_mo_categories") or [])
cands = []
for r in rows:
    slot, c = need[r["i"]], cat[r["j"]]
    ok = (c["fps"] >= sm_rule["requires_clip_fps_at_least"] and slot["dur_s"] >= sm_rule["min_slot_seconds"] and slot["energy"] >= 3 and c["energy"] >= 3
          and not P.orientation_mismatch(c) and c["category"] != "timelapse" and (not SM_CATS or c["category"] in SM_CATS)
          and c["duration_s"] >= slot["dur_s"] / 2 + 0.2)
    if ok:
        cands.append((c["energy"] + (1 if c["hero"] else 0) + slot["energy"] * .5 + 2 * w_of(c)
                      + (2 if (c["vt"] and c["vt"]["expression"] == "laughing") else 0), r["slot"]))
slow = {sid for _, sid in sorted(cands, reverse=True)[:sm_rule["max_slots"]]}

# ---------- output ----------
chosen_ids = {cat[r["j"]]["id"] for r in rows}
on_timeline_elsewhere = lambda cid, sid: cid in cur_pick_of and cur_pick_of[cid] != sid
out = []
for r in rows:
    slot, c = need[r["i"]], cat[r["j"]]
    is_slow = slot["id"] in slow
    tb = t_for(slot, c)
    start, end = expr.window(slot, c, is_slow)
    fl = []
    if P.orientation_mismatch(c) and c["category"] != "timelapse": fl.append(P.MISMATCH_LABEL.upper() + "-needs-reframe")
    if c["category"] == "timelapse": fl.append("timelapse-needs-crop")
    if c["id"] in NEEDS_GRADE: fl.append("flat-needs-grade")
    if c["id"] in CHECK_RELEASES: fl.append("check-releases")
    alts = sorted([(S[r["i"]][jj], cat[jj]["id"]) for jj in range(len(cat))
                   if S[r["i"]][jj] is not None and cat[jj]["id"] not in chosen_ids and cat[jj]["category"] != "timelapse"
                   and not on_timeline_elsewhere(cat[jj]["id"], slot["id"])], reverse=True)[:3]
    out.append({"slot": slot["id"], "start_s": slot["start_s"], "dur_s": slot["dur_s"], "slot_kind": slot["slot_kind"], "slot_summary": slot["summary"],
                "fx_in_post": "; ".join(P.treatment_fx(slot)), "clip": c["id"], "file": c["file"], "folder": c["folder"], "fps": c["fps"],
                "speed": "50% SLOW" if is_slow else "100%", "src_in_s": start, "src_out_s": end,
                "score": round(r["score"], 2), "flags": ", ".join(fl), "clip_summary": c["summary"], "demand": demand(slot),
                "good_time": c["vt"]["good_time"] if c["vt"] else "", "waves": bool(w_of(c)), "smile_cam": bool(s_of(c) >= 1),
                "expr_note": c["vt"]["notes"] if c["vt"] else "", "alts": ", ".join(a for _, a in alts), "path": c["path"], "best_t": tb})

# near-duplicate warnings (same scene shot back-to-back) - warning only
by_id = {c["id"]: c for c in cat}
pairs = near_duplicate_pairs([by_id[o["clip"]] for o in out if by_id[o["clip"]]["category"] != "timelapse"])
dup_of = collections.defaultdict(list)
for a_, b_ in pairs:
    dup_of[a_].append(b_); dup_of[b_].append(a_)
for o in out:
    if o["clip"] in dup_of:
        o["flags"] = (o["flags"] + ", " if o["flags"] else "") + "possible-duplicate-scene-of:" + "/".join(dup_of[o["clip"]])

P.save_json(P.CATALOG / f"match_sheet_{args.name}.json", out)
if out:
    with open(P.CATALOG / f"match_sheet_{args.name}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[k for k in out[0] if k not in ("path", "best_t")], extrasaction="ignore")
        w.writeheader(); w.writerows(out)

print(f"assigned {len(out)} of {len(need)} slots | locked footage slots kept: {sorted(locked)} | unmatched: {[need[i]['id'] for i in range(n) if i not in assign]}")
print("slow-mo slots:", sorted(slow))
print("timelapses used:", [(o["clip"], o["slot"]) for o in out if by_id[o["clip"]]["category"] == "timelapse"])
print(f"{P.MISMATCH_LABEL} used:", [(o["slot"], o["clip"]) for o in out if "needs-reframe" in o["flags"]])
print("possible duplicate scenes:", sorted({tuple(sorted((a_, b_))) for a_, b_ in pairs}))
print("wrote", P.CATALOG / f"match_sheet_{args.name}.json")

#!/usr/bin/env python3
"""Bring the project records in line with what is ACTUALLY on a Resolve timeline (the user edits timelines by hand between turns).

  1. in Resolve (MCP run_script_unsafe):  CFG = dict(NAME="<timeline>", OUT="<work>/timeline_dump.json"); exec(open("<skill>/resolve/dump_timeline.resolve.py").read())
  2. python3 sb.py sync [--dump <work>/timeline_dump.json] [--timeline NAME] [--apply]       (without --apply it only prints the report)

V2 (b-roll): every item is matched to the slot it overlaps most; the slot takes the item's clip, source window, speed, zoom/pan/tilt and start/end.
Items with no slot become new inserted slots (gNN); slots with no item go to catalog/slots_removed.json (reveal slots follow the empty V2 gaps instead).
Interviews (V1/A1): start_frame, source pieces, per-piece gains, picture offsets (picture_override) and per-piece zoom (framing_pieces) are re-read from the items.
When one source file feeds several interviews, give each interview a "sync" filter in history/interviews.json:
  {"src_frames": [lo, hi]} (source frames of its pieces) and/or {"timeline_range": [a, b]} (timeline frames where it sits).
Everything is logged to history/decisions_log.csv as 'user_edit_kept'.
CAUTION: matching is by overlap in time. On a timeline that was re-ordered or heavily re-timed by hand, run the dry run first and check the report."""
import argparse, csv, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P

ap = argparse.ArgumentParser(); ap.add_argument("--dump", default=str(P.WORK / "timeline_dump.json")); ap.add_argument("--timeline"); ap.add_argument("--apply", action="store_true"); a = ap.parse_args()
D = P.load_json(a.dump); TL = a.timeline or D.get("timeline", "")
cat = P.catalog(); by_id = {c["id"]: c for c in cat}
slots = P.slots(); removed = P.load_json(P.CATALOG / "slots_removed.json", [])
doc = P.picks_doc(); picks = doc["picks"]; iv = P.load_json(P.HISTORY / "interviews.json", {})

_tail_cache = {}
def tail(p):
    """the part of a path below its footage root, so a raw-footage path, a mirrored copy and a stored catalog path all compare equal"""
    p = p or ""
    if p not in _tail_cache: _tail_cache[p] = P.strip_prefix(P.rel_path(P.abs_path(p))) if p else ""
    return _tail_cache[p]


cat_by_tail = {tail(c["path"]): c["id"] for c in cat}
FPS = float(P.FPS)
report = []

# ---------------------------------------------------------------- V2 -> slots/picks
v2 = sorted(D["video2"], key=lambda x: x["s"])
slot_by = {s["id"]: s for s in slots}
reveal = {sid for sid, p in picks.items() if p.get("interview")}
claimed, assigned = set(), []
def overlap(a0, a1, b0, b1): return max(0, min(a1, b1) - max(a0, b0))
def item_key(it):
    t = tail(it["path"] or ""); return cat_by_tail.get(t) or ("asset:" + t.split("/")[-1])
def slot_key(sid):
    p = picks.get(sid, {}); return p.get("clip") or ("asset:" + os.path.basename(p.get("asset", "")))
res = {}                                                  # item index -> slot id
# phase 1: same clip/asset and overlapping in time
for idx, it in enumerate(v2):
    cands = [(overlap(it["s"], it["e"], s["tl_start"], s["tl_end"]), s["id"]) for s in slots if s["id"] not in claimed and s["id"] not in reveal and slot_key(s["id"]) == item_key(it)]
    cands = [c for c in cands if c[0] > 0]
    if cands: o, sid = max(cands); claimed.add(sid); res[idx] = sid
# phase 2: remaining items take the free slot they overlap most
for idx, it in enumerate(v2):
    if idx in res: continue
    dur = it["e"] - it["s"]; best, bo = None, 0
    for s in slots:
        if s["id"] in claimed or s["id"] in reveal: continue
        o = overlap(it["s"], it["e"], s["tl_start"], s["tl_end"])
        if o > bo: best, bo = s, o
    if best is not None and bo >= 0.5 * min(dur, best["tl_end"] - best["tl_start"]): claimed.add(best["id"]); res[idx] = best["id"]
assigned = [(it, res.get(idx)) for idx, it in enumerate(v2)]
n_new = 0
existing_g = [int(s["id"][1:]) for s in slots + removed if s["id"].startswith("g") and s["id"][1:].isdigit()]
nxt = max(existing_g + [0]) + 1
now = datetime.date.today().isoformat(); log = []
for it, sid in assigned:
    path = it["path"] or ""; t = tail(path)
    clip = cat_by_tail.get(t)
    stored = (P.project_rel(path) or (("assets/" + path.split("/assets/")[-1]) if "/assets/" in path else "")) if path else ""
    kind = "footage" if clip else ("graphic" if stored.startswith("assets/") else None)
    if not kind: report.append(f"?? V2 item {it['s']}-{it['e']} {it['name']} not in the catalog - skipped"); continue
    fps = it["fps"] or FPS; slow = it["speed"] or 100
    new_pick = {"kind": kind, "src_in_s": round(it["ss"] / fps, 3), "src_out_s": round(it["se"] / fps, 3), "speed_percent": int(round(slow))}
    if clip: c = by_id[clip]; new_pick.update(clip=clip, file=c["file"], path=c["path"])
    else: new_pick.update(asset=stored)
    for k, key in (("zoom", "zoom"), ("pan", "pan"), ("tilt", "tilt")):
        v = it.get(key)
        if v and abs(v - (1.0 if key == "zoom" else 0.0)) > 1e-3: new_pick[k] = round(v, 3)
    if sid is None:
        sid = f"g{nxt:02d}"; nxt += 1; n_new += 1; claimed.add(sid)
        slots.append({"id": sid, "inserted": True, "start_frame": 0, "end_frame": it["e"] - it["s"], "dur_frames": it["e"] - it["s"], "start_s": 0.0, "dur_s": round((it["e"] - it["s"]) / FPS, 3), "frame_times_s": [],
                      "tl_start": it["s"], "tl_end": it["e"], "summary": (by_id[clip]["summary"] if clip else it["name"]), "slot_kind": "inserted", "category": (by_id[clip]["category"] if clip else "other"),
                      "people": (by_id[clip]["people"] if clip else "none"), "framing": (by_id[clip]["framing"] if clip else "wide"), "energy": (by_id[clip]["energy"] if clip else 3), "camera_look": (by_id[clip]["camera_look"] if clip else "unknown"),
                      "treatment": "none", "text_on_screen": "", "needs_real_footage": True, "notes": f"Added by the user by hand in {TL} (synced {now})."})
        slot_by[sid] = slots[-1]
        report.append(f"NEW slot {sid} {it['s']}-{it['e']} {clip or new_pick.get('asset')} {new_pick['src_in_s']}-{new_pick['src_out_s']}s")
        log.append([now, 1, sid, "user_edit_kept", "", clip or new_pick.get("asset"), "", new_pick["speed_percent"], "slot", f"User added this shot by hand in {TL}", "user"])
    else:
        old = picks.get(sid, {}); s = slot_by[sid]
        changed = []
        if (old.get("clip") or old.get("asset")) != (clip or new_pick.get("asset")): changed.append(f"clip {old.get('clip') or old.get('asset')} -> {clip or new_pick.get('asset')}")
        if (s["tl_start"], s["tl_end"]) != (it["s"], it["e"]): changed.append(f"range {s['tl_start']}-{s['tl_end']} -> {it['s']}-{it['e']}")
        if clip and (abs(old.get("src_in_s", 0) - new_pick["src_in_s"]) > 0.08): changed.append(f"window {old.get('src_in_s')} -> {new_pick['src_in_s']}s")
        if int(old.get("speed_percent", 100)) != new_pick["speed_percent"]: changed.append(f"speed {old.get('speed_percent', 100)} -> {new_pick['speed_percent']}%")
        if (old.get("zoom"), old.get("pan"), old.get("tilt")) != (new_pick.get("zoom"), new_pick.get("pan"), new_pick.get("tilt")): changed.append("framing")
        if changed:
            report.append(f"{sid}: " + "; ".join(changed))
            log.append([now, 1, sid, "user_edit_kept", old.get("clip") or old.get("asset", ""), clip or new_pick.get("asset"), old.get("speed_percent", 100), new_pick["speed_percent"], "slot", f"User edited by hand in {TL}: " + "; ".join(changed), "user"])
    s = slot_by[sid]; s["tl_start"], s["tl_end"] = it["s"], it["e"]
    keep = {k: v for k, v in (picks.get(sid) or {}).items() if k in ("inserted", "grade", "stretched_by_user", "edited_by_user", "displaced_note")}
    picks[sid] = {**new_pick, "locked": False, "round": 1, "timeline": TL, **keep}
    if keep.get("inserted") or s.get("inserted"): picks[sid]["inserted"] = True
# slots without an item
gaps = [(x["e"], y["s"]) for x, y in zip(v2, v2[1:]) if x["e"] != y["s"]]
gone = [s for s in slots if s["id"] not in claimed and s["id"] not in reveal]
for s in gone:
    report.append(f"REMOVED slot {s['id']} (was {s['tl_start']}-{s['tl_end']}): no V2 item there any more")
    log.append([now, 1, s["id"], "user_edit_kept", picks.get(s["id"], {}).get("clip", ""), "", "", "", "slot", f"Slot removed: the user took this shot out / merged it in {TL}", "user"])
    removed.append(s); picks.pop(s["id"], None)
slots = [s for s in slots if s not in gone]
# reveal slots follow the empty V2 gaps that have an interview picture under them (V1 item)
v1 = sorted(D["video1"], key=lambda x: x["s"])
def src_to_iv(path):
    t = tail(path or "")
    for k, v in iv.items():
        if tail(v["source"]) == t: return k
    return None
gap_iv = []
for g0, g1 in gaps:
    mid = (g0 + g1) // 2; under = [x for x in v1 if x["s"] <= mid < x["e"]]
    gap_iv.append((g0, g1, src_to_iv(under[0]["path"]) if under else None))
by_iv = {}
for sid in sorted(reveal, key=lambda x: slot_by[x]["tl_start"] if x in slot_by else 0): by_iv.setdefault(picks[sid]["interview"], []).append(sid)
gaps_by_iv = {}
for g0, g1, ivid in gap_iv:
    if ivid is None: report.append(f"EMPTY V2+V1 gap {g0}-{g1} (black frames) - needs footage"); continue
    gaps_by_iv.setdefault(ivid, []).append((g0, g1))
for ivid in sorted(set(list(gaps_by_iv) + list(by_iv))):
    gl = sorted(gaps_by_iv.get(ivid, [])); sl = [x for x in by_iv.get(ivid, []) if x in slot_by]
    for k in range(max(len(gl), len(sl))):
        if k < len(gl) and k < len(sl):
            sid = sl[k]; g0, g1 = gl[k]; s_ = slot_by[sid]
            if (s_["tl_start"], s_["tl_end"]) != (g0, g1):
                report.append(f"reveal {sid} ({ivid}): {s_['tl_start']}-{s_['tl_end']} -> {g0}-{g1}"); log.append([now, 1, sid, "user_edit_kept", "", f"reveal {g0}-{g1}", "", "", "slot", f"Interview reveal gap moved by the user in {TL}", "user"])
            s_["tl_start"], s_["tl_end"] = g0, g1
        elif k < len(sl):
            sid = sl[k]; report.append(f"REMOVED reveal slot {sid} ({ivid}): no matching V2 gap any more"); log.append([now, 1, sid, "user_edit_kept", "", "", "", "", "slot", f"Reveal slot merged/removed by the user in {TL}", "user"])
            removed.append(slot_by[sid]); slots = [x for x in slots if x["id"] != sid]; picks.pop(sid, None)
        else:
            g0, g1 = gl[k]; sid = f"g{nxt:02d}"; nxt += 1
            slots.append({"id": sid, "inserted": True, "start_frame": 0, "end_frame": g1 - g0, "dur_frames": g1 - g0, "start_s": 0.0, "dur_s": round((g1 - g0) / FPS, 3), "frame_times_s": [], "tl_start": g0, "tl_end": g1,
                          "summary": f"{ivid} interview picture revealed", "slot_kind": "inserted", "category": P.INTERVIEW_CATEGORY, "people": "one", "framing": "medium", "energy": 3, "camera_look": "static", "treatment": "none",
                          "text_on_screen": "", "needs_real_footage": False, "notes": f"Interview reveal gap added by the user in {TL}."})
            slot_by[sid] = slots[-1]; picks[sid] = {"kind": "template", "interview": ivid, "inserted": True, "round": 1, "timeline": TL}
            report.append(f"NEW reveal slot {sid} ({ivid}) {g0}-{g1}"); log.append([now, 1, sid, "user_edit_kept", "", f"reveal {g0}-{g1}", "", "", "slot", f"Interview reveal gap added by the user in {TL}", "user"])

# ---------------------------------------------------------------- interviews (V1/A1)
a1 = sorted(D["audio1"], key=lambda x: x["s"])
for ivid, e in iv.items():
    t = tail(e["source"])
    items = [x for x in a1 if tail(x["path"] or "") == t]
    # keep only items that overlap the interview's own source ranges (a source file can serve several interviews)
    lo = min(p[0] for p in e["pieces_src_frames"]); hi = max(p[1] for p in e["pieces_src_frames"])
    cand = [x for x in items if x["ss"] <= hi + 400 and x["se"] >= lo - 400 and abs(x["s"] - e["start_frame"]) < 700]
    sf = e.get("sync") or {}
    if sf.get("src_frames"): lo_, hi_ = sf["src_frames"]; cand = [x for x in items if lo_ <= x["ss"] <= hi_]
    if sf.get("timeline_range"): ta, tb = sf["timeline_range"]; cand = [x for x in (cand if sf.get("src_frames") else items) if ta <= x["s"] < tb]
    if not cand: continue
    cand = sorted(cand, key=lambda x: x["s"]); start = cand[0]["s"]
    newp = [[x["ss"], x["se"]] for x in cand]
    if start != e["start_frame"] or [list(p) for p in newp] != [list(p) for p in e["pieces_src_frames"]]:
        # only record when the source ranges really differ by more than rounding (the dump reports GetSourceEndFrame one frame off)
        close = len(newp) == len(e["pieces_src_frames"]) and all(abs(p[0] - q[0]) <= 2 and abs(p[1] - q[1]) <= 2 for p, q in zip(newp, e["pieces_src_frames"]))
        if not close or start != e["start_frame"]:
            report.append(f"interview {ivid}: start {e['start_frame']} -> {start}; pieces {len(e['pieces_src_frames'])} -> {len(newp)}" + ("" if close else " (source ranges changed)"))
            log.append([now, 1, "", "user_edit_kept", ivid, f"start {start}, pieces {newp}", "", "", "global", f"User re-timed/trimmed this interview by hand in {TL}", "user"])
            if not close: e["pieces_src_frames"] = newp
            e["start_frame"] = start
    vols = [round(x["vol"] or 0, 2) for x in cand]
    meas = (e.get("measured") or {}).get("gain_db")
    if meas is not None and any(abs(v - meas) > 0.05 for v in vols):
        e["gain_pieces_db"] = vols; report.append(f"interview {ivid}: per-piece gains {vols} (measured {meas})")
        log.append([now, 1, "", "user_edit_kept", ivid, f"gains {vols}", "", "", "global", f"User changed the interview gains by hand in {TL} (measured {meas})", "user"])
    elif "gain_pieces_db" in e: e.pop("gain_pieces_db")
    vids = sorted([x for x in v1 if tail(x["path"] or "") == t and any(abs(x["ss"] - c["ss"]) < 400 for c in cand)], key=lambda x: x["s"])
    if vids:
        fp = [None] * len(vids)
        for k, x in enumerate(vids):
            if x["zoom"] and abs(x["zoom"] - 1.0) > 1e-3: fp[k] = {"zoom": round(x["zoom"], 3), "pan": round(x.get("pan") or 0, 1), "tilt": round(x.get("tilt") or 0, 1)}
        if any(fp) and fp != e.get("framing_pieces"):
            e["framing_pieces"] = fp; report.append(f"interview {ivid}: picture framing per cut {fp}")
        al = [(x["s"], x["e"]) for x in cand]; pl = [(x["s"], x["e"]) for x in vids]
        if al != pl and len(al) == len(pl):
            e["picture_override"] = {"pieces_src_frames": [[x["ss"], x["se"]] for x in vids], "relative_timeline": [[x["s"] - start, x["e"] - start] for x in vids],
                                      "note": f"Picture offset from the audio by the user (synced from {TL}); relative to start_frame."}
            report.append(f"interview {ivid}: picture differs from audio (picture_override)")
        elif al != pl: report.append(f"interview {ivid}: picture has {len(pl)} cuts vs {len(al)} audio cuts - check by hand")

print("\n".join(report) if report else "no differences")
if a.apply:
    live = {s['id'] for s in slots}
    for v in iv.values(): v['spots'] = [x for x in v.get('spots', []) if x in live]      # reveal spots whose slot the user removed/merged must not stay listed (verify would fail)
    slots.sort(key=lambda s: s["tl_start"])
    doc["timeline"] = TL
    P.save_json(P.SLOTS_FILE, slots); P.save_json(P.CATALOG / "slots_removed.json", removed)
    P.save_json(P.PICKS_FILE, doc); P.save_json(P.HISTORY / "interviews.json", iv)
    with open(P.HISTORY / "decisions_log.csv", "a", newline="", encoding="utf-8") as fh: csv.writer(fh).writerows(log)
    print(f"applied: {len(log)} log rows, total frames now {max(s['tl_end'] for s in slots)}")
else: print("(dry run - add --apply to write)")

#!/usr/bin/env python3
"""Build the storyboard web page.   python3 sb.py storyboard [--proposal round1] [--round 1] [--no-thumbs] [--force-thumbs]

Writes  storyboard/index.html, storyboard/data.js, storyboard/thumbs/...   (open storyboard/index.html in Chrome or Edge; no server needed)
  thumbs/ref/sNN.jpg                  template frame for each slot
  thumbs/slot/<slot>_<clip>_<t>.jpg   what a clip looks like inside the window it would use for that slot
  thumbs/clips/<clipid>.jpg           one preview per clip in the catalog (its best / happiest moment) - for browsing later
Row options: A = pick on the timeline now, then up to 3 options: the proposal (if it differs from A) followed by the best unused alternates.
Before there is any footage (or for slots nothing was picked for yet) a row shows the template frame next to a TO FILM card describing the
shot to capture, and storyboard/shot_list.md lists every slot as a printable shot list.
Re-run after every round (it is idempotent; existing images are reused)."""
import argparse, csv, datetime, json, os, pathlib, re, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P
import expr

ap = argparse.ArgumentParser()
ap.add_argument("--proposal", default="round1", help="catalog/match_sheet_<name>.json to take the proposed pick + alternates from (created if missing)")
ap.add_argument("--round", type=int, default=1)
ap.add_argument("--no-thumbs", action="store_true")
ap.add_argument("--force-thumbs", action="store_true")
args = ap.parse_args()
P.require_tools()

SB = P.STORYBOARD
for d in ("ref", "slot", "clips", "graphics"): (SB / "thumbs" / d).mkdir(parents=True, exist_ok=True)
(SB / "decisions").mkdir(parents=True, exist_ok=True)
TW, TH = (270, 480) if P.PORTRAIT_PROJECT else (480, 270)       # thumbnail box in the project's orientation

cat = expr.load(P.catalog())
ms_path = P.CATALOG / f"match_sheet_{args.proposal}.json"
if not ms_path.exists() and cat:
    subprocess.run([sys.executable, str(P.SCRIPTS / "match.py"), "--project", str(P.PROJECT), "--name", args.proposal], check=True)
elif not cat:
    print("no footage in the catalog yet: building the page as a shot list (template frame + what to film per slot)")
proposal = {o["slot"]: o for o in P.load_json(ms_path, [])}

by_id = {c["id"]: c for c in cat}
slots = P.slots()
if not slots: sys.exit("no slots yet: analyze the template first (sb.py template-cuts / template-slots / template-merge)")
picks_doc = P.picks_doc()
picks = picks_doc["picks"]
flags = P.clip_flags()
REL, GRADE = flags["check_releases"], flags["needs_grade"]
FPS = P.FPS
START_FRAMES = P.START_FRAMES

rejected = {}
if (P.HISTORY / "rejected_clips.csv").exists():
    for r in csv.DictReader(open(P.HISTORY / "rejected_clips.csv", encoding="utf-8")):
        if r["scope"] == "slot": rejected.setdefault(r["slot"], []).append(r)
log_rows = list(csv.DictReader(open(P.HISTORY / "decisions_log.csv", encoding="utf-8"))) if (P.HISTORY / "decisions_log.csv").exists() else []
graphic_info = P.load_json(P.CATALOG / "graphic_slots.json", {})
suggestions = P.load_json(P.CATALOG / "suggestions.json", {})
pending = P.load_json(P.HISTORY / "pending_decisions.json", {})
interviews = P.load_json(P.HISTORY / "interviews.json", {})


def slot_history(sid):
    h = [f"rejected for this slot: {r['clip_id']} ({r['reason']})" for r in rejected.get(sid, [])]
    for r in log_rows:
        if r["slot"] == sid and r["action"] not in ("initial_pick", "locked_template"):
            h.append(f"round {r['round']}: {r['action']} {r['clip_before'] or ''}{' -> ' if r['clip_before'] and r['clip_after'] else ''}{r['clip_after'] or ''} ({r['reason']})")
    if sid in pending:
        e = pending[sid]; h.append(f"PENDING (deferred): you chose {e.get('choice', '')} {e.get('clip', '')}" + (f" - note: {e['note']}" if e.get("note") else "") + " - waiting for your answer")
    return h


jobs = []            # (out_path, source_abs_path, time_s, filter)
def thumb_job(out, src, t, vf=""):
    jobs.append((out, src, max(0.0, t), vf))
    return str(out.relative_to(SB)).replace(os.sep, "/")


def clip_info(c):
    created = 0
    try: created = datetime.datetime.fromisoformat((c.get("created") or "").replace("Z", "+00:00")).timestamp()
    except Exception: pass
    m = re.match(r"^(.*?)(\d+)(\D*)$", c["file"].rsplit(".", 1)[0])
    v, d = c.get("vt"), c.get("det")
    return {"file": c["file"], "folder": c["folder"], "summary": c["summary"], "fps": c["fps"], "dur": c["duration_s"], "portrait": bool(c["portrait"]),
            "mismatch": P.orientation_mismatch(c), "category": c["category"], "waves": bool(v and v["waving_at_camera"]), "smile": bool(v and v["smile_at_camera"]) or False,
            "good": v["good_time"] if v else None, "expression": v["expression"] if v else None,
            "det": round(d["smile_score"], 2) if d else None, "release": c["id"] in REL, "grade": c["id"] in GRADE,
            "created": created, "numkey": [m.group(1), m.group(3), int(m.group(2))] if m else None, "img": f"thumbs/clips/{c['id']}.jpg"}


PEOPLE_TXT = {"none": "no people needed", "one": "one person", "few": "a few people", "crowd": "a crowd"}
CAMERA_TXT = {"static": "hold the camera still", "handheld": "handheld", "pan_or_tilt": "slow pan or tilt", "zoom_or_crash_zoom": "zoom / punch in",
              "moving_subject_static_camera": "camera still, subject moves", "whip_pan": "fast whip pan"}


def film_seconds(s):
    """how much to shoot for a slot: its length plus about a second of trimming room"""
    return int(s["dur_s"] + 1.0 + 0.999)


def film_note(s):
    """what to film for a slot without footage, in plain words from its tags"""
    bits = [s.get("summary") or "(slot not described yet)"]
    how = [f"{s['framing']} shot" if s.get("framing") else "", PEOPLE_TXT.get(s.get("people"), ""), CAMERA_TXT.get(s.get("camera_look"), "")]
    if s.get("energy"): how.append(f"energy {s['energy']}/5")
    bits.append(", ".join(x for x in how if x))
    bits.append(f"film at least {film_seconds(s)} s")
    if s.get("text_on_screen"): bits.append(f"text added in the edit: {s['text_on_screen']}")
    if s.get("notes"): bits.append(s["notes"])
    return " - ".join(b for b in bits if b)


used_clips = set()
out_slots = []
shot_list = []
for s in slots:
    sid = s["id"]
    p = picks.get(sid)
    row = {"id": sid, "tl_start": s["tl_start"], "tl_end": s["tl_end"], "tc_in": P.tc(s["tl_start"]), "tc_out": P.tc(s["tl_end"]), "dur_s": s["dur_s"],
           "desc": s["summary"], "slot_kind": s["slot_kind"], "category": s["category"], "demand": expr.demand(s) if s.get("summary") is not None and s.get("people") else "none",
           "text_on_screen": s.get("text_on_screen", ""), "inserted": bool(s.get("inserted")),
           "ref_img": None if s.get("inserted") or not P.REFERENCE else thumb_job(SB / "thumbs" / "ref" / f"{sid}.jpg", str(P.REFERENCE), s["frame_times_s"][1]), "history": slot_history(sid)}
    fx = P.treatment_fx(s)
    if s.get("treatment") not in (None, "", "none", "bw_grain", "blur_streak", "flash_glow"): fx.append(s["treatment"].replace("_", " "))
    if s.get("inserted"): fx.append("inserted shot")
    row["fx"] = fx
    t0 = s["start_frame"] / float(P.TEMPLATE_FPS or P.FPS) if not s.get("inserted") else s["tl_start"] / P.FPS
    when = f"{int(t0 // 60)}:{t0 % 60:04.1f}"
    if p is None:
        if s.get("needs_real_footage") is False or s.get("category") == "graphic":
            card = {"built": False, "badge": "IN EDIT", "title": "Made in the edit", "how": "Card / graphic - nothing to film", "asset": "", "needs": s.get("summary") or ""}
            shot_list.append((sid, when, s["dur_s"], "made in the edit", s.get("summary", "")))
        else:
            card = {"built": False, "badge": "TO FILM", "title": f"To film - {film_seconds(s)} s or more", "how": "No footage yet: film this, then scan it (sb.py scan)", "asset": "", "needs": film_note(s)}
            shot_list.append((sid, when, s["dur_s"], f"to film ({film_seconds(s)} s+)", film_note(s)))
        row.update(locked=True, lock_reason="no clip yet", current=None, options=[], card=card)
        out_slots.append(row); continue
    if p["kind"] in ("template", "graphic") or p.get("interview"):
        k = graphic_info.get(sid, {})
        card = {"built": bool(k.get("built")), "title": k.get("title") or "Template placeholder", "how": k.get("how", ""), "asset": k.get("asset", ""),
                "needs": k.get("needs") or p.get("reason") or "Kept as the template's own shot until you supply an asset."}
        if k.get("badge"): card["badge"] = k["badge"]
        shot_list.append((sid, when, s["dur_s"], "card / graphic" if not p.get("interview") else f"interview {p['interview']}", card["title"] + (": " + card["needs"] if card["needs"] else "")))
        if card["built"] and card["asset"]:
            asset = pathlib.Path(P.source_path(card["asset"])); at_t = s["dur_s"] * 0.55
            if p.get("interview") and p["interview"] in interviews:      # show the interview at the moment this spot plays (pieces laid out as in make_build_plan.py)
                iv = interviews[p["interview"]]; off = (s["tl_start"] + s["tl_end"]) / 2 - iv["start_frame"]; cum = prev = 0
                for src0, src1 in iv["pieces_src_frames"]:
                    cum += src1 - src0; bound = round(cum / iv["source_fps"] * FPS)
                    if off < bound or (src0, src1) == tuple(iv["pieces_src_frames"][-1]):
                        at_t = (src0 + max(0.0, off - prev) * iv["source_fps"] / FPS) / iv["source_fps"]; break
                    prev = bound
            if asset.exists():
                card["img"] = thumb_job(SB / "thumbs" / "graphics" / f"{sid}_{int(asset.stat().st_mtime)}_{int(at_t * 10)}.jpg", str(asset), at_t)
        row.update(locked=True, lock_reason=p.get("reason", ""), current=None, options=[], card=card)
        out_slots.append(row); continue
    row["locked"] = bool(p.get("locked"))
    row["lock_reason"] = "locked by user" if p.get("locked") else ""
    cc = by_id[p["clip"]]; used_clips.add(cc["id"])
    mid = (p["src_in_s"] + p["src_out_s"]) / 2
    zsuf = ('_z' + str(p['zoom']) + '_' + str(p.get('pan', 0)) + '_' + str(p.get('tilt', 0))) if p.get('zoom') else ''
    row["current"] = {"clip": cc["id"], "in": p["src_in_s"], "out": p["src_out_s"], "speed": p["speed_percent"],
                      "slow_ok": expr.slow_ok(s, cc), "zoom": p.get("zoom"), "pan": p.get("pan", 0), "tilt": p.get("tilt", 0),
                      "img": thumb_job(SB / "thumbs" / "slot" / f"{sid}_{cc['id']}_{int(mid * 10):05d}{zsuf}.jpg", P.abs_path(cc["path"]), mid, expr.crop_filter(cc, p.get("zoom"), p.get("pan", 0), p.get("tilt", 0)))}
    prop = proposal.get(sid)
    cand = []
    sg = suggestions.get(sid)
    if sg:
        row["sug"] = sg["criteria"]
        for a in sg["clips"]:
            if a != cc["id"] and a not in [x[0] for x in cand] and a in by_id:
                c = by_id[a]; i, o = expr.window(s, c, False); cand.append((a, "SUGGESTED", i, o, 100))
    if prop and not sg and prop["clip"] != cc["id"]:
        cand.append((prop["clip"], "PROPOSED", prop["src_in_s"], prop["src_out_s"], 50 if prop["speed"] != "100%" else 100))
    for a in (prop["alts"].split(",") if prop else []):
        if len(cand) >= 3: break
        a = a.strip()
        if a and a != cc["id"] and a not in [x[0] for x in cand] and a in by_id:
            c = by_id[a]; i, o = expr.window(s, c, False)
            cand.append((a, "ALTERNATE", i, o, 100))
    opts = []
    for letter, (cid, label, i, o, spd) in zip("BCD", cand[:3]):
        c = by_id[cid]; used_clips.add(cid)
        ni, no = expr.window(s, c, False); si, so = expr.window(s, c, True)
        mid = (i + o) / 2; af = expr.auto_framing(c)
        opts.append({"letter": letter, "clip": cid, "label": label, "in": i, "out": o, "speed": spd, "win_normal": [ni, no], "win_slow": [si, so],
                     "slow_ok": expr.slow_ok(s, c), "zoom": af.get("zoom"),
                     "img": thumb_job(SB / "thumbs" / "slot" / f"{sid}_{cid}_{int(mid * 10):05d}{'_z' + str(af['zoom']) if af else ''}.jpg", P.abs_path(c["path"]), mid, expr.crop_filter(c, af.get("zoom")))})
    row["options"] = opts
    out_slots.append(row)
    shot_list.append((sid, when, s["dur_s"], f"picked: {cc['id']}", f"{cc['file']} {p['src_in_s']:.1f}-{p['src_out_s']:.1f}s - {cc['summary']}"))

L_ = [f"# Shot list - {P.TITLE}", "",
      f"Template `{P.REFERENCE.name if P.REFERENCE else '-'}`, {len(slots)} slots, {slots[-1]['tl_end'] / FPS:.1f} s. Built {datetime.date.today().isoformat()} with the storyboard"
      " (`storyboard/index.html` shows the template frame of every slot). Film each shot a bit longer than its length so it can be trimmed.", "",
      "| Slot | At | Length | Status | What |", "|---|---|---|---|---|"]
L_ += [f"| {sid} | {when} | {dur:.1f} s | {status} | {what.replace('|', '/')} |" for sid, when, dur, status, what in shot_list]
open(SB / "shot_list.md", "w", encoding="utf-8").write("\n".join(L_) + "\n")

clips_out = {cid: clip_info(by_id[cid]) for cid in used_clips}
for c in cat:            # one preview per clip in the catalog (best moment)
    thumb_job(SB / "thumbs" / "clips" / f"{c['id']}.jpg", P.abs_path(c["path"]), expr.generic_time(c))

if not args.no_thumbs:
    seen, todo = set(), []
    for out, src, t, vf in jobs:
        if out in seen: continue
        seen.add(out)
        if args.force_thumbs or not out.exists(): todo.append((out, src, t, vf))
    print(f"preview images: {len(seen)} needed, {len(todo)} to render", flush=True)
    def render(j):
        out, src, t, vf = j
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", "-an", "-sn", "-dn",
                        "-vf", vf + f"scale={TW}:{TH}:force_original_aspect_ratio=decrease,pad={TW}:{TH}:(ow-iw)/2:(oh-ih)/2:color=black", "-q:v", "5", str(out)],
                       capture_output=True, timeout=180)
        return out.exists()
    with ThreadPoolExecutor(12) as ex:
        res = list(ex.map(render, todo))
    print("rendered", sum(res), "failed", len(res) - sum(res), flush=True)
    keep = {o for o, _, _, _ in jobs}
    for d in ("ref", "slot", "graphics"):
        for f in (SB / "thumbs" / d).glob("*.jpg"):
            if f not in keep: f.unlink()          # drop images from earlier rounds

data = {"app": "video-storyboard", "project": P.NAME, "title": P.TITLE, "built": datetime.datetime.now().isoformat(timespec="seconds"), "round": args.round,
        "timeline": picks_doc.get("timeline", ""), "fps": FPS, "start_frames": START_FRAMES, "total_frames": slots[-1]["tl_end"],
        "aspect": [P.W, P.H], "mismatch_label": P.MISMATCH_LABEL, "clips": clips_out, "slots": out_slots}
open(SB / "data.js", "w", encoding="utf-8").write("window.SB = " + json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";\n")
shutil.copy(P.PAGE, SB / "index.html")
n_foot = sum(1 for s in out_slots if not s["locked"] and s["current"])
print(f"storyboard built: {len(out_slots)} rows ({n_foot} footage, {len(out_slots) - n_foot} locked) -> {SB / 'index.html'}")

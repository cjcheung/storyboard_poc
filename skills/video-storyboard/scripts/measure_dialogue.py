#!/usr/bin/env python3
"""Loudness of every dialogue piece on an audio track of a timeline dump, and the clip gains that bring them all to one level.

  1. in Resolve: CFG = dict(NAME="<timeline>", OUT="<work>/timeline_dump.json"); exec(open("<skill>/resolve/dump_timeline.resolve.py").read())
  2. python3 sb.py measure-dialogue --dump <work>/timeline_dump.json [--track audio1] [--target -16] [--ceiling -1] [--leveler-above 20]
  3. in Resolve: CFG = dict(NAME="<copy of the timeline>", PLAN="<the json this wrote>"); exec(open("<skill>/resolve/dialogue_level.resolve.py").read())

Read-only on the media. One short ffmpeg per piece: input seek (-ss before -i), audio only (-vn -sn -dn), -t = piece length, and a
watchdog that kills ffmpeg if its memory passes 1.5 GB. (NEVER measure these files with a filter graph that also decodes the video: one such
run buffered tens of GB of frames and froze the machine.)
Gain per piece = min(target - loudness, ceiling - true peak), so loud peaks are never pushed over the ceiling; clip gain is capped at +30 dB
(Resolve's limit) and any rest goes to the Dialogue Leveler's output gain (0-6 dB). Speakers that need more than --leveler-above dB get the
Dialogue Leveler on all their pieces (far microphones / room sound). Speaker loudness = duration-weighted power mean of its pieces.
Pieces shorter than ~1 s give unreliable LUFS values (flagged)."""
import argparse, collections, json, math, os, re, subprocess, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P

ap = argparse.ArgumentParser()
ap.add_argument("--dump", default=str(P.WORK / "timeline_dump.json"))
ap.add_argument("--track", default="audio1", help="track key in the dump (audio1, audio2, ...)")
ap.add_argument("--target", type=float, default=-16.0, help="integrated loudness per piece (LUFS)")
ap.add_argument("--ceiling", type=float, default=-1.0, help="true-peak ceiling (dBTP)")
ap.add_argument("--leveler-above", type=float, default=20.0, help="speakers needing more gain than this get the Dialogue Leveler")
ap.add_argument("--out", help="default: history/dialogue_levels_<timeline>.json")
ap.add_argument("--limit", type=int, help="measure only the first N pieces (testing)")
a = ap.parse_args()
P.require_tools()
LIMIT_KB = 1_500_000


def parse(err):
    I = re.search(r"Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+|-inf) LUFS", err); LRA = re.search(r"LRA:\s*([\d.]+) LU", err); TP = re.search(r"True peak:\s*\n\s*Peak:\s*(-?[\d.]+|-inf) dBFS", err)
    f = lambda m: (float(m.group(1)) if m and m.group(1) != "-inf" else None)
    return f(I), f(TP), f(LRA)


def run(path, t0, d):
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-ss", f"{t0:.4f}", "-t", f"{d:.4f}", "-i", path, "-vn", "-sn", "-dn", "-af", "ebur128=peak=true", "-f", "null", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True); peak = [0]; killed = [False]
    def watch():
        while p.poll() is None:
            r = subprocess.run(["ps", "-o", "rss=", "-p", str(p.pid)], capture_output=True, text=True).stdout.strip()
            if r.isdigit():
                peak[0] = max(peak[0], int(r))
                if int(r) > LIMIT_KB: killed[0] = True; p.kill(); return
            time.sleep(0.2)
    th = threading.Thread(target=watch, daemon=True); th.start()
    err = p.communicate()[1]; th.join(timeout=1)
    return parse(err), peak[0], killed[0]


D = P.load_json(a.dump); items = sorted(D.get(a.track) or [], key=lambda x: x["s"])
if not items: sys.exit(f"no items on {a.track} in {a.dump}")
ivs = P.load_json(P.HISTORY / "interviews.json", {})
key = lambda p: P.strip_prefix(P.rel_path(P.abs_path(p))) if p else ""
iv_keys = {k: key(v["source"]) for k, v in ivs.items()}


def speaker(it):
    k = key(it["path"])
    for ivid, ik in iv_keys.items():
        e = ivs[ivid]
        if ik != k: continue
        sf = e.get("sync") or {}
        if sf.get("src_frames") and not (sf["src_frames"][0] <= it["ss"] <= sf["src_frames"][1]): continue
        if sf.get("timeline_range") and not (sf["timeline_range"][0] <= it["s"] < sf["timeline_range"][1]): continue
        return ivid
    return os.path.splitext(os.path.basename(it["path"] or it["name"]))[0]


rows = []
for n, it in enumerate(items):
    if a.limit is not None and n >= a.limit: break
    fps = it["fps"] or P.FPS
    t0 = it["ss"] / fps; d = (it["se"] - it["ss"]) / fps
    (I, TP, LRA), rss, killed = run(it["path"], t0, d)
    rec = {"start": it["s"], "end": it["e"], "speaker": speaker(it), "dur_s": round(d, 2), "current_gain": round(it.get("vol") or 0, 2), "raw_lufs": I, "raw_tp": TP, "lra": LRA,
           "peak_rss_mb": round(rss / 1024), "killed": killed, "short": d < 1.0}
    rows.append(rec); print(json.dumps(rec), flush=True)

groups = collections.OrderedDict()
for r in rows: groups.setdefault(r["speaker"], []).append(r)
speakers = []
for g, rs in groups.items():
    ok = [r for r in rs if r["raw_lufs"] is not None]
    if not ok: speakers.append({"speaker": g, "raw_lufs": None, "leveler": False}); continue
    w = sum(r["dur_s"] for r in ok); pw = sum(r["dur_s"] * 10 ** (r["raw_lufs"] / 10) for r in ok) / w
    raw = round(10 * math.log10(pw), 2)
    speakers.append({"speaker": g, "raw_lufs": raw, "raw_tp": max((r["raw_tp"] for r in ok if r["raw_tp"] is not None), default=None), "pieces": len(rs), "dur_s": round(w, 1),
                     "leveler": (a.target - raw) > a.leveler_above})
lev = {s["speaker"]: s["leveler"] for s in speakers}
for r in rows:
    if r["raw_lufs"] is None: r.update(gain_db=r["current_gain"], leveler=False, leveler_output_gain=0.0, expected_lufs=None, peak_limited=False); continue
    want = a.target - r["raw_lufs"]
    room = (a.ceiling - r["raw_tp"]) if r["raw_tp"] is not None else want
    final = min(want, room)
    clip = min(final, 30.0); extra = max(0.0, min(6.0, final - 30.0))
    r.update(gain_db=round(clip, 1), leveler=lev.get(r["speaker"], False) or extra > 0, leveler_output_gain=round(extra, 1),
             expected_lufs=round(r["raw_lufs"] + clip + extra, 1), peak_limited=room < want)
out = a.out or str(P.HISTORY / f"dialogue_levels_{D.get('timeline') or 'timeline'}.json")
P.save_json(out, {"_about": "Per-piece dialogue gains (clip gain + optional Dialogue Leveler) for one level across speakers; apply with resolve/dialogue_level.resolve.py. "
                  "Levels after the leveler are estimates (it only runs inside Resolve): check with the Fairlight loudness meter.",
                  "timeline": D.get("timeline"), "track": a.track, "target_lufs": a.target, "ceiling_dbtp": a.ceiling, "pieces": rows, "speakers": speakers})
print(f"\n{'start':>6} {'speaker':24s} {'dur':>5} {'raw LUFS':>8} {'TP':>6} {'gain':>6} {'lev':>4} {'expect':>7}")
for r in rows:
    print(f"{r['start']:6d} {r['speaker'][:24]:24s} {r['dur_s']:5.2f} {r['raw_lufs'] if r['raw_lufs'] is not None else '-':>8} {r['raw_tp'] if r['raw_tp'] is not None else '-':>6} {r['gain_db']:6.1f} "
          f"{('+' + str(r['leveler_output_gain'])) if r['leveler'] else '':>4} {r['expected_lufs'] if r['expected_lufs'] is not None else '-':>7}{'  peak-limited' if r['peak_limited'] else ''}{'  short' if r['short'] else ''}")
print("wrote", out)

#!/usr/bin/env python3
"""Measure how bright every shot of the current edit is (uses the window of each clip that is actually on the timeline).

  python3 sb.py exposure                       # -> catalog/exposure_check.csv + .json, prints the darkest shots
  python3 sb.py exposure --calibrate           # measure the TEMPLATE's own shots first and use its darkest quartile as the thresholds
  python3 sb.py exposure --top 25 --sheet      # also a contact sheet of the darkest shots (needs Pillow)

Per shot we sample 3-5 frames inside the used source window and read ffmpeg's signalstats:
  avg    = mean brightness over the shot, 0% = black ... 100% = white (limited-range luma rescaled)
  bright = brightness of the 90th-percentile pixels (how bright the highlights get; stage lights keep this high even when avg is low)
  low    = the darkest frame's average
Verdicts (defaults come from a typical promo: average brightness p10 12%, p25 17%; highlights p25 42% - or use --calibrate):
  too dark   = avg < floor, or (avg < low AND highlights < hi_low)   -> murky, nothing bright in frame
  borderline = avg < low OR highlights < hi_low
  ok         = everything else
Timelapses and the template's own shots are listed but marked in 'note' (dark by design / not ours)."""
import argparse, csv, json, os, re, statistics, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P

ap = argparse.ArgumentParser()
ap.add_argument("--picks", default=str(P.PICKS_FILE))
ap.add_argument("--avg-low", type=float, default=17.0, help="25th percentile of average brightness")
ap.add_argument("--avg-floor", type=float, default=12.0, help="10th percentile")
ap.add_argument("--hi-low", type=float, default=42.0, help="25th percentile of highlights")
ap.add_argument("--calibrate", action="store_true", help="derive the three thresholds from the template's own footage shots")
ap.add_argument("--top", type=int, default=20)
ap.add_argument("--out", default="exposure_check", help="output name under catalog/ (default exposure_check)")
ap.add_argument("--sheet", action="store_true")
a = ap.parse_args()
P.require_tools()

slots = P.slots()
doc = P.load_json(a.picks); picks = doc["picks"]
cat = {c["id"]: c for c in P.catalog()}
TFPS = float(P.TEMPLATE_FPS or 24)


def level(v): return max(0.0, min(100.0, (v - 16.0) * 100.0 / 219.0))


def stats(src, t):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", "-an", "-vf", "scale=384:-2,signalstats,metadata=mode=print:file=-", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=180)
    g = lambda k: (re.search(rf"lavfi\.signalstats\.{k}=([0-9.]+)", r.stdout) or [None, None])[1]
    if g("YAVG") is None: return None
    return level(float(g("YAVG"))), level(float(g("YHIGH"))), level(float(g("YLOW")))


def measure(j):
    n = 5 if j["out"] - j["in"] >= 0.5 else 3
    ts = [j["in"] + (j["out"] - j["in"]) * (k + 0.5) / n for k in range(n)]
    st = [x for x in (stats(j["src"], t) for t in ts) if x]
    if not st: return None
    return {"avg": sum(x[0] for x in st) / len(st), "bright": sum(x[1] for x in st) / len(st), "low": min(x[0] for x in st), "mid_t": (j["in"] + j["out"]) / 2}


if a.calibrate:
    ref = [{"src": str(P.REFERENCE), "in": s["start_frame"] / TFPS, "out": s["end_frame"] / TFPS} for s in slots if s.get("needs_real_footage")]
    with ThreadPoolExecutor(10) as ex:
        rm = [m for m in ex.map(measure, ref) if m]
    if len(rm) >= 8:
        av = sorted(m["avg"] for m in rm); hi = sorted(m["bright"] for m in rm)
        q = lambda v, p: v[min(len(v) - 1, int(p * len(v)))]
        a.avg_floor, a.avg_low, a.hi_low = round(q(av, 0.10), 1), round(q(av, 0.25), 1), round(q(hi, 0.25), 1)
        print(f"calibrated on {len(rm)} template shots: floor {a.avg_floor}%, low {a.avg_low}%, highlights {a.hi_low}%")

jobs = []
for s in slots:
    p = picks.get(s["id"])
    if not p: continue
    if p["kind"] == "footage":
        c = cat[p["clip"]]; src = P.abs_path(c["path"]); i, o = p["src_in_s"], p["src_out_s"]; name = f'{p["clip"]} {c["file"]}'
    elif p["kind"] == "template" and P.REFERENCE:
        src = str(P.REFERENCE); i, o = s["start_frame"] / TFPS, s["end_frame"] / TFPS; name = "template shot (reference video)"
    else:
        continue
    jobs.append({"slot": s["id"], "tc": P.tc(s["tl_start"]), "dur_s": round((s["tl_end"] - s["tl_start"]) / P.FPS, 2), "kind": p["kind"], "name": name, "src": src, "in": i, "out": o,
                 "clip": p.get("clip", "")})

with ThreadPoolExecutor(10) as ex:
    res = list(ex.map(measure, jobs))
rows = []
for j, m in zip(jobs, res):
    if not m: continue
    v = "too dark" if (m["avg"] < a.avg_floor or (m["avg"] < a.avg_low and m["bright"] < a.hi_low)) else "borderline" if (m["avg"] < a.avg_low or m["bright"] < a.hi_low) else "ok"
    note = "template's own shot (not ours)" if j["kind"] == "template" else "timelapse - may be dark by design" if j["clip"] and cat[j["clip"]]["category"] == "timelapse" else ""
    rows.append({"slot": j["slot"], "timecode": j["tc"], "dur_s": j["dur_s"], "clip": j["clip"], "shot": j["name"], "avg_pct": round(m["avg"], 1), "highlights_pct": round(m["bright"], 1),
                 "darkest_frame_pct": round(m["low"], 1), "verdict": v, "note": note, "_src": j["src"], "_t": m["mid_t"]})
if not rows: sys.exit("nothing to measure (no picks yet?)")
av = [r["avg_pct"] for r in rows]
print(f"{len(rows)} shots measured | median brightness {statistics.median(av):.0f}% | too dark {sum(r['verdict']=='too dark' for r in rows)} | borderline {sum(r['verdict']=='borderline' for r in rows)} | ok {sum(r['verdict']=='ok' for r in rows)}")
srt = sorted(rows, key=lambda r: r["avg_pct"])
for r in srt[:a.top]: print(f'  {r["slot"]:4s} {r["timecode"]} {r["dur_s"]:4.2f}s avg {r["avg_pct"]:4.1f}%  highlights {r["highlights_pct"]:4.1f}%  {r["verdict"]:10s} {r["shot"][:40]} {("[" + r["note"][:18] + "]") if r["note"] else ""}')
out = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
P.save_json(P.CATALOG / f"{a.out}.json", out)
with open(P.CATALOG / f"{a.out}.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(out[0])); w.writeheader(); w.writerows(sorted(out, key=lambda r: r["avg_pct"]))
if a.sheet:
    from PIL import Image, ImageDraw, ImageFont
    top = srt[:a.top]; cols = 5; W, H = (216, 384) if P.PORTRAIT_PROJECT else (384, 216); rws = -(-len(top) // cols)
    def font(sz):
        for f in ("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            try: return ImageFont.truetype(f, sz)
            except Exception: pass
        return ImageFont.load_default()
    F, F2 = font(22), font(15)
    sheet = Image.new("RGB", (cols * W, rws * (H + 40)), (24, 24, 28)); d = ImageDraw.Draw(sheet)
    P.WORK.mkdir(parents=True, exist_ok=True)
    for n, r in enumerate(top):
        f = str(P.WORK / "exp_tmp.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{r['_t']:.3f}", "-i", r["_src"], "-frames:v", "1", "-an", "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2", "-q:v", "4", f], check=True)
        x, y = (n % cols) * W, (n // cols) * (H + 40); sheet.paste(Image.open(f), (x, y))
        col = (200, 60, 50) if r["verdict"] == "too dark" else (214, 120, 20) if r["verdict"] == "borderline" else (60, 150, 80)
        d.rectangle([x, y, x + 74, y + 34], fill=col); d.text((x + 8, y + 5), r["slot"], font=F, fill="white"); d.rectangle([x, y, x + W - 1, y + H - 1], outline=col, width=3)
        d.text((x + 4, y + H + 3), f'avg {r["avg_pct"]:.0f}%  highlights {r["highlights_pct"]:.0f}%  {r["verdict"]}', font=F2, fill=(235, 235, 235))
        d.text((x + 4, y + H + 21), r["shot"][:48], font=F2, fill=(170, 170, 178))
    dest = P.CATALOG / f"{a.out}_darkest.jpg"; sheet.save(dest, quality=88); print("sheet ->", dest)

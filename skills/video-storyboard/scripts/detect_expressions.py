#!/usr/bin/env python3
"""Face / smile / camera-facing scan with macOS Core Image + Vision (no extra packages; needs the Xcode command line tools). Optional:
on other systems (or without swiftc) it exits and the matcher simply works without smile data.

  python3 sb.py expressions            # only clips not scanned yet
  python3 sb.py expressions --all      # rescan everything

Writes/extends catalog/expression/expression_detect.json. The detector over-flags singing / talking mouths and
misses small faces, so treat it as a hint; visual tags (sb.py expression-sheets) override it.
The first compile of the Swift helper can take ~10 minutes; it is cached in ~/.cache/video-storyboard (machine specific)."""
import argparse, json, os, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P

ap = argparse.ArgumentParser(); ap.add_argument("--all", action="store_true"); ap.add_argument("--ids", nargs="*"); args = ap.parse_args()
P.require_tools()
if sys.platform != "darwin" or not shutil.which("swiftc"):
    sys.exit("expression scan skipped: needs macOS with the Xcode command line tools (xcode-select --install). Matching works without it.")
FRONTAL_YAW, MIN_FACE_H = 0.6, 0.05            # radians (~34 deg); face height as fraction of frame height
bin_path = P.CACHE / "detect"
if not bin_path.exists() or os.path.getmtime(bin_path) < os.path.getmtime(P.SCRIPTS / "detect.swift"):
    P.CACHE.mkdir(parents=True, exist_ok=True)
    print("compiling detect.swift (first time can take ~10 minutes)...", flush=True)
    subprocess.run(["swiftc", "-O", str(P.SCRIPTS / "detect.swift"), "-o", str(bin_path)], check=True)

out_path = P.CATALOG / "expression" / "expression_detect.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
done = P.load_json(out_path, {})
cat = P.catalog()
todo = [c for c in cat if c["category"] != "timelapse" and (args.all or c["id"] not in done) and (not args.ids or c["id"] in args.ids)]
print(f"clips to scan: {len(todo)}", flush=True)
tmp = P.WORK / "detect_frames"; tmp.mkdir(parents=True, exist_ok=True)


def process(c):
    cid, path, dur = c["id"], P.abs_path(c["path"]), c["duration_s"]
    n = 6 if dur < 4 else 8 if dur < 15 else 10 if dur < 40 else 12
    times = [round(dur * (k + 0.5) / n, 3) for k in range(n)]
    d = tmp / cid; d.mkdir(exist_ok=True)
    files = []
    for k, t in enumerate(times):
        fp = str(d / f"{k:02d}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-an", "-vf", "scale=960:-2", "-q:v", "4", fp], capture_output=True, timeout=120)
        if os.path.exists(fp): files.append((k, t, fp))
    res = []
    if files:
        r = subprocess.run([str(bin_path)] + [f[2] for f in files], capture_output=True, text=True, timeout=300)
        by = {}
        for line in r.stdout.splitlines():
            try: j = json.loads(line); by[j["f"]] = j
            except Exception: pass
        for k, t, fp in files:
            faces = [f for f in by.get(fp, {}).get("faces", []) if f["h"] >= MIN_FACE_H]
            front = lambda f: f["yaw"] is not None and abs(f["yaw"]) <= FRONTAL_YAW
            res.append({"k": k, "t": t, "n_faces": len(faces), "n_smile": sum(f["smile"] for f in faces), "n_front": sum(1 for f in faces if front(f)),
                        "n_front_smile": sum(1 for f in faces if f["smile"] and front(f)), "max_face_h": max([f["h"] for f in faces], default=0),
                        "max_smile_h": max([f["h"] for f in faces if f["smile"]], default=0)})
    shutil.rmtree(d, ignore_errors=True)
    nf = len(res)
    agg = {"id": cid, "frames_checked": nf, "frames_with_faces": sum(1 for r in res if r["n_faces"]), "frames_with_smile": sum(1 for r in res if r["n_smile"]),
           "frames_front_smile": sum(1 for r in res if r["n_front_smile"]), "frames_front": sum(1 for r in res if r["n_front"]),
           "max_faces": max([r["n_faces"] for r in res], default=0), "max_smiling": max([r["n_smile"] for r in res], default=0),
           "max_face_h": max([r["max_face_h"] for r in res], default=0)}
    ranked = sorted(res, key=lambda r: (r["n_front_smile"] > 0, r["n_smile"] > 0, r["max_smile_h"], r["n_smile"]), reverse=True)
    if ranked:
        b = ranked[0]; agg.update(best_smile_t=b["t"], best_smile_frontal=b["n_front_smile"] > 0, best_smile_faces=b["n_smile"])
    agg["smile_score"] = round((agg["frames_with_smile"] / nf if nf else 0) * 0.5 + (agg["frames_front_smile"] / nf if nf else 0) * 0.5, 3)
    agg["frames"] = res
    return agg


with ThreadPoolExecutor(8) as ex:
    for i, a in enumerate(ex.map(process, todo), 1):
        done[a["id"]] = a
        if i % 50 == 0:
            print("scanned", i, flush=True); P.save_json(out_path, done, None)
P.save_json(out_path, done, None)
print("done; expression_detect.json now has", len(done), "clips")

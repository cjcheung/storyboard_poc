#!/usr/bin/env python3
"""Find catalogued clips whose file was renamed or moved, and relink them.

  python3 sb.py relink            # report only
  python3 sb.py relink --apply    # rewrite the old path/filename everywhere in catalog/ and history/

A missing clip is matched to an uncatalogued video in the same folder (or anywhere under the footage roots)
with the same duration (+-0.05s) and frame size. Ids never change, so history stays valid.
(If a whole folder moved, it is simpler to fix the roots in storyboard_project.json "paths".)"""
import argparse, glob, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P

ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); args = ap.parse_args()
P.require_tools()
cat = P.catalog()
known = {c["path"] for c in cat}
missing = [c for c in cat if not os.path.exists(P.abs_path(c["path"]))]
print(f"catalogued clips missing on disk: {len(missing)}")
if not missing:
    sys.exit(0)
exts = tuple(e.lower() for e in P.CFG["scan"]["extensions"])


def probe(rel):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json", P.abs_path(rel)], capture_output=True, text=True)
    try:
        j = json.loads(r.stdout); s = j["streams"][0]
        return float(j["format"]["duration"]), s["width"], s["height"]
    except Exception:
        return None


pool = {}
for dp, dn, fn in P.walk_footage():
    for f in fn:
        if f.startswith(".") or not f.lower().endswith(exts): continue
        rel = P.rel_path(os.path.join(dp, f))
        if rel not in known: pool.setdefault(os.path.dirname(rel), []).append(rel)

moves = {}
for c in missing:
    folder = os.path.dirname(c["path"])
    cands = pool.get(folder, []) + [r for d, rs in pool.items() if d != folder for r in rs]
    hit = None
    for rel in cands:
        if rel in moves.values(): continue
        pr = probe(rel)
        if pr and abs(pr[0] - c["duration_s"]) <= 0.05 and (pr[1], pr[2]) in ((c["width"], c["height"]), (c["height"], c["width"])):
            hit = rel; break
    print(f"  {c['id']}: {c['path']}\n      -> {hit or 'NO MATCH FOUND'}")
    if hit: moves[c["path"]] = hit

if args.apply and moves:
    touched = 0
    for pat in ("catalog/**/*.json", "catalog/**/*.csv", "history/**/*.json", "history/**/*.csv"):
        for f in glob.glob(str(P.PROJECT / pat), recursive=True):
            s = open(f, encoding="utf-8").read(); s2 = s
            for old, new in moves.items():
                s2 = s2.replace(old, new).replace(os.path.basename(old), os.path.basename(new))
            if s2 != s:
                if f.endswith(".json"): json.loads(s2)
                open(f, "w", encoding="utf-8").write(s2); touched += 1
    print(f"relinked {len(moves)} clip(s); updated {touched} file(s).")
elif moves:
    print("re-run with --apply to update the catalog.")

#!/usr/bin/env python3
"""Contact sheets for the visual 'waving / smiling at camera / good time' check (candidates = clips with large faces
that have no visual expression tag yet).   python3 sb.py expression-sheets [--agents 4]
Output: <work>/expr/expr_NN.png + agent_X.json. Give each helper the tag_expression prompt (python3 sb.py prompt tag_expression ...);
they write catalog/expression/tags_expr_<letter>.json (use new letters, e.g. E, F... - existing files are never overwritten)."""
import argparse, glob, json, os, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P, sb_sheets as L

ap = argparse.ArgumentParser(); ap.add_argument("--agents", type=int, default=4); ap.add_argument("--min-face", type=float, default=0.15); args = ap.parse_args()
P.require_tools()
det = P.load_json(P.CATALOG / "expression" / "expression_detect.json", {})
cat = {c["id"]: c for c in P.catalog()}
tagged = set()
for f in glob.glob(str(P.CATALOG / "expression" / "tags_expr_*.json")):
    tagged |= {t["id"] for t in json.load(open(f, encoding="utf-8"))}
cand = sorted(k for k, a in det.items() if k in cat and k not in tagged and a["max_face_h"] >= args.min_face and a["frames_front"] >= 1 and cat[k]["people"] != "none")
cand += sorted(k for k, c in cat.items() if k not in tagged and k not in cand and "wav" in (c["summary"] + c.get("notes", "")).lower())
print("clips to check visually:", len(cand))
if not cand: sys.exit(0)
W = P.WORK / "expr"; W.mkdir(parents=True, exist_ok=True)
N = 8
cw, ch = L.cell_size(P.PORTRAIT_PROJECT)
rows = [{"label": f"{i:03d}", "id": k, "c": cat[k], "times": [round(cat[k]["duration_s"] * (j + 0.5) / N, 3) for j in range(N)]} for i, k in enumerate(cand, 1)]
with ThreadPoolExecutor(12) as ex:
    futs = {(r["label"], j): ex.submit(L.grab, P.abs_path(r["c"]["path"]), t, cw, ch) for r in rows for j, t in enumerate(r["times"])}
    frames = {k: f.result() for k, f in futs.items()}
sheets = []
for si in range(0, len(rows), 5):
    chunk = rows[si:si + 5]; path = str(W / f"expr_{si // 5 + 1:02d}.png")
    L.compose([(r["label"], [frames[(r["label"], j)] for j in range(N)]) for r in chunk], path, cw, ch)
    sheets.append({"sheet": path, "rows": [{"label": r["label"], "id": r["id"], "folder": r["c"]["folder"], "file": r["c"]["file"], "duration_s": r["c"]["duration_s"],
        "portrait": r["c"]["portrait"], "frame_times_s": r["times"],
        "detector_hint": {"max_faces": det[r["id"]]["max_faces"], "max_smiling_faces": det[r["id"]]["max_smiling"], "frames_with_frontal_smile": det[r["id"]]["frames_front_smile"], "frames_checked": det[r["id"]]["frames_checked"]} if r["id"] in det else {}} for r in chunk]})
per = -(-len(sheets) // args.agents)
for i in range(args.agents):
    g = sheets[i * per:(i + 1) * per]
    if g:
        P.save_json(W / f"agent_{chr(65 + i)}.json", {"cell_px": [cw, ch], "columns": L.COLS, "label_column_px": L.LABEL_W, "sheets": g})
        print(f"  helper {chr(65 + i)}: {len(g)} sheets, {sum(len(s['rows']) for s in g)} clips -> {W / ('agent_' + chr(65 + i) + '.json')}")

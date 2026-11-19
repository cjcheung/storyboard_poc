#!/usr/bin/env python3
"""Find footage that is not in the catalog yet, probe it, and prepare contact sheets for tagging.

  python3 sb.py scan --dry-run                 # list what is new, change nothing
  python3 sb.py scan --batch b01               # probe + build sheets for batch b01 (always name the batch when several agents work on one project)
  python3 sb.py scan --only "Footage/Day 2"    # only files under this stored-path prefix (implies --include for it)
  python3 sb.py scan --include "Footage/Raw"   # also scan a folder that storyboard_project.json scan.skip_path_prefixes skips

Creates  catalog/batches/<batch>/technical.json and clip_index.json  (small, part of the project)
and      <work>/<batch>/clips_NN.png + agent_X.json                    (big, scratch only).
Files that are not on the disk yet (cloud 'online-only' placeholders) are skipped and listed, so nothing triggers a huge download.
Next: give each agent_X.json to a tagging helper (python3 sb.py prompt tag_clips --manifest ... --out ...), then python3 sb.py merge-batch <batch>."""
import argparse, glob, json, os, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P
import sb_sheets as L

ap = argparse.ArgumentParser()
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--batch", help="batch name (default: next free bNN)")
ap.add_argument("--include", action="append", default=[], help="stored-path prefix to scan even if the scan rules skip it")
ap.add_argument("--only", help="scan only files under this stored-path prefix, e.g. \"Footage/Day 2\"; implies --include for it")
ap.add_argument("--agents", type=int, help="number of tagging helpers to split the sheets across (default: ~50 clips each)")
args = ap.parse_args()
P.require_tools()

rules = P.CFG["scan"]
exts = tuple(e.lower() for e in rules["extensions"])
if args.only: args.include = args.include + [args.only]
skip_prefixes = [s for s in rules["skip_path_prefixes"] if not any(s.startswith(i) or i.startswith(s) for i in args.include)]
skip_names = [s.lower() for s in rules["skip_filename_contains"]]
if not P.FOOTAGE_ROOTS: sys.exit("no footage roots configured (storyboard_project.json paths.roots)")

known = {c["path"] for c in P.catalog()}
for f in glob.glob(str(P.CATALOG / "batches" / "*" / "technical.json")):
    known |= {r["path"] for r in json.load(open(f, encoding="utf-8")) if "path" in r}

new, not_local, skipped = [], [], 0
for dp, dn, fn in P.walk_footage():
    for f in fn:
        if f.startswith(".") or not f.lower().endswith(exts):
            continue
        rel = P.rel_path(os.path.join(dp, f))
        if rel in known or (args.only and not rel.startswith(args.only)):
            continue
        if any(rel.startswith(s) for s in skip_prefixes) or any(s in f.lower() for s in skip_names):
            skipped += 1
            continue
        st = os.stat(os.path.join(dp, f))
        if st.st_size == 0 or st.st_blocks * 512 < st.st_size * 0.95:
            not_local.append(rel)          # cloud online-only placeholder: reading it would trigger a download
            continue
        new.append(rel)
new.sort()
print(f"new video files: {len(new)} | skipped by rules: {skipped} | online-only (not downloaded): {len(not_local)}")
for r in not_local[:10]:
    print("  not downloaded:", r)
if args.dry_run or not new:
    for r in new[:40]:
        print("  new:", r)
    sys.exit(0)

existing = sorted(os.path.basename(d) for d in glob.glob(str(P.CATALOG / "batches" / "b*")))
batch = args.batch or f"b{(max([int(b[1:]) for b in existing if b[1:].isdigit()] + [0]) + 1):02d}"
bdir = P.CATALOG / "batches" / batch
wdir = P.WORK / batch
if (bdir / "technical.json").exists(): sys.exit(f"batch {batch} already exists - pick another --batch name")
bdir.mkdir(parents=True, exist_ok=True); wdir.mkdir(parents=True, exist_ok=True)


def probe(rel):
    p = P.abs_path(rel)
    row = {"path": rel, "folder": P.strip_prefix(os.path.dirname(rel)), "file": os.path.basename(rel), "size_mb": round(os.path.getsize(p) / 1e6, 1)}
    info = P.probe_video(p)
    if "error" in info:
        row["error"] = info["error"]; return row
    row.update(duration_s=round(info["duration_s"], 2), fps=info["fps"], width=info["width"], height=info["height"], codec=info["codec"], rotation=info["rotation"],
               portrait=info["portrait"], has_audio=info["has_audio"], created=info["created"], pix_fmt=info["pix_fmt"])
    return row


with ThreadPoolExecutor(8) as ex:
    rows = list(ex.map(probe, new))
P.save_json(bdir / "technical.json", rows)
ok = [r for r in rows if "error" not in r and r["duration_s"] > 0]
for r in rows:
    if "error" in r: print("  probe error:", r["path"], r["error"])
ok.sort(key=lambda r: (r["folder"], r["file"]))
for i, r in enumerate(ok, 1):
    r["id"] = f"{batch}_{i:03d}"
    r["times"] = [round(r["duration_s"] * (k + 0.5) / L.nframes(r["duration_s"]), 3) for k in range(L.nframes(r["duration_s"]))]

cw, ch = L.cell_size(P.PORTRAIT_PROJECT)
jobs = [(r["id"], k, P.abs_path(r["path"]), t) for r in ok for k, t in enumerate(r["times"])]
with ThreadPoolExecutor(12) as ex:
    futs = {(cid, k): ex.submit(L.grab, p, t, cw, ch) for cid, k, p, t in jobs}
    mot = {r["id"]: ex.submit(L.motion_ydif, P.abs_path(r["path"]), r["duration_s"]) for r in ok}
    frames = {k: f.result() for k, f in futs.items()}
    for r in ok:
        r["motion_ydif"] = mot[r["id"]].result()

sheets = []
for si in range(0, len(ok), L.ROWS_PER_SHEET):
    chunk = ok[si:si + L.ROWS_PER_SHEET]
    path = str(wdir / f"clips_{si // L.ROWS_PER_SHEET + 1:02d}.png")
    L.compose([(r["id"].split("_")[-1], [frames[(r["id"], k)] for k in range(len(r["times"]))]) for r in chunk], path, cw, ch)
    sheets.append({"kind": "clips", "sheet": path, "rows": [{"id": r["id"], "label": r["id"].split("_")[-1], "folder": r["folder"], "file": r["file"],
        "duration_s": r["duration_s"], "fps": r["fps"], "width": r["width"], "height": r["height"], "portrait": r["portrait"],
        "has_audio": r["has_audio"], "motion_ydif": r["motion_ydif"], "frame_times_s": r["times"]} for r in chunk]})
P.save_json(bdir / "clip_index.json", [{k: r[k] for k in ("id", "folder", "file", "path", "duration_s", "fps", "width", "height", "portrait", "has_audio", "created", "motion_ydif", "times")} for r in ok])

n_agents = args.agents or max(1, -(-len(ok) // 50))
per = -(-len(sheets) // n_agents)
for i in range(n_agents):
    g = sheets[i * per:(i + 1) * per]
    if g:
        letter = chr(ord("A") + i)
        P.save_json(wdir / f"agent_{letter}.json", {"cell_px": [cw, ch], "columns": L.COLS, "label_column_px": L.LABEL_W, "sheets": g})
        print(f"  helper {letter}: {len(g)} sheets, {sum(len(s['rows']) for s in g)} clips -> {wdir / ('agent_' + letter + '.json')}  (writes {bdir / ('tags_' + letter + '.json')})")
print(f"\nbatch {batch}: {len(ok)} clips ready. Tag them (python3 sb.py prompt tag_clips --manifest <agent_X.json> --out {bdir}/tags_<X>.json),")
print(f"then run:  python3 sb.py merge-batch {batch}")

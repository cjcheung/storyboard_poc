#!/usr/bin/env python3
"""Score clips: how good is the footage, and which template slots does it suit?

  python3 sb.py score --batch b01            # clips of a scanned+merged batch -> catalog/batches/b01/scores.csv/.json
  python3 sb.py score --ids b01_001 b02_014  # specific clips (prints only)
  python3 sb.py score --batch b01 --top 5

QUALITY (0-10, higher = better footage, independent of any slot):
  start 5.0
  + hero +1.5 | good_light +0.5 | energy (1..5) +0..+0.8 | good-time (visual tag 1..5) +0..+1.5 | smiling at camera +0.5 | waving +0.5
  + detector-only smile (not visually checked) up to +0.4 | 4K +0.3
  - dark -2 | blurry -3 | shaky -1 | obstructed -1.5 | overexposed -1 | awkward framing -1 | unflattering face -1 | text unreadable -0.3
  - wrong orientation for the project (vertical clip in a 16:9 edit, or the reverse) -3 (not used in automatic picks) | upside down / rotated -3 | shorter than 1 s -1
FIT (per slot, same scoring as sb.py match, ~3-12): category x3 + people + framing + energy + camera + quality flags + smile/wave bonus.
  'beats' = the clip fits that slot at least 0.5 better than the clip currently on the timeline there (fit scores only; it ignores taste). Timelapse slots and inserted shots are not compared.
Availability gates (history): never/hold clips and per-slot rejections are shown as 'blocked'."""
import argparse, collections, csv, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P, expr, scoring

ap = argparse.ArgumentParser()
ap.add_argument("--batch")
ap.add_argument("--ids", nargs="*")
ap.add_argument("--top", type=int, default=3, help="best-fit slots to list per clip")
a = ap.parse_args()

cat = expr.load(P.catalog())
by = {c["id"]: c for c in cat}
if a.batch:
    ids = [c["id"] for c in P.load_json(P.CATALOG / "batches" / a.batch / "clip_index.json")]
else:
    ids = a.ids or sys.exit("give --batch or --ids")
slots = {s["id"]: s for s in P.slots()}
picks = P.picks_doc()["picks"]
g = scoring.load_gates()
flags = P.clip_flags()
foot = [slots[sid] for sid, p in picks.items() if p["kind"] == "footage" and sid in slots and by[p["clip"]]["category"] != "timelapse"]   # footage slots; timelapse slots are fixed by the user
if not foot: foot = [s for s in slots.values() if s.get("needs_real_footage") and s.get("category") not in P.RULES["template_locked"]["categories"]]
cur_fit = {s["id"]: scoring.fit_score(s, by[picks[s["id"]]["clip"]]) for s in foot if picks.get(s["id"], {}).get("kind") == "footage"}

QPEN = {"dark": 2.0, "blurry": 3.0, "shaky": 1.0, "obstructed": 1.5, "overexposed": 1.0, "awkward_framing": 1.0, "unflattering_face": 1.0, "text_unreadable": 0.3}


def quality(c):
    q, why = 5.0, []
    def add(v, t):
        nonlocal q
        q += v; why.append(f"{v:+.1f} {t}")
    if c["hero"]: add(1.5, "hero")
    if "good_light" in c["quality_flags"]: add(0.5, "good light")
    add(round((c["energy"] - 1) / 4 * 0.8, 2), f"energy {c['energy']}")
    v = c.get("vt")
    if v:
        add(round((v["good_time"] - 1) / 4 * 1.5, 2), f"good-time {v['good_time']}/5")
        if v["smile_at_camera"]: add(0.5, "smiles at camera")
        if v["waving_at_camera"]: add(0.5, "waves")
    elif c.get("det"): add(round(min(0.4, 0.4 * c["det"]["smile_score"]), 2), "detector smile (unchecked)")
    if c["width"] >= 3840 or c["height"] >= 3840: add(0.3, "4K")
    for f in c["quality_flags"]:
        if f in QPEN: add(-QPEN[f], f)
    if "upside_down_or_rotated" in c["quality_flags"]: add(-3, "rotated")
    if P.orientation_mismatch(c): add(-3, P.MISMATCH_LABEL)
    if c["duration_s"] < 1: add(-1, "under 1s")
    return max(0.0, min(10.0, round(q, 1))), "; ".join(why)


rows = []
for cid in ids:
    c = by[cid]; q, why = quality(c)
    blocked = "never" if cid in g["never"] else "hold" if cid in g["hold"] else ""
    fits = []
    for s in foot:
        if c["category"] == "timelapse" or P.orientation_mismatch(c): continue
        if not scoring.duration_ok(s, c): continue
        if (s["id"], cid) in g["slot_rej"]: continue
        f = scoring.fit_score(s, c); fits.append((f, s["id"]))
    fits.sort(reverse=True)
    top = fits[:a.top]
    beats = [(sid, round(f - cur_fit[sid], 1)) for f, sid in fits if sid in cur_fit and f - cur_fit[sid] >= 0.5 and not slots[sid].get("inserted")]
    beats.sort(key=lambda x: -x[1])
    rows.append({"id": cid, "file": c["file"], "folder": c["folder"], "duration_s": c["duration_s"], "fps": c["fps"], "res": f'{c["width"]}x{c["height"]}',
                 "category": c["category"], "people": c["people"], "energy": c["energy"], "hero": c["hero"], "summary": c["summary"],
                 "quality": q, "usable": "no" if (P.orientation_mismatch(c) or blocked or q < 3) else "yes", "blocked": blocked, "quality_notes": why,
                 "best_slots": ", ".join(f"{sid}:{f:.1f}" for f, sid in top), "beats_current": ", ".join(f"{sid}(+{d})" for sid, d in beats[:5]),
                 "release_check": cid in flags["check_releases"], "needs_grade": cid in flags["needs_grade"]})
rows.sort(key=lambda r: -r["quality"])
if a.batch and rows:
    out = P.CATALOG / "batches" / a.batch
    P.save_json(out / "scores.json", rows)
    with open(out / "scores.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print("wrote", out / "scores.csv")
qs = [r["quality"] for r in rows]
if qs:
    print(f"{len(rows)} clips | quality mean {sum(qs)/len(qs):.1f} | usable {sum(r['usable']=='yes' for r in rows)} | scoring 7+: {sum(q>=7 for q in qs)} | below 4: {sum(q<4 for q in qs)} | beat a current pick: {sum(bool(r['beats_current']) for r in rows)}")

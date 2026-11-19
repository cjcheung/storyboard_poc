#!/usr/bin/env python3
"""Merge a tagged batch into the catalog (catalog/clips.json or storyboard_project.json catalog_file).   usage: python3 sb.py merge-batch b01

Checks that every clip of the batch has exactly one tag and that the categories are in the project's taxonomy.
Optional storyboard_project.json "days": {"path_regex": "Day (\\\\d+)", "tz": "America/New_York", "dates": ["2027-05-01", "2027-05-02"]}
adds a 'day' number per clip (from the folder name, else from the recording date)."""
import datetime, glob, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P

if len(sys.argv) < 2: sys.exit(__doc__)
batch = sys.argv[1]
DAYS = P.CFG.get("days") or None


def day_of(c):
    m = re.search(DAYS.get("path_regex", r"Day (\d+)"), c["path"]) if DAYS.get("path_regex", r"Day (\d+)") else None
    if m: return int(m.group(1))
    try:
        import zoneinfo
        t = datetime.datetime.fromisoformat(c.get("created", "").replace("Z", "+00:00"))
        if DAYS.get("tz"): t = t.astimezone(zoneinfo.ZoneInfo(DAYS["tz"]))
        d = t.date().isoformat()
        return DAYS.get("dates", []).index(d) + 1 if d in DAYS.get("dates", []) else 0
    except Exception:
        return 0


bdir = P.CATALOG / "batches" / batch
idx = {c["id"]: c for c in P.load_json(bdir / "clip_index.json")}
tags = {}
for f in sorted(glob.glob(str(bdir / "tags_*.json"))):
    for t in json.load(open(f, encoding="utf-8")):
        if t["id"] in tags: sys.exit(f"duplicate tag for {t['id']}")
        tags[t["id"]] = t
missing, extra = sorted(set(idx) - set(tags)), sorted(set(tags) - set(idx))
if missing or extra:
    sys.exit(f"tags do not match the batch. untagged: {missing[:10]} unknown ids: {extra[:10]}")
CATS = set(P.CATEGORIES)
bad = [i for i, t in tags.items() if t["category"] not in CATS]
if bad:
    sys.exit(f"off-schema categories on: {bad[:10]} (allowed: {sorted(CATS)})")
cat = P.catalog()
have = {c["id"] for c in cat}
if have & set(idx):
    sys.exit("batch already merged")
for i, c in idx.items():
    d = dict(c); d.update({k: v for k, v in tags[i].items() if k != "id"})
    if DAYS: d["day"] = day_of(c)
    cat.append(d)
P.save_json(P.CATALOG_FILE, cat)
print(f"merged {len(idx)} clips from {batch}; catalog now has {len(cat)} clips.")
print("Next: python3 sb.py expressions  (macOS smile/face scan, optional), python3 sb.py score --batch " + batch)

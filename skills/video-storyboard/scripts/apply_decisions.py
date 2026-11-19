#!/usr/bin/env python3
"""Apply a round of storyboard decisions to the project (picks, history, rejections) - does NOT touch Resolve.

  python3 sb.py apply --from-proposal round1 --timeline <name>_v1           # first round: the matcher's proposal becomes the current picks
  python3 sb.py apply --timeline <name>_v3 [--round 2] [--defer s22] [--overrides FILE] [--allow-reuse b01_012] [--dry-run]
  python3 sb.py apply --timeline <name>_v3 --suggestions-only              # apply suggestions.json 'replace_current' picks

Reads storyboard/decisions/inbox.json (swap | keep | speed_change | note). For each entry: updates history/current_picks.json, appends to
history/decisions_log.csv, records the replaced clip in history/rejected_clips.csv (scope from the page: slot | never | none), checks that no clip
is used twice at overlapping moments (unless --allow-reuse), writes history/rounds/round_NNN_<timeline>.json, and archives the inbox to
storyboard/decisions/processed/.
--overrides: JSON list of interpreted notes, each {slot, clip, src_in_s, src_out_s, speed_percent, zoom?, pan?, tilt?, reason, reject_previous?}.
--defer: slots left unchanged and recorded in history/pending_decisions.json (shown on the storyboard row)."""
import argparse, csv, datetime, json, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P, expr

ap = argparse.ArgumentParser()
ap.add_argument("--timeline", help="name of the Resolve timeline these picks are for (default: the current one, or version 1)")
ap.add_argument("--round", type=int)
ap.add_argument("--defer", nargs="*", default=[])
ap.add_argument("--overrides")
ap.add_argument("--allow-reuse", nargs="*", default=[])
ap.add_argument("--suggestions-only", action="store_true")
ap.add_argument("--from-proposal", help="match sheet name: take its picks as the current picks (first round)")
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()
TODAY = datetime.date.today().isoformat()

cat = {c["id"]: c for c in expr.load(P.catalog())}
slots = {s["id"]: s for s in P.slots()}
doc = P.picks_doc(); picks = doc["picks"]
a.timeline = a.timeline or doc.get("timeline") or P.timeline_name(1)
inbox_path = P.STORYBOARD / "decisions" / "inbox.json"
log, rej = [], []

auto_framing = expr.auto_framing


def set_pick(sid, clip, i, o, speed, lock=False, rnd=None, framing=None):
    c = cat[clip]; p = {"kind": "footage", "clip": clip, "file": c["file"], "path": c["path"], "src_in_s": i, "src_out_s": o,
                        "speed_percent": speed, "locked": lock, "round": rnd, "timeline": a.timeline}
    p.update(auto_framing(c)); p.update(framing or {})
    picks[sid] = p


def add_log(rnd, sid, action, before="", after="", sb="", sa="", scope="slot", reason="", by="user"):
    log.append([TODAY, rnd, sid, action, before, after, sb, sa, scope, reason, by])


def add_rej(clip, scope, sid, reason, rnd):
    if clip and scope in ("slot", "never"): rej.append([clip, scope, sid if scope == "slot" else "", reason, rnd, TODAY, "user"])


rnd = a.round
pending = P.load_json(P.HISTORY / "pending_decisions.json", {})
if a.from_proposal:
    rnd = rnd or 1
    for o in P.load_json(P.CATALOG / f"match_sheet_{a.from_proposal}.json"):
        sid = o["slot"]
        if picks.get(sid, {}).get("locked"): continue
        before = picks.get(sid, {}).get("clip", "")
        set_pick(sid, o["clip"], o["src_in_s"], o["src_out_s"], 50 if o["speed"] != "100%" else 100, False, rnd)
        add_log(rnd, sid, "initial_pick", before, o["clip"], "", picks[sid]["speed_percent"], "none", f"proposal {a.from_proposal} (score {o['score']})", "agent")
elif not a.suggestions_only:
    inbox = P.load_json(inbox_path); rnd = rnd or inbox["round"]; who = inbox.get("who") or "user"
    ov = {o["slot"]: o for o in P.load_json(a.overrides)} if a.overrides else {}
    for e in inbox["decisions"]:
        sid = e["slot"]; note = e.get("note", "")
        if sid in a.defer:
            pending[sid] = e; add_log(rnd, sid, "deferred", reason="left unchanged for now: " + (note or e["action"] + " " + str(e.get("clip", ""))), by=who); continue
        if e["action"] == "note":
            add_log(rnd, sid, "note", reason=note, by=who)
        elif e["action"] == "swap":
            before = picks.get(sid, {}).get("clip", "")
            set_pick(sid, e["clip"], e["src_in_s"], e["src_out_s"], e["speed_percent"], e.get("lock", False), rnd)
            add_log(rnd, sid, "swap", before, e["clip"], e.get("previous_speed_percent", ""), e["speed_percent"], e.get("reject_previous", "slot"), "storyboard choice " + e["choice"] + ("; " + note if note else ""), who)
            add_rej(before, e.get("reject_previous", "slot"), sid, "replaced in round %d" % rnd, rnd)
        elif e["action"] in ("keep", "speed_change"):
            p = picks[sid]
            if e["action"] == "speed_change" or e["speed_percent"] != p.get("speed_percent"):
                add_log(rnd, sid, "speed_change", p["clip"], p["clip"], p.get("speed_percent"), e["speed_percent"], reason=note, by=who)
                p.update(speed_percent=e["speed_percent"], src_in_s=e["src_in_s"], src_out_s=e["src_out_s"])
            else:
                add_log(rnd, sid, "keep", p["clip"], p["clip"], reason=("reviewed, kept" + ("; " + note if note else "")), by=who)
            if e.get("lock") and not p.get("locked"):
                p["locked"] = True; add_log(rnd, sid, "lock", p["clip"], p["clip"], by=who)
            p["round"] = rnd
    for sid, o in ov.items():                                   # interpreted notes win over the page's raw choice
        before = picks.get(sid, {}).get("clip", "")
        fr = {k: o[k] for k in ("zoom", "pan", "tilt") if k in o}
        set_pick(sid, o["clip"], o["src_in_s"], o["src_out_s"], o.get("speed_percent", 100), False, rnd, fr)
        add_log(rnd, sid, "swap" if before != o["clip"] else "reframe", before, o["clip"], picks[sid].get("speed_percent", ""), o.get("speed_percent", 100), o.get("reject_previous", "none"), o["reason"], who)
        if before and before != o["clip"]: add_rej(before, o.get("reject_previous", "none"), sid, o["reason"], rnd)
else:
    rnd = rnd or 2
    sug = P.load_json(P.CATALOG / "suggestions.json")
    for sid, s in sug.items():
        if not s.get("replace_current"): continue
        before = picks.get(sid, {}).get("clip", ""); top = s["clips"][0]
        i, o = expr.window(slots[sid], cat[top]); set_pick(sid, top, i, o, 100, False, rnd)
        add_log(rnd, sid, "swap", before, top, "", 100, "none", "user note: shuffle current + suggestions (%s); top suggestion becomes current" % s["criteria"], "user")
        s["clips"] = s["clips"][1:]

# ---- duplicate check on the final state: the same FILE may be reused, but never the same FRAMES (source windows must not overlap) ----
use = {}
for sid, p in picks.items():
    if p["kind"] == "footage": use.setdefault(p["clip"], []).append(sid)
dups = {}
for c, v in use.items():
    if len(v) < 2 or c in a.allow_reuse: continue
    bad = [(x, y) for i, x in enumerate(v) for y in v[i + 1:] if picks[x]["src_in_s"] < picks[y]["src_out_s"] and picks[y]["src_in_s"] < picks[x]["src_out_s"]]
    if bad: dups[c] = bad
if dups:
    print("OVERLAPPING frames of the same file in the final picks (nothing written):", dups); sys.exit(1)
for c, v in use.items():
    if len(v) > 1:
        for sid in v: add_log(rnd, sid, "reuse_ok", c, c, reason="same file used in %s at different, non-overlapping moments" % "/".join(v))

print(f"round {rnd}: {len(log)} log rows, {len(rej)} rejections | deferred: {a.defer or '-'}")
swaps = [r for r in log if r[3] in ("swap", "initial_pick")]; print("picks changed:", [(r[2], (r[4] or '-') + '->' + r[5]) for r in swaps][:40])
if a.dry_run: sys.exit(0)

doc["timeline"] = a.timeline
P.save_json(P.PICKS_FILE, doc)
P.save_json(P.HISTORY / "pending_decisions.json", pending)
P.save_json(P.HISTORY / "rounds" / f"round_{rnd:03d}_{a.timeline}.json", {"round": rnd, "timeline": a.timeline, "note": "picks after applying the storyboard decisions", "picks": picks})
def append_csv(path, cols, rows):
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new: w.writerow(cols)
        w.writerows(rows)
append_csv(P.HISTORY / "decisions_log.csv", ["date", "round", "slot", "action", "clip_before", "clip_after", "speed_before", "speed_after", "scope", "reason", "by"], log)
append_csv(P.HISTORY / "rejected_clips.csv", ["clip_id", "scope", "slot", "reason", "round", "date", "by"], rej)
if a.suggestions_only: P.save_json(P.CATALOG / "suggestions.json", sug)
elif not a.from_proposal and inbox_path.exists():
    done = P.STORYBOARD / "decisions" / "processed"; done.mkdir(parents=True, exist_ok=True)
    shutil.move(str(inbox_path), str(done / f"round_{rnd:03d}_{TODAY}.json")); print("inbox archived ->", done.name)
print("picks, log and rejections written")

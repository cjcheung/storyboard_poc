#!/usr/bin/env python3
"""Look things up in, and append to, the running history (history/ in the project).

  python3 sb.py history slot s04            # everything that ever happened on slot s04
  python3 sb.py history clip b01_007        # where a clip is used / was tried / was rejected
  python3 sb.py history summary             # current picks, locks, rejections at a glance
  python3 sb.py history log --round 1 --slot s04 --action swap --before b01_003 --after b01_007 --reason "waving shot" --by editor
  python3 sb.py history reject --clip b01_003 --scope slot --slot s04 --reason "too dark" --round 1 --by editor
      scope: slot = not for this slot (default) | never = never use anywhere | hold = needs a fix first
"""
import argparse, csv, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P

LOG, REJ, PICKS = P.HISTORY / "decisions_log.csv", P.HISTORY / "rejected_clips.csv", P.PICKS_FILE
LOG_COLS = ["date", "round", "slot", "action", "clip_before", "clip_after", "speed_before", "speed_after", "scope", "reason", "by"]
REJ_COLS = ["clip_id", "scope", "slot", "reason", "round", "date", "by"]


def rows(path): return list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []


def append(path, cols, row):
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        if new: w.writeheader()
        w.writerow({c: row.get(c, "") for c in cols})


ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
for name in ("slot", "clip"):
    sub.add_parser(name).add_argument("id")
sub.add_parser("summary")
lg = sub.add_parser("log")
for a in ("round", "slot", "action", "before", "after", "speed_before", "speed_after", "scope", "reason", "by"): lg.add_argument("--" + a, default="")
rj = sub.add_parser("reject")
for a in ("clip", "slot", "reason", "round", "by"): rj.add_argument("--" + a, default="")
rj.add_argument("--scope", default="slot", choices=["slot", "never", "hold"])
a = ap.parse_args()
today = datetime.date.today().isoformat()

if a.cmd == "slot":
    print(f"== log for {a.id} ==")
    for r in rows(LOG):
        if r["slot"] == a.id: print(" ", r["date"], f"round {r['round']}", r["action"], r["clip_before"] or "-", "->", r["clip_after"] or "-", "|", r["reason"], f"({r['by']})")
    print("== rejected for this slot ==")
    for r in rows(REJ):
        if r["slot"] == a.id: print(" ", r["clip_id"], r["scope"], "|", r["reason"])
    p = P.picks_doc()["picks"].get(a.id)
    print("== on the timeline now ==\n ", p)
elif a.cmd == "clip":
    print(f"== log mentions of {a.id} ==")
    for r in rows(LOG):
        if a.id in (r["clip_before"], r["clip_after"]): print(" ", r["date"], f"round {r['round']}", r["slot"], r["action"], r["clip_before"] or "-", "->", r["clip_after"] or "-", "|", r["reason"])
    print("== rejections ==")
    for r in rows(REJ):
        if r["clip_id"] == a.id: print(" ", r["scope"], r["slot"] or "(any slot)", "|", r["reason"], f"(round {r['round']})")
    print("== on the timeline now ==")
    for sid, p in P.picks_doc()["picks"].items():
        if p.get("clip") == a.id: print("  slot", sid, p)
elif a.cmd == "summary":
    picks = P.picks_doc()
    ps = picks["picks"].values()
    print("timeline:", picks.get("timeline"), "| footage slots:", sum(1 for p in ps if p["kind"] == "footage"), "| graphics:", sum(1 for p in ps if p["kind"] == "graphic"),
          "| template placeholders:", sum(1 for p in ps if p["kind"] == "template" and not p.get("interview")), "| interview-picture spots:", sum(1 for p in ps if p.get("interview")),
          "| user-locked footage:", sum(1 for p in ps if p["kind"] == "footage" and p.get("locked")))
    rj_ = rows(REJ); print("rejections:", {s: sum(1 for r in rj_ if r["scope"] == s) for s in ("never", "hold", "slot")})
    lg_ = rows(LOG); print("log entries:", len(lg_), "| rounds seen:", sorted({r["round"] for r in lg_}))
elif a.cmd == "log":
    append(LOG, LOG_COLS, {"date": today, "round": a.round, "slot": a.slot, "action": a.action, "clip_before": a.before, "clip_after": a.after,
                           "speed_before": a.speed_before, "speed_after": a.speed_after, "scope": a.scope, "reason": a.reason, "by": a.by})
    print("logged.")
elif a.cmd == "reject":
    append(REJ, REJ_COLS, {"clip_id": a.clip, "scope": a.scope, "slot": a.slot if a.scope == "slot" else "", "reason": a.reason, "round": a.round, "date": today, "by": a.by})
    print("rejection recorded:", a.clip, a.scope, a.slot)

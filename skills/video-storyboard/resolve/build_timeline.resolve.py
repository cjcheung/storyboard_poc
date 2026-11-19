# Runs INSIDE DaVinci Resolve (the davinci-resolve MCP tool `run_script_unsafe`, which injects `resolve` and `project`).
# Usage: send a script whose first line sets CFG, then execs this file (python3 sb.py resolve-script build_timeline prints it):
#
#   CFG = dict(PLAN="<work>/build_plan.json", NAME="<project>_main_v1", MODE="import")
#   exec(open("<skill>/resolve/build_timeline.resolve.py", encoding="utf-8").read())
#
# MODE order (each MCP call must finish in < ~60 s, so build in chunks of ~25-30 slots):
#   "import"  - make bins (Reference, Music, Graphics + one per top-level footage folder), import every clip of the plan, create the empty timeline
#   "build"   - append slots A..B (python slice) one by one on Video 1;  e.g. A=0,B=30 then A=30,B=60 ...
#   "finish"  - music bed on Audio 1, per-shot zoom/pan/tilt, one marker per footage slot (single-track layout; the overlay layout re-lays music)
#   "replace" - swap the clip in the plan slots listed in CFG["SLOTS"] in place (keeps each slot's exact range; replaces its marker). Run `import` first.
#   "frame"   - re-apply only zoom/pan/tilt
#   "fill"    - place the plan slots flagged "inserted" into an EXISTING timeline's empty gap (no ripple), sequentially from the actual end of the
#               previous shot so the last one lands exactly on the next slot's start; adds their markers. Run `import` first (on a duplicate of the timeline).
#   "verify"  - READ-ONLY check of the timeline against the plan (safe on any existing timeline)
# What this encodes (learned the hard way):
#   * AppendToTimeline startFrame/endFrame are in the CLIP's own frame rate, endFrame EXCLUSIVE; durations are converted to the
#     timeline rate. Never place by recordFrame in a busy track - overlaps get silently trimmed. Append sequentially and size each clip to hit the
#     slot boundary from the ACTUAL end so rounding never accumulates.
#   * Slow motion: append HALF the source span, then SetSpeed(50, RippleTimeline=True) while it is the last item.
#   * Audio-only placement of a music file: endFrame is counted in the PROJECT frame rate, not the timeline's.
#   * mediaType 1 = video only (camera audio is not used; dialogue comes from the interview layer).
import json, os
cfg = dict(PLAN=None, NAME=None, MODE="verify", A=0, B=30)
cfg.update(globals().get("CFG", {}))
plan = json.load(open(cfg["PLAN"], encoding="utf-8")); slots = plan["slots"]
FPS = float(plan["fps"]); TFPS = float(plan.get("template_fps") or FPS)
ROOTS = sorted(plan.get("footage_roots", []), key=len, reverse=True)
mp = project.GetMediaPool(); root = mp.GetRootFolder()


class _Pool(dict):
    """media-pool lookup by File Path; falls back to the path below a footage root, so a clip is found whether the pool links it to the
    original footage folder or to a mirrored copy"""
    @staticmethod
    def tail(p):
        for r in ROOTS:
            if p.startswith(r.rstrip("/") + "/"): return p[len(r.rstrip("/")) + 1:]
        if "/footage/" in p: return p.split("/footage/")[-1]
        return p
    def __missing__(self, key):
        t = self.tail(key)
        for k, v in self.items():
            if self.tail(k) == t: return v
        raise KeyError(key)
    def __contains__(self, key):
        try: self[key]; return True
        except KeyError: return False


def pool_by_path():
    out = _Pool()
    def walk(f):
        for c in f.GetClipList():
            p = c.GetClipProperty("File Path")
            if p: out[p] = c
        for s in f.GetSubFolderList(): walk(s)
    walk(root); return out


def get_timeline(name):
    for i in range(1, project.GetTimelineCount() + 1):
        t = project.GetTimelineByIndex(i)
        if t.GetName() == name: return t
    return None


def bin_named(name):
    for f in root.GetSubFolderList():
        if f.GetName() == name: return f
    return mp.AddSubFolder(root, name)


def bin_for(path):
    if "/assets/" in path: return "Graphics"
    t = _Pool.tail(path)
    return (t.split("/")[0] if "/" in t else "Footage")[:40] or "Footage"


def apply_frame(e, it):
    """Per-shot framing from the pick: zoom (1.0 = fit), pan / tilt in timeline pixels (Resolve: +pan moves the image right, +tilt moves it up)."""
    if e.get("zoom"): it.SetProperty("ZoomX", e["zoom"]); it.SetProperty("ZoomY", e["zoom"])
    if e.get("pan") is not None: it.SetProperty("Pan", float(e["pan"]))
    if e.get("tilt") is not None: it.SetProperty("Tilt", float(e["tilt"]))


mode = cfg["MODE"]; result = {"mode": mode}

if mode == "import":
    have = pool_by_path(); n_new, failed = 0, []
    wanted = [(plan["reference"], "Reference")] + ([(plan["music"], "Music")] if plan.get("music") else []) + [(e["path"], bin_for(e["path"])) for e in slots if e["kind"] == "new"]
    bins = {}
    for path, b in wanted:
        if not path or path in have: continue
        if b not in bins: bins[b] = bin_named(b)
        mp.SetCurrentFolder(bins[b])
        items = mp.ImportMedia([path])
        if items: n_new += 1; have[path] = items[0]
        else: failed.append(path)              # an empty result is a stop sign (a file Resolve cannot read can hang/crash it on retry): pick another clip
    mp.SetCurrentFolder(root)
    tl = get_timeline(cfg["NAME"]); created = False
    if tl is None:
        tl = mp.CreateEmptyTimeline(cfg["NAME"])
        tl.SetSetting("useCustomSettings", "1"); tl.SetSetting("timelineFrameRate", str(plan["fps"]))
        tl.SetSetting("timelineResolutionWidth", str(plan.get("width", 1920))); tl.SetSetting("timelineResolutionHeight", str(plan.get("height", 1080)))
        created = True
    result.update(imported=n_new, failed=failed, timeline_created=created, fps=tl.GetSetting("timelineFrameRate"),
                  size=(tl.GetSetting("timelineResolutionWidth"), tl.GetSetting("timelineResolutionHeight")))

elif mode == "build":
    tl = get_timeline(cfg["NAME"]); project.SetCurrentTimeline(tl); base = tl.GetStartFrame(); pool = pool_by_path(); log = []
    for e in slots[cfg["A"]:cfg["B"]]:
        items = tl.GetItemListInTrack("video", 1)
        cur = (items[-1].GetEnd() - base) if items else 0
        T = e["b_next"] - cur                                  # frames still needed to land on the template boundary
        item = pool[e["path"]]; fps = float(item.GetClipProperty("FPS"))
        if e["kind"] == "ref":
            n = max(1, round(T * TFPS / FPS)); sf, ef = e["ref_s"], e["ref_s"] + n
        else:
            secs = (T / FPS) / (2 if e["slow"] else 1)
            n = max(1, round(secs * fps)); sf = round(e["in_s"] * fps); ef = sf + n
        ok = mp.AppendToTimeline([{"mediaPoolItem": item, "startFrame": sf, "endFrame": ef, "mediaType": 1}])
        it = tl.GetItemListInTrack("video", 1)[-1]
        if ok and e.get("slow"):
            it.SetSpeed({"Percentage": 50.0, "RippleTimeline": True}); it = tl.GetItemListInTrack("video", 1)[-1]
        log.append([e["slot"], T, it.GetDuration(), it.GetEnd() - base, e["b_next"], bool(ok)])
    items = tl.GetItemListInTrack("video", 1)
    result.update(items=len(items), end_rel=items[-1].GetEnd() - base, bad=[l for l in log if (not l[5]) or abs(l[3] - l[4]) > 1])

elif mode == "finish":
    tl = get_timeline(cfg["NAME"]); project.SetCurrentTimeline(tl); base = tl.GetStartFrame(); pool = pool_by_path()
    items = tl.GetItemListInTrack("video", 1)
    ok = None
    if plan.get("music"):
        pf = float(project.GetSetting("timelineFrameRate"))              # audio endFrame counts in PROJECT fps
        end_f = round(plan["total_frames"] / plan["fps"] * pf)
        old = tl.GetItemListInTrack("audio", 1)
        if old: tl.DeleteClips(old)
        ok = mp.AppendToTimeline([{"mediaPoolItem": pool[plan["music"]], "startFrame": 0, "endFrame": end_f, "mediaType": 2, "trackIndex": 1, "recordFrame": base}])
    markers = 0
    for e, it in zip(slots, items):
        apply_frame(e, it)
        if e.get("marker") and tl.AddMarker(it.GetStart() - base, e["marker"]["color"], e["slot"], e["marker"]["note"], 1): markers += 1
    a1 = tl.GetItemListInTrack("audio", 1)
    result.update(music_ok=bool(ok) if ok is not None else "no music in the plan", music=[(i.GetStart() - base, i.GetDuration()) for i in a1], markers=markers)

elif mode == "fill":
    tl = get_timeline(cfg["NAME"]); project.SetCurrentTimeline(tl); base = tl.GetStartFrame(); pool = pool_by_path(); log = []
    ins = [e for e in slots if e.get("inserted")]; cur = ins[0]["b_start"]
    for e in ins:
        T = e["b_next"] - cur; item = pool[e["path"]]; fps = float(item.GetClipProperty("FPS"))
        n = max(1, round(T / FPS * fps)); sf = round(e["in_s"] * fps)
        ok = mp.AppendToTimeline([{"mediaPoolItem": item, "startFrame": sf, "endFrame": sf + n, "mediaType": 1, "trackIndex": 1, "recordFrame": base + cur}])
        placed = [i for i in tl.GetItemListInTrack("video", 1) if i.GetStart() - base == cur]
        it = placed[0] if placed else None
        log.append([e["slot"], cur, T, it.GetDuration() if it else None, bool(ok)])
        if it:
            cur = it.GetEnd() - base
            if e.get("marker"): tl.AddMarker(it.GetStart() - base, e["marker"]["color"], e["slot"], e["marker"]["note"], 1)
        else: break
    result.update(placed=len([l for l in log if l[3]]), end_rel=cur, wanted_end=ins[-1]["b_next"], bad=[l for l in log if (not l[4]) or l[3] != l[2]])

elif mode == "replace":            # swap the clip in the given plan slots (cfg["SLOTS"]) in place: each keeps the ACTUAL range of the shot it replaces, nothing ripples
    tl = get_timeline(cfg["NAME"]); project.SetCurrentTimeline(tl); base = tl.GetStartFrame(); pool = pool_by_path(); log = []
    for e in slots:
        if e["slot"] not in cfg["SLOTS"]: continue
        vid = tl.GetItemListInTrack("video", 1)
        near = sorted(vid, key=lambda i: abs(i.GetStart() - base - e["b_start"]))
        if not near or abs(near[0].GetStart() - base - e["b_start"]) > 2: log.append([e["slot"], "no item near the planned start"]); continue
        old = near[0]; os_, oe = old.GetStart() - base, old.GetEnd() - base; T = oe - os_          # the shot's real range (the build can be 1 frame off the plan)
        if e["slot"] in cfg.get("RANGES", {}):                                                  # explicit range, e.g. to finish an interrupted replace
            os_, oe = cfg["RANGES"][e["slot"]]; T = oe - os_; old = ([i for i in vid if i.GetStart() - base == os_] or [None])[0]
        nxt = [i for i in vid if i.GetStart() - base == oe]; nxt_dur = nxt[0].GetDuration() if nxt else None
        if old is not None: tl.DeleteClips([old], False)
        tl.DeleteMarkerAtFrame(os_)
        item = pool[e["path"]]; fps = float(item.GetClipProperty("FPS")); sf = round(e["in_s"] * fps); n = max(1, round(T / FPS * fps))
        ok = mp.AppendToTimeline([{"mediaPoolItem": item, "startFrame": sf, "endFrame": sf + n, "mediaType": 1, "trackIndex": 1, "recordFrame": base + os_}])
        if ok and e.get("slow"):                      # full-length span placed; SetSpeed 50% without ripple keeps the length and plays the first half of the span at half speed
            placed = [i for i in tl.GetItemListInTrack("video", 1) if i.GetStart() - base == os_]
            if placed: placed[0].SetSpeed({"Percentage": 50.0, "RippleTimeline": False})
        vid = tl.GetItemListInTrack("video", 1)
        new = [i for i in vid if i.GetStart() - base == os_]; nxt2 = [i for i in vid if i.GetStart() - base == oe]
        good = bool(ok) and len(new) == 1 and new[0].GetDuration() == T and (nxt_dur is None or (nxt2 and nxt2[0].GetDuration() == nxt_dur))
        if good and e.get("marker"): tl.AddMarker(os_, e["marker"]["color"], e["slot"], e["marker"]["note"], 1)
        log.append([e["slot"], good, new[0].GetDuration() if new else None, T])
    result.update(replaced=len([l for l in log if l[1] is True]), bad=[l for l in log if l[1] is not True], log=log)

elif mode == "frame":              # re-apply zoom/pan/tilt only (after editing the framing in the picks)
    tl = get_timeline(cfg["NAME"]); items = tl.GetItemListInTrack("video", 1)
    for e, it in zip(slots, items): apply_frame(e, it)
    result.update(framed=[(e["slot"], e.get("zoom"), e.get("pan"), e.get("tilt")) for e in slots if e.get("zoom") or e.get("pan") is not None])

elif mode == "verify":
    tl = get_timeline(cfg["NAME"]); base = tl.GetStartFrame(); items = tl.GetItemListInTrack("video", 1)
    wrong_src, off_cut, slow_bad = [], [], []
    for e, it in zip(slots, items):
        mpi = it.GetMediaPoolItem(); p = mpi.GetClipProperty("File Path") if mpi else None
        if _Pool.tail(p or "") != _Pool.tail(e["path"]): wrong_src.append(e["slot"])
        if abs((it.GetEnd() - base) - e["b_next"]) > 1: off_cut.append((e["slot"], it.GetEnd() - base, e["b_next"]))
        if e.get("slow"):
            sp = it.GetSpeed()
            if not sp or abs(sp.get("Percentage", 0) - 50.0) > 0.5: slow_bad.append(e["slot"])
    gaps = sum(1 for a, b in zip(items, items[1:]) if a.GetEnd() != b.GetStart())
    a1 = tl.GetItemListInTrack("audio", 1)
    result.update(timeline=cfg["NAME"], fps=tl.GetSetting("timelineFrameRate"), items=len(items), expected_items=len(slots), wrong_source=wrong_src,
                  cut_off_by_more_than_1f=off_cut, slow_wrong=slow_bad, gaps=gaps, end_rel=(items[-1].GetEnd() - base) if items else 0, expected_end=plan["total_frames"],
                  music=[(i.GetStart() - base, i.GetDuration()) for i in a1], markers=len(tl.GetMarkers()))
print(json.dumps(result, default=str))

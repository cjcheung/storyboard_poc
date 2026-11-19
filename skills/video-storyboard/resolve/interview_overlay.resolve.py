# Runs INSIDE DaVinci Resolve (MCP tool `run_script_unsafe`). Turns a finished single-track edit (built with build_timeline.resolve.py) into the
# INTERVIEW OVERLAY layout:   Video 2 = b-roll / graphics / template shots (moved up one track, same timing)
#                             Video 1 = the interview (A-roll) pictures (they show through where Video 2 is empty = the plan's "gap" slots)
#                             Audio 1 = interview audio, each interview normalized to its True Peak target (or leveled per piece, see dialogue_level)
#                             Audio 2 = ONE music clip at a constant level (no ducking) - plan["music_cfg"]
# Usage (run on a DUPLICATE of the timeline, never on the original; one MODE per call):
#   CFG = dict(PLAN="<work>/build_plan.json", NAME="<project>_main_v10", MODE="relocate", A=0, B=32)
#   exec(open("<skill>/resolve/interview_overlay.resolve.py", encoding="utf-8").read())
# MODES
#   relocate    A..B slices of the plan (~32 slots per call): move each shot Video 1 -> Video 2 (gap slots are deleted instead). Use on a single-track edit.
#   clear_gaps  delete the Video 2 shots at every gap slot (use when a new interview adds gap spots to an edit that is already in the overlay layout)
#   place       re-place the plan slots in CFG["SLOTS"] on Video 2 at their planned positions (template shots whose interview moved away, or any shot that was cleared)
#   swap        change the clip/source window of CFG["SLOTS"] on Video 2 in place (keeps each shot's actual range; rewrites its marker). Run build_timeline MODE import first if the new clip is not in the media pool
#   frame_iv    (re)apply every interview's framing ('framing': zoom/tilt, e.g. to fill the frame with a portrait clip; 'framing_pieces' per cut) to its Video 1 pictures
#   blur_bg     "Instagram" layout for interviews with "background": "blur" (a clip of the other orientation): Fusion comp per Video 1 picture, sharp original fitted over a blurred copy that fills the frame
#   fill_gap    lay CFG["SLOTS"] (ids, in order) into the empty gap on the b-roll track at the first slot's planned start (inserted b-roll covering an interview picture); EXACT=True keeps planned lengths
#   grade_iv    apply each interview's "grade" (CDL slope/power) to its Video 1 pictures
#   end_fades   music fade-out + fade to black on the last Video 2 shot (plan music_cfg fade_out_frames / picture_fade_frames)
#   clear_range delete the interview picture (Video 1) + audio (audio track 1) items and INTERVIEW markers inside CFG["RANGE"]=[lo, hi] timeline frames (an interview that moved elsewhere)
#   clear_audio delete everything on audio tracks 1 and 2 (before re-laying the interview audio / music)
#   interview   place every interview (Video 1 picture + audio on its audio track); skips the picture if Video 1 already has it; ONLY=[ids] limits it
#   normalize   per interview: Resolve's True Peak normalizer (relative), then the exact measured gain (sb.py measure-interviews) because Resolve rounds to 0.1 dB
#   music       one music clip on the music track at the plan level for the whole video (with music_outro_*: the keyframed nested music timeline made by sb.py plan)
#   markers     delete ALL markers and rebuild them from the actual Video 2 shots + the interviews (after hand edits / ripple inserts)
#   markers_by_clip  same, but each shot keeps the marker of the same FILE (for timelines the person re-ordered / lengthened by hand)
#   verify      READ-ONLY check of the whole layout
# Never re-run `music` or `end_fades` on a timeline where the user keyframed the music by hand: `music` deletes and re-adds the clip.
# Learned the hard way: audio-only AppendToTimeline of a VIDEO file's audio takes the clip's own frame-rate units; a music file uses PROJECT-fps units;
# 23.976/24 fps shots can land one timeline frame short when re-placed (retry one source frame longer); never ripple in the middle of a timeline.
import json
cfg = dict(PLAN=None, NAME=None, MODE="verify", A=0, B=32)
cfg.update(globals().get("CFG", {}))
plan = json.load(open(cfg["PLAN"], encoding="utf-8")); slots = plan["slots"]; ovs = plan.get("overlay", []); mc = plan.get("music_cfg", {"track": 2, "level_db": 0.0})
mp = project.GetMediaPool(); root = mp.GetRootFolder()
FPS = float(plan["fps"]); BR = plan.get("b_roll_track") or (ovs[0]["b_roll_track"] if ovs else 2); VT = ovs[0]["video_track"] if ovs else 1
ROOTS = sorted(plan.get("footage_roots", []), key=len, reverse=True)


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


def apply_frame(e, it):
    if e.get("zoom"): it.SetProperty("ZoomX", e["zoom"]); it.SetProperty("ZoomY", e["zoom"])
    if e.get("pan") is not None: it.SetProperty("Pan", float(e["pan"]))
    if e.get("tilt") is not None: it.SetProperty("Tilt", float(e["tilt"]))


tl = get_timeline(cfg["NAME"]); mode = cfg["MODE"]; result = {"mode": mode}
project.SetCurrentTimeline(tl); base = tl.GetStartFrame()


def at(kind, track, start_rel):
    return [i for i in tl.GetItemListInTrack(kind, track) if i.GetStart() - base == start_rel]


def near(kind, track, rel, tol=1):
    c = [i for i in tl.GetItemListInTrack(kind, track) if abs(i.GetStart() - base - rel) <= tol]
    return sorted(c, key=lambda i: abs(i.GetStart() - base - rel))


def iv_items(ov, track_kind, track):
    """The timeline items of one interview (by its planned start..start+length window, +- a few frames)."""
    lo, hi = ov["start_frame"] - 2, ov["start_frame"] + ov["length"] + 3
    return [i for i in tl.GetItemListInTrack(track_kind, track) if i.GetStart() - base >= lo and i.GetEnd() - base <= hi]


if mode == "relocate":
    while tl.GetTrackCount("video") < max(VT, BR): tl.AddTrack("video")
    pool = pool_by_path(); log = []
    for e in slots[cfg["A"]:cfg["B"]]:
        vid = tl.GetItemListInTrack("video", 1)
        nr = sorted(vid, key=lambda i: abs(i.GetStart() - base - e["b_start"]))
        if not nr or abs(nr[0].GetStart() - base - e["b_start"]) > 2: log.append([e["slot"], "no item on Video 1 near the planned start"]); continue
        old = nr[0]; os_, oe = old.GetStart() - base, old.GetEnd() - base; T = oe - os_
        tl.DeleteClips([old], False)
        if e.get("gap"): log.append([e["slot"], "cleared"]); continue
        item = pool[e["path"]]; fps = float(item.GetClipProperty("FPS"))
        if e["kind"] == "ref": sf = e["ref_s"]; n = max(1, round(T / FPS * fps))
        else: sf = round(e["in_s"] * fps); n = max(1, round(T / FPS * fps))
        ok = mp.AppendToTimeline([{"mediaPoolItem": item, "startFrame": sf, "endFrame": sf + n, "mediaType": 1, "trackIndex": BR, "recordFrame": base + os_}])
        new = at("video", BR, os_)
        if ok and new and not e.get("slow") and new[0].GetDuration() == T - 1:       # 23.976/24 fps frames can land one timeline frame short: retry one source frame longer
            tl.DeleteClips(new, False)
            ok = mp.AppendToTimeline([{"mediaPoolItem": item, "startFrame": sf, "endFrame": sf + n + 1, "mediaType": 1, "trackIndex": BR, "recordFrame": base + os_}])
            new = at("video", BR, os_)
        if ok and new and e.get("slow"): new[0].SetSpeed({"Percentage": 50.0, "RippleTimeline": False})
        new = at("video", BR, os_)
        if ok and new: apply_frame(e, new[0])
        log.append([e["slot"], bool(ok and new and new[0].GetDuration() == T), new[0].GetDuration() if new else None, T])
    result.update(done=len(log), bad=[l for l in log if l[1] not in (True, "cleared")], cleared=[l[0] for l in log if l[1] == "cleared"], v1_left=len(tl.GetItemListInTrack("video", 1)))

elif mode == "clear_gaps":
    cleared = []
    for e in slots:
        if not e.get("gap"): continue
        for it in near("video", BR, e["b_start"]):
            tl.DeleteClips([it], False); cleared.append(e["slot"])
        mk = tl.GetMarkers().get(e["b_start"])
        if mk and mk.get("name") == e["slot"]: tl.DeleteMarkerAtFrame(e["b_start"])           # the slot's own marker (not the INTERVIEW start/end markers)
    result.update(cleared=cleared, v2_items=len(tl.GetItemListInTrack("video", BR)))

elif mode == "place":
    pool = pool_by_path(); log = []
    for e in slots:
        if e["slot"] not in cfg["SLOTS"] or e.get("gap"): continue
        T = e["b_next"] - e["b_start"]
        for it in near("video", BR, e["b_start"], 0): tl.DeleteClips([it], False)
        item = pool[e["path"]]; fps = float(item.GetClipProperty("FPS"))
        if e["kind"] == "ref": sf = e["ref_s"]; n = max(1, round(T / FPS * fps))
        else: sf = round(e["in_s"] * fps); n = max(1, round(T / FPS * fps))
        ok = mp.AppendToTimeline([{"mediaPoolItem": item, "startFrame": sf, "endFrame": sf + n, "mediaType": 1, "trackIndex": BR, "recordFrame": base + e["b_start"]}])
        new = at("video", BR, e["b_start"])
        if ok and new and not e.get("slow") and new[0].GetDuration() == T - 1:
            tl.DeleteClips(new, False)
            ok = mp.AppendToTimeline([{"mediaPoolItem": item, "startFrame": sf, "endFrame": sf + n + 1, "mediaType": 1, "trackIndex": BR, "recordFrame": base + e["b_start"]}])
            new = at("video", BR, e["b_start"])
        if ok and new and e.get("slow"): new[0].SetSpeed({"Percentage": 50.0, "RippleTimeline": False})
        new = at("video", BR, e["b_start"])
        if ok and new: apply_frame(e, new[0])
        if ok and new and e.get("marker") and e["b_start"] not in tl.GetMarkers(): tl.AddMarker(e["b_start"], e["marker"]["color"], e["slot"], e["marker"]["note"], 1)
        log.append([e["slot"], bool(ok and new and new[0].GetDuration() == T), new[0].GetDuration() if new else None, T])
    result.update(placed=len(log), bad=[l for l in log if l[1] is not True], log=log, v2_items=len(tl.GetItemListInTrack("video", BR)))

elif mode == "swap":      # change the clip / source window of CFG["SLOTS"] on Video 2 in place: each keeps the ACTUAL range of the shot it replaces (the build can be 1 frame off the plan); marker is rewritten
    pool = pool_by_path(); log = []
    for e in slots:
        if e["slot"] not in cfg["SLOTS"] or e.get("gap"): continue
        nr = near("video", BR, e["b_start"], 2)
        if not nr: log.append([e["slot"], "no item near the planned start"]); continue
        old = nr[0]; os_, oe = old.GetStart() - base, old.GetEnd() - base; T = oe - os_
        tl.DeleteClips([old], False); tl.DeleteMarkerAtFrame(os_)
        item = pool[e["path"]]; fps = float(item.GetClipProperty("FPS")); sf = round(e["in_s"] * fps); n = max(1, round(T / FPS * fps))
        n_before = len(tl.GetItemListInTrack("video", BR))
        for dn in (0, 1, -1, -2):                                           # 23.976/24 fps clips can land a frame off: retry; never accept a shot that overruns its slot and eats the neighbour
            ok = mp.AppendToTimeline([{"mediaPoolItem": item, "startFrame": sf, "endFrame": sf + max(1, n + dn), "mediaType": 1, "trackIndex": BR, "recordFrame": base + os_}])
            new = at("video", BR, os_)
            if ok and new and e.get("slow"): new[0].SetSpeed({"Percentage": 50.0, "RippleTimeline": False}); new = at("video", BR, os_)
            if ok and new and new[0].GetDuration() == T and len(tl.GetItemListInTrack("video", BR)) == n_before + 1: break
            for it in at("video", BR, os_): tl.DeleteClips([it], False)
            if ok and len(tl.GetItemListInTrack("video", BR)) != n_before: break      # something else was touched (a neighbour eaten): stop and report
        new = at("video", BR, os_)
        if ok and new: apply_frame(e, new[0])
        if ok and new and e.get("marker"): tl.AddMarker(os_, e["marker"]["color"], e["slot"], e["marker"]["note"], 1)
        log.append([e["slot"], bool(ok and new and new[0].GetDuration() == T), new[0].GetDuration() if new else None, T])
    result.update(swapped=len(log), bad=[l for l in log if l[1] is not True], log=log, v2_items=len(tl.GetItemListInTrack("video", BR)))

elif mode == "frame_iv":      # (re)apply each interview's framing (zoom/tilt) to its Video 1 pictures
    n = 0
    for ov in ovs:
        fr = ov.get("framing"); fp = ov.get("framing_pieces") or []
        for k, it in enumerate(sorted(iv_items(ov, "video", VT), key=lambda i: i.GetStart())):
            pf = fp[k] if k < len(fp) and fp[k] else None                     # per-cut framing (e.g. the user's crop on one cut) wins over the interview-wide one
            z, t, pn = (pf["zoom"], float(pf.get("tilt", 0)), float(pf.get("pan", 0))) if pf else ((fr["zoom"], float(fr["tilt"]), 0.0) if fr else (1.0, 0.0, 0.0))
            it.SetProperty("ZoomX", z); it.SetProperty("ZoomY", z); it.SetProperty("Tilt", t); it.SetProperty("Pan", pn); n += 1
    result.update(framed=n)

elif mode == "blur_bg":       # a clip of the other orientation fills the frame: Fusion comp on each Video 1 picture = original fitted inside the frame over a blurred enlarged copy that covers it
    n = 0
    for ov in ovs:
        if ov.get("background") != "blur": continue
        for it in iv_items(ov, "video", VT):
            comp = it.GetFusionCompByIndex(1) if it.GetFusionCompCount() else it.AddFusionComp()
            for _, t in list(comp.GetToolList(False).items()):
                if t.GetAttrs()["TOOLS_RegID"] not in ("MediaIn", "MediaOut"): t.Delete()
            mi = comp.FindTool("MediaIn1"); mo = comp.FindTool("MediaOut1")
            w, h = [float(x) for x in it.GetMediaPoolItem().GetClipProperty("Resolution").split("x")]       # MediaIn delivers the raw source size
            ow, oh = float(project.GetSetting("timelineResolutionWidth")), float(project.GetSetting("timelineResolutionHeight"))
            cv = comp.AddTool("Background", -32768, -32768); cv.SetAttrs({"TOOLS_Name": "Canvas"})
            cv.SetInput("UseFrameFormatSettings", 0, 0); cv.SetInput("Width", ow, 0); cv.SetInput("Height", oh, 0); cv.SetInput("TopLeftAlpha", 1, 0)
            bl = comp.AddTool("Blur", -32768, -32768); bl.SetAttrs({"TOOLS_Name": "BG_Blur"}); bl.Input = mi.Output; bl.SetInput("XBlurSize", 60.0, 0)
            m1 = comp.AddTool("Merge", -32768, -32768); m1.SetAttrs({"TOOLS_Name": "BG_Fill"}); m1.Background = cv.Output; m1.Foreground = bl.Output; m1.SetInput("Size", max(ow / w, oh / h), 0)
            m2 = comp.AddTool("Merge", -32768, -32768); m2.SetAttrs({"TOOLS_Name": "Sharp_Fit"}); m2.Background = m1.Output; m2.Foreground = mi.Output; m2.SetInput("Size", min(ow / w, oh / h), 0)
            mo.Input = m2.Output; n += 1
    result.update(blurred=n, note="open the Fusion page once per changed clip (or run effects.resolve.py's flush) - scripted comps are only saved after that")

elif mode == "fill_gap":      # lay the plan slots CFG["SLOTS"] (in order) into the existing EMPTY gap on the b-roll track that starts at the first slot's planned start; the last shot absorbs any 1-frame drift (CFG["EXACT"]=True: every shot keeps its planned length and the rest of the gap stays empty, e.g. to leave interview-reveal slots open)
    pool = pool_by_path(); log = []
    es = [next(x for x in slots if x["slot"] == sid) for sid in cfg["SLOTS"]]
    v2 = sorted(tl.GetItemListInTrack("video", BR), key=lambda i: i.GetStart())
    prev = [i for i in v2 if i.GetStart() - base < es[0]["b_start"]][-1]; nxt = [i for i in v2 if i.GetStart() - base >= es[0]["b_start"]][0]
    cur, g_end = (cfg["START"] if cfg.get("START") is not None else prev.GetEnd() - base), nxt.GetStart() - base      # START = begin inside the gap (leave the first part empty)
    for k, e in enumerate(es):
        T = (g_end - cur) if (k == len(es) - 1 and not cfg.get("EXACT")) else e["b_next"] - e["b_start"]
        item = pool[e["path"]]; fps = float(item.GetClipProperty("FPS")); sf = round(e["in_s"] * fps); n = max(1, round(T / FPS * fps))
        ok = False; new = []
        for dn in (0, 1, -1):                                           # 23.976/24 fps clips can land a frame off: retry one source frame longer / shorter
            for it in at("video", BR, cur): tl.DeleteClips([it], False)
            ok = mp.AppendToTimeline([{"mediaPoolItem": item, "startFrame": sf, "endFrame": sf + n + dn, "mediaType": 1, "trackIndex": BR, "recordFrame": base + cur}])
            new = at("video", BR, cur)
            if ok and new and new[0].GetDuration() == T: break
        if ok and new:
            apply_frame(e, new[0])
            if e.get("marker") and cur not in tl.GetMarkers(): tl.AddMarker(cur, e["marker"]["color"], e["slot"], e["marker"]["note"], 1)
        log.append([e["slot"], cur, T, new[0].GetDuration() if new else None, bool(ok)])
        if not new: break
        cur = new[0].GetEnd() - base
    result.update(gap=[prev.GetEnd() - base, g_end], end=cur, log=log, bad=[l for l in log if l[3] != l[2] or not l[4]], v2_items=len(tl.GetItemListInTrack("video", BR)))

elif mode == "grade_iv":      # interviews.json "grade": {cdl_slope, cdl_power} on the Video 1 pictures of that interview (e.g. brighten a dim face)
    n = 0
    for ov in ovs:
        gr = ov.get("grade")
        if not gr: continue
        for it in iv_items(ov, "video", VT):
            sl, pw = gr.get("cdl_slope", 1.0), gr.get("cdl_power", 1.0)
            if it.SetCDL({"NodeIndex": "1", "Slope": f"{sl} {sl} {sl}", "Offset": "0 0 0", "Power": f"{pw} {pw} {pw}", "Saturation": "1"}): n += 1
    result.update(graded=n)

elif mode == "end_fades":     # music fade-out (audio fader of the music clip) + fade to black (video fader of the last Video 2 shot); lengths from the plan's music_cfg
    mus = tl.GetItemListInTrack("audio", mc["track"]); last = sorted(tl.GetItemListInTrack("video", BR), key=lambda i: i.GetStart())[-1]
    ok1 = (True if mc.get("swell_timeline") else mus[0].SetFades({"FadeIn": 0, "FadeOut": int(mc.get("fade_out_frames", 0))})) if mus else False      # the swell clip has its fade-out baked into the level keyframes
    ok2 = last.SetFades({"FadeIn": 0, "FadeOut": int(mc.get("picture_fade_frames", 0))})
    result.update(music_fades=(mus[0].GetFades() if mus else None), picture_fades=last.GetFades(), ok=(bool(ok1), bool(ok2)),
                  note="video fades were lost once after a Resolve restart: re-check GetFades() on the last shot after reopening the project")

elif mode == "clear_range":
    lo, hi = cfg["RANGE"]; n = 0
    for kind, tr in (("video", VT), ("audio", 1)):
        its = [i for i in tl.GetItemListInTrack(kind, tr) if i.GetStart() - base >= lo - 2 and i.GetEnd() - base <= hi + 3]
        if its: tl.DeleteClips(its, False); n += len(its)
    for fr, mk in list(tl.GetMarkers().items()):
        if lo - 2 <= fr <= hi + 3 and str(mk.get("name", "")).startswith("INTERVIEW"): tl.DeleteMarkerAtFrame(fr)
    result.update(deleted=n, v1=len(tl.GetItemListInTrack("video", VT)), a1=len(tl.GetItemListInTrack("audio", 1)))

elif mode == "clear_audio":
    n = 0
    for tr in (1, 2):
        its = tl.GetItemListInTrack("audio", tr)
        if its: tl.DeleteClips(its, False); n += len(its)
    result.update(deleted=n, a1=len(tl.GetItemListInTrack("audio", 1)), a2=len(tl.GetItemListInTrack("audio", 2)))

elif mode == "interview":
    pool = pool_by_path(); pf = float(project.GetSetting("timelineFrameRate")); res = {}
    for ov in ovs:
        if cfg.get("ONLY") and ov["id"] not in cfg["ONLY"]: continue
        item = pool[ov["source"]]; sfps = ov["source_fps"]; AT = ov["audio_track"]; VTk = ov["video_track"]
        while tl.GetTrackCount("audio") < max(AT, mc["track"]): tl.AddTrack("audio", "stereo")
        vlog = []; cur = ov["start_frame"]
        for pc in ov["pieces"]:
            have = at("video", VTk, cur)
            if have: pl_ = have                                                         # picture already on Video 1 (kept)
            else:
                ok = mp.AppendToTimeline([{"mediaPoolItem": item, "startFrame": pc["src_in"], "endFrame": pc["src_in"] + pc["src_n"], "mediaType": 1, "trackIndex": VTk, "recordFrame": base + cur}])
                pl_ = at("video", VTk, cur)
            if pl_ and ov.get("framing"):                                               # e.g. fill the frame with a clip of the other orientation
                pl_[0].SetProperty("ZoomX", ov["framing"]["zoom"]); pl_[0].SetProperty("ZoomY", ov["framing"]["zoom"]); pl_[0].SetProperty("Tilt", float(ov["framing"]["tilt"]))
            vlog.append([cur, pl_[0].GetDuration() if pl_ else None, pc["T"]])
            if not pl_: break
            cur = pl_[0].GetEnd() - base
        end = cur; cur = ov["start_frame"]; alog = []
        for pc, v in zip(ov["pieces"], vlog):
            want = v[1]
            for units in ("source", "project"):
                if units == "source": sf, ef = pc["src_in"], pc["src_in"] + pc["src_n"]
                else: sf, ef = round(pc["src_in"] / sfps * pf), round((pc["src_in"] + pc["src_n"]) / sfps * pf)
                ok = mp.AppendToTimeline([{"mediaPoolItem": item, "startFrame": sf, "endFrame": ef, "mediaType": 2, "trackIndex": AT, "recordFrame": base + cur}])
                pa = at("audio", AT, cur)
                if ok and pa and abs(pa[0].GetDuration() - want) <= 1: break
                if pa: tl.DeleteClips(pa, False)
                pa = []
            alog.append([cur, units, pa[0].GetDuration() if pa else None, want]); cur += want
        for k, mk in (("start", ov["start_frame"]), ("end", end)):
            if mk not in tl.GetMarkers(): tl.AddMarker(mk, "Green", "INTERVIEW " + k, ov["title"], 1)
        res[ov["id"]] = {"video": vlog, "audio": alog, "end": end}
    result.update(res)

elif mode == "normalize":
    out = {}
    for ov in ovs:
        items = iv_items(ov, "audio", ov["audio_track"]); nm = ov["normalize"]
        opt = {"normalizationMode": nm["mode"], "targetLevel": float(nm["target_dbtp"]), "setLevelMode": resolve.NORMALIZE_AUDIO_SET_LEVEL_RELATIVE}
        ok = tl.NormalizeAudioLevel(items, opt) if items else False
        resolve_gain = [i.GetProperty("AudioVolume") for i in items]
        exact = (ov.get("measured") or {}).get("gain_db")
        if exact is not None:
            for i in items: i.SetProperty("AudioVolume", float(exact))
        out[ov["id"]] = {"items": len(items), "normalize_ok": bool(ok), "resolve_gain": resolve_gain, "exact_gain": exact, "final": [i.GetProperty("AudioVolume") for i in items]}
    result.update(out)

elif mode == "music":
    if not plan.get("music"):
        result.update(ok=False, error="no music file in the plan (storyboard_project.json timeline.music_file)")
    else:
        pool = pool_by_path(); pf = float(project.GetSetting("timelineFrameRate")); MT = mc["track"]
        while tl.GetTrackCount("audio") < MT: tl.AddTrack("audio", "stereo")
        old = tl.GetItemListInTrack("audio", MT)
        if old: tl.DeleteClips(old, False)
        end_f = round(plan["total_frames"] / FPS * pf)
        if mc.get("swell_timeline"):           # outro swell with REAL level keyframes: import the keyframed music timeline once, then append it as one nested clip (AudioVolume stays 0 dB, the levels live in the keyframes)
            sw_tl = get_timeline(mc["swell_timeline"])
            if sw_tl is None: sw_tl = mp.ImportTimelineFromFile(mc["swell_xml"], {"timelineName": mc["swell_timeline"], "importSourceClips": True}); project.SetCurrentTimeline(tl)
            def _find(f):
                for c in f.GetClipList():
                    if c.GetClipProperty("Clip Name") == mc["swell_timeline"]: return c
                for sf in f.GetSubFolderList():
                    r = _find(sf)
                    if r: return r
            ok = mp.AppendToTimeline([{"mediaPoolItem": _find(root), "mediaType": 2, "trackIndex": MT, "recordFrame": base}])
            m = at("audio", MT, 0)
        else:
            ok = mp.AppendToTimeline([{"mediaPoolItem": pool[plan["music"]], "startFrame": 0, "endFrame": end_f, "mediaType": 2, "trackIndex": MT, "recordFrame": base}])
            m = at("audio", MT, 0)
            if ok and m and mc["level_db"]: m[0].SetProperty("AudioVolume", float(mc["level_db"]))
        result.update(ok=bool(ok), music=[(i.GetStart() - base, i.GetEnd() - base, i.GetProperty("AudioVolume")) for i in tl.GetItemListInTrack("audio", MT)])

elif mode == "markers":       # rebuild ALL markers from the timeline as it is now: one per Video 2 shot (named after the plan slot it matches: same start +-2 frames, else the biggest overlap) + INTERVIEW start/end per interview (start_frame / start_frame+length; moved 1 frame inward if a slot marker already sits there). Run after the user re-timed things by hand
    for fr in list(tl.GetMarkers()): tl.DeleteMarkerAtFrame(fr)
    cand = [e for e in slots if e.get("marker")]; claimed = set(); added = []; unmatched = []
    for it in sorted(tl.GetItemListInTrack("video", BR), key=lambda i: i.GetStart()):
        s0, e0 = it.GetStart() - base, it.GetEnd() - base
        best = sorted((c for c in cand if c["slot"] not in claimed), key=lambda c: (abs(c["b_start"] - s0) > 2, -(min(e0, c["b_next"]) - max(s0, c["b_start"])), abs(c["b_start"] - s0)))
        m = best[0] if best and (abs(best[0]["b_start"] - s0) <= 2 or min(e0, best[0]["b_next"]) - max(s0, best[0]["b_start"]) > 0) else None
        if not m: unmatched.append([s0, e0, it.GetName()]); continue
        claimed.add(m["slot"]); tl.AddMarker(s0, m["marker"]["color"], m["slot"], m["marker"]["note"], 1); added.append([m["slot"], s0])
    for ov in ovs:
        for k, mk, step in (("start", ov["start_frame"], 1), ("end", ov["start_frame"] + ov["length"], -1)):
            while mk in tl.GetMarkers(): mk += step
            tl.AddMarker(mk, "Green", "INTERVIEW " + k, ov["title"], 1)
    result.update(slot_markers=len(added), total=len(tl.GetMarkers()), unmatched=unmatched, unclaimed=[c["slot"] for c in cand if c["slot"] not in claimed],
                  note="matching is by position: on a re-ordered timeline name markers by clip instead (see references/resolve-build.md)")

elif mode == "markers_by_clip":   # rebuild markers on a timeline the person re-ordered / re-timed by hand: each V2 shot keeps the marker of the SAME FILE (old marker nearest in time, else the plan slot of that file, else a new one); interview start/end markers from the actual A1 runs of each interview source
    import os
    old = tl.GetMarkers(); used = set(); out = []; nnew = 0
    by_file = {}
    for e in slots:
        if e.get("marker"): by_file.setdefault(os.path.basename(e["path"]), []).append(e)
    for it in sorted(tl.GetItemListInTrack("video", BR), key=lambda i: i.GetStart()):
        s0 = it.GetStart() - base; mpi = it.GetMediaPoolItem(); fn = os.path.basename(mpi.GetClipProperty("File Path")) if mpi else it.GetName()
        cands = sorted((abs(fr - s0), fr) for fr, mk in old.items() if fr not in used and f" | {fn} | " in f" {mk.get('note', '')} | ")
        if cands:
            fr = cands[0][1]; used.add(fr); mk = old[fr]; out.append((s0, mk["color"], mk["name"], mk.get("note", "")))
        elif by_file.get(fn):
            e = by_file[fn].pop(0); out.append((s0, e["marker"]["color"], e["slot"], e["marker"]["note"]))
        else:
            nnew += 1; out.append((s0, "Blue", f"new{nnew:02d}", f"NEW | {fn} | added by hand"))
    a_items = sorted(tl.GetItemListInTrack("audio", ovs[0]["audio_track"] if ovs else 1) or [], key=lambda i: i.GetStart())
    for ov in ovs:
        runs = []
        for i in a_items:
            mpi = i.GetMediaPoolItem()
            if not mpi or _Pool.tail(mpi.GetClipProperty("File Path") or "") != _Pool.tail(ov["source"]): continue
            s0, e0 = i.GetStart() - base, i.GetEnd() - base
            if runs and s0 - runs[-1][1] <= 30: runs[-1][1] = e0
            else: runs.append([s0, e0])
        for s0, e0 in runs:
            out.append((s0, "Green", "INTERVIEW start", ov["title"])); out.append((e0 - 1, "Green", "INTERVIEW end", ov["title"]))
    for fr in list(old): tl.DeleteMarkerAtFrame(fr)
    placed = set(); bad = []
    for fr, color, name, note in sorted(out):
        while fr in placed: fr += 1
        placed.add(fr)
        if not tl.AddMarker(fr, color, name, note, 1): bad.append((fr, name))
    result.update(markers=len(placed), new_shots=nnew, failed=bad, old_unused=[old[f]["name"] for f in old if f not in used])

elif mode == "verify":
    items2 = tl.GetItemListInTrack("video", BR); items1 = tl.GetItemListInTrack("video", VT); issues = []
    for e in slots:
        nr = [i for i in items2 if abs(i.GetStart() - base - e["b_start"]) <= 1]
        if e.get("gap"):
            if nr: issues.append(("gap slot still filled", e["slot"]))
            continue
        if not nr: issues.append(("missing on Video 2", e["slot"])); continue
        it = nr[0]; mpi = it.GetMediaPoolItem(); p = mpi.GetClipProperty("File Path") if mpi else None
        if _Pool.tail(p or "") != _Pool.tail(e["path"]): issues.append(("wrong source", e["slot"]))
        if abs((it.GetEnd() - base) - e["b_next"]) > 1: issues.append(("end off", e["slot"], it.GetEnd() - base, e["b_next"]))
        if e.get("slow") and abs((it.GetSpeed() or {}).get("Percentage", 0) - 50.0) > 0.5: issues.append(("slow wrong", e["slot"]))
    gaps = [(a.GetEnd() - base, b.GetStart() - base) for a, b in zip(items2, items2[1:]) if a.GetEnd() != b.GetStart()]
    ivr = {}
    for ov in ovs:
        v = iv_items(ov, "video", VT); a = iv_items(ov, "audio", ov["audio_track"]); exact = (ov.get("measured") or {}).get("gain_db")
        contiguous = all(x.GetEnd() == y.GetStart() for x, y in zip(v, v[1:])); same = [(x.GetStart(), x.GetEnd()) for x in v] == [(x.GetStart(), x.GetEnd()) for x in a]
        if len(v) != len(ov["pieces"]) or len(a) != len(ov["pieces"]): issues.append(("interview piece count", ov["id"], len(v), len(a)))
        if (not contiguous or not same) and not ov.get("picture_override"): issues.append(("interview video/audio not aligned", ov["id"]))     # picture_override = the user deliberately offset the picture from the audio
        gp = ov.get("gain_pieces_db")      # the user set a gain per cut by hand: compare each cut with its own value
        if gp and len(gp) == len(a): bad_gain = any(abs((i.GetProperty("AudioVolume") or 0) - g) > 0.11 for i, g in zip(a, gp))
        else: bad_gain = exact is not None and any(abs((i.GetProperty("AudioVolume") or 0) - exact) > 0.011 for i in a)
        if bad_gain: issues.append(("interview gain differs from the measured value", ov["id"]))
        for sid in ov["spots"]:
            sp = [e for e in slots if e["slot"] == sid]
            if sp and any(abs(i.GetStart() - base - sp[0]["b_start"]) <= 1 for i in items2): issues.append(("interview spot covered by b-roll", sid))
        ivr[ov["id"]] = {"video": [(i.GetStart() - base, i.GetEnd() - base) for i in v], "audio": [(i.GetStart() - base, i.GetEnd() - base) for i in a],
                         "gain": sorted({i.GetProperty("AudioVolume") for i in a}), "expected_gain": exact}
    mus = tl.GetItemListInTrack("audio", mc["track"]); a1_other = [i for i in tl.GetItemListInTrack("audio", 1) if not any(ov["audio_track"] == 1 and ov["start_frame"] - 2 <= i.GetStart() - base <= ov["start_frame"] + ov["length"] + 3 for ov in ovs)]
    if mc["track"] != 1 and a1_other: issues.append(("unexpected audio on track 1", [(i.GetStart() - base, i.GetEnd() - base) for i in a1_other]))
    if plan.get("music"):
        if len(mus) != 1 or mus[0].GetStart() - base != 0 or abs(mus[0].GetEnd() - base - plan["total_frames"]) > 1: issues.append(("music is not one full-length clip", [(i.GetStart() - base, i.GetEnd() - base) for i in mus]))
        if mus and not mc.get("swell_timeline") and abs((mus[0].GetProperty("AudioVolume") or 0) - mc["level_db"]) > 0.011: issues.append(("music level", mus[0].GetProperty("AudioVolume"), mc["level_db"]))
    result.update(timeline=cfg["NAME"], tracks=(tl.GetTrackCount("video"), tl.GetTrackCount("audio")), v2_items=len(items2), expected_v2=len([e for e in slots if not e.get("gap")]), v1_items=len(items1),
                  interviews=ivr, music=[(i.GetStart() - base, i.GetEnd() - base, i.GetProperty("AudioVolume")) for i in mus], v2_gaps=gaps, issues=issues,
                  end_v2=(items2[-1].GetEnd() - base) if items2 else 0, markers=len(tl.GetMarkers()))
print(json.dumps(result, default=str))

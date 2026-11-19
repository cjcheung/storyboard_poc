# Runs INSIDE DaVinci Resolve (MCP run_script_unsafe). Builds the effects layer of <project>/config/effects.json on a finished timeline.
#   CFG = dict(NAME="<timeline>", MODE="emphasis"|"whips"|"remove_whips", CONFIG="<project>/config/effects.json", ONLY=None, FRESH=False)
#   exec(open("<skill>/resolve/effects.resolve.py", encoding="utf-8").read())
# MODE emphasis: per entry (1) B&W + contrast on the shots under the phrase (CDL on the listed items: track/start), (2) a carrier clip on Video 3 over [overlay] holding a Fusion comp:
#   big words (sizes/positions from sb.py fit-text) that SMASH in on their frame, edges roughened (noise Displace + soft blur), animated film grain over everything, thick black rounded film frame.
# MODE whips: subtle whip pans / crash zooms as Fusion comps on the V2 shots next to a cut (Transform slide / zoom + Directional Blur driven by `time` expressions).
# MODE remove_whips: CFG["CUTS"] = timeline frames of V2 items whose comp should be emptied.
# FRESH=True builds each comp in a NEW Fusion composition (item.AddFusionComp) instead of reusing Composition 1 - use it when a clip's comp fails to
#   render ("The Fusion composition at <TC> could not be processed" / log "No frame available for MediaOut1"): rebuilding inside the old comp did not help, a new comp did.
# Fusion comps made from scripts are only saved once the Fusion page was opened (done here); opening it can drop the LAST connections a script made, so every connection is recorded and re-checked afterwards.
# Run ONE mode per call (the MCP call may time out while the script keeps running - wait ~30 s, then check).
import json, time
cfg = dict(NAME=None, MODE="emphasis", CONFIG=None, ONLY=None, FRESH=False); cfg.update(globals().get("CFG", {}))
fx = json.load(open(cfg["CONFIG"], encoding="utf-8")); S = fx["style"]
tl = None
for i in range(1, project.GetTimelineCount() + 1):
    t = project.GetTimelineByIndex(i)
    if t.GetName() == cfg["NAME"]: tl = t
project.SetCurrentTimeline(tl); base = tl.GetStartFrame(); mp = project.GetMediaPool(); result = {"mode": cfg["MODE"], "built": []}
W, H = float(tl.GetSetting("timelineResolutionWidth")), float(tl.GetSetting("timelineResolutionHeight"))
TFPS = float(tl.GetSetting("timelineFrameRate"))


def find_clip(name):
    def walk(f):
        for c in f.GetClipList():
            if c.GetClipProperty("File Name") == name: return c
        for s in f.GetSubFolderList():
            r = walk(s)
            if r: return r
    return walk(mp.GetRootFolder())


def at(track, start, kind="video"):
    return [i for i in (tl.GetItemListInTrack(kind, track) or []) if abs(i.GetStart() - base - start) <= 1]


def get_comp(it):
    comp = None
    if cfg.get("FRESH"): comp = it.AddFusionComp()                 # a new composition becomes the active one
    elif it.GetFusionCompCount(): comp = it.GetFusionCompByIndex(1)
    for _try in range(5):                                          # right after AppendToTimeline AddFusionComp can return None for a moment
        if comp is not None: break
        time.sleep(0.6); comp = it.AddFusionComp()
    return comp


def active_comp(it):
    return it.GetFusionCompByIndex(it.GetFusionCompCount()) if cfg.get("FRESH") else it.GetFusionCompByIndex(1)


def clear(comp):
    for _ in range(5):
        old = [t for t in comp.GetToolList(False).values() if t.GetAttrs()["TOOLS_RegID"] not in ("MediaIn", "MediaOut")]
        if not old: break
        for t in old: t.Delete()


def name_of(t): return t.GetAttrs()["TOOLS_Name"]


class Wiring:
    """records every connection so they can be verified / redone after the Fusion page was opened"""
    def __init__(self, comp): self.comp = comp; self.conns = []
    def link(self, dst, attr, src):
        setattr(dst, attr, src.Output); self.conns.append((name_of(dst), attr, name_of(src)))
    def repair(self, comp):
        fixed = 0
        for d, a, s in self.conns:
            dst = comp.FindTool(d); inp = getattr(dst, a)
            if inp is None or not inp.GetConnectedOutput(): setattr(dst, a, comp.FindTool(s).Output); fixed += 1
        return fixed


def open_fusion_at(frame):
    """park the playhead on a timeline frame (relative) and open/close the Fusion page once - this is what saves a scripted comp"""
    r = int(round(TFPS)); f = base + frame
    tl.SetCurrentTimecode("%02d:%02d:%02d:%02d" % (f // (r * 3600), f // (r * 60) % 60, f // r % 60, f % r))
    resolve.OpenPage("fusion"); time.sleep(2.5); resolve.OpenPage("edit")


def trans_bg(comp, name):
    bg = comp.AddTool("Background", -32768, -32768); bg.SetAttrs({"TOOLS_Name": name}); bg.SetInput("UseFrameFormatSettings", 1, 0); bg.SetInput("TopLeftAlpha", 0, 0); return bg


def text(comp, name, s, cx_px, y_px, size_px):
    t = comp.AddTool("TextPlus", -32768, -32768); t.SetAttrs({"TOOLS_Name": name})
    t.SetInput("StyledText", s, 0); t.SetInput("Font", S["font"], 0); t.SetInput("Style", S["big_style"], 0); t.SetInput("Size", size_px / H, 0)
    r, g, b = S["color"]; t.SetInput("Red1", r, 0); t.SetInput("Green1", g, 0); t.SetInput("Blue1", b, 0)
    t.SetInput("LayoutType", 0, 0)                      # point layout: no word wrap, even while the smash-in scale makes the line wider than the frame
    t.SetInput("Center", {1: cx_px / W, 2: 1.0 - y_px / H}, 0)
    t.SetInput("HorizontalJustificationNew", 0, 0); t.SetInput("HorizontalLeftCenterRight", 0, 0); t.SetInput("VerticalJustificationNew", 3, 0)
    return t


def noise(comp, name, detail, contrast, scale, rate):
    n = comp.AddTool("FastNoise", -32768, -32768); n.SetAttrs({"TOOLS_Name": name})
    n.SetInput("UseFrameFormatSettings", 1, 0); n.SetInput("Detail", detail, 0); n.SetInput("Contrast", contrast, 0); n.SetInput("Brightness", 0.0, 0); n.SetInput("XScale", scale, 0); n.SetInput("YScale", scale, 0)
    n.Seethe.SetExpression(f"time * {rate}"); return n


def merge(comp, w, name, bg, fg):
    m = comp.AddTool("Merge", -32768, -32768); m.SetAttrs({"TOOLS_Name": name}); w.link(m, "Background", bg); w.link(m, "Foreground", fg); return m


def build_overlay(it, e):
    comp = get_comp(it); clear(comp); mo = comp.FindTool("MediaOut1"); lo = e["overlay"][0]; w = Wiring(comp)
    wb = trans_bg(comp, "Words_Base"); sp = trans_bg(comp, "Words_Spacer"); prev = merge(comp, w, "Words_M0", wb, sp)           # the first merge shows no foreground in this Resolve: feed it an empty layer
    for k, wd in enumerate(e["words"], 1):
        t0 = wd["at"] - lo; tx = text(comp, f"Word{k}", wd["text"], wd.get("cx", W / 2), wd["y"], wd["size"])
        a, b = S["smash"]; tx.Size.SetExpression(f"{wd['size'] / H} * (1 + iif(time < {t0} + 1, {a}, iif(time < {t0} + 2, {b}, 0)))")       # slams in oversize on its first frame(s), then rests
        mg = merge(comp, w, f"Words_M{k}", prev, tx); mg.Blend.SetExpression(f"iif(time >= {t0}, 1, 0)"); prev = mg
    rn = noise(comp, "Rough_Noise", 5.0, 1.6, 140.0, 0.6)
    disp = comp.AddTool("Displace", -32768, -32768); disp.SetAttrs({"TOOLS_Name": "Words_Rough"}); w.link(disp, "Input", prev); w.link(disp, "Foreground", rn)
    disp.SetInput("XRefraction", S["rough_px"], 0); disp.SetInput("YRefraction", S["rough_px"], 0)
    soft = comp.AddTool("Blur", -32768, -32768); soft.SetAttrs({"TOOLS_Name": "Words_Soft"}); soft.SetInput("XBlurSize", S["soft_blur_px"], 0); soft.SetInput("YBlurSize", S["soft_blur_px"], 0); w.link(soft, "Input", disp)
    gn = noise(comp, "Grain_Noise", 4.0, 2.2, 520.0, 0.37)
    frame = comp.AddTool("Background", -32768, -32768); frame.SetAttrs({"TOOLS_Name": "Film_Frame"}); frame.SetInput("UseFrameFormatSettings", 1, 0)
    for c in ("Red", "Green", "Blue"): frame.SetInput("TopLeft" + c, 0.0, 0)
    frame.SetInput("TopLeftAlpha", 1, 0)
    mk = comp.AddTool("RectangleMask", -32768, -32768); mk.SetAttrs({"TOOLS_Name": "Film_Frame_Mask"})
    m = S["frame_margin_px"]; mk.SetInput("Width", (W - 2 * m) / W, 0); mk.SetInput("Height", (H - 2 * m) / H, 0); mk.SetInput("CornerRadius", S["frame_radius"], 0); mk.SetInput("Invert", 1, 0)
    frame.EffectMask = mk.Mask
    mb = trans_bg(comp, "FX_Base"); ms = trans_bg(comp, "FX_Spacer"); cur = merge(comp, w, "FX_M0", mb, ms)
    cur = merge(comp, w, "FX_M1", cur, soft)
    cur = merge(comp, w, "FX_M2", cur, gn); cur.SetInput("Blend", S["grain_blend"], 0)
    cur = merge(comp, w, "FX_M3", cur, frame); w.link(mo, "Input", cur)
    for t in list(comp.GetToolList(False).values()):
        if name_of(t).startswith("Merge") and not name_of(t).startswith(("Words_", "FX_")): t.Delete()           # AddTool auto-inserts a Merge when another tool is selected
    return comp, w


if cfg["MODE"] == "emphasis":
    carrier = find_clip(fx["carrier"])
    for e in fx["emphasis"]:
        if cfg["ONLY"] and e["id"] not in cfg["ONLY"]: continue
        lo, hi = e["overlay"]; dur = hi - lo; log = {"id": e["id"]}; bw = S["bw"]
        for tgt in e["bw"]:
            its = at(tgt["track"], tgt["start"])
            log.setdefault("bw", []).append((tgt, bool(its and its[0].SetCDL({"NodeIndex": "1", "Slope": " ".join([str(bw["slope"])] * 3), "Offset": " ".join([str(bw["offset"])] * 3), "Power": " ".join([str(bw["power"])] * 3), "Saturation": "0"}))))
        for old in at(3, lo): tl.DeleteClips([old], False)
        ok = mp.AppendToTimeline([{"mediaPoolItem": carrier, "startFrame": 0, "endFrame": dur, "mediaType": 1, "trackIndex": 3, "recordFrame": base + lo}])
        it = at(3, lo)[0]; log["v3"] = (it.GetStart() - base, it.GetEnd() - base)
        comp, w = build_overlay(it, e); open_fusion_at(lo + 4)
        comp = active_comp(it); log["rewired"] = w.repair(comp)
        if log["rewired"]: open_fusion_at(lo + 4)
        result["built"].append(log)


def build_whip(it, ramps, tint):
    """ramps: [{"side": "in"|"out", "kind": "whip"|"zoom", "dir": +-1, "k": frames, "blur": width fraction, "slide": width fraction | "zoom": extra scale}] -> one Fusion comp on the item:
    Transform (slide with mirrored edges, or a zoom punch) -> Directional Blur (horizontal for whips, zoom blur for crash zooms), driven by time expressions; optional warm tint merged in with the same ramps"""
    D = it.GetDuration(); comp = get_comp(it); clear(comp); mi = comp.FindTool("MediaIn1"); mo = comp.FindTool("MediaOut1"); w = Wiring(comp)
    off, blr, amt, zm, zblr = [], [], [], [], []
    for r in ramps:
        k = r["k"]
        u = f"max(0, min(1, (time - ({D} - {k}) + 1) / {k}))" if r["side"] == "out" else f"max(0, min(1, ({k} - time) / {k}))"
        if r.get("kind") == "zoom": zm.append(f"{r['zoom']} * {u} * {u}"); zblr.append(f"{r['blur']} * {u} * {u}")
        else:
            sign = r["dir"] if r["side"] == "out" else -r["dir"]; off.append(f"{sign * r['slide']} * {u} * {u}"); blr.append(f"{r['blur']} * {u} * {u}")
        amt.append(f"{u} * {u}")
    tr = comp.AddTool("Transform", -32768, -32768); tr.SetAttrs({"TOOLS_Name": "Whip_Slide"}); tr.SetInput("Edges", 3, 0); w.link(tr, "Input", mi)
    if off: tr.Center.SetExpression("Point(0.5 + " + " + ".join(off) + ", 0.5)")
    if zm: tr.Size.SetExpression("1 + " + " + ".join(zm))
    bl = comp.AddTool("DirectionalBlur", -32768, -32768); bl.SetAttrs({"TOOLS_Name": "Whip_Blur"}); w.link(bl, "Input", tr)
    if zm and not off: bl.SetInput("Type", 3, 0); bl.Length.SetExpression(" + ".join(zblr))          # zoom blur for a crash zoom
    else: bl.SetInput("Angle", 0.0, 0); bl.Length.SetExpression(" + ".join(blr or ["0"]))
    last = bl
    if tint:
        bg = comp.AddTool("Background", -32768, -32768); bg.SetAttrs({"TOOLS_Name": "Whip_Tint"}); bg.SetInput("UseFrameFormatSettings", 1, 0)
        bg.SetInput("TopLeftRed", tint["rgb"][0], 0); bg.SetInput("TopLeftGreen", tint["rgb"][1], 0); bg.SetInput("TopLeftBlue", tint["rgb"][2], 0); bg.SetInput("TopLeftAlpha", 1, 0)
        mg = merge(comp, w, "Whip_TintMerge", bl, bg); mg.Blend.SetExpression(f"{tint['blend']} * min(1, " + " + ".join(amt) + ")"); last = mg
    w.link(mo, "Input", last)
    for t in list(comp.GetToolList(False).values()):
        if name_of(t) not in ("MediaIn1", "MediaOut1", "Whip_Slide", "Whip_Blur", "Whip_Tint", "Whip_TintMerge"): t.Delete()
    return comp, w


if cfg["MODE"] == "whips":
    D0 = fx["whip_defaults"]; roles = {}
    def add_role(it, ramp, tint):
        key = it.GetStart() - base; roles.setdefault(key, [it, [], None]); roles[key][1].append(ramp)
        if tint: roles[key][2] = tint
    for wp in fx.get("whips", []):
        if cfg["ONLY"] and wp["cut"] not in cfg["ONLY"]: continue
        k = wp.get("k", D0["k"]); blur = wp.get("blur", D0["blur"]); slide = wp.get("slide", D0["slide"]); tint = {"rgb": wp["tint"], "blend": wp["tint_blend"]} if wp.get("tint") else None
        outs = [i for i in tl.GetItemListInTrack("video", 2) if i.GetType() == "video" and abs(i.GetEnd() - base - wp["cut"]) <= 1]
        ins = [i for i in tl.GetItemListInTrack("video", 2) if i.GetType() == "video" and abs(i.GetStart() - base - wp["cut"]) <= 1]
        if wp.get("out", True) and outs: add_role(outs[0], {"side": "out", "kind": "whip", "dir": wp["dir"], "k": wp.get("k_out", k), "blur": blur, "slide": slide}, tint)
        if wp.get("in", True) and ins: add_role(ins[0], {"side": "in", "kind": "whip", "dir": wp["dir"], "k": wp.get("k_in", k), "blur": blur, "slide": slide}, tint)
    for cz in fx.get("crash_zooms", []):
        if cfg["ONLY"] and cz["cut"] not in cfg["ONLY"]: continue
        outs = [i for i in tl.GetItemListInTrack("video", 2) if i.GetType() == "video" and abs(i.GetEnd() - base - cz["cut"]) <= 1]
        ins = [i for i in tl.GetItemListInTrack("video", 2) if i.GetType() == "video" and abs(i.GetStart() - base - cz["cut"]) <= 1]
        if outs: add_role(outs[0], {"side": "out", "kind": "zoom", "dir": 1, "k": cz["k_out"], "blur": cz["blur"], "zoom": cz["zoom"]}, None)
        if ins: add_role(ins[0], {"side": "in", "kind": "zoom", "dir": 1, "k": cz["k_in"], "blur": cz["blur"], "zoom": cz["zoom"]}, None)
    for st in sorted(roles):
        it, ramps, tint = roles[st]
        comp, w = build_whip(it, ramps, tint); open_fusion_at(it.GetStart() - base + min(2, it.GetDuration() - 1))
        fixed = w.repair(active_comp(it))
        if fixed: open_fusion_at(it.GetStart() - base + min(2, it.GetDuration() - 1))
        result["built"].append({"item": st, "ramps": len(ramps), "rewired": fixed, "comps": it.GetFusionCompNameList()})

if cfg["MODE"] == "remove_whips":        # CFG["CUTS"] = [timeline frames of V2 items whose Fusion comp (whip / crash zoom) should go]
    for st in cfg["CUTS"]:
        for it in at(2, st):
            names = list(it.GetFusionCompNameList().values()) if isinstance(it.GetFusionCompNameList(), dict) else list(it.GetFusionCompNameList() or [])
            gone = [bool(it.DeleteFusionCompByName(n)) for n in names]
            if not all(gone):        # DeleteFusionCompByName often refuses: empty the comp instead (MediaIn -> MediaOut pass-through)
                comp = it.GetFusionCompByIndex(1); clear(comp); comp.FindTool("MediaOut1").Input = comp.FindTool("MediaIn1").Output; open_fusion_at(it.GetStart() - base + 1)
                gone = [len(comp.GetToolList(False)) == 2]
            result["built"].append({"item": st, "removed": gone})
print(json.dumps(result, default=str))

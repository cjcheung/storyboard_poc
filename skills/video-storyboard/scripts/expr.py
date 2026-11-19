"""Expression helpers shared by match.py and build_storyboard.py (smile / wave / good-time scoring and shot windows)."""
import glob, json, re
import sb_paths as P

DEMAND_RULES = [(name, re.compile(rx)) for name, rx in P.TAX.get("demand_rules", [])]
NO_DEMAND = set(P.TAX.get("no_demand_categories", ["graphic"]))


def load(cat):
    """Attach detector ('det') and visual-tag ('vt') data to each catalog clip (in place)."""
    det = P.load_json(P.CATALOG / "expression" / "expression_detect.json", {})
    vt = {}
    for f in sorted(glob.glob(str(P.CATALOG / "expression" / "tags_expr_*.json"))):
        for t in json.load(open(f, encoding="utf-8")):
            vt[t["id"]] = t
    for c in cat:
        c["det"], c["vt"] = det.get(c["id"]), vt.get(c["id"])
    return cat


def g_of(c):   # good-time 0..1 (visual tag wins; detector-only is weighted low because it over-flags singing/talking mouths)
    if c["vt"]: return (c["vt"]["good_time"] - 1) / 4
    return 0.25 * c["det"]["smile_score"] if c["det"] else 0.0


def s_of(c):   # smiling at the camera 0..1
    if c["vt"]: return 1.0 if c["vt"]["smile_at_camera"] else 0.0
    return 0.2 * min(1.0, c["det"]["frames_front_smile"] / 4) if c["det"] else 0.0


def w_of(c):
    return 1.0 if (c["vt"] and c["vt"]["waving_at_camera"]) else 0.0


def demand(slot):
    """what kind of human moment a slot asks for: wave | posed | smile | cheer (from its description) | general (people in it) | none"""
    t = slot["summary"].lower()
    for name, rx in DEMAND_RULES:
        if rx.search(t): return name
    if slot["people"] != "none" and slot["category"] not in NO_DEMAND: return "general"
    return "none"


def expr_bonus(slot, c):
    g, sm, w = g_of(c), s_of(c), w_of(c)
    return {"wave": 3.0 * w + 2.0 * sm + 1.5 * g, "posed": 2.5 * sm + 2.0 * g, "smile": 3.0 * g + 1.5 * sm,
            "cheer": 2.0 * g, "general": 1.2 * g + 0.5 * sm, "none": 0.0}.get(demand(slot), 0.0)


def t_for(slot, c):
    """Time (s) in the clip to centre the shot on: the wave / smile-at-camera / best moment."""
    v, d, dem = c["vt"], c["det"], demand(slot)
    if v:
        j = v["best_frame"]
        if dem == "wave" and v["waving_at_camera"] and v.get("wave_frame") is not None: j = v["wave_frame"]
        elif v["smile_at_camera"] and v.get("camera_frame") is not None and dem in ("wave", "posed", "smile"): j = v["camera_frame"]
        return c["duration_s"] * (j + 0.5) / 8
    if d and d.get("best_smile_t") and dem in ("wave", "posed", "smile", "general") and d["smile_score"] > 0: return d["best_smile_t"]
    return c["times"][min(c["best_frame"], len(c["times"]) - 1)]


def window(slot, c, slow=False):
    """(in_s, out_s) of the source span used for this slot; slow motion uses half the span."""
    L = max(slot["dur_s"] / 2 if slow else slot["dur_s"], 0.05)
    start = max(0.0, min(t_for(slot, c) - L / 2, c["duration_s"] - L))
    return round(start, 2), round(start + L, 2)


def slow_ok(slot, c, min_fps=None):
    """Can this clip fill the slot at 50%? (needs a high frame rate and enough footage for half the slot)"""
    min_fps = min_fps or P.RULES["slow_mo"].get("requires_clip_fps_at_least", 59)
    return c["fps"] >= min_fps and c["duration_s"] >= max(slot["dur_s"] / 2, 0.05) + 0.2 and not P.orientation_mismatch(c)


def generic_time(c):
    """Time for the clip's own preview image (its happiest / best moment)."""
    v, d = c.get("vt"), c.get("det")
    if v: return c["duration_s"] * (v["best_frame"] + 0.5) / 8
    if d and d.get("best_smile_t") and d["smile_score"] >= 0.3: return d["best_smile_t"]
    return c["times"][min(c["best_frame"], len(c["times"]) - 1)]


def auto_framing(c):
    """Timelapses (often square fisheye or 4:3) are scaled up to fill the project frame."""
    if c["category"] != "timelapse": return {}
    ratio = c["width"] / c["height"]
    if ratio < P.ASPECT * 0.98: return {"zoom": round(P.ASPECT / ratio, 3)}
    if ratio > P.ASPECT * 1.02 and P.PORTRAIT_PROJECT: return {"zoom": round(ratio / P.ASPECT, 3)}
    return {}


def crop_filter(c, zoom=None, pan=0, tilt=0):
    """ffmpeg filter reproducing Resolve's zoom / pan / tilt on a project-size frame (+pan = image right, +tilt = image up)."""
    if not zoom or zoom == 1: return ""
    W, H = P.W, P.H
    ratio = c["width"] / c["height"]
    fw, fh = (W, W / ratio) if ratio >= W / H else (H * ratio, H)
    ev = lambda v: int(round(v / 2.0)) * 2                      # even sizes only (yuv420)
    return (f"scale={ev(fw * zoom)}:{ev(fh * zoom)},pad='max(iw,{W})':'max(ih,{H})':'(ow-iw)/2':'(oh-ih)/2':color=black,"
            f"crop={W}:{H}:'max(0,min(iw-{W},(iw-{W})/2-({pan})))':'max(0,min(ih-{H},(ih-{H})/2+({tilt})))',")

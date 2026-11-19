"""Shared scoring: how well a clip fits a template slot (used by match.py, suggest.py and score_clips.py).
Category compatibility comes from the project's taxonomy ('compat' pairs); everything else is generic."""
import csv
import sb_paths as P
import expr

COMPAT = {}
for _a, _b, _v in P.TAX.get("compat", []):
    COMPAT[(_a, _b)] = _v; COMPAT[(_b, _a)] = _v


def cat_c(a, b): return 1.0 if a == b else COMPAT.get((a, b), 0.0)


PEOPLE = ["none", "one", "few", "crowd"]
def people_c(a, b):
    if a == b: return 1.0
    if "none" in (a, b) or a not in PEOPLE or b not in PEOPLE: return 0.0
    return 0.5 if abs(PEOPLE.index(a) - PEOPLE.index(b)) == 1 else 0.1


FR = ["wide", "medium", "close", "detail"]
def fr_c(a, b):
    if a == b: return 1.0
    if a not in FR or b not in FR: return 0.0
    return 0.5 if abs(FR.index(a) - FR.index(b)) == 1 else 0.0


CAMT = {("static", "static"): 1, ("static", "moving_subject_static_camera"): .8, ("static", "handheld"): .3, ("static", "pan_or_tilt"): .2, ("static", "zoom"): .2,
        ("handheld", "handheld"): 1, ("handheld", "pan_or_tilt"): .6, ("handheld", "static"): .4, ("handheld", "moving_subject_static_camera"): .5, ("handheld", "zoom"): .4,
        ("pan_or_tilt", "pan_or_tilt"): 1, ("pan_or_tilt", "handheld"): .5, ("pan_or_tilt", "static"): .2, ("pan_or_tilt", "zoom"): .5,
        ("zoom_or_crash_zoom", "zoom"): 1, ("zoom_or_crash_zoom", "static"): .4}
def cam_c(slot_cam, clip_cam):
    if slot_cam in ("whip_pan", "not_applicable", "unknown", "moving_subject_static_camera"): return .6
    if clip_cam == "unknown": return .4
    return CAMT.get((slot_cam, clip_cam), .3)


PEN = {"dark": 1.0, "blurry": 1.5, "shaky": .7, "obstructed": .8, "overexposed": .7, "awkward_framing": .5, "unflattering_face": .8}


def fit_score(slot, c):
    """Content fit of clip c for slot (no history gates): category x3 + people + framing + energy + camera + quality + smile/wave bonus."""
    s = expr.expr_bonus(slot, c) + 3.0 * cat_c(slot["category"], c["category"]) + people_c(slot["people"], c["people"]) + fr_c(slot["framing"], c["framing"]) \
        + (1 - abs(slot["energy"] - c["energy"]) / 4) + cam_c(slot["camera_look"], c["camera_look"]) + (0.5 if c["hero"] else 0) \
        + (0.3 if "good_light" in c["quality_flags"] else 0)
    for q in c["quality_flags"]:
        if q in PEN: s -= PEN[q] * (0.4 if (q == "shaky" and slot["camera_look"] in ("handheld", "whip_pan")) else 1)
    return s


def duration_ok(slot, c):
    """the clip is long enough for the slot (or for half of it at 50% speed when it was shot at a high frame rate)"""
    hi = P.RULES["slow_mo"].get("requires_clip_fps_at_least", 59)
    if c["duration_s"] < slot["dur_s"] + 0.15 and not (c["fps"] >= hi and c["duration_s"] >= slot["dur_s"] / 2 + 0.15): return False
    if c["duration_s"] < slot["dur_s"] + 0.15 and c["fps"] < hi: return False
    return True


def load_gates():
    """History gates: clips never/hold, per-slot rejections, locked slots' clips, clips currently on the timeline."""
    g = {"never": set(), "hold": set(), "slot_rej": set(), "locked_clips": set(), "cur_pick_of": {}}
    rej = P.HISTORY / "rejected_clips.csv"
    if rej.exists():
        for r in csv.DictReader(open(rej, encoding="utf-8")):
            if r["scope"] == "never": g["never"].add(r["clip_id"])
            elif r["scope"] == "hold": g["hold"].add(r["clip_id"])
            elif r["scope"] == "slot": g["slot_rej"].add((r["slot"], r["clip_id"]))
    for sid, p in P.picks_doc()["picks"].items():
        if p["kind"] == "footage":
            g["cur_pick_of"][p["clip"]] = sid
            if p.get("locked"): g["locked_clips"].add(p["clip"])
    return g

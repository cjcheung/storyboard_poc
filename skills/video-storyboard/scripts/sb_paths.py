"""The current video project: its folder, settings and path conversions. Importing this module finds the project
(first match wins):  --project DIR on the command line (removed from sys.argv)  >  $SB_PROJECT  >  the current folder or
one of its parents that contains storyboard_project.json.

Stored clip paths are RELATIVE to a logical prefix, e.g. 'Footage/Day 1/C0001.MP4'; storyboard_project.json maps each
prefix to an ORDERED list of folders ("paths": {"roots": {"Footage": ["footage", "/Volumes/media/Raw"]}}) and the first
folder that has the file wins, so the project keeps working when footage moves (edit the roots, not the catalog).
Project-relative paths ('assets/...', 'footage/...') and absolute paths work too.   Run `sb.py where` to see what it resolved."""
import json, os, pathlib, sys, tempfile
from sb_core import *          # noqa: F401,F403  (SKILL, SCRIPTS, DEFAULTS, helpers)
import sb_core as _core


def _take_project_arg():
    a = sys.argv
    for i, x in enumerate(a[1:], 1):
        if x == "--project" and i + 1 < len(a):
            v = a[i + 1]; del a[i:i + 2]; return v
        if x.startswith("--project="):
            v = x.split("=", 1)[1]; del a[i]; return v
    return None


def find_project(start=None):
    p = pathlib.Path(start or os.getcwd()).resolve()
    for d in [p] + list(p.parents):
        if (d / PROJECT_FILE).exists(): return d
    return None


_arg = _take_project_arg() or os.environ.get("SB_PROJECT")
PROJECT = pathlib.Path(_arg).expanduser().resolve() if _arg else find_project()
if PROJECT is None or not (PROJECT / PROJECT_FILE).exists():
    raise SystemExit(f"No video project found ({PROJECT_FILE}). cd into a project folder, pass --project DIR, set SB_PROJECT, "
                     f"or create one with:  python3 {SCRIPTS / 'sb.py'} init <folder> --template <video>")

RAW_CFG = load_json(PROJECT / PROJECT_FILE)
CFG = deep_merge(DEFAULTS, RAW_CFG)
NAME = CFG["name"]
TITLE = CFG.get("title") or NAME
TAX = load_taxonomy(CFG["taxonomy"])
CATEGORIES = list(TAX["categories"])
INTERVIEW_CATEGORY = TAX.get("interview_category", "interview_talking_head")
RULES = CFG["rules"]
TL = CFG["timeline"]
FPS = TL["fps"]
W, H = int(TL["width"]), int(TL["height"])
ASPECT = W / H
PORTRAIT_PROJECT = H > W
START_FRAMES = tc_to_frames(TL["start_timecode"], FPS)

CATALOG = PROJECT / "catalog"
HISTORY = PROJECT / "history"
CONFIG = PROJECT / "config"
ASSETS = PROJECT / "assets"
STORYBOARD = PROJECT / "storyboard"
CATALOG_FILE = PROJECT / CFG["catalog_file"]
SLOTS_FILE = CATALOG / "slots.json"
PICKS_FILE = HISTORY / "current_picks.json"
WORK = pathlib.Path(os.environ.get("SB_WORK") or CFG.get("work_dir") or (pathlib.Path(tempfile.gettempdir()) / "video-storyboard" / NAME)).expanduser()


def _resolve_root(v):
    q = pathlib.Path(os.path.expanduser(str(v)))
    return q if q.is_absolute() else (PROJECT / q).resolve()


FOOTAGE_PREFIX = CFG["paths"]["footage_prefix"]
ROOTS = {k: [_resolve_root(v) for v in vs] for k, vs in CFG["paths"]["roots"].items()}     # prefix -> ordered folders
if os.environ.get("SB_FOOTAGE_ROOTS"):
    ROOTS[FOOTAGE_PREFIX] = [pathlib.Path(x).expanduser() for x in os.environ["SB_FOOTAGE_ROOTS"].split(os.pathsep) if x]
FOOTAGE_ROOTS = ROOTS.get(FOOTAGE_PREFIX, [])


def abs_path(rel):
    """stored path -> real absolute path (logical prefix: first root that has the file, else the first root; project-relative; absolute)"""
    rel = str(rel)
    if os.path.isabs(rel): return rel
    for prefix, roots in ROOTS.items():
        if rel.startswith(prefix + "/") and roots:
            sub = rel[len(prefix) + 1:]
            for r in roots:
                if (r / sub).exists(): return str(r / sub)
            return str(roots[0] / sub)
    return str(PROJECT / rel)


source_path = abs_path


def rel_path(path):
    """real path -> stored path (logical prefix if the file is under one of its roots, else project-relative, else absolute)"""
    p = pathlib.Path(os.path.abspath(str(path)))
    forms = [p]
    try:
        if p.resolve() != p: forms.append(p.resolve())         # symlinked folders: the roots are stored resolved
    except OSError: pass
    for q in forms:
        for prefix, roots in ROOTS.items():
            for r in roots:
                try: return prefix + "/" + q.relative_to(r).as_posix()
                except ValueError: pass
    for q in forms:
        try: return q.relative_to(PROJECT).as_posix()
        except ValueError: pass
    return str(p)


def project_rel(path):
    """project-relative path ('assets/x.mp4') of a file inside the project folder, else None"""
    p = pathlib.Path(os.path.abspath(str(path)))
    for q in (p, p.resolve()):
        try: return q.relative_to(PROJECT).as_posix()
        except ValueError: pass
    return None


def strip_prefix(rel):
    """'Footage/Day 1/x.mp4' -> 'Day 1/x.mp4' (the folder shown to people / used for grouping)"""
    for prefix in ROOTS:
        if rel.startswith(prefix + "/"): return rel[len(prefix) + 1:]
    return rel


def walk_footage():
    """os.walk over every footage root; a file that exists in two roots is yielded once (first root wins)"""
    seen = set()
    for root in FOOTAGE_ROOTS:
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if not d.startswith(".")]
            keep = []
            for f in fn:
                key = os.path.relpath(os.path.join(dp, f), str(root))
                if key in seen: continue
                seen.add(key); keep.append(f)
            yield dp, dn, keep


REFERENCE_REL = CFG["template"].get("video") or ""
REFERENCE = pathlib.Path(abs_path(REFERENCE_REL)) if REFERENCE_REL else None
TEMPLATE_FPS = CFG["template"].get("fps")


def template_fps():
    if not TEMPLATE_FPS: raise SystemExit("template fps unknown: run  sb.py template-cuts  first (it records template.fps)")
    return float(TEMPLATE_FPS)


def tc(frames):
    """timeline-relative frame -> timecode of the Resolve timeline (start timecode added)"""
    return frames_to_tc(START_FRAMES + int(frames), FPS)


def orientation_mismatch(c):
    """a clip whose orientation differs from the project's (vertical clip in a 16:9 edit, or landscape clip in a 9:16 edit)"""
    return bool(c.get("portrait")) != PORTRAIT_PROJECT


MISMATCH_LABEL = "landscape" if PORTRAIT_PROJECT else "vertical"


def treatment_fx(slot):
    """labels of the post effects a template slot calls for (from its treatment / camera move)"""
    lab = RULES.get("treatment_labels", {}); fx = []
    if slot.get("treatment") == "bw_grain": fx.append(lab.get("bw_grain", "B&W + grain"))
    if slot.get("treatment") == "blur_streak" or slot.get("camera_look") == "whip_pan": fx.append(lab.get("blur_streak", "whip-pan blur"))
    if slot.get("treatment") == "flash_glow": fx.append(lab.get("flash_glow", "flash glow"))
    return fx


def catalog():
    return load_json(CATALOG_FILE, [])


def clip_flags():
    f = load_json(CATALOG / "clip_flags.json", {})
    return {"check_releases": set(f.get("check_releases", [])), "needs_grade": set(f.get("needs_grade", []))}


def slots():
    return load_json(SLOTS_FILE, [])


def picks_doc():
    return load_json(PICKS_FILE, {"timeline": "", "picks": {}})


def timeline_name(n):
    return TL["name_pattern"].replace("{N}", str(n))


def set_config(path, value):
    """write one setting (dotted path, e.g. 'template.fps') into storyboard_project.json, keeping everything else"""
    raw = load_json(PROJECT / PROJECT_FILE); d = raw; keys = path.split(".")
    for k in keys[:-1]: d = d.setdefault(k, {})
    d[keys[-1]] = value
    save_json(PROJECT / PROJECT_FILE, raw)


if __name__ == "__main__":
    print("project      :", PROJECT, f"({NAME})")
    print("template     :", REFERENCE or "(not set)", "" if not REFERENCE else ("exists" if REFERENCE.exists() else "MISSING"), f"fps={TEMPLATE_FPS}")
    for k, rs in ROOTS.items():
        for r in rs: print(f"root {k:12s}:", r, "exists" if r.exists() else "MISSING")
    print("timeline     :", f"{W}x{H} @ {FPS} fps, start {TL['start_timecode']}, names {TL['name_pattern']}")
    print("taxonomy     :", CFG["taxonomy"] if isinstance(CFG["taxonomy"], str) else "(inline)", f"{len(CATEGORIES)} categories")
    print("work dir     :", WORK)
    print("skill        :", SKILL)

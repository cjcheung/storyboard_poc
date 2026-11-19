"""Things every tool needs that do not depend on a project: where the skill's own files are, the default
project settings, taxonomy presets and a few small helpers (ffprobe, timecode, JSON)."""
import copy, json, os, pathlib, shutil, subprocess

SCRIPTS = pathlib.Path(__file__).resolve().parent
SKILL = SCRIPTS.parent
RESOLVE_DIR = SKILL / "resolve"
PROMPTS = SKILL / "prompts"
PRESETS = SKILL / "presets"
PAGE = SKILL / "storyboard" / "page.html"
PROJECT_FILE = "storyboard_project.json"
CACHE = pathlib.Path(os.environ.get("SB_CACHE") or (pathlib.Path.home() / ".cache" / "video-storyboard"))   # compiled helpers (machine specific)

DEFAULTS = {
    "name": "project",
    "title": "",
    "description": "",
    "template": {"video": "", "fps": None},
    # stored clip paths look like "<prefix>/<path below a root>"; the first root that has the file wins
    "paths": {"footage_prefix": "Footage", "roots": {"Footage": ["footage"]}},
    "catalog_file": "catalog/clips.json",
    "work_dir": None,
    "timeline": {
        "fps": 30, "width": 1920, "height": 1080, "start_timecode": "01:00:00:00",
        "name_pattern": "main_v{N}", "resolve_project": "",
        "b_roll_track": 2, "a_roll_video_track": 1, "a_roll_audio_track": 1,
        "music_file": "", "music_track": 2, "music_level_db": -18.0,
        "music_fade_out_frames": 90, "picture_fade_to_black_frames": 30,
    },
    "taxonomy": "event_recap",
    "rules": {
        "template_locked": {"categories": ["interview_talking_head"], "note": "talking-head slots keep the template's own shot until an interview is placed"},
        "exclude_mismatched_orientation_from_auto": True,
        "forced_timelapses": [], "timelapse_slots": [],
        "slow_mo": {"max_slots": 10, "min_slot_seconds": 1.0, "speed_percent": 50, "requires_clip_fps_at_least": 59, "categories": None},
        "content_exclusions": [],
        "treatment_labels": {"bw_grain": "B&W + grain", "blur_streak": "whip-pan blur", "flash_glow": "flash glow"},
    },
    "scan": {"extensions": [".mp4", ".mov", ".m4v"], "skip_path_prefixes": [], "skip_filename_contains": []},
    "days": None,
}


def deep_merge(base, over):
    """dict merge where nested dicts merge and everything else (lists, scalars) is replaced"""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def load_json(path, default=None):
    p = pathlib.Path(path)
    if not p.exists():
        if default is None: raise SystemExit(f"missing file: {p}")
        return copy.deepcopy(default)
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, data, indent=1):
    p = pathlib.Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=indent, ensure_ascii=False)
    os.replace(tmp, p)


def presets():
    return sorted(p.stem for p in PRESETS.glob("*.json"))


def load_taxonomy(spec):
    """spec = preset name, or {"preset": name, ...overrides}, or a complete inline taxonomy"""
    if isinstance(spec, str):
        return load_json(PRESETS / f"{spec}.json")
    spec = dict(spec or {})
    base = load_json(PRESETS / f"{spec.pop('preset')}.json") if spec.get("preset") else {}
    return deep_merge(base, spec)


def require_tools(*extra):
    missing = [t for t in ("ffmpeg", "ffprobe") + extra if not shutil.which(t)]
    if missing:
        raise SystemExit("Missing required tools: " + ", ".join(missing) + "  (macOS: brew install ffmpeg)")


def parse_rate(s):
    try:
        n, d = (s or "0/1").split("/")
        return float(n) / float(d) if float(d) else 0.0
    except Exception:
        return 0.0


def probe_video(path):
    """ffprobe summary of a video file: duration_s, fps, frames, width, height, rotation, portrait, has_audio, codec, created, pix_fmt"""
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], capture_output=True, text=True)
    try:
        j = json.loads(r.stdout)
        s = [x for x in j["streams"] if x["codec_type"] == "video"][0]
    except Exception:
        return {"error": (r.stderr or "no video stream").strip()[:160]}
    rot = 0
    for sd in s.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd.get("rotation", rot))
    if not rot and s.get("tags", {}).get("rotate"):
        rot = int(s["tags"]["rotate"])
    w, h = s["width"], s["height"]
    fps = parse_rate(s.get("avg_frame_rate")) or parse_rate(s.get("r_frame_rate"))
    dur = float(j["format"].get("duration") or s.get("duration") or 0)
    frames = int(s["nb_frames"]) if str(s.get("nb_frames", "")).isdigit() else int(round(dur * fps))
    return {"duration_s": round(dur, 3), "fps": round(fps, 3), "frames": frames, "width": w, "height": h, "codec": s.get("codec_name", ""),
            "rotation": rot, "portrait": (w < h) != (abs(rot) in (90, 270)), "has_audio": any(x["codec_type"] == "audio" for x in j["streams"]),
            "created": j["format"].get("tags", {}).get("creation_time", ""), "pix_fmt": s.get("pix_fmt", "")}


def tc_to_frames(tc, fps):
    h, m, s, f = [int(x) for x in tc.replace(";", ":").split(":")]
    r = int(round(fps))
    return ((h * 60 + m) * 60 + s) * r + f


def frames_to_tc(frames, fps):
    r = int(round(fps))
    return f"{frames // (r * 3600):02d}:{frames // (r * 60) % 60:02d}:{frames // r % 60:02d}:{frames % r:02d}"

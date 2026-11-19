#!/usr/bin/env python3
"""Create a new video project folder (the place where catalog, picks, history and the storyboard live).

  python3 sb.py init ~/videos/my_recap --template ~/videos/reference_promo.mp4 --footage ~/videos/raw --preset event_recap
  python3 sb.py init ./family_trip --template ./style.mov --footage ~/Pictures/trip --preset everyday_vlog --title "Summer trip"

Options: --name (id used in file and timeline names, default = folder name), --title, --description (one paragraph about the
subject; it goes into the tagging prompts), --fps (timeline rate, default 30), --size WxH (default: the template's orientation,
1920x1080 or 1080x1920), --music FILE. Nothing is copied: the template and the footage stay where they are (absolute paths).
Edit storyboard_project.json afterwards for anything else (rules, scan skips, extra footage roots)."""
import argparse, csv, datetime, os, pathlib, re, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_core as C

ap = argparse.ArgumentParser(description="create a video project")
ap.add_argument("folder")
ap.add_argument("--template", required=True, help="the video to imitate")
ap.add_argument("--footage", action="append", default=[], help="folder with raw footage (repeatable; first match wins)")
ap.add_argument("--name"); ap.add_argument("--title", default=""); ap.add_argument("--description", default="")
ap.add_argument("--preset", default="event_recap", help="taxonomy preset: " + ", ".join(C.presets()))
ap.add_argument("--fps", type=float, default=30); ap.add_argument("--size", help="WxH, e.g. 1080x1920")
ap.add_argument("--music", default="")
ap.add_argument("--force", action="store_true", help="overwrite an existing storyboard_project.json")
a = ap.parse_args()

proj = pathlib.Path(a.folder).expanduser().resolve()
if (proj / C.PROJECT_FILE).exists() and not a.force:
    sys.exit(f"{proj / C.PROJECT_FILE} already exists (use --force to overwrite the settings; data files are never touched)")
tpl = pathlib.Path(a.template).expanduser().resolve()
if not tpl.exists(): sys.exit(f"template not found: {tpl}")
if a.preset not in C.presets(): sys.exit(f"unknown preset {a.preset!r}; choose one of {C.presets()}")
C.require_tools()
info = C.probe_video(tpl)
if "error" in info: sys.exit(f"cannot read the template: {info['error']}")

if a.size:
    w, h = [int(x) for x in a.size.lower().split("x")]
else:
    w, h = (1080, 1920) if info["portrait"] else (1920, 1080)
name = a.name or re.sub(r"[^A-Za-z0-9_-]+", "_", proj.name).strip("_").lower() or "project"

def stored(p):
    """absolute path, or project-relative when it sits inside the project"""
    p = pathlib.Path(p).expanduser().resolve()
    try: return p.relative_to(proj).as_posix()
    except ValueError: return str(p)

roots = [stored(f) for f in a.footage] or ["footage"]
cfg = {
    "_about": "Settings of this video project for the video-storyboard skill. Paths are absolute or relative to this folder. See the skill's references/project-config.md for every key.",
    "name": name,
    "title": a.title or proj.name,
    "description": a.description,
    "template": {"video": stored(tpl), "fps": None},
    "paths": {"footage_prefix": "Footage", "roots": {"Footage": roots}},
    "catalog_file": "catalog/clips.json",
    "timeline": {"fps": a.fps, "width": w, "height": h, "start_timecode": "01:00:00:00", "name_pattern": f"{name}_main_v{{N}}",
                 "resolve_project": "", "music_file": stored(a.music) if a.music else "", "music_track": 2, "music_level_db": -18.0,
                 "music_fade_out_frames": 90, "picture_fade_to_black_frames": 30},
    "taxonomy": a.preset,
    "rules": {"template_locked": {"categories": [C.load_taxonomy(a.preset).get("interview_category", "interview_talking_head")]},
              "exclude_mismatched_orientation_from_auto": True, "forced_timelapses": [], "timelapse_slots": []},
    "scan": {"extensions": [".mp4", ".mov", ".m4v"], "skip_path_prefixes": [], "skip_filename_contains": []},
}
for d in ("catalog/batches", "catalog/expression", "history/rounds", "storyboard/decisions", "assets", "music", "outputs", "config"):
    (proj / d).mkdir(parents=True, exist_ok=True)
if roots == ["footage"]: (proj / "footage").mkdir(exist_ok=True)
C.save_json(proj / C.PROJECT_FILE, cfg)
def ensure(path, make):
    if not path.exists(): make(path)
ensure(proj / cfg["catalog_file"], lambda p: C.save_json(p, []))
ensure(proj / "catalog/clip_flags.json", lambda p: C.save_json(p, {"_about": "check_releases: clips with identifiable people who may need a release (flagged to the user, never decided by the agent); needs_grade: flat clips that need a colour grade", "check_releases": [], "needs_grade": []}))
ensure(proj / "history/current_picks.json", lambda p: C.save_json(p, {"_about": "what is on the timeline now, per slot", "timeline": "", "built_timeline": "", "picks": {}}))
def csv_header(cols):
    def make(p):
        with open(p, "w", newline="", encoding="utf-8") as fh: csv.writer(fh).writerow(cols)
    return make
ensure(proj / "history/decisions_log.csv", csv_header(["date", "round", "slot", "action", "clip_before", "clip_after", "speed_before", "speed_after", "scope", "reason", "by"]))
ensure(proj / "history/rejected_clips.csv", csv_header(["clip_id", "scope", "slot", "reason", "round", "date", "by"]))
notes = proj / "PROJECT.md"
if not notes.exists():
    t = (C.SKILL / "project_template" / "PROJECT.md").read_text(encoding="utf-8")
    t = t.replace("{TITLE}", cfg["title"]).replace("{NAME}", name).replace("{DATE}", datetime.date.today().isoformat()).replace("{TEMPLATE}", tpl.name)
    notes.write_text(t, encoding="utf-8")

print(f"project created: {proj}")
print(f"  template : {tpl.name}  {info['width']}x{info['height']} @ {info['fps']} fps, {info['duration_s']} s, {'vertical' if info['portrait'] else 'landscape'}")
print(f"  timeline : {w}x{h} @ {a.fps:g} fps, names {cfg['timeline']['name_pattern']}")
print(f"  footage  : {', '.join(roots)}")
print(f"  taxonomy : {a.preset}")
print("next:  python3 sb.py template-cuts --project " + str(proj))

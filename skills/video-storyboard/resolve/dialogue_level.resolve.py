# Runs INSIDE DaVinci Resolve (MCP run_script_unsafe). Applies the per-piece dialogue gains written by `sb.py measure-dialogue` to a timeline.
#   CFG = dict(NAME="<copy of the timeline>", PLAN="<project>/history/dialogue_levels_<timeline>.json", TRACK=1)
#   exec(open("<skill>/resolve/dialogue_level.resolve.py", encoding="utf-8").read())
# Per piece (matched by its start frame on the audio track): AudioVolume = gain_db; Dialogue Leveler on/off (mode "optimize moderate levels",
# reduce loud + lift soft on, background reduction off) with output gain = leveler_output_gain. These item properties are "active timeline only":
# the script makes the timeline current first. Run it on a NEW version (DuplicateTimeline), never on the user's timeline.
# Not scriptable (the user does these in Fairlight): track compressor/limiter/EQ, volume keyframes, listening.
import json
cfg = dict(NAME=None, PLAN=None, TRACK=1); cfg.update(globals().get("CFG", {}))
assert cfg["NAME"] and cfg["PLAN"], "pass CFG NAME and PLAN"
plan = json.load(open(cfg["PLAN"], encoding="utf-8"))
tl = [project.GetTimelineByIndex(i) for i in range(1, project.GetTimelineCount() + 1) if project.GetTimelineByIndex(i).GetName() == cfg["NAME"]][0]
project.SetCurrentTimeline(tl); base = tl.GetStartFrame()
items = {i.GetStart() - base: i for i in tl.GetItemListInTrack("audio", cfg["TRACK"])}
mode = getattr(resolve, "DIALOGUE_LEVELER_MODE_OPTIMIZE_MODERATE_LEVELS", None)
done, missing = [], []
for p in plan["pieces"]:
    it = items.get(p["start"])
    if it is None: missing.append(p["start"]); continue
    ok = [it.SetProperty("AudioVolume", float(p["gain_db"]))]
    if p.get("leveler"):
        ok.append(it.SetProperty("AudioDialogueLevelerEnabled", True))
        if mode is not None: ok.append(it.SetProperty("AudioDialogueLevelerMode", mode))
        ok += [it.SetProperty("AudioDialogueLevelerReduceLoudDialogue", True), it.SetProperty("AudioDialogueLevelerLiftSoftDialogue", True),
               it.SetProperty("AudioDialogueLevelerBackgroundReduction", False), it.SetProperty("AudioDialogueLevelerOutputGain", float(p.get("leveler_output_gain", 0.0)))]
    else:
        ok.append(it.SetProperty("AudioDialogueLevelerEnabled", False))
    done.append({"start": p["start"], "gain": it.GetProperty("AudioVolume"), "leveler": it.GetProperty("AudioDialogueLevelerEnabled"), "all_ok": all(bool(x) for x in ok)})
saved = resolve.GetProjectManager().SaveProject()
result = {"applied": len(done), "missing_starts": missing, "failed": [d for d in done if not d["all_ok"]], "saved": saved, "pieces": done}
print(json.dumps(result, default=str))

# Runs INSIDE DaVinci Resolve (MCP run_script_unsafe). READ-ONLY. Dumps every item of tracks V1-V3/A1-A3 of timeline CFG["NAME"] plus its markers to CFG["OUT"]
# so sb.py sync (hand edits -> project records) and sb.py measure-dialogue (loudness per dialogue piece) can work from a file.
#   CFG = dict(NAME="<timeline>", OUT="<work>/timeline_dump.json"); exec(open("<skill>/resolve/dump_timeline.resolve.py", encoding="utf-8").read())
import json
cfg = dict(NAME=None, OUT=None); cfg.update(globals().get("CFG", {}))
assert cfg["NAME"] and cfg["OUT"], "pass CFG NAME and OUT"
tl = [project.GetTimelineByIndex(i) for i in range(1, project.GetTimelineCount() + 1) if project.GetTimelineByIndex(i).GetName() == cfg["NAME"]][0]
b = tl.GetStartFrame(); out = {}
for kind, tr in (("video", 1), ("video", 2), ("video", 3), ("audio", 1), ("audio", 2), ("audio", 3)):
    rows = []
    for i in (tl.GetItemListInTrack(kind, tr) or []):
        m = i.GetMediaPoolItem(); p = i.GetProperty() or {}
        rows.append({"s": i.GetStart() - b, "e": i.GetEnd() - b, "path": m.GetClipProperty("File Path") if m else None, "fps": float(m.GetClipProperty("FPS")) if m and m.GetClipProperty("FPS") else None,
                     "ss": i.GetSourceStartFrame(), "se": i.GetSourceEndFrame(), "speed": (i.GetSpeed() or {}).get("Percentage"), "zoom": p.get("ZoomX"), "pan": p.get("Pan"), "tilt": p.get("Tilt"),
                     "vol": p.get("AudioVolume"), "name": i.GetName(), "fades": i.GetFades(), "fusion": i.GetFusionCompCount() if kind == "video" else 0, "enabled": i.GetClipEnabled()})
    out[f"{kind}{tr}"] = rows
out["markers"] = {str(k): [v["name"], v.get("color"), v.get("note")] for k, v in tl.GetMarkers().items()}
out["endframe"] = tl.GetEndFrame() - b; out["timeline"] = cfg["NAME"]
out["settings"] = {k: tl.GetSetting(k) for k in ("timelineFrameRate", "timelineResolutionWidth", "timelineResolutionHeight")}
open(cfg["OUT"], "w", encoding="utf-8").write(json.dumps(out))
result = {k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in out.items()}
print(result)

# Runs INSIDE DaVinci Resolve (MCP tool run_script_unsafe). Puts a table of text (e.g. dates + places, a schedule, credits) on one clip as a
# Fusion comp: one multi-line Text+ node per column (so all the wording is edited in a few inspector text boxes) plus optional thin rules between rows.
#   CFG = dict(NAME="<timeline>", START=900, TRACK=2, CONFIG="<project>/config/text_card.json")   # START = the clip's first frame (timeline-relative)
#   exec(open("<skill>/resolve/text_card.resolve.py", encoding="utf-8").read())
# Config (pixels of the timeline frame):
#   {"font": "Montserrat", "rows": [["JAN 10, 2027", "SEATTLE"], ["FEB 2, 2027", "DENVER"]],
#    "columns": [{"name": "Dates", "x": 300, "width_px": 560, "size_px": 44, "style": "Bold", "color": "#202020", "line_spacing": 1.9},
#                {"name": "Cities", "x": 900, "width_px": 600, "size_px": 64, "style": "ExtraBold", "color": "#3A7BD5", "line_spacing": 1.3}],
#    "layout": {"first_row_y": 180, "pitch": 120}, "rules": {"x0": 280, "x1": 1500, "px": 2, "color": "#202020"}}
# line_spacing must be calibrated once against a rendered still so the lines of each column sit on the row pitch.
# Re-running rebuilds the comp from scratch. Then CHECK the text read back below (if a row vanished after a hand edit or a duplicate, the comp was
# copied before it was saved - rebuild with this script). To tweak by hand: Fusion page of that clip.
import json, time
cfg = dict(NAME=None, START=None, TRACK=2, CONFIG=None)
cfg.update(globals().get("CFG", {}))
assert cfg["CONFIG"] and cfg["NAME"] and cfg["START"] is not None, "pass CFG NAME, START and CONFIG (absolute path)"
tc = json.load(open(cfg["CONFIG"], encoding="utf-8")); L = tc["layout"]
tl = None
for i in range(1, project.GetTimelineCount() + 1):
    t = project.GetTimelineByIndex(i)
    if t.GetName() == cfg["NAME"]: tl = t
project.SetCurrentTimeline(tl); base = tl.GetStartFrame()
W, H = float(tl.GetSetting("timelineResolutionWidth")), float(tl.GetSetting("timelineResolutionHeight"))
it = [i for i in tl.GetItemListInTrack("video", cfg["TRACK"]) if abs(i.GetStart() - base - cfg["START"]) <= 1][0]
comp = it.GetFusionCompByIndex(1) if it.GetFusionCompCount() else it.AddFusionComp()
for _pass in range(5):                                           # one pass can leave tools behind (merges that were still connected): repeat until only MediaIn/MediaOut are left
    old_tools = [t for t in comp.GetToolList(False).values() if t.GetAttrs()["TOOLS_RegID"] not in ("MediaIn", "MediaOut")]
    if not old_tools: break
    for t in old_tools: t.Delete()
assert len(comp.GetToolList(False)) == 2, "could not clear the old comp"
mi = comp.FindTool("MediaIn1"); mo = comp.FindTool("MediaOut1")
def rgb(h): h = h.lstrip("#"); return [int(h[k:k + 2], 16) / 255.0 for k in (0, 2, 4)]
def text(name, s, x_px, y_px, size_px, color, style, align, box_w_px, box_h_px):
    """Left-aligned text whose left edge is at x_px: Frame layout (box starts at x_px) so the justification works from the box edge."""
    t = comp.AddTool("TextPlus", -32768, -32768); t.SetAttrs({"TOOLS_Name": name})
    t.SetInput("StyledText", s, 0); t.SetInput("Font", tc["font"], 0); t.SetInput("Style", style, 0)
    t.SetInput("Size", size_px / H, 0)
    r, g, b = rgb(color); t.SetInput("Red1", r, 0); t.SetInput("Green1", g, 0); t.SetInput("Blue1", b, 0)
    t.SetInput("LayoutType", 1, 0); t.SetInput("LayoutWidth", box_w_px / W, 0); t.SetInput("LayoutHeight", box_h_px / H, 0)
    t.SetInput("Center", {1: (x_px + box_w_px / 2) / W, 2: 1.0 - y_px / H}, 0)
    t.SetInput("HorizontalJustificationNew", align, 0); t.SetInput("HorizontalLeftCenterRight", align, 0); t.SetInput("VerticalJustificationNew", 3, 0)    # align: -1 left, 0 centre, 1 right; vertical 3 = centre
    return t
def rule(name, x0, x1, y_px, px, color):
    bg = comp.AddTool("Background", -32768, -32768); bg.SetAttrs({"TOOLS_Name": name})
    bg.SetInput("UseFrameFormatSettings", 1, 0); r, g, b = rgb(color)
    bg.SetInput("TopLeftRed", r, 0); bg.SetInput("TopLeftGreen", g, 0); bg.SetInput("TopLeftBlue", b, 0); bg.SetInput("TopLeftAlpha", 1, 0)
    mk = comp.AddTool("RectangleMask", -32768, -32768); mk.SetAttrs({"TOOLS_Name": name + "_Mask"})
    mk.SetInput("Width", (x1 - x0) / W, 0); mk.SetInput("Height", px / H, 0); mk.SetInput("Center", {1: (x0 + x1) / 2 / W, 2: 1.0 - y_px / H}, 0)
    bg.EffectMask = mk.Mask
    return bg
rows = tc["rows"]; nrows = len(rows); mid_y = L["first_row_y"] + (nrows - 1) / 2.0 * L["pitch"]
layers = []
# the FIRST merge over MediaIn does not show its foreground in this Resolve (a first row once lost its text this way): feed it a transparent spacer so the real layers start at merge 2
sp = comp.AddTool("Background", -32768, -32768); sp.SetAttrs({"TOOLS_Name": "Spacer"})
sp.SetInput("UseFrameFormatSettings", 1, 0); sp.SetInput("TopLeftAlpha", 0, 0)
layers.append(sp)
for ci, col in enumerate(tc["columns"]):
    lines = [r[ci] if ci < len(r) else "" for r in rows]
    t = text(col["name"], "\n".join(lines), col["x"], mid_y, col["size_px"], col["color"], col.get("style", "Regular"), col.get("align", -1), col["width_px"], nrows * L["pitch"] + 20)
    t.SetInput("LineSpacing", col.get("line_spacing", 1.0), 0); layers.append(t)
R = tc.get("rules")
if R:
    for n in range(1, nrows):
        layers.append(rule(f"Rule{n}", R["x0"], R["x1"], L["first_row_y"] + (n - 1) * L["pitch"] + L["pitch"] / 2, R["px"], R["color"]))
def wire():
    prev = mi
    for k, lay in enumerate(layers, 1):
        m = comp.FindTool(f"TC_Merge{k}") or comp.AddTool("Merge", -32768, -32768)
        m.SetAttrs({"TOOLS_Name": f"TC_Merge{k}"}); m.Background = prev.Output; m.Foreground = lay.Output; prev = m
        if lay.GetAttrs()["TOOLS_Name"].startswith("Rule"): lay.EffectMask = comp.FindTool(lay.GetAttrs()["TOOLS_Name"] + "_Mask").Mask
    mo.Input = prev.Output
wire()
wire()        # repair pass: AddTool auto-connects to whatever tool is selected, which can steal the LAST connections
# AddTool auto-inserts a "Merge" when another tool is selected (stray Merge1/Merge2...): delete every tool that is not one of ours
_ours = {"MediaIn1", "MediaOut1"} | {l.GetAttrs()["TOOLS_Name"] for l in layers} | {f"TC_Merge{k}" for k in range(1, len(layers) + 1)} | {l.GetAttrs()["TOOLS_Name"] + "_Mask" for l in layers if l.GetAttrs()["TOOLS_RegID"] == "Background"}
for t in list(comp.GetToolList(False).values()):
    if t.GetAttrs()["TOOLS_Name"] not in _ours: t.Delete()
# Fusion edits made from a script are only written to the project when the Fusion page has been opened: without this, DuplicateTimeline copies the OLD comp
fps = float(tl.GetSetting("timelineFrameRate")); r = int(round(fps)); f = int(it.GetStart() + 10)
tl.SetCurrentTimecode("%02d:%02d:%02d:%02d" % (f // (r * 3600), f // (r * 60) % 60, f // r % 60, f % r))
resolve.OpenPage("fusion"); time.sleep(3.0); resolve.OpenPage("edit")
# opening the Fusion page can drop the last connections made by the script: check them again afterwards, redo what is missing and open the page once more
comp = it.GetFusionCompByIndex(1); fixed = 0
for k, lay in enumerate(layers, 1):
    m = comp.FindTool(f"TC_Merge{k}")
    if not m.Foreground.GetConnectedOutput(): m.Foreground = lay.Output; fixed += 1
    if not m.Background.GetConnectedOutput(): m.Background = (mi if k == 1 else comp.FindTool(f"TC_Merge{k - 1}")).Output; fixed += 1
if fixed or not mo.Input.GetConnectedOutput():
    mo.Input = comp.FindTool(f"TC_Merge{len(layers)}").Output
    resolve.OpenPage("fusion"); time.sleep(3.0); resolve.OpenPage("edit")
texts = {t.GetAttrs()["TOOLS_Name"]: t.GetInput("StyledText") for t in comp.GetToolList(False).values() if t.GetAttrs()["TOOLS_RegID"] == "TextPlus"}
result = {"item": it.GetName(), "start": it.GetStart() - base, "end": it.GetEnd() - base, "layers": len(layers), "rewired": fixed, "texts": texts}
print(json.dumps(result))

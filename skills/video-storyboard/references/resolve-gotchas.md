# Resolve scripting facts learned the hard way (Resolve Studio 20-21, macOS, via the MCP server)

## Placing clips
- `MediaPool.AppendToTimeline([{mediaPoolItem, startFrame, endFrame, mediaType, trackIndex, recordFrame}])`: start/endFrame are in the
  CLIP's own frame rate, endFrame EXCLUSIVE; mediaType 1 = video only, 2 = audio only. Audio-only placement of a VIDEO file uses the
  clip's frame units; a music file uses the PROJECT frame rate. `recordFrame` into occupied space silently trims - check the result.
- 23.976/24 fps clips can land one timeline frame short or long on a 30 fps timeline: retry +-1 source frame and verify durations;
  never accept a shot that overruns its slot (it eats the neighbour).
- Timelines start at 01:00:00:00 (`GetStartFrame()`); marker frames are relative to it. `GetSourceStartFrame()` includes a timecode
  offset for some clips - compare durations and positions, not raw source frames.
- Slow motion mid-timeline: place the FULL span, then `SetSpeed({"Percentage": 50.0, "RippleTimeline": False})`. When appending at the
  end: half the span + `RippleTimeline: True`. Whole clip: `SetClipProperty("FPS", "30")` on a 60 fps clip.
- `InsertFusionTitleIntoTimeline` always lands on V1 and ripples every unlocked track (audio gets split): avoid on the main timeline.
- `AddTransition` works for Cross/Additive/Dip/Smooth Cut/Push/Slide and Fusion "Spin"/"Zoom In" (no whip pan); transitions show up in
  track item lists with `GetType() == "transition"`.

## Properties, fades, grades
- Framing: `SetProperty("ZoomX"/"ZoomY", z)`, `"Pan"` (+ = image right), `"Tilt"` (+ = image up), in timeline pixels.
- Fades: `SetFades({"FadeIn": 0, "FadeOut": n})`. A VIDEO fade-out was lost after a Resolve restart while the audio fade survived:
  after reopening a project re-check `GetFades()` on the last shot.
- Grade: `item.SetCDL({"NodeIndex": "1", "Slope": "1.2 1.2 1.2", "Offset": "0 0 0", "Power": "1 1 1", "Saturation": "1"})`.
- `Timeline.NormalizeAudioLevel` ("True Peak", relative) rounds to 0.1 dB: set `AudioVolume` to the measured value afterwards.
- Clip volume range is -100..+30 dB. Dialogue Leveler / Voice Isolation item properties (`AudioDialogueLeveler*`, `AudioVoiceIsolation*`)
  are "active timeline only": `SetCurrentTimeline` first. No API for audio keyframes, Fairlight track effects or splitting a clip.

## Fusion
- Comps made or changed from a script are NOT saved to the project until the Fusion page has been opened for that clip: park the
  playhead on the clip, `OpenPage("fusion")`, wait ~2.5 s, `OpenPage("edit")`. Until then `DuplicateTimeline` copies the OLD comp and a
  render uses the old one (this is how an end card "lost" its first row after a duplicate).
- Opening the Fusion page can drop the LAST connections a script made: record every connection, re-check after the flush, rewire,
  flush again (the builders do this).
- `AddTool` auto-inserts a Merge when another tool is selected: give your tools names and delete strays by name.
- The FIRST Merge over MediaIn did not show its foreground: feed it a transparent spacer first.
- `AddFusionComp` can return None right after `AppendToTimeline`: retry after a short sleep.
- Never open the Fusion page on a Fusion *title* item from a script (Resolve hung for 20+ minutes).
- Text+: `tool.SetInput(name, value, 0)`; left-aligned text needs `LayoutType=1` (frame) and `HorizontalLeftCenterRight=-1`.
- `DeleteFusionCompByName` often returns False; emptying the comp (MediaIn -> MediaOut) works; a broken comp is fixed by a NEW comp
  (`AddFusionComp` makes "Composition 2" the active one) - see effects-and-cards.md, render errors.

## Media pool and project
- `ImportMedia` returning nothing is a stop sign: one unreadable file hung/crashed Resolve on retry.
- `MediaPool.RelinkClips` relinks per FOLDER, not per clip (it relinked clips whose files were not copied -> offline);
  `ReplaceClip` / `SetClipProperty("File Path")` could not fix single clips from a script. Copy files first or relink in the UI.
- `MediaPoolItem.ReplaceClip` swaps the file for EVERY timeline using that pool clip (keeps the person's keyframes) - fine for a licensed
  music version, surprising otherwise.
- Network / cloud mounts drop out briefly: "media offline" may just be the mount - re-check before assuming files are gone. Reading
  multi-GB files over such a mount takes minutes.
- Deleting timelines or clips from a script can be blocked by the agent's safety checks and is irreversible in a shared project:
  ask the person to do it by hand.
- Call `resolve.GetProjectManager().SaveProject()` after a scripted session; a force-quit loses unsaved scripted edits.
- Log file (macOS): `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/logs/davinci_resolve.log` - render errors, locks.
- The MCP bridge can fail to start while Resolve is fine (check the process); a call that hangs for minutes means Resolve is frozen and
  the person has to restart it.

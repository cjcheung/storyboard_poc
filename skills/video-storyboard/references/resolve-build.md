# Building and revising the edit in DaVinci Resolve

All timeline work goes through the `davinci-resolve` MCP server: `run_script_unsafe` runs Python inside Resolve with `resolve` and
`project` injected (it needs file access, so our scripts use it); `get_scripting_api` / `search_scripting_api` / `get_scripting_docs`
answer API questions (Resolve adds APIs often - check before assuming something is impossible). `python3 sb.py resolve-script <script>
--mode <MODE> --timeline <name>` prints the two lines to paste; add other CFG keys (A, B, SLOTS, ONLY, RANGE, EXACT...) as needed.
Each call must finish in ~60 s: build in chunks. A call can time out in the MCP layer while Resolve keeps working - wait, then
re-check with a read-only `verify` before retrying anything.

## Before writing
- Know which Resolve project is open (`project.GetName()`); never switch projects or timelines the person is working in without asking.
- Shared (collaboration) projects: probe a harmless write first (add + delete an empty bin). If writes return None, items are locked
  by another machine - stop and tell the person; do not retry in a loop.
- `sb.py plan` writes `<work>/build_plan.json` (absolute paths for THIS machine; rebuild it on the machine that runs Resolve).

## First build
1. `build_timeline` MODE `import` - bins (Reference, Music, Graphics, one per top-level footage folder), imports every clip, creates
   the empty timeline with the project's fps and size. An empty ImportMedia result is a stop sign: pick another clip.
2. MODE `build` with `A`/`B` slices (~25-30 slots per call) - appends shots on Video 1, each sized to land on its slot boundary
   from the actual end of the previous shot (no drift); template placeholders use the template's own frames.
3. MODE `finish` (single-track layout: music on Audio 1, framing, one marker per slot) or go on to the overlay layout.
4. MODE `verify` (read-only): sources, cut positions within 1 frame, slow-mo, gaps, end frame, music, marker count.

## Overlay layout (interviews / A-roll over b-roll) - on a DuplicateTimeline copy
`interview_overlay`: `relocate` (chunks; V1 shots move to V2, gap slots are cleared) -> `interview` (pictures on V1 + audio on A1 from
`history/interviews.json`) -> `normalize` (true peak, exact measured gain) or the dialogue leveling of audio.md -> `music` -> `end_fades`
-> `markers` -> `verify`. Interview pictures show only where V2 is empty (reveal spots). `frame_iv` / `blur_bg` (other-orientation
interviews: blurred fill + sharp fit; open the Fusion page once per clip to save the comp) / `grade_iv` refine the pictures.

## Every change = a new version
`DuplicateTimeline("<pattern with N+1>")`, then edit the copy, `verify`, `SaveProject()`. Update the records the same turn:
`current_picks.json` (`timeline`, `built_timeline`), a `history/rounds/` snapshot, the decisions log, `PROJECT.md` current state,
and rebuild the storyboard.
- Change a shot in place: `swap` (keeps the shot's actual range; retries +-1 source frame; refuses to eat a neighbour).
- Put planned shots back: `place`. Fill an empty gap with planned slots: `fill_gap` (`EXACT=True` keeps planned lengths).
- Stretch / merge slots: delete the V2 items and markers in the range, then `fill_gap` the surviving slot over the gap; record the
  merge in `slots.json` (the removed slot goes to `slots_removed.json`).
- Remove an interview that moved: `clear_range RANGE=[a, b]`; clear gap slots after new interview spots: `clear_gaps`.
- Insert time mid-timeline: `InsertGeneratorIntoTimeline('Solid Color')` at the playhead ripples ALL tracks by its fixed 150 frames.
  For exactly N frames: delete the generator, put a (150-N)-frame temp clip on V1 at the END of the freed gap and ripple-delete it
  (`DeleteClips([temp], True)`) - items after it move back, keeping comps and fades. The long music clip gets split: re-lay it with
  MODE `music` + `end_fades` (only if the person has not keyframed it). Do this before placing clips across the insertion point.

## The person's hand edits
1. `dump_timeline` (read-only) -> `<work>/timeline_dump.json`.
2. `sb.py sync --dump ... --timeline <name>` (dry run): V2 items matched to slots by overlap (same clip first), new shots become
   inserted slots gNN, vanished slots go to slots_removed.json, interview starts/pieces/gains/framing/picture offsets are re-read.
3. Read the report; if it makes sense, `--apply`; then `plan`, MODE `markers`, `verify`.
On a timeline the person re-ordered or lengthened a lot, overlap matching mis-assigns slots: do not apply it - rebuild the markers by
clip instead (overlay MODE `markers_by_clip`: each V2 shot keeps the old marker that names the same file, nearest in time; interview
start/end from the actual A1 runs) and note in PROJECT.md that the records describe the older version.

## Checking pictures
Stills: Color page `SetCurrentTimecode`, `GrabStill`, `ExportStills`, then `DeleteStills` (6-8 per call), or render to a scratch folder
and pull frames with ffmpeg. A test render: `SetRenderSettings({"SelectAllFrames": True, "TargetDir": <scratch>, "CustomName": ...})`,
`AddRenderJob`, `StartRendering`, poll `GetRenderJobStatus`; delete the test jobs and restore the person's render settings afterwards
(MarkIn/MarkOut in SetRenderSettings did not limit a render - budget a full render). Export a .drp only when asked.

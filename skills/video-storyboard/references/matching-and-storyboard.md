# Matching and storyboard rounds

## The matcher (`sb.py match --name roundN`)
- Slots that need footage = tagged slots with `needs_real_footage`, not in a template-locked category, not locked/inserted.
- Fit score = category x3 (partial credit from the taxonomy's `compat`) + people + framing + energy closeness + camera move +
  hero/good-light bonus - quality penalties (dark, blurry, shaky ...) + an expression bonus when the slot asks for a wave / posed
  smile / smile / cheer (from its summary) and the clip has one.
- Hard gates: never/hold clips, per-slot rejections, locked picks' clips, rotated clips, too short (a high-fps clip may fill half
  the slot at 50%), content exclusions, wrong orientation (rule), timelapses except forced ones on their allowed slots.
- One clip per slot, optimal overall (Hungarian assignment). In/out points are centred on the clip's best/happiest moment.
- Slow motion: up to `rules.slow_mo.max_slots` high-energy slots get a 60 fps clip at 50%.
- Writes `catalog/match_sheet_<name>.json/.csv` with up to 3 alternates per slot and flags (wrong orientation, timelapse crop,
  needs grade, check releases, possible duplicate scene = same folder + shot within 90 s or consecutive file numbers).

## Before there is footage: a shooting storyboard
`sb.py storyboard --round 0` right after the template analysis builds the page as a shot list: each row shows the template's frame next
to a TO FILM card (what is in the shot, framing, people, camera, energy, how many seconds to film, text added in the edit, the slot's notes)
or an IN EDIT card for cards/graphics (describe those in `catalog/graphic_slots.json`, optional `"badge": "IN EDIT"`). It also writes
`storyboard/shot_list.md`, a printable table of every slot. Rows switch to clip options automatically once footage is scanned and matched.

## Rounds
1. First round: `match --name round1` -> `apply --from-proposal round1 --timeline <name>_v1` (the proposal becomes the current picks,
   logged as initial_pick) -> `storyboard --proposal round1 --round 1` -> build v1 in Resolve (resolve-build.md).
2. The person opens `storyboard/index.html` in Chrome/Edge: per slot REF (template frame) | A = current | B/C/D = proposal /
   suggestions / alternates. They click a picture, can set 50% slow-mo, say what happens to the replaced clip (rejected for this slot /
   never / just replaced), lock a slot, or write a note. "Connect folder (autosave)" once -> `storyboard/decisions/inbox.json`;
   otherwise "Download JSON" or "Copy for Claude" (paste).
3. When they say they are done: read the inbox, interpret every note (ask when ambiguous), then
   `apply --timeline <name>_vN+1 [--overrides notes.json] [--defer s12]` -> new timeline version -> `storyboard --round N+1`.
   Never apply a choice that reuses the same frames of a file in two slots (apply refuses).

## Interpreting notes
- "find other options / something with people smiling": `sb.py suggest --slot s07 --category crowd_audience --n 3 --round N`
  (filters: `--text` word on screen or in the summary, `--folder`, `--category`, `--exclude`, `--first`); the page shows them as
  SUGGESTED next round. `--replace-current` + `apply --suggestions-only` makes the top one current.
- A precise instruction (a clip, a moment, a crop): write an overrides file - a JSON list of
  `{slot, clip, src_in_s, src_out_s, speed_percent, zoom?, pan?, tilt?, reason, reject_previous?}` - and pass `--overrides`.
- A source timecode the person quotes is in the camera's timecode: check the clip's Start TC in Resolve before converting.
- Not decidable now: `--defer sNN` keeps the slot and shows the pending choice on the page.

## History tools
`sb.py history slot s04 | clip <id> | summary`, `history log ...` (anything not applied by a tool), `history reject --clip <id> --scope
slot|never|hold --slot s04 --reason ...`. The matcher and the page honour the history.

## Exposure
`sb.py exposure [--calibrate] [--top 20 --sheet]` measures every shot on the timeline (3-5 frames inside the used window): too dark /
borderline / ok against the template's own darkest quartile (`--calibrate`). Offer brighter alternatives or a CDL grade.

# Template analysis: cuts -> slots -> tags -> brief

Goal: a slot table that says, for every shot of the template, how long it is and what kind of picture it is, plus a one-page
brief the person agrees with. Everything downstream (matching, the storyboard, the build) hangs off `catalog/slots.json`.

## 1. Cuts (`sb.py template-cuts`)
- Probes the template (fps, frames, size, audio) and records `template.fps` in the settings.
- Decodes every frame at 64x36 and scores each frame by the PROMINENCE of two changes over its neighbours (pixel difference and
  RGB-histogram difference; motion and strobes inside a shot cancel out). Default threshold 0.10, shortest shot 2 frames.
  Checked on an 83-shot promo: all 82 cuts found within a frame, ~10 false alarms (glitch animations, flashes, strobes).
- Writes `catalog/template_cuts.json` (`cuts`, per-cut `scores`, weaker `maybe` changes, near-black / near-white frame ranges) and
  review sheets in the work folder: one row per cut showing frames cut-2, cut-1 | cut, cut+1 (red bar = first frame of the new shot).

**Review (you, before slots):** read every `cuts_NN.png` and `maybe_NN.png` with the Read tool.
- Remove false cuts: a glitch/logo animation that changes every frame, a flash inside one shot, a whip pan's blur frames that belong
  to one shot, camera moves, strobes. Rule of thumb: the template editor's cut = where the CONTENT changes.
- Add missed cuts from `maybe` (dissolves, cuts between similar shots, cuts in dark sections): put the frame number into `cuts`.
- Keep deliberate 1-6 frame flash/glitch shots as their own slots when they are part of the rhythm (they become graphic slots).
- Dissolves: put the cut in the middle of the dissolve. Fades to black: the frames inside a fade often score as weak "cuts" (remove
  them); the black frames become their own slot only if they hold (`dark_frames` in the cuts file gives the range - cut at its start).
- Edit `cuts` in `catalog/template_cuts.json` (plain frame numbers) and say in one line what you changed.

## 2. Slots (`sb.py template-slots`)
- Slot `sNN` = [cut, next cut) in template frames; timeline frames `tl_start/tl_end` are scaled to the project's fps, rounded per
  boundary (no drift). `frame_times_s` = 3 frame centres at ~15/50/85% of the shot.
- Writes tagging sheets (3 frames per slot, 5 slots per sheet) and helper manifests `agent_X.json` (~40 slots each). Refuses to
  overwrite tagged slots without `--force` (keeps a `.backup.json`).

## 3. Tags (helpers) and merge
- `sb.py prompt tag_template_slots --manifest <agent_X.json> --out <project>/catalog/template_tags/tags_X.json` prints the helper
  prompt filled with the project's description and categories. Give each helper (Agent tool; a fast model is fine) one manifest;
  they write one JSON file and reply in under 100 words. Small templates (< ~40 slots): tag them yourself from the sheets.
- `sb.py template-merge` validates every value (slot_kind, category incl. "graphic", people, framing, energy 1-5, camera_look,
  treatment, needs_real_footage) and merges; graphic slots and talking-head slots get template placeholder picks.
- Spot-check: logo / text cards must be `needs_real_footage: false`; whip-pan blur frames `camera_look: whip_pan`; B&W sections
  `treatment: bw_grain`; on-screen text copied exactly.

## 4. Brief (`sb.py template-brief`) - confirm with the person
`template_brief.md`: rhythm (shot lengths, cuts per 10 s, busiest stretch), audio loudness/silences, kinds/categories/camera/effects,
on-screen text, cards to rebuild, talking-head stretches, energy curve and a **shot list to find in the footage**. Fill the style notes
(structure, look, transitions, text style, music, what must stay exact) from the sheets, then ask the person to confirm or correct:
- which cards/graphics they will supply or want rebuilt (logo, end card text, dates), and which template shots stay as placeholders;
- whether the length / music / aspect ratio change (a vertical template for a landscape edit means every slot needs reframing);
- which talking-head stretches become their interviews / voice-over;
- anything to skip (sections that do not fit their footage).
Record their answers in `PROJECT.md` (rules) and in the brief.

## Changing the slot table later
- Merge / stretch / insert slots in `catalog/slots.json` first (inserted slots: `"inserted": true`, ids gNN), then rebuild the plan.
- Slots the person removed go to `catalog/slots_removed.json` (`sync` does this for hand edits).
- Template frame numbers stay as they are; only `tl_start/tl_end` follow the edit.

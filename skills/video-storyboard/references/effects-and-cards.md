# Cards, effects and Fusion comps

## Graphic slots (logo animations, end cards, title cards)
Slots tagged `needs_real_footage: false` start as template placeholders. When the person supplies an asset (or you build one), put it in
`assets/`, set the pick to `{"kind": "graphic", "asset": "assets/<file>", "src_in_s": 0.0}` and describe it in
`catalog/graphic_slots.json` (`built`, `title`, `asset`, `how`, `needs`) so the storyboard shows it. Brand-kit PDFs can be turned into
PNGs with `swift scripts/pdf_pages.swift <file.pdf> <out_dir> [width]` (macOS) to cut logos and textures from.

## Text cards (`resolve/text_card.resolve.py`)
A table of text (dates + cities, a schedule, credits) over a backdrop clip as a Fusion comp: one multi-line Text+ node per column, so
the wording is edited in a few text boxes on the Fusion page, plus optional rules between rows. Config in `config/text_card.json`
(see the script header). Calibrate `line_spacing` once against a rendered still. The script reads the texts back - check them; if a row
disappears after a hand edit or duplicate, the comp was copied before it was saved: rebuild it with the script.

## Effects layer (`resolve/effects.resolve.py`, `config/effects.json`) - run after the cut is final
- `style`: font, big_style, font_file (for `sb.py fit-text`), color [r, g, b], frame_margin_px, frame_radius, grain_blend,
  bw {slope, offset, power}, text_pad_px, line_gap_px, rough_px, soft_blur_px, smash [first-frame oversize, second-frame oversize].
- `carrier`: file name of a clip in the media pool used as the Video 3 carrier for emphasis comps (any backdrop clip).
- `emphasis`: [{id, phrase, bw: [{track, start}], overlay: [lo, hi], words: [{text, at}]}] - the template's "big words over B&W"
  card on a spoken phrase. Word timings come from the transcript + the audio envelope. `sb.py fit-text` fills size/cx/y.
- `whip_defaults` {k, blur, slide}, `whips` [{cut, dir, k?, k_in?, k_out?, blur?, slide?, tint?, tint_blend?, in?, out?}],
  `crash_zooms` [{cut, k_out, k_in, zoom, blur}] - comps on the shots on both sides of a cut, driven by `time` expressions.
- Frames are timeline frames of the version you build on: re-derive them after the edit changes. Afterwards re-check `GetFades()` on
  the last shot (re-run MODE `end_fades` if the fade-out vanished).
- MODE `remove_whips` `CUTS=[...]` empties comps. `FRESH=True` builds in a new composition (see below).

## Render error: "The Fusion composition at <TC> could not be processed successfully"
Log: `No frame available for MediaOut1`. TC - timeline start = the first frame of the clip with the broken comp.
1. Find the item at that frame (all tracks) and list its comps (`GetFusionCompNameList`, tools, connections).
2. Bisect on a DuplicateTimeline copy: `SetClipEnabled(False)` on suspects + a full render to a scratch folder (~25 s for 90 s).
   Unsaved scripted comp edits only reach the render after a Fusion-page flush, so flush before each test.
3. Fix that worked: a NEW comp on the item (`AddFusionComp`, or effects MODE whips with `FRESH=True`), rebuild the chain in it,
   flush, verify connections, test-render. Rebuilding inside the old comp did not help; `DeleteFusionCompByName` returned False
   (the old comp stays listed but unused).
4. Delete the test render jobs and restore the person's render settings (TargetDir, CustomName, audio export).

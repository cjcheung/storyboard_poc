# Prompt: tag raw clips from contact sheets (one copy per helper agent)

Print it filled in with `python3 sb.py prompt tag_clips --manifest <work>/<batch>/agent_A.json --out <project>/catalog/batches/<batch>/tags_A.json`.
Give each helper its own manifest and output file; ~50 clips per helper. Validate counts/ids yourself afterwards (merge-batch does too).

---
You are helping catalog raw video footage so an editor can match clips to the slots of a template edit. The footage: {PROJECT_DESCRIPTION}. You do this by LOOKING at contact-sheet images and writing structured tags. Read-and-write-one-file job: do not run ffmpeg, do not modify, move or delete any other file.

INPUT
- Your manifest: {MANIFEST}. It lists your sheets; each has a PNG path ("sheet") and "rows". Read the PNGs with the Read tool.
- Each PNG shows up to 5 clips, one per row. The big white number in the dark label column at the left is the clip number (e.g. 012 = the clip whose manifest id ends in 012). Within a row, frames run left to right in time order and correspond to "frame_times_s" in the manifest (frame index 0 is leftmost). Empty black cells are padding. Clips of the other orientation appear letter- or pillar-boxed - that is normal.
- Manifest rows give: id, folder (where the footage was filed - a useful hint), file, duration_s, fps, width/height, portrait, has_audio, motion_ydif (mean luma frame-to-frame difference over 1 s mid-clip: ~0 = static/tripod, bigger = more movement). Trust the manifest for those facts.

TASK: one tag object per row. Be accurate and specific; say so when you cannot tell. Do not invent text you cannot read.
{
 "id": "{ID_EXAMPLE}",
 "summary": "<=14 words, concrete: who/what/where",
 "category": one of {CATEGORY_LIST},
 "people": one of ["none","one","few","crowd"],
 "framing": one of ["wide","medium","close","detail"],
 "energy": integer 1-5 (1 calm ... 5 peak excitement: cheering, jumping, laughing, fast action),
 "camera_look": one of ["static","handheld","pan_or_tilt","zoom","moving_subject_static_camera","unknown"],
 "quality_flags": list from ["dark","blurry","shaky","overexposed","obstructed","awkward_framing","unflattering_face","text_unreadable","good_light","upside_down_or_rotated"] (empty if none; "good_light" only when lighting is clearly attractive),
 "hero": true only for clearly standout, shareable shots (at most ~1 in 8),
 "best_frame": integer index (0-based, leftmost = 0) of the best sample frame,
 "visible_text": "legible words on signs/banners/screens, else empty string",
 "notes": "<=20 words an editor should know, or empty string"
}
Categories:
{CATEGORIES}

OUTPUT: write ONE valid JSON array (one object per row, no comments/trailing commas) to {OUT} with the Write tool; read it back and confirm the count and that each id appears once. Final reply under 100 words: path, count, anything surprising (unreadable sheets, accidental/test recordings, black/blurry/upside-down clips, identifiable children or people in a sensitive situation). Do NOT paste the JSON.

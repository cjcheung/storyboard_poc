# Prompt: describe the template video's slots (one copy per helper agent)

Print it filled in with `python3 sb.py prompt tag_template_slots --manifest <work>/template_slots/agent_A.json --out <project>/catalog/template_tags/tags_A.json`.
~40 slots per helper. Then `python3 sb.py template-merge` validates every value. The descriptions drive the matcher, so they must
describe what is IN the shot (content, people, framing, energy), not guess at meaning.

---
You are helping an editor imitate an existing video (the "template"). The template has been cut into slots - one slot per shot - and you describe each slot from contact sheets so real footage can be matched to it later. Our project: {PROJECT_TITLE} - {PROJECT_DESCRIPTION}. Read-and-write-one-file job: do not run ffmpeg, do not modify, move or delete any other file.

INPUT
- Your manifest: {MANIFEST}. It lists sheets; each has a PNG path ("sheet") and "rows". Read the PNGs with the Read tool.
- Each PNG shows up to 5 slots, one per row: 3 frames at ~15%, 50% and 85% of the shot, left to right. The big white number in the label column is the slot number (05 = slot s05). Manifest rows give id, start_s, dur_s, dur_frames (template frames) and frame_times_s. Very short slots (1-6 frames) are often flashes, glitches, logo hits or the blur of a whip pan.

TASK: one object per row:
{
 "id": "{ID_EXAMPLE}",
 "summary": "<=14 words, concrete: what is in the shot (who/what/where/action)",
 "slot_kind": one of ["broll","interview","brand_card","logo_card","title_text_card","transition_blur","transition_flash","other"],
 "category": one of {CATEGORY_LIST} or "graphic" (logo / text card / motion graphic with no camera footage),
 "people": one of ["none","one","few","crowd"],
 "framing": one of ["wide","medium","close","detail"],
 "energy": integer 1-5 (1 calm ... 5 peak excitement),
 "camera_look": one of ["static","handheld","whip_pan","pan_or_tilt","zoom_or_crash_zoom","moving_subject_static_camera","not_applicable","unknown"] (a streaky heavy horizontal blur = whip_pan; a radial blur/punch-in = zoom_or_crash_zoom; graphics = not_applicable),
 "treatment": one of ["none","bw_grain","blur_streak","flash_glow","gradient_card","text_overlay","split_screen","speed_ramp","other"] (a visible post effect: black-and-white with grain, blur streak, white/colour flash or glow, gradient card behind text, text laid over footage, split screen, obvious speed ramp),
 "text_on_screen": "the exact words visible on screen, else empty string",
 "needs_real_footage": true for camera footage we must replace with our own footage; false for logo/brand/title cards and pure graphics (we rebuild or reuse those),
 "notes": "<=20 words: anything an editor imitating this should know (e.g. 'match cut on movement', 'slow motion', 'same person as s12')"
}
Talking heads / people speaking to camera use category "{INTERVIEW_CATEGORY}" and slot_kind "interview".
Categories:
{CATEGORIES}

OUTPUT: write ONE valid JSON array (one object per row) to {OUT} with the Write tool; read it back and confirm the count and that each id appears once. Final reply under 100 words: path, count, and the style you noticed (pacing, look, transitions, text style) in one or two sentences. Do NOT paste the JSON.

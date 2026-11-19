# Prompt: visual check for waving / smiling at the camera / having a good time

Print it filled in with `python3 sb.py prompt tag_expression --manifest <work>/expr/agent_A.json --out <project>/catalog/expression/tags_expr_A.json`
(choose a letter whose file does not exist yet - existing files are never overwritten).

---
You are helping an editor find happy, welcoming shots in raw footage for a promo/recap video ({PROJECT_DESCRIPTION}). You LOOK at contact-sheet images and write structured tags about people's expressions and behavior. Read-and-write-one-file job: do not run ffmpeg or touch any other file.

INPUT: manifest {MANIFEST}; each sheet PNG shows up to 5 clips, one per row, 8 frames per row left to right in time order (frame index 0 leftmost; exact times in "frame_times_s"). The big white number at the left of a row is the row label. Rows include a "detector_hint" from an automatic face/smile detector - it is imperfect (it calls singing/talking open mouths smiles and misses small faces); use it only as a hint and trust your own eyes.

JUDGE (be strict; if unsure say false / lower score and explain in notes):
1. waving_at_camera: someone waves a hand at the camera/photographer. Hands raised while singing or cheering, pointing, or holding up a phone are NOT waving at the camera.
2. smile_at_camera: someone looks into the lens (or clearly at the camera operator) while smiling/laughing.
3. good_time (1-5): do the people look genuinely like they are having a good time (smiling, laughing, hugging, high-fiving, cheering, dancing, playful) EVEN IF nobody looks at the camera? 1 = not at all/neutral/serious, 3 = pleasant, 5 = clearly joyful and lively.

SCHEMA, one object per clip row:
{ "id": "<id from the manifest row>", "waving_at_camera": true/false, "wave_frame": 0-7 or null, "smile_at_camera": true/false,
  "camera_frame": 0-7 or null (best smile-at-camera / eye-contact moment),
  "expression": one of ["laughing","big_smile","smiling","neutral","serious","reverent","singing","other"],
  "good_time": 1-5, "best_frame": 0-7 (best frame for a happy promo shot), "notes": "<=20 words or empty string" }

OUTPUT: one valid JSON array to {OUT} (Write tool); read it back, confirm count and unique ids. Final reply under 90 words: path, count, how many waving / smile_at_camera, anything surprising. Do NOT paste the JSON.

# Audio: interviews, dialogue leveling, music bed

Layout: Audio 1 = interview / dialogue pieces, Audio 2 = the music bed (`timeline.music_track`).

## Measuring safely
Long recordings (talks, lectures, interviews) are multi-GB. Always measure with input seeking (`-ss` before `-i`), `-t`, and
`-vn -sn -dn`; never with a filter graph that also decodes the video - one such run buffered tens of GB of frames and froze the machine.
`measure_dialogue.py` also kills ffmpeg if it passes 1.5 GB.

## Interview gain (true peak) - simple
`sb.py measure-interviews` -> exact `gain_db` per interview (target dBTP from `interviews.json` normalize), then overlay MODE
`normalize` (Resolve's normalizer, then the exact value). Good when all interviews are recorded alike.

## Dialogue leveling (LUFS) - when speakers differ (close mics vs a room / stage recording)
1. `dump_timeline` of the version to level -> `<work>/timeline_dump.json`.
2. `sb.py measure-dialogue --dump ... [--target -16] [--ceiling -1] [--leveler-above 20]`: per piece integrated loudness and true
   peak, gain = min(target - loudness, ceiling - peak); clip gain up to +30 dB, the rest (up to +6) as Dialogue Leveler output gain;
   speakers that need more than `--leveler-above` dB get the Dialogue Leveler (optimize moderate levels, reduce loud + lift soft).
   Writes `history/dialogue_levels_<timeline>.json` and prints which pieces are peak-limited (cannot reach the target without a
   limiter) and which are too short (< 1 s, unreliable).
3. DuplicateTimeline, then `dialogue_level.resolve.py` with `PLAN=` that file on the copy.
4. Tell the person what only they can do in Fairlight: solo Audio 1 and read the loudness meter (BS.1770) - the leveler's effect cannot
   be measured outside Resolve; add a gentle compressor (2:1-3:1, 10-20 ms attack, 100-200 ms release, 3-6 dB reduction) and a limiter
   at -1 dBTP on the track; listen to the far-mic pieces for lifted noise (Voice Isolation per piece if needed); re-check the music
   level against the new dialogue level.
No new audio files and no nested timelines for leveling unless the person asks.

## Music bed
- One clip for the whole video at a constant level (default -18 dB), no ducking, fade-out over `music_fade_out_frames`, picture fades to
  black over `picture_fade_to_black_frames` (overlay MODE `music` + `end_fades`).
- If the person keyframes the music by hand, never re-run `music` (it deletes and re-adds the clip) or touch its volume.
- Optional outro swell (`timeline.music_outro_db`, `music_outro_ramp_frames`): `sb.py plan` writes an FCP7-XML timeline with real level
  keyframes; MODE `music` imports it once and appends it as one nested clip (nested clips take no fade handles; a 0 keyframe silenced
  everything after it, so the floor is just above 0).
- Swapping a preview track for the licensed file: `MediaPoolItem.ReplaceClip` keeps the keyframes but changes every timeline using it.
- To check levels: render audio only (QuickTime, LPCM, ExportVideo False) to a scratch folder and measure with ffmpeg ebur128.

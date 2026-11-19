# Project settings, folders and data files

## storyboard_project.json
Created by `sb.py init`; edit by hand afterwards. Missing keys fall back to the defaults in `scripts/sb_core.py` (DEFAULTS).

| Key | Meaning |
|---|---|
| `name` | short id (file names, storage keys of the storyboard page, default timeline names) |
| `title`, `description` | shown on the page; the description goes into every tagging prompt ("what the footage is") |
| `template.video` | the video to imitate (absolute, project-relative, or `<prefix>/...`); `template.fps` is written by `template-cuts` |
| `paths.footage_prefix`, `paths.roots` | stored clip paths are `<prefix>/<path below a root>`; `roots` maps each prefix to an ORDERED list of folders, first one that has the file wins. Add a prefix for any other location you want stored relatively. Override the footage roots for one run with `$SB_FOOTAGE_ROOTS` (os.pathsep-separated). |
| `catalog_file` | the clip catalog (default `catalog/clips.json`) |
| `work_dir` | scratch folder (default `<tmp>/video-storyboard/<name>`; or `$SB_WORK`) |
| `timeline.fps`, `width`, `height`, `start_timecode` | the Resolve timeline (a vertical project is simply 1080x1920) |
| `timeline.name_pattern` | e.g. `myvideo_main_v{N}` |
| `timeline.b_roll_track`, `a_roll_video_track`, `a_roll_audio_track` | overlay layout tracks (default V2 b-roll, V1 + A1 interviews) |
| `timeline.music_file`, `music_track`, `music_level_db`, `music_fade_out_frames`, `picture_fade_to_black_frames` | the music bed (one clip, constant level) and end fades; optional `music_outro_db` + `music_outro_ramp_frames` = keyframed swell after the last interview |
| `taxonomy` | a preset name from `presets/` (`event_recap`, `everyday_vlog`) or `{"preset": "...", ...overrides}` or a full inline taxonomy |
| `rules.template_locked.categories` | slot categories kept as the template's own shot (default: the talking-head category) |
| `rules.exclude_mismatched_orientation_from_auto` | no vertical clips in a landscape edit (or the reverse) in automatic picks |
| `rules.forced_timelapses`, `rules.timelapse_slots` | timelapse clips that must be used, and the slots they may go to (timelapses are never auto-picked otherwise) |
| `rules.slow_mo` | `max_slots`, `min_slot_seconds`, `speed_percent` (50), `requires_clip_fps_at_least` (59), `categories` (default: the taxonomy's slow_mo_categories) |
| `rules.content_exclusions` | list of `{"pattern": regex on summary+notes, "expression": visual-tag expression, "unless_slot_category": [...]}` - e.g. quiet, serious moments only on stage slots |
| `rules.treatment_labels` | how slot treatments are named on markers / the page |
| `scan.extensions`, `skip_path_prefixes`, `skip_filename_contains` | what `scan` looks at |
| `days` | optional `{"path_regex": "Day (\\d+)", "tz": "...", "dates": ["2027-05-01", ...]}` to number event days |

## Taxonomy (presets/*.json)
`categories` (name -> description, used in prompts and validation), `interview_category`, `compat` ([a, b, 0..1] partial credit
between related categories), `demand_rules` ([name, regex] on a slot summary -> which human moment it needs: wave / posed / smile /
cheer), `no_demand_categories`, `slow_mo_categories`, `subject_hint`. Write a new preset when a project's world differs (sports,
weddings, product videos); keep category names short snake_case and give every one a one-line description.

## Project folder
| Path | What |
|---|---|
| `PROJECT.md` | running notes: purpose, the person's rules, current state, open items (keep it short) |
| `template_brief.md` | the template analysis, confirmed with the person |
| `catalog/template_probe.json`, `template_cuts.json`, `template_tags/`, `template_summary.json` | template analysis data |
| `catalog/slots.json` | the slot table (template slots + `inserted` ones); `catalog/slots_removed.json` slots the person removed/merged |
| `catalog/clips.json` | the clip catalog (ids never change) |
| `catalog/batches/<bNN>/` | technical.json, clip_index.json, tags_*.json, scores.csv per scanned batch |
| `catalog/expression/` | expression_detect.json (detector), tags_expr_*.json (visual check) |
| `catalog/clip_flags.json` | `check_releases`, `needs_grade` clip id lists |
| `catalog/match_sheet_<name>.json/.csv`, `suggestions.json`, `exposure_check.*`, `graphic_slots.json` | proposals, targeted options, brightness check, cards shown for graphic/interview slots |
| `history/current_picks.json` | what is on the timeline now, per slot |
| `history/decisions_log.csv` | append-only log: date, round, slot, action, clip_before, clip_after, speed_before, speed_after, scope, reason, by |
| `history/rejected_clips.csv` | clip_id, scope (slot / never / hold), slot, reason, round, date, by |
| `history/rounds/round_NNN_<timeline>.json` | snapshot of the picks per round / version |
| `history/pending_decisions.json` | deferred storyboard choices |
| `history/interviews.json` | interview / A-roll definitions (below) |
| `history/dialogue_levels_<timeline>.json` | per-piece dialogue gains |
| `storyboard/` | index.html (open in Chrome/Edge), data.js, thumbs/, decisions/inbox.json (+ processed/) |
| `config/effects.json`, `config/text_card*.json` | effects layer and text cards |
| `assets/` | graphics (logo animations, end-card backdrops); `outputs/` renders |

## Data shapes
- **slot**: `id` (s01...), `start_frame`/`end_frame` (template frames, end exclusive), `dur_frames`, `start_s`, `dur_s`, `frame_times_s`, `tl_start`/`tl_end` (timeline frames, relative to the start timecode), `summary`, `slot_kind`, `category`, `people`, `framing`, `energy`, `camera_look`, `treatment`, `text_on_screen`, `needs_real_footage`, `notes`; optional `inserted`.
- **clip**: `id`, `path` (stored), `folder`, `file`, `duration_s`, `fps`, `width`, `height`, `portrait`, `has_audio`, `created`, `motion_ydif`, `times` (sheet frame times), tags (`summary`, `category`, `people`, `framing`, `energy`, `camera_look`, `quality_flags`, `hero`, `best_frame`, `visible_text`, `notes`), optional `day`.
- **pick** (`current_picks.json` `picks[slot]`): `kind` footage | graphic | template; footage: `clip`, `src_in_s`, `src_out_s`, `speed_percent`, optional `zoom`/`pan`/`tilt` (Resolve units: +pan = image right, +tilt = image up), `locked`, `round`, `timeline`; graphic: `asset` (+ `src_in_s`); template: `reason`, optional `interview` (= a reveal spot where the interview picture shows).
- **interview** (`interviews.json[id]`): `title`, `source` (stored path), `source_fps`, `pieces_src_frames` ([[in, out), ...] in source frames), `start_frame` (timeline), `spots` (reveal slot ids), `video_track`/`audio_track`/`b_roll_track`, `normalize` {mode "True Peak", target_dbtp}, optional `measured`, `framing` {zoom, tilt}, `framing_pieces`, `background: "blur"`, `grade` {cdl_slope, cdl_power}, `gain_pieces_db`, `picture_override`, `sync` {src_frames, timeline_range}.
- **graphic_slots.json[slot]**: `built`, `title`, `asset`, `how`, `needs` - the card the storyboard shows for graphic / interview / placeholder slots.

# Footage: scan, tag, keep the catalog healthy

## Scan a batch (`sb.py scan --batch bNN`)
- Walks every footage root (first root that has a file wins, duplicates are listed once), skips known clips, scan rules
  (`scan.skip_path_prefixes`, `skip_filename_contains`, extensions) and **cloud online-only files** (size on disk < size): reading
  those would trigger huge downloads - ask the person to make the folder available offline first.
- `--dry-run` lists what is new; `--only "<prefix>/<folder>"` scans one folder; `--include` scans a normally skipped one.
- Probes each file (fps, size, rotation -> `portrait`, audio, creation time), grabs 3-8 frames per clip, measures motion, and writes
  `catalog/batches/<bNN>/technical.json` + `clip_index.json` and contact sheets + helper manifests (~50 clips each) in the work folder.
- **Always pass `--batch` explicitly** when more than one agent works on a project (names collide otherwise).

## Tag (helpers)
- `sb.py prompt tag_clips --manifest <work>/<bNN>/agent_A.json --out <project>/catalog/batches/<bNN>/tags_A.json` for each helper
  (Agent tool, one manifest each, a fast model is fine). They write one JSON array and reply in under 100 words.
- Validate yourself: count, unique ids, categories in the taxonomy. Re-tag rows that look wrong (read the sheet).
- `sb.py merge-batch <bNN>` checks every id has exactly one tag and every category is allowed, then appends to the catalog.
  Re-read the catalog right before merging if another agent may have merged meanwhile.

## Optional enrichment
- `sb.py expressions` (macOS + Xcode command line tools): face / smile / camera-facing detector on 6-12 frames per clip; first
  compile ~10 min, cached in `~/.cache/video-storyboard`. It over-flags singing/talking mouths: a hint only.
- `sb.py expression-sheets` + `prompt tag_expression`: visual check of waving / smiling at camera / good time for clips with big faces.
  Visual tags override the detector in matching.
- `catalog/clip_flags.json`: add clip ids to `check_releases` (identifiable people, minors) and `needs_grade` (flat/log footage).
- `sb.py score --batch <bNN>`: quality 0-10 + best slots + "beats the current pick" per clip - use it to tell the person which new
  clips are worth a look.

## Upkeep
- Renamed/moved files: `sb.py relink` (report) / `--apply` (rewrites paths in catalog + history; ids never change). If a whole
  folder moved, change the roots in `storyboard_project.json` instead.
- Footage copied to a faster disk: add that folder FIRST in the root list; the old location stays as a fallback.
- Never delete or move the person's footage unless they ask (and then to the Trash, not `rm`).

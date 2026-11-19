---
name: video-storyboard
description: Use when making a video that imitates an existing one (a template / reference edit) from your own footage - analyzing the template's cuts and shot types, cataloging and tagging raw footage, matching clips to the template's slots, reviewing picks on the storyboard web page, building and revising the edit in DaVinci Resolve through scripts (interviews over b-roll, music bed, end cards, whip pans, dialogue leveling, markers), and keeping the decision history. Triggers on: imitate / recreate / recut a video, "make it like this video", template video, storyboard, shot list from a reference, match footage to slots, swap or reject a clip, storyboard_project.json, Resolve timeline versions.
---

# Video storyboard - imitate a template edit with your own footage

You help a person re-create the cut structure and style of a **template video** with **their own footage**:
analyze the template into **slots** (one per shot), tag the footage, propose one clip per slot, let the person choose on a
**storyboard page** (Chrome), then build the edit in **DaVinci Resolve** through the `davinci-resolve` MCP server, one timeline
version per change. The person also edits the timeline by hand between turns; their edits always win.

Everything runs through one CLI: `python3 <this skill's folder>/scripts/sb.py <command>` (the folder is shown as the skill's base
directory when it loads; `sb.py help` lists the commands). A project is a folder with `storyboard_project.json`; commands find it from
`--project DIR`, `$SB_PROJECT`, or the current folder. Needs Python 3.9+ (standard library only), ffmpeg/ffprobe, Chrome or Edge;
DaVinci Resolve Studio + its MCP server for the timeline; optional macOS Swift (smile detector) and Pillow (a few images).

## Start of every session
1. Find the project (`sb.py where`). No project yet -> phase 1. Read the project's `PROJECT.md` first (its rules beat the defaults below).
2. Check what changed since last time: new footage (`sb.py scan --dry-run`), a storyboard inbox (`storyboard/decisions/inbox.json`), or a timeline the person edited by hand (dump + `sb.py sync`, dry run).
3. Plan the turn in a few lines and get a yes before writing files, building timelines or deleting anything (a direct instruction like "swap s05 and s17" is the approval for that change).

## Workflow
| Phase | What | Commands | Details |
|---|---|---|---|
| 1 Project | ask for the inputs below in one message, then create the folder and pick the taxonomy preset | `init <dir> --template <video> --footage <dir> --preset event_recap\|everyday_vlog` | references/project-config.md |
| 2 Template | cuts -> **you review the cut sheets** -> slots -> tag slots (helpers) -> merge -> brief; confirm the brief with the person; no footage yet? `storyboard --round 0` = a shooting storyboard + shot_list.md | `template-cuts`, `template-slots`, `prompt tag_template_slots`, `template-merge`, `template-brief`, `storyboard` | references/template-analysis.md |
| 3 Footage | scan a batch -> tag clip sheets (helpers) -> merge -> optional smile scan -> scores | `scan --batch bNN`, `prompt tag_clips`, `merge-batch`, `expressions`, `score` | references/footage-and-tagging.md |
| 4 Match | proposal -> first picks -> storyboard page; the person chooses, you apply; repeat per round | `match --name roundN`, `apply --from-proposal`, `storyboard`, `apply`, `suggest` | references/matching-and-storyboard.md |
| 5 Build | plan -> Resolve: import, build, overlay (interviews/A-roll, music), markers, verify; one new timeline version per change | `plan`, `resolve-script <name>` | references/resolve-build.md, references/resolve-gotchas.md |
| 6 Polish | end cards / text cards, whips, emphasis text, exposure check, dialogue leveling, render check | `exposure`, `fit-text`, `measure-dialogue` | references/effects-and-cards.md, references/audio.md |

**Inputs to ask for at the start of a new project** (one message; record the answers in PROJECT.md "Inputs"):
1. The template as a file on disk (not a link) and what the new video is for (subject, people, date, where it will be shown).
2. The footage folder(s), stored locally - cloud online-only files are skipped. Suggest one subfolder per day / place / camera
   (folder names reach the taggers), original camera file names, and long talks / interviews in their own folder.
3. Text for the title / end cards; music they may use (or camera sound); logos, colours, fonts for the cards; interview recordings
   if the template has talking heads. Missing footage is fine: phase 2 ends with a shooting storyboard (`storyboard --round 0`).
The README has the same checklist and a suggested folder layout for people reading it on GitHub.

After every round or timeline version: update `PROJECT.md` (current state, open items), make sure `history/` has the change
(`apply`/`sync` write it; log anything else with `sb.py history log ...`), and rebuild the storyboard so the page matches the timeline.

## Default rules (unless PROJECT.md says otherwise)
- **Never edit the person's timelines or the template's own timeline.** Every change is a new version via `DuplicateTimeline` (`<name>_v<N+1>`), then `verify`. Deleting timelines/clips/footage only on an explicit request (they may prefer to do it by hand; the scripting safety check can block it).
- **Hand edits are deliberate.** Before building on the latest version, diff it against the records (dump + `sync` dry run) and keep what the person changed.
- **Never reuse the same frames** (one file may serve two slots at non-overlapping moments); never offer a clip again that was rejected for that slot or "never".
- Automatic picks never use clips of the wrong orientation (vertical clips in a 16:9 edit or the reverse); timelapses only where the rules allow; prefer people having a good time; skip dark/blurry/accidental clips.
- Releases for identifiable people (minors especially) are flagged to the person (`catalog/clip_flags.json` check_releases), never decided by you.
- Music: one bed clip at a constant level, no ducking, unless asked. If the person keyframed the music by hand, never re-lay it.
- Dialogue: level with clip gain / Dialogue Leveler on a new version; no new audio files, no nested timelines, unless asked.
- Big media: never run ffmpeg over long recordings with a filter graph that also decodes video (use `-vn` and input seeking); skip cloud online-only files instead of downloading them.
- Several agents may share a project: always name batches explicitly (`--batch bNN`), re-read the catalog right before merging, and check for other sessions.

## Where things live (project folder)
`storyboard_project.json` settings - `PROJECT.md` notes - `template_brief.md` - `catalog/` (slots.json, clips.json, batches/, expression/, match sheets, suggestions) - `history/` (current_picks.json, decisions_log.csv, rejected_clips.csv, rounds/, interviews.json) - `storyboard/` (index.html, data.js, thumbs/, decisions/inbox.json) - `config/` (effects.json, text cards) - `assets/` (graphics) - `outputs/` (renders). Scratch (sheets, frames, the build plan) goes to the work folder (`sb.py where`), never into a shared folder.

## References
- references/project-config.md - every setting, folder and data file
- references/template-analysis.md - cut review, slot tagging, the brief
- references/footage-and-tagging.md - scanning, helper agents, catalog upkeep
- references/matching-and-storyboard.md - scoring, rounds, interpreting notes
- references/resolve-build.md - build sequence, layouts, versions, hand-edit sync, markers
- references/resolve-gotchas.md - Resolve scripting facts learned the hard way
- references/effects-and-cards.md - text cards, whips, emphasis text, Fusion comps, render errors
- references/audio.md - interview gain, dialogue leveling, music bed

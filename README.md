# storyboard_poc - make a video like another video, from your own footage

A Claude Code skill plus a small toolkit for one job: you have a **template** (a promo, recap or reel whose rhythm and style you like)
and a pile of **your own footage**. Claude analyzes the template into slots (one per shot), tags your footage, proposes a clip for every
slot, shows you a **storyboard page** to choose from, and builds the edit in **DaVinci Resolve** through Resolve's MCP server, one
timeline version per change. You keep editing by hand whenever you like; it records your edits instead of overwriting them.

```
template video --cuts--> slots --tags--> slot table ----\
                                                          match --> storyboard page (you choose) --> picks --> Resolve timeline vN
your footage  --scan--> contact sheets --tags--> catalog-/                                                    ^          |
                                                                          your hand edits (dump + sync) ------+----------/
```

Status: proof of concept, extracted from a real project (an ~80 s event recap with 80+ shots, interviews over b-roll, music bed, end
cards and dialogue leveling). The local pipeline is tested end to end on a synthetic demo; the Resolve scripts come from that project
and were generalized - expect to adjust them for your setup.

## What you need
- [Claude Code](https://claude.com/claude-code) (the skill drives everything; you talk to Claude, it runs the tools).
- Python 3.9+ (standard library only) and ffmpeg + ffprobe on the PATH.
  - macOS: `brew install python ffmpeg` · Linux: your package manager (`apt install python3 ffmpeg`) · Windows: `winget install Python.Python.3.12 Gyan.FFmpeg`.
  - Developed and tested on macOS; the local pipeline is plain Python + ffmpeg and should run elsewhere, but that is untested.
- Chrome or Edge for the storyboard page (folder autosave needs one of them; other browsers can still download the choices as JSON).
- For the timeline stage only: DaVinci Resolve **Studio** with its MCP server connected to Claude Code (see below).
- Optional: macOS + Xcode command line tools (`xcode-select --install`) for the face / smile detector; Pillow (`pip install pillow`) for `fit-text` and the exposure contact sheet.

## What to bring
- **The template**: the video to imitate, as a file on disk (download it first; a link isn't enough). Your edit takes its orientation
  (vertical or landscape) unless you say otherwise.
- **Your footage**: a folder (with subfolders) of raw clips, stored on the disk. Cloud "online-only" files are skipped so nothing
  triggers a huge download - make the folder available offline first.
- **Text for the cards**: what the template's title and end cards should say in your version (names, dates, places).
- Optional:
  - music you're allowed to use (or say you'll keep the camera sound)
  - logos, brand colours and fonts for the cards
  - interview or talk recordings, if the template has talking heads
- No footage yet? The template analysis alone gives you a **shooting storyboard** (`sb.py storyboard --round 0`): the template's
  frame for every shot next to what to film, plus a printable `storyboard/shot_list.md`.

## How to organize your footage
```
my_video/                    the project folder (sb.py init creates catalog/, history/, storyboard/ ...)
  footage/                   or keep the footage where it is and pass --footage <folder> (several allowed)
    2027-05-01 beach/        one folder per day, place or camera - folder names are shown to the taggers as hints
    2027-05-02 park/
    interviews/              long talks / interviews in their own folder (skip it in scans; it feeds the interview layer)
  music/                     the track(s) you may use
  assets/                    logos, backdrops, fonts for the cards
```
- Keep the camera's original file names: consecutive numbers help spot near-duplicate shots.
- One shot per file works best; a finished edit used as footage is catalogued as a single clip.
- Don't move or rename files after scanning. If you do, run `sb.py relink`, or change the folder list in `storyboard_project.json`
  when a whole folder moved (the first folder that has a file wins - handy for a fast local copy plus an archive drive).
- Only videos are scanned (photos are ignored); the template can stay wherever it is, it is referenced by path.

## Install the skill
**As a plugin (recommended).** Inside Claude Code:
```
/plugin marketplace add cjcheung/storyboard_poc
/plugin install video-storyboard@storyboard-poc
```
or from a terminal: `claude plugin marketplace add cjcheung/storyboard_poc && claude plugin install video-storyboard@storyboard-poc`.
- Check: `claude plugin list` shows `video-storyboard`; start a new Claude Code session and the skill is listed (it loads when you
  ask for something it covers, or ask for it by name).
- Update later: `claude plugin marketplace update storyboard-poc && claude plugin update video-storyboard@storyboard-poc`.
- With the plugin, Claude runs the tools for you from the plugin's own folder; you never need the paths below.

**From a clone** (to read or change the code):
```
git clone https://github.com/cjcheung/storyboard_poc.git
ln -s "$PWD/storyboard_poc/skills/video-storyboard" ~/.claude/skills/video-storyboard     # makes it a personal skill
```
Update with `git -C storyboard_poc pull`. Commands in this README are relative to the clone
(`python3 skills/video-storyboard/scripts/sb.py ...`).

**Connect DaVinci Resolve (only for building the timeline).** Resolve Studio ships its own MCP server (`ResolveMCP`, inside the app,
e.g. `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Applications/ResolveMCP` on macOS). Set it up for Claude Code as
Blackmagic describes; on the machine this was built on it is a stdio server named `davinci-resolve` (a small Node wrapper from
Blackmagic that starts `ResolveMCP`). Check with `/mcp` inside Claude Code that `davinci-resolve` is connected, and keep Resolve open
on the project you want to edit. Everything up to the storyboard works without Resolve.

Then just ask, e.g. *"I want to make a video like ~/Videos/reference.mp4 from the footage in ~/Videos/trip - set up a project"*.

## For AI agents
- **Start with `skills/video-storyboard/SKILL.md`** - the workflow, the default rules and where every file lives - then the
  `references/` page for the phase you are in. Claude Code loads it automatically once installed; other agents should read it first.
- One CLI does the work: `python3 <skill folder>/scripts/sb.py <command>` (`sb.py help`); a project is a folder with
  `storyboard_project.json`, found from `--project DIR`, `$SB_PROJECT` or the current folder.
- You need to be able to **look at images**: tagging the template slots and the footage means reading contact-sheet PNGs and writing
  JSON (`sb.py prompt <name>` prints the exact instructions). Helper sub-agents are optional - one agent can tag everything itself.
- Building in Resolve needs the Resolve MCP server with script execution (`run_script_unsafe`); `sb.py resolve-script <name>` prints
  the code to send. Without it, stop at the storyboard and say so.
- The person decides: show a short plan before writing files or building timelines, make every timeline change a new version,
  keep their hand edits, and never delete footage. `SKILL.md` lists the rest.

## Try it without real footage
```
python3 examples/demo/make_demo.py /tmp/sb_demo          # synthetic template + 14 clips + the tags a helper would write
python3 -m unittest discover -s tests -v                   # runs the whole local pipeline on it
```
`examples/demo/README.md` walks through the same steps by hand and opens the storyboard page.

## The command line
`python3 skills/video-storyboard/scripts/sb.py help` lists everything; the main path is:

| Step | Command |
|---|---|
| new project | `sb.py init <dir> --template <video> --footage <dir> --preset event_recap\|everyday_vlog` |
| template | `template-cuts` (review the cut sheets) -> `template-slots` -> tag -> `template-merge` -> `template-brief` |
| footage | `scan --batch b01` -> tag -> `merge-batch b01` -> `score --batch b01` (optional `expressions`) |
| storyboard | `match --name round1` -> `apply --from-proposal round1` -> `storyboard --round 1` -> you choose -> `apply` |
| Resolve | `plan` -> `resolve-script build_timeline --mode import` (paste into the MCP tool) ... `verify` |
| hand edits | `resolve/dump_timeline.resolve.py` -> `sync` |
| audio | `measure-interviews`, or `measure-dialogue` + `resolve/dialogue_level.resolve.py` |

Tagging (describing contact sheets) is done by Claude: `sb.py prompt tag_clips ...` prints the helper prompt for a sub-agent.

## Your data stays yours
A project folder holds everything about one video (settings, catalog, history, storyboard); footage and the template stay where they
are and are referenced by path. Nothing is uploaded anywhere by the tools. This repo contains only code, prompts and docs - keep
project folders out of it (the `.gitignore` refuses media and project data by default).

## Layout
```
.claude-plugin/              plugin + marketplace manifest (install from GitHub)
skills/video-storyboard/
  SKILL.md                   the skill: workflow, default rules, where things live
  references/                details per phase (template analysis, tagging, matching, Resolve build, gotchas, effects, audio, config)
  scripts/                   sb.py and the tools it runs
  resolve/                   scripts that run inside Resolve via the MCP server
  prompts/                   helper prompts (filled per project by `sb.py prompt`)
  presets/                   category taxonomies (event_recap, everyday_vlog)
  storyboard/page.html       the storyboard page
  project_template/          PROJECT.md skeleton for new projects
examples/demo/               synthetic demo generator
tests/                       end-to-end test of the local pipeline
```

## License
MIT - see LICENSE.

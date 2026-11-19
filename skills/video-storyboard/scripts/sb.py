#!/usr/bin/env python3
"""video-storyboard command line.   python3 sb.py <command> [--project DIR] [options]      (python3 sb.py help)

The project is found from --project DIR, $SB_PROJECT, or the current folder (or a parent) holding storyboard_project.json.
Every command is a small script in this folder; `python3 sb.py <command> -h` shows its options."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMMANDS = {
    # name: (script, fixed leading args, one-line help)
    "init": ("init_project.py", [], "create a project folder for a new video (template + footage folders)"),
    "where": ("sb_paths.py", [], "show the resolved project, template, footage roots and work folder"),
    "template-cuts": ("template.py", ["cuts"], "probe the template and detect its cuts (+ review sheets)"),
    "template-slots": ("template.py", ["slots"], "turn the reviewed cuts into slots + tagging sheets"),
    "template-merge": ("template.py", ["merge"], "merge the slot tags into catalog/slots.json"),
    "template-brief": ("template.py", ["brief"], "write template_brief.md (rhythm, shot types, shot list)"),
    "scan": ("scan_footage.py", [], "find new footage, probe it, make tagging sheets (a batch)"),
    "merge-batch": ("merge_batch.py", [], "merge a tagged batch into the catalog"),
    "expressions": ("detect_expressions.py", [], "macOS face/smile scan of catalog clips (optional)"),
    "expression-sheets": ("make_expression_sheets.py", [], "sheets for the visual smile/wave check (optional)"),
    "score": ("score_clips.py", [], "quality score + best slots per clip"),
    "match": ("match.py", [], "propose one clip per slot (optimal assignment)"),
    "suggest": ("suggest.py", [], "targeted options for one slot (from a user note)"),
    "storyboard": ("build_storyboard.py", [], "build the storyboard page (storyboard/index.html)"),
    "apply": ("apply_decisions.py", [], "apply the user's storyboard choices (or the first proposal) to the picks"),
    "history": ("history.py", [], "look up / append to the decision history"),
    "exposure": ("check_exposure.py", [], "brightness check of every shot in the current edit"),
    "relink": ("relink_renamed.py", [], "find renamed/moved footage and fix the catalog"),
    "plan": ("make_build_plan.py", [], "build plan for the Resolve scripts"),
    "sync": ("sync_from_timeline.py", [], "record the user's hand edits from a Resolve timeline dump"),
    "measure-interviews": ("measure_interview.py", [], "true-peak gain per interview (interviews.json)"),
    "measure-dialogue": ("measure_dialogue.py", [], "LUFS per dialogue piece + gains to level all speakers"),
    "fit-text": ("fit_effect_text.py", [], "fit emphasis words to the frame (config/effects.json, needs Pillow)"),
    "prompt": ("fill_prompt.py", [], "print a tagging prompt filled in for this project"),
    "resolve-script": ("fill_prompt.py", ["--resolve"], "print the exec() snippet for a resolve/*.resolve.py script"),
}


def usage():
    print(__doc__)
    w = max(len(k) for k in COMMANDS)
    for k, (_, _, h) in COMMANDS.items():
        print(f"  {k:{w}s}  {h}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "-h", "--help"):
        usage(); sys.exit(0)
    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"unknown command {cmd!r}\n"); usage(); sys.exit(2)
    script, lead, _ = COMMANDS[cmd]
    path = os.path.join(HERE, script)
    os.execv(sys.executable, [sys.executable, path] + lead + sys.argv[2:])

#!/usr/bin/env python3
"""Print a helper prompt filled in for this project, or the snippet that runs a Resolve script.

  python3 sb.py prompt tag_clips --manifest <work>/b01/agent_A.json --out <project>/catalog/batches/b01/tags_A.json
  python3 sb.py prompt tag_template_slots --manifest <work>/template_slots/agent_A.json --out <project>/catalog/template_tags/tags_A.json
  python3 sb.py prompt tag_expression --manifest <work>/expr/agent_A.json --out <project>/catalog/expression/tags_expr_A.json
  python3 sb.py resolve-script interview_overlay --timeline <timeline> --mode verify  # code to paste into the MCP run_script_unsafe tool

Prompts live in the skill's prompts/ folder; {PLACEHOLDERS} are filled from storyboard_project.json and the taxonomy."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P

ap = argparse.ArgumentParser()
ap.add_argument("--resolve", action="store_true", help=argparse.SUPPRESS)
ap.add_argument("name")
ap.add_argument("--manifest", default="{MANIFEST}"); ap.add_argument("--out", default="{OUT}"); ap.add_argument("--id-example")
ap.add_argument("--mode", default="verify"); ap.add_argument("--plan", default=str(P.WORK / "build_plan.json")); ap.add_argument("--timeline")
a = ap.parse_args()

if a.resolve:
    script = P.RESOLVE_DIR / f"{a.name.replace('.resolve.py', '')}.resolve.py"
    if not script.exists(): sys.exit(f"no such Resolve script: {script.name} (have: {', '.join(p.name for p in sorted(P.RESOLVE_DIR.glob('*.resolve.py')))})")
    tl = a.timeline or P.picks_doc().get("timeline") or P.timeline_name(1)
    print(f'CFG = dict(PROJECT={str(P.PROJECT)!r}, PLAN={a.plan!r}, NAME={tl!r}, MODE={a.mode!r})')
    print(f'exec(open({str(script)!r}, encoding="utf-8").read())')
    sys.exit(0)

src = P.PROMPTS / f"{a.name}.md"
if not src.exists(): sys.exit(f"no such prompt: {src.name} (have: {', '.join(p.stem for p in sorted(P.PROMPTS.glob('*.md')))})")
cats = P.TAX["categories"]
fill = {
    "{PROJECT_TITLE}": P.TITLE,
    "{PROJECT_DESCRIPTION}": P.CFG.get("description") or P.TAX.get("subject_hint", "raw video footage"),
    "{SUBJECT_HINT}": P.TAX.get("subject_hint", "raw video footage"),
    "{CATEGORY_LIST}": json.dumps(list(cats)),
    "{CATEGORIES}": "\n".join(f"  - {k}: {v}" for k, v in cats.items()),
    "{INTERVIEW_CATEGORY}": P.INTERVIEW_CATEGORY,
    "{MANIFEST}": a.manifest, "{OUT}": a.out,
    "{ID_EXAMPLE}": a.id_example or ("s01" if "slot" in a.name else "b01_001"),
    "{ORIENTATION}": "vertical 9:16" if P.PORTRAIT_PROJECT else "landscape 16:9",
}
t = src.read_text(encoding="utf-8")
if "\n---\n" in t: t = t.split("\n---\n", 1)[1]          # the part above --- is a note for the agent, not for the helper
for k, v in fill.items(): t = t.replace(k, v)
print(t.strip())

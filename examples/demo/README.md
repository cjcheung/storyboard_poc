# Demo: the whole local pipeline on synthetic media

`make_demo.py` builds a 6.4 s "template" of 8 test-pattern shots (24 fps, hard cuts, two flash frames, a logo and an end card),
14 fake footage clips in two folders (one vertical, two at 60 fps) and the tags a tagging helper would have written
(`fixtures/`), so everything runs without real footage and without a vision model.

Run from the repo root:
```
SB="$PWD/skills/video-storyboard/scripts/sb.py"
python3 examples/demo/make_demo.py /tmp/sb_demo
python3 "$SB" init /tmp/sb_demo/project --template /tmp/sb_demo/template.mp4 --footage /tmp/sb_demo/footage --title "Demo recap"
cd /tmp/sb_demo/project
python3 "$SB" template-cuts            # 7 cuts; look at the review sheet it prints
python3 "$SB" template-slots           # 8 slots + tagging sheets
mkdir -p catalog/template_tags && cp ../fixtures/template_tags.json catalog/template_tags/tags_A.json
python3 "$SB" template-merge
python3 "$SB" template-brief           # template_brief.md
python3 "$SB" scan --batch b01
cp ../fixtures/clip_tags.json catalog/batches/b01/tags_A.json
python3 "$SB" merge-batch b01
python3 "$SB" match --name round1
python3 "$SB" apply --from-proposal round1 --timeline project_main_v1
python3 "$SB" storyboard --proposal round1 --round 1
open storyboard/index.html             # choose B/C/D on a row, then "Download JSON" or "Connect folder (autosave)"
```
`tests/test_pipeline.py` does the same, applies a choice from the page as round 2 and writes the Resolve build plan.
With Resolve and its MCP server available you can build the demo timeline too (skills/video-storyboard/references/resolve-build.md).

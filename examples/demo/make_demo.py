#!/usr/bin/env python3
"""Make a tiny synthetic demo: a 'template' of 8 test-pattern shots with hard cuts, 14 fake footage clips, and the tags a
tagging helper would have written for them (tagging needs a vision model, so the demo ships them as fixtures).

  python3 examples/demo/make_demo.py /tmp/sb_demo        -> /tmp/sb_demo/{template.mp4, footage/..., fixtures/...}

Then (see examples/demo/README.md):
  python3 skills/video-storyboard/scripts/sb.py init /tmp/sb_demo/project --template /tmp/sb_demo/template.mp4 --footage /tmp/sb_demo/footage
  ... template-cuts, template-slots, template-merge, scan, merge-batch, match, apply, storyboard
Only ffmpeg is needed."""
import json, os, subprocess, sys

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "sb_demo")
FPS = 24
SHOTS = [  # (lavfi source, frames)  - each one looks clearly different, so every boundary is a hard cut
    ("testsrc2=size=640x360:rate=24", 12),
    ("smptebars=size=640x360:rate=24", 18),
    ("color=c=0xC0392B:size=640x360:rate=24", 8),
    ("mandelbrot=size=640x360:rate=24", 30),
    ("rgbtestsrc=size=640x360:rate=24", 24),
    ("color=c=0x1F618D:size=640x360:rate=24", 6),
    ("cellauto=size=640x360:rate=24:rule=110", 36),
    ("testsrc=size=640x360:rate=24", 20),
]
CLIPS = [  # (folder, file, lavfi source, seconds, fps, with audio)
    ("Day 1", "clip_001.mp4", "testsrc2=size=1280x720:rate=30,hue=h=40", 3.0, 30, True),
    ("Day 1", "clip_002.mp4", "smptehdbars=size=1280x720:rate=30", 2.5, 30, False),
    ("Day 1", "clip_003.mp4", "mandelbrot=size=1280x720:rate=60", 4.0, 60, True),
    ("Day 1", "clip_004.mp4", "cellauto=size=1280x720:rate=30:rule=30", 3.0, 30, False),
    ("Day 1", "clip_005.mp4", "testsrc=size=1280x720:rate=30", 2.0, 30, False),
    ("Day 1", "clip_006.mp4", "rgbtestsrc=size=1280x720:rate=30", 3.5, 30, True),
    ("Day 1", "clip_007.mp4", "testsrc2=size=720x1280:rate=30,hue=h=200", 3.0, 30, False),
    ("Day 2", "clip_008.mp4", "life=size=1280x720:rate=30:mold=10:ratio=0.2", 3.0, 30, False),
    ("Day 2", "clip_009.mp4", "testsrc2=size=1280x720:rate=60,hue=h=120", 4.0, 60, True),
    ("Day 2", "clip_010.mp4", "color=c=0x117A65:size=1280x720:rate=30", 2.5, 30, False),
    ("Day 2", "clip_011.mp4", "mandelbrot=size=1280x720:rate=30:start_scale=1.5", 3.0, 30, False),
    ("Day 2", "clip_012.mp4", "yuvtestsrc=size=1280x720:rate=30", 2.0, 30, False),
    ("Day 2", "clip_013.mp4", "testsrc2=size=1280x720:rate=30,hue=h=300", 5.0, 30, True),
    ("Day 2", "clip_014.mp4", "smptebars=size=1280x720:rate=30,hue=s=0", 3.0, 30, False),
]
SLOT_TAGS = [  # what a helper would write for the 8 template shots
    ("brand_card", "graphic", "none", "wide", 3, "not_applicable", "gradient_card", "DEMO", False, "Logo card on a colour test pattern"),
    ("broll", "crowd_audience", "crowd", "wide", 4, "handheld", "none", "", True, "Crowd cheering in a big hall"),
    ("transition_flash", "graphic", "none", "wide", 5, "not_applicable", "flash_glow", "", False, "Red flash frame between shots"),
    ("broll", "stage_music", "few", "medium", 4, "pan_or_tilt", "none", "", True, "Band on stage with lights, camera pans"),
    ("broll", "booth_exhibit", "few", "medium", 3, "static", "none", "", True, "People at a booth smiling at the camera"),
    ("transition_flash", "graphic", "none", "wide", 5, "not_applicable", "flash_glow", "", False, "Blue flash frame"),
    ("broll", "outdoor_activity", "crowd", "wide", 5, "handheld", "none", "", True, "Outdoor games, people jumping and laughing"),
    ("logo_card", "graphic", "none", "wide", 2, "not_applicable", "none", "SEE YOU THERE", False, "End card with dates"),
]
CLIP_TAGS = [  # category, people, framing, energy, camera, flags, hero, summary
    ("crowd_audience", "crowd", "wide", 4, "handheld", [], True, "Crowd cheering with hands up"),
    ("signage_text", "none", "detail", 2, "static", [], False, "Colour bars sign at the entrance"),
    ("stage_music", "few", "medium", 5, "pan_or_tilt", ["good_light"], True, "Band on stage under bright lights"),
    ("indoor_activity", "few", "medium", 3, "handheld", ["shaky"], False, "Workshop table with people building things"),
    ("booth_exhibit", "few", "medium", 3, "static", [], False, "Visitors at a booth smiling at the camera"),
    ("food_market", "few", "close", 3, "handheld", [], False, "Food truck serving tacos"),
    ("crowd_audience", "few", "medium", 4, "handheld", [], False, "Phone video of friends cheering (vertical)"),
    ("outdoor_activity", "crowd", "wide", 5, "handheld", [], True, "Outdoor games, people jumping and laughing"),
    ("outdoor_activity", "few", "medium", 4, "pan_or_tilt", ["good_light"], False, "Sunset relay race on the lawn"),
    ("hallway_walking", "few", "wide", 2, "static", ["dark"], False, "Lobby with people walking past"),
    ("stage_music", "crowd", "wide", 4, "static", [], False, "Wide shot of the stage and audience"),
    ("registration_checkin", "few", "medium", 2, "static", [], False, "Check-in desk with badges"),
    ("crowd_audience", "crowd", "medium", 5, "handheld", [], False, "Audience laughing at the host"),
    ("closeup_detail", "none", "detail", 1, "static", [], False, "Close-up of a printed schedule"),
]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode: sys.exit(" ".join(cmd) + "\n" + r.stderr[-2000:])


os.makedirs(OUT, exist_ok=True)
args, fc = [], []
for i, (src, n) in enumerate(SHOTS):
    args += ["-f", "lavfi", "-i", src]
    fc.append(f"[{i}:v]trim=end_frame={n},setpts=PTS-STARTPTS,format=yuv420p[v{i}]")
total = sum(n for _, n in SHOTS)
args += ["-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={total / FPS}"]
fc.append("".join(f"[v{i}]" for i in range(len(SHOTS))) + f"concat=n={len(SHOTS)}:v=1:a=0[v]")
run(["ffmpeg", "-v", "error", "-y"] + args + ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", f"{len(SHOTS)}:a", "-c:v", "libx264", "-preset", "ultrafast",
     "-r", str(FPS), "-c:a", "aac", "-shortest", os.path.join(OUT, "template.mp4")])
for folder, name, src, secs, fps, audio in CLIPS:
    d = os.path.join(OUT, "footage", folder); os.makedirs(d, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src]
    if audio: cmd += ["-f", "lavfi", "-i", f"sine=frequency=330:sample_rate=48000:duration={secs}"]
    cmd += ["-t", str(secs), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", str(fps)]
    cmd += (["-c:a", "aac", "-shortest"] if audio else ["-an"])
    run(cmd + [os.path.join(d, name)])
fx = os.path.join(OUT, "fixtures"); os.makedirs(fx, exist_ok=True)
slot_tags = [{"id": f"s{i:02d}", "slot_kind": k, "category": c, "people": p, "framing": f, "energy": e, "camera_look": cam, "treatment": t, "text_on_screen": txt,
              "needs_real_footage": need, "summary": summ, "notes": ""} for i, (k, c, p, f, e, cam, t, txt, need, summ) in enumerate(SLOT_TAGS, 1)]
json.dump(slot_tags, open(os.path.join(fx, "template_tags.json"), "w"), indent=1)
clip_tags = [{"id": f"b01_{i:03d}", "summary": summ, "category": c, "people": p, "framing": f, "energy": e, "camera_look": cam, "quality_flags": fl, "hero": hero,
              "best_frame": 1, "visible_text": "", "notes": ""} for i, (c, p, f, e, cam, fl, hero, summ) in enumerate(CLIP_TAGS, 1)]
json.dump(clip_tags, open(os.path.join(fx, "clip_tags.json"), "w"), indent=1)
print(f"demo media in {OUT}: template.mp4 ({total} frames at {FPS} fps, {len(SHOTS)} shots), {len(CLIPS)} clips, fixtures/")

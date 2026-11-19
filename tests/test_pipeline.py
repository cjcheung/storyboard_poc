"""End-to-end test of the local pipeline on the synthetic demo (no Resolve, no vision model needed).

  python3 -m unittest discover -s tests -v          (needs ffmpeg with libx264)
"""
import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SB = ROOT / "skills" / "video-storyboard" / "scripts" / "sb.py"
DEMO = ROOT / "examples" / "demo" / "make_demo.py"


def run(*args, check=True):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True)
    if check and r.returncode:
        raise AssertionError(f"{' '.join(map(str, args))}\n{r.stdout}\n{r.stderr}")
    return r


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")
class DemoPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="sb_test_"))
        cls.media = cls.tmp / "media"; cls.proj = cls.tmp / "project"
        os.environ["SB_WORK"] = str(cls.tmp / "work")
        run(DEMO, cls.media)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def sb(self, *args, check=True):
        return run(SB, *args, "--project", self.proj, check=check)

    def test_pipeline(self):
        run(SB, "init", self.proj, "--template", self.media / "template.mp4", "--footage", self.media / "footage", "--preset", "event_recap", "--title", "Demo")
        cfg = json.loads((self.proj / "storyboard_project.json").read_text())
        self.assertEqual(cfg["timeline"]["width"], 1920)

        self.sb("template-cuts")
        cuts = json.loads((self.proj / "catalog" / "template_cuts.json").read_text())
        self.assertEqual(cuts["cuts"], [12, 30, 38, 68, 92, 98, 134], "every hard cut of the demo template, nothing else")
        self.assertEqual(json.loads((self.proj / "storyboard_project.json").read_text())["template"]["fps"], 24.0)

        self.sb("template-slots")
        slots = json.loads((self.proj / "catalog" / "slots.json").read_text())
        self.assertEqual(len(slots), 8)
        self.assertEqual((slots[1]["tl_start"], slots[1]["tl_end"]), (15, 38))        # 12..30 template frames at 24 fps -> 30 fps
        tdir = self.proj / "catalog" / "template_tags"; tdir.mkdir(exist_ok=True)
        shutil.copy(self.media / "fixtures" / "template_tags.json", tdir / "tags_A.json")
        self.sb("template-merge")
        self.assertNotEqual(self.sb("template-slots", check=False).returncode, 0, "tagged slots must not be overwritten without --force")
        self.sb("template-brief")
        self.assertIn("Shot list to find in the footage", (self.proj / "template_brief.md").read_text())

        # before any footage: the storyboard is a shot list (template frame + what to film per slot)
        self.sb("storyboard", "--round", "0")
        d0 = (self.proj / "storyboard" / "data.js").read_text()
        sb0 = json.loads(d0[len("window.SB = "):].rstrip().rstrip(";"))
        badges = [(s["id"], (s.get("card") or {}).get("badge")) for s in sb0["slots"]]
        self.assertEqual(sum(1 for _, b in badges if b == "TO FILM"), 4, badges)      # the 4 footage slots of the demo
        shots = (self.proj / "storyboard" / "shot_list.md").read_text()
        self.assertIn("to film", shots); self.assertIn("card / graphic", shots)

        out = self.sb("scan", "--batch", "b01").stdout
        self.assertIn("14 clips ready", out)
        shutil.copy(self.media / "fixtures" / "clip_tags.json", self.proj / "catalog" / "batches" / "b01" / "tags_A.json")
        self.sb("merge-batch", "b01")
        self.assertEqual(len(json.loads((self.proj / "catalog" / "clips.json").read_text())), 14)
        self.sb("score", "--batch", "b01")

        self.sb("match", "--name", "round1")
        sheet = json.loads((self.proj / "catalog" / "match_sheet_round1.json").read_text())
        self.assertEqual(sorted(o["slot"] for o in sheet), ["s02", "s04", "s05", "s07"])
        self.assertNotIn("b01_007", [o["clip"] for o in sheet], "the vertical clip is never auto-picked in a 16:9 edit")

        self.sb("apply", "--from-proposal", "round1", "--timeline", "demo_main_v1")
        self.sb("storyboard", "--proposal", "round1", "--round", "1")
        data = (self.proj / "storyboard" / "data.js").read_text()
        self.assertTrue(data.startswith("window.SB = "))
        sb = json.loads(data[len("window.SB = "):].rstrip().rstrip(";"))
        self.assertEqual(sb["project"], "project"); self.assertEqual(len(sb["slots"]), 8)
        self.assertTrue((self.proj / "storyboard" / "index.html").exists())

        # the person picks option B on the first footage slot that has one -> apply as round 2
        row = next(s for s in sb["slots"] if s.get("options"))
        b = row["options"][0]
        inbox = {"app": "video-storyboard", "round": 1, "who": "tester", "decisions": [
            {"slot": row["id"], "action": "swap", "choice": "B", "clip": b["clip"], "speed_percent": 100, "src_in_s": b["in"], "src_out_s": b["out"],
             "lock": False, "previous_clip": row["current"]["clip"], "previous_speed_percent": 100, "reject_previous": "slot"}]}
        (self.proj / "storyboard" / "decisions" / "inbox.json").write_text(json.dumps(inbox))
        self.sb("apply", "--timeline", "demo_main_v2", "--round", "2")
        picks = json.loads((self.proj / "history" / "current_picks.json").read_text())
        self.assertEqual(picks["picks"][row["id"]]["clip"], b["clip"])
        self.assertIn(row["current"]["clip"], (self.proj / "history" / "rejected_clips.csv").read_text())
        self.assertTrue((self.proj / "storyboard" / "decisions" / "processed").exists())

        self.sb("plan", "--out", self.tmp / "work" / "build_plan.json")
        plan = json.loads((self.tmp / "work" / "build_plan.json").read_text())
        self.assertEqual(len(plan["slots"]), 8); self.assertEqual(plan["total_frames"], 192); self.assertEqual(plan["template_fps"], 24.0)

        prompt = self.sb("prompt", "tag_clips", "--manifest", "M.json", "--out", "O.json").stdout
        self.assertIn("M.json", prompt); self.assertNotIn("{CATEGORY_LIST}", prompt); self.assertIn("stage_music", prompt)
        snippet = self.sb("resolve-script", "interview_overlay", "--mode", "verify").stdout
        self.assertIn("interview_overlay.resolve.py", snippet)


if __name__ == "__main__":
    unittest.main()

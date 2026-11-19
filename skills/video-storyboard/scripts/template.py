#!/usr/bin/env python3
"""Analyze the template video (the edit to imitate): find its cuts, turn them into slots, prepare sheets for tagging,
merge the tags and write a one-page brief.

  python3 sb.py template-cuts  [--threshold 0.10] [--min-frames 2]  probe + cut detection -> catalog/template_cuts.json + review sheets
  python3 sb.py template-slots [--agents N] [--force]               slots from the (reviewed) cuts -> catalog/slots.json + tagging sheets
  python3 sb.py template-merge                                      catalog/template_tags/tags_*.json -> catalog/slots.json (validated)
  python3 sb.py template-brief                                      template_brief.md + catalog/template_summary.json

Review step (between cuts and slots): open the review sheets (one row per cut: frames cut-2, cut-1 | CUT, cut+1; the red bar marks
the first frame of the new shot) and the 'maybe' sheets (weaker changes that were NOT counted as cuts). Fast promos have 4-8 frame
shots, white/black flashes, whip pans and dissolves: remove false cuts (camera moves, flashes inside one shot) and add missed ones
by editing the "cuts" list (frame numbers of the template) in catalog/template_cuts.json, then run template-slots."""
import argparse, collections, json, math, os, re, statistics, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P
import sb_sheets as L

SLOT_KINDS = ["broll", "interview", "brand_card", "logo_card", "title_text_card", "transition_blur", "transition_flash", "other"]
CAMERA = ["static", "handheld", "whip_pan", "pan_or_tilt", "zoom_or_crash_zoom", "moving_subject_static_camera", "not_applicable", "unknown"]
TREATMENT = ["none", "bw_grain", "blur_streak", "flash_glow", "gradient_card", "text_overlay", "split_screen", "speed_ramp", "other"]
PEOPLE = ["none", "one", "few", "crowd"]
FRAMING = ["wide", "medium", "close", "detail"]
CUTS_FILE = P.CATALOG / "template_cuts.json"
TAGS_DIR = P.CATALOG / "template_tags"


def need_template():
    if not P.REFERENCE or not P.REFERENCE.exists(): sys.exit(f"template video not found: {P.REFERENCE} (storyboard_project.json template.video)")
    return P.REFERENCE


def probe():
    info = P.probe_video(need_template())
    if "error" in info: sys.exit("cannot read the template: " + info["error"])
    return info


TW, TH = 64, 36                     # analysis size: every frame is decoded once at this size


def _passthrough():
    """ffmpeg option that emits every decoded frame exactly once (no duplicates/drops for variable-frame-rate phone videos),
    so frame numbers = decode order; '-fps_mode' on ffmpeg >= 5.1, '-vsync' before"""
    try:
        h = subprocess.run(["ffmpeg", "-hide_banner", "-h", "full"], capture_output=True, text=True, timeout=30).stdout
        return ["-fps_mode", "passthrough"] if "-fps_mode" in h else ["-vsync", "passthrough"]
    except Exception:
        return ["-vsync", "passthrough"]


PASSTHROUGH = _passthrough()


def frames_by_index(path, wanted, w, h):
    """{frame number: rgb24 bytes (w x h, letter/pillar-boxed)} for the wanted frame numbers, from ONE decode pass (exact frames, no seeking)"""
    wanted = set(wanted); n = w * h * 3; out = {}
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,format=rgb24"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-nostats", "-i", str(path), "-an", "-sn", "-dn", "-vf", vf, *PASSTHROUGH, "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    i = 0; last = max(wanted) if wanted else -1
    while i <= last:
        f = p.stdout.read(n)
        if len(f) < n: break
        if i in wanted: out[i] = f
        i += 1
    p.kill(); p.wait()
    return out


def frame_stats(path):
    """Per-frame cut score + mean brightness (0-255), from one ffmpeg pass that streams tiny RGB frames.
    Two signals per frame, each taken as its PROMINENCE over the median of the 4 frames before and after (so camera motion, strobes
    and busy patterns that change every frame do not look like cuts): mean absolute pixel difference to the previous frame, and the
    L1 difference of the RGB histograms (robust to motion inside a shot). score = sum of both prominences.
    Checked on an 83-shot promo: threshold 0.10 found all 82 cuts (within 1 frame) with 11 false alarms, which the review removes."""
    n = TW * TH * 3
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-nostats", "-i", str(path), "-an", "-sn", "-dn", "-vf", f"scale={TW}:{TH}:flags=area,format=rgb24",
                          *PASSTHROUGH, "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    prev = prev_h = None; mafd, hd, luma = [], [], []
    while True:
        f = p.stdout.read(n)
        if len(f) < n: break
        h = [0] * 24
        for k in range(0, n, 3):
            h[f[k] >> 5] += 1; h[8 + (f[k + 1] >> 5)] += 1; h[16 + (f[k + 2] >> 5)] += 1
        luma.append(sum(f) / n)
        if prev is None: mafd.append(0.0); hd.append(0.0)
        else:
            mafd.append(sum(abs(a - b) for a, b in zip(f, prev)) / n / 255)
            hd.append(sum(abs(a - b) for a, b in zip(h, prev_h)) / (2 * 3 * TW * TH))
        prev, prev_h = f, h
    p.wait()
    def prom(v, i, k=4):
        nb = sorted(v[j] for j in range(max(1, i - k), min(len(v), i + k + 1)) if j != i)
        return v[i] - (nb[len(nb) // 2] if nb else 0.0)
    score = [0.0] + [max(0.0, prom(mafd, i)) + max(0.0, prom(hd, i)) for i in range(1, len(mafd))]
    return score, luma


def pick_cuts(score, thr, min_gap):
    """frames where a new shot starts: score >= thr and the highest score within min_gap frames"""
    cand = sorted((f for f in range(1, len(score)) if score[f] >= thr), key=lambda f: -score[f])
    cuts = []
    for f in cand:
        if all(abs(f - c) >= min_gap for c in cuts): cuts.append(f)
    return sorted(cuts)


def frame_t(f, fps): return (f + 0.5) / fps


def review_sheets(path, fps, nframes, rows, kind, portrait):
    """rows: [(label, frame)] -> sheets with frames f-2, f-1, f, f+1 per row (red bar before f)"""
    cw, ch = L.cell_size(portrait); per = 8; out = []
    wdir = P.WORK / "template"; wdir.mkdir(parents=True, exist_ok=True)
    idx = {(label, k): max(0, min(nframes - 1, f + d)) for label, f in rows for k, d in enumerate((-2, -1, 0, 1))}
    got = frames_by_index(path, set(idx.values()), cw, ch); blank = bytes([60]) * (cw * ch * 3)
    frames = {key: got.get(ff, blank) for key, ff in idx.items()}
    for si in range(0, len(rows), per):
        chunk = rows[si:si + per]; png = str(wdir / f"{kind}_{si // per + 1:02d}.png")
        L.compose([(str(lab), [frames[(lab, k)] for k in range(4)]) for lab, _ in chunk], png, cw, ch, cols=4, marks={i: [2] for i in range(len(chunk))})
        out.append({"sheet": png, "rows": [{"label": lab, "frame": f, "frames_shown": [max(0, f - 2), max(0, f - 1), f, min(nframes - 1, f + 1)]} for lab, f in chunk]})
    return out


def cmd_cuts(a):
    P.require_tools()
    info = probe(); fps = info["fps"]; n = info["frames"]
    P.set_config("template.fps", fps)
    P.save_json(P.CATALOG / "template_probe.json", info)
    print(f"template: {P.REFERENCE.name}  {info['width']}x{info['height']} @ {fps} fps, {n} frames, {info['duration_s']} s, audio={info['has_audio']}", flush=True)
    score, luma = frame_stats(P.REFERENCE)
    if abs(len(score) - n) > 2: print(f"note: decoded {len(score)} frames, the container says {n}; using {len(score)}")
    n = len(score)
    cuts = pick_cuts(score, a.threshold, a.min_frames)
    maybe = [f for f in range(1, n) if a.threshold * 0.5 <= score[f] < a.threshold and score[f] >= max(score[f - 1], score[min(n - 1, f + 1)])
             and all(abs(f - c) >= 2 for c in cuts)]
    dark = [f for f in range(n) if luma[f] < 22]
    flashes = [f for f in range(n) if luma[f] > 225]
    scores = {f: score[f] for f in range(n)}
    def ranges(fr):
        out = []
        for f in fr:
            if out and f == out[-1][1] + 1: out[-1][1] = f
            else: out.append([f, f])
        return out
    sheets = review_sheets(P.REFERENCE, fps, n, [(i + 1, f) for i, f in enumerate(cuts)], "cuts", info["portrait"])
    msheets = review_sheets(P.REFERENCE, fps, n, [(i + 1, f) for i, f in enumerate(maybe[:200])], "maybe", info["portrait"]) if maybe else []
    lens = [b - a_ for a_, b in zip([0] + cuts, cuts + [n])]
    doc = {"_about": "Cut list of the template (frame numbers where a new shot starts, template frame rate). EDIT 'cuts' after reviewing the sheets, then run template-slots.",
           "template": P.REFERENCE_REL, "fps": fps, "frames": n, "threshold": a.threshold, "min_frames": a.min_frames,
           "cuts": cuts, "scores": {str(f): round(scores[f], 3) for f in cuts},
           "maybe": [{"frame": f, "score": round(scores[f], 3)} for f in maybe],
           "dark_frames": ranges(dark), "bright_frames": ranges(flashes),
           "review": {"cut_sheets": sheets, "maybe_sheets": msheets}}
    P.save_json(CUTS_FILE, doc)
    print(f"cuts: {len(cuts)} -> {len(cuts) + 1} shots | shot length median {statistics.median(lens) / fps:.2f}s, min {min(lens)}f, max {max(lens)}f | weaker 'maybe' changes: {len(maybe)}")
    if doc["dark_frames"]: print("near-black frame ranges:", doc["dark_frames"][:12])
    if doc["bright_frames"]: print("near-white frame ranges (flashes?):", doc["bright_frames"][:12])
    for s in sheets: print("  review:", s["sheet"])
    for s in msheets: print("  maybe :", s["sheet"])
    print(f"\nwrote {CUTS_FILE}\nnext: look at the sheets, fix the 'cuts' list if needed, then:  python3 sb.py template-slots")


def cmd_slots(a):
    P.require_tools()
    doc = P.load_json(CUTS_FILE); fps = doc["fps"]; n = doc["frames"]
    old = P.slots()
    if old and any(s.get("summary") for s in old) and not a.force:
        sys.exit(f"{P.SLOTS_FILE} already has tagged slots; use --force to rebuild them from the cut list (a backup is kept)")
    if old: P.save_json(P.SLOTS_FILE.with_suffix(".backup.json"), old)
    cuts = sorted({int(c) for c in doc["cuts"] if 0 < int(c) < n})
    bounds = [0] + cuts + [n]; nslots = len(bounds) - 1; digits = 2 if nslots < 100 else 3
    slots = []
    for i, (s, e) in enumerate(zip(bounds, bounds[1:]), 1):
        d = e - s
        ft = [round((s + min(d - 1, math.floor(p * d)) + 0.5) / fps, 3) for p in (0.15, 0.5, 0.85)]
        slots.append({"id": f"s{i:0{digits}d}", "start_frame": s, "end_frame": e, "dur_frames": d, "start_s": round(s / fps, 3), "dur_s": round(d / fps, 3),
                      "frame_times_s": ft, "tl_start": round(s / fps * P.FPS), "tl_end": round(e / fps * P.FPS),
                      "summary": "", "slot_kind": "", "category": "", "people": "", "framing": "", "energy": None, "camera_look": "", "treatment": "",
                      "text_on_screen": "", "needs_real_footage": None, "notes": ""})
    P.save_json(P.SLOTS_FILE, slots)
    info = P.load_json(P.CATALOG / "template_probe.json", {}); portrait = bool(info.get("portrait"))
    cw, ch = L.cell_size(portrait)
    wdir = P.WORK / "template_slots"; wdir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(12) as ex:
        futs = {(s["id"], k): ex.submit(L.grab, P.REFERENCE, t, cw, ch) for s in slots for k, t in enumerate(s["frame_times_s"])}
        frames = {k: f.result() for k, f in futs.items()}
    sheets = []
    for si in range(0, len(slots), L.ROWS_PER_SHEET):
        chunk = slots[si:si + L.ROWS_PER_SHEET]; png = str(wdir / f"slots_{si // L.ROWS_PER_SHEET + 1:02d}.png")
        L.compose([(s["id"][1:], [frames[(s["id"], k)] for k in range(3)]) for s in chunk], png, cw, ch, cols=3)
        sheets.append({"kind": "template_slots", "sheet": png, "rows": [{"id": s["id"], "label": s["id"][1:], "start_s": s["start_s"], "dur_s": s["dur_s"],
                       "dur_frames": s["dur_frames"], "frame_times_s": s["frame_times_s"]} for s in chunk]})
    n_agents = a.agents or max(1, -(-len(slots) // 40)); per = -(-len(sheets) // n_agents)
    TAGS_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(n_agents):
        g = sheets[i * per:(i + 1) * per]
        if not g: continue
        letter = chr(ord("A") + i); man = wdir / f"agent_{letter}.json"
        P.save_json(man, {"cell_px": [cw, ch], "columns": 3, "label_column_px": L.LABEL_W, "template_fps": fps, "sheets": g})
        print(f"  helper {letter}: {len(g)} sheets, {sum(len(s['rows']) for s in g)} slots -> {man}  (writes {TAGS_DIR / ('tags_' + letter + '.json')})")
    tl_end = slots[-1]["tl_end"]
    print(f"{len(slots)} slots -> {P.SLOTS_FILE} | timeline {tl_end} frames at {P.FPS} fps ({tl_end / P.FPS:.1f}s)")
    print("next: tag the sheets (python3 sb.py prompt tag_template_slots --manifest <agent_X.json> --out <tags_X.json>), then python3 sb.py template-merge")


def cmd_merge(a):
    slots = P.slots(); by = {s["id"]: s for s in slots}
    tags = {}
    for f in sorted(TAGS_DIR.glob("tags_*.json")):
        for t in json.load(open(f, encoding="utf-8")):
            if t["id"] in tags: sys.exit(f"duplicate tag for {t['id']} ({f.name})")
            tags[t["id"]] = t
    missing, extra = sorted(set(by) - set(tags)), sorted(set(tags) - set(by))
    if extra: sys.exit(f"tags for unknown slots: {extra[:10]}")
    cats = set(P.CATEGORIES) | {"graphic"}
    problems = []
    for sid, t in tags.items():
        for k, allowed in (("slot_kind", SLOT_KINDS), ("category", cats), ("people", PEOPLE), ("framing", FRAMING), ("camera_look", CAMERA), ("treatment", TREATMENT)):
            if t.get(k) not in allowed: problems.append(f"{sid}.{k}={t.get(k)!r}")
        if not isinstance(t.get("energy"), int) or not 1 <= t["energy"] <= 5: problems.append(f"{sid}.energy={t.get('energy')!r}")
        if not isinstance(t.get("needs_real_footage"), bool): problems.append(f"{sid}.needs_real_footage={t.get('needs_real_footage')!r}")
    if problems: sys.exit("off-schema values (fix the tag files): " + ", ".join(problems[:30]))
    for sid, t in tags.items():
        by[sid].update({k: v for k, v in t.items() if k != "id"})
    P.save_json(P.SLOTS_FILE, slots)
    doc = P.picks_doc(); picks = doc["picks"]; added = 0
    for s in slots:
        if s["id"] in picks or s["id"] not in tags: continue
        if not s["needs_real_footage"]:
            picks[s["id"]] = {"kind": "template", "locked": True, "reason": "graphic / card kept from the template until an asset is supplied", "round": 0}; added += 1
        elif s["category"] in P.RULES["template_locked"]["categories"]:
            picks[s["id"]] = {"kind": "template", "locked": True, "reason": "talking-head shot kept from the template until an interview is placed", "round": 0}; added += 1
    if added: P.save_json(P.PICKS_FILE, doc)
    print(f"merged tags for {len(tags)} of {len(slots)} slots" + (f" (untagged: {missing[:12]})" if missing else ""))
    print("kinds:", dict(collections.Counter(t["slot_kind"] for t in tags.values())))
    print("categories:", dict(collections.Counter(t["category"] for t in tags.values()).most_common()))
    print(f"template placeholders added to current_picks.json: {added}")
    print("next: python3 sb.py template-brief   (then scan + tag the footage)")


def audio_facts(path):
    out = {}
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-sn", "-dn", "-af", "ebur128=peak=true,silencedetect=noise=-40dB:d=0.4", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=1800)
    m = re.search(r"Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+) LUFS", r.stderr)
    if m: out["integrated_lufs"] = float(m.group(1))
    m = re.search(r"True peak:\s*\n\s*Peak:\s*(-?[\d.]+) dBFS", r.stderr)
    if m: out["true_peak_dbtp"] = float(m.group(1))
    st = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]; en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    out["silences_s"] = [[round(max(0, s), 2), round(e, 2)] for s, e in zip(st, en)]
    return out


def sparkline(vals):
    bars = " .:-=+*#%@"
    hi = max(vals) if vals else 1
    return "".join(bars[min(len(bars) - 1, int(round(v / hi * (len(bars) - 1))))] if hi else " " for v in vals)


def cmd_brief(a):
    P.require_tools()
    info = P.load_json(P.CATALOG / "template_probe.json", {}) or probe()
    slots = P.slots(); fps = float(P.TEMPLATE_FPS or info["fps"])
    if not slots: sys.exit("no slots yet: run template-cuts and template-slots first")
    lens = [s["dur_frames"] for s in slots]; dur = info["duration_s"]
    starts = [s["start_s"] for s in slots]
    per10 = [sum(1 for t in starts if w <= t < w + 10) for w in range(0, int(math.ceil(dur)), 10)]
    win = max(((sum(1 for t in starts if w <= t < w + 3), w) for w in [x / 2 for x in range(0, int(dur * 2))]), key=lambda x: (x[0], -x[1]), default=(0, 0))
    tagged = [s for s in slots if s.get("slot_kind")]
    aud = audio_facts(P.REFERENCE) if info.get("has_audio") else {}
    summary = {"template": P.REFERENCE_REL, "duration_s": dur, "fps": fps, "size": [info["width"], info["height"]], "vertical": bool(info.get("portrait")),
               "shots": len(slots), "shot_frames": {"median": statistics.median(lens), "mean": round(statistics.mean(lens), 1), "min": min(lens), "max": max(lens)},
               "cuts_per_10s": per10, "busiest_3s": {"start_s": win[1], "cuts": win[0]}, "audio": aud,
               "kinds": dict(collections.Counter(s["slot_kind"] for s in tagged)), "categories": dict(collections.Counter(s["category"] for s in tagged).most_common()),
               "treatments": dict(collections.Counter(s["treatment"] for s in tagged if s["treatment"] not in ("none", ""))),
               "camera": dict(collections.Counter(s["camera_look"] for s in tagged)),
               "footage_slots": sum(1 for s in tagged if s["needs_real_footage"]), "tagged": len(tagged)}
    P.save_json(P.CATALOG / "template_summary.json", summary)
    L_ = [f"# Template brief - {P.TITLE}", "",
          f"Template: `{P.REFERENCE.name}` - {dur:.1f} s, {info['width']}x{info['height']} ({'vertical 9:16' if info.get('portrait') else 'landscape'}), {fps:g} fps, audio: {'yes' if info.get('has_audio') else 'no'}.",
          f"Our timeline: {P.W}x{P.H} at {P.FPS:g} fps (`{P.TL['name_pattern']}`).", "",
          "## Rhythm", "",
          f"- {len(slots)} shots; median {statistics.median(lens) / fps:.2f} s ({statistics.median(lens):g} frames), shortest {min(lens)} frames, longest {max(lens) / fps:.2f} s.",
          f"- New shots per 10 s: {per10}  `{sparkline(per10)}`",
          f"- Busiest stretch: {win[0]} shots start in the 3 s from {win[1]:.1f} s.",
          f"- Longest shots: " + ", ".join(f"{s['id']} ({s['dur_s']:.2f}s at {s['start_s']:.1f}s)" for s in sorted(slots, key=lambda s: -s["dur_frames"])[:5]) + "."]
    if aud:
        L_ += [f"- Audio: {aud.get('integrated_lufs', '?')} LUFS integrated, true peak {aud.get('true_peak_dbtp', '?')} dBTP; silences: {aud['silences_s'][:8] or 'none'}."]
    if tagged:
        L_ += ["", "## What the shots are", "",
               f"- Kinds: {summary['kinds']}", f"- Categories: {summary['categories']}",
               f"- Camera: {summary['camera']}", f"- Treatments / effects: {summary['treatments'] or 'none tagged'}",
               f"- Slots that need real footage: {summary['footage_slots']} of {len(tagged)}."]
        txt = [s for s in tagged if s.get("text_on_screen")]
        if txt: L_ += ["- On-screen text: " + "; ".join(f"{s['id']} \"{s['text_on_screen']}\"" for s in txt[:20])]
        cards = [s for s in tagged if not s["needs_real_footage"]]
        if cards: L_ += ["- Cards / graphics to rebuild or replace: " + ", ".join(f"{s['id']} ({s['slot_kind']}: {s['summary']})" for s in cards[:20])]
        talk = [s for s in tagged if s["category"] == P.INTERVIEW_CATEGORY]
        if talk: L_ += [f"- Talking-head slots ({len(talk)}): " + ", ".join(s["id"] for s in talk) + " - candidates for interview/voice segments."]
        en = [round(statistics.mean([s["energy"] for s in tagged if w <= s["start_s"] < w + 10] or [0]), 1) for w in range(0, int(math.ceil(dur)), 10)]
        L_ += [f"- Energy per 10 s (1-5): {en}  `{sparkline(en)}`", "",
               "## Shot list to find in the footage", ""]
        need = collections.Counter((s["category"], s["framing"]) for s in tagged if s["needs_real_footage"] and s["category"] != P.INTERVIEW_CATEGORY)
        L_ += [f"- {n} x {c} ({fr})" for (c, fr), n in need.most_common()]
    L_ += ["", "## Style notes (filled in by the agent after looking at the sheets; confirm with the user)", "",
           "- Structure / sections:", "- Look and colour:", "- Transitions and effects:", "- Text and graphics style:", "- Music and sound:", "- What must be kept exactly (locked):", ""]
    out = P.PROJECT / "template_brief.md"
    if out.exists() and not a.force:
        out = P.PROJECT / "template_brief.generated.md"
        print("template_brief.md exists (kept); wrote the fresh numbers to", out.name)
    out.write_text("\n".join(L_), encoding="utf-8")
    print(f"wrote {out} and {P.CATALOG / 'template_summary.json'}")


ap = argparse.ArgumentParser(description="template analysis")
sub = ap.add_subparsers(dest="cmd", required=True)
c = sub.add_parser("cuts"); c.add_argument("--threshold", type=float, default=0.10, help="cut score threshold (lower = more cuts; the review removes false ones)")
c.add_argument("--min-frames", type=int, default=2, help="shortest shot in frames")
s = sub.add_parser("slots"); s.add_argument("--agents", type=int); s.add_argument("--force", action="store_true")
sub.add_parser("merge")
b = sub.add_parser("brief"); b.add_argument("--force", action="store_true", help="overwrite template_brief.md")
a = ap.parse_args()
{"cuts": cmd_cuts, "slots": cmd_slots, "merge": cmd_merge, "brief": cmd_brief}[a.cmd](a)

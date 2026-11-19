#!/usr/bin/env python3
"""Turn the picks into the build plan that the Resolve scripts (resolve/*.resolve.py) read.

  python3 sb.py plan                                    # from history/current_picks.json -> <work>/build_plan.json
  python3 sb.py plan --picks history/rounds/round_002_xxx.json --out /some/where/build_plan.json

Plan paths are ABSOLUTE for this machine (Resolve imports by absolute path), so build the plan on the machine that runs Resolve.
Optional history/interviews.json adds the interview (A-roll) overlay; storyboard_project.json timeline.music_* the music bed."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P
import expr

ap = argparse.ArgumentParser()
ap.add_argument("--picks", default=str(P.PICKS_FILE))
ap.add_argument("--out", default=str(P.WORK / "build_plan.json"))
a = ap.parse_args()

slots = P.slots()
picks = P.load_json(a.picks)["picks"]
cat = {c["id"]: c for c in P.catalog()}
flags = P.clip_flags()
TL = P.TL
out = []
for s in slots:
    p = picks.get(s["id"])
    if p is None:
        sys.exit(f"slot {s['id']} has no pick yet (run sb.py apply --from-proposal <name> first, or give it a template/graphic pick)")
    e = {"slot": s["id"], "b_start": s["tl_start"], "b_next": s["tl_end"]}
    if p["kind"] == "template":
        e.update(kind="ref", path=str(P.REFERENCE), ref_s=s["start_frame"], ref_e=s["end_frame"])
    elif p["kind"] == "graphic":
        e.update(kind="new", path=P.source_path(p["asset"]), clip="graphic:" + s["id"], in_s=float(p.get("src_in_s", 0.0)), slow=False, graphic=True)
        e["marker"] = {"color": "Purple", "note": "GRAPHIC | " + p["asset"] + " | " + p.get("reason", "")}
    else:
        c = cat[p["clip"]]
        slow = p.get("speed_percent", 100) == 50
        e.update(kind="new", path=P.abs_path(c["path"]), clip=c["id"], in_s=p["src_in_s"], slow=slow)
        note = f'{c["id"]} | {c["file"]} | {"50% SLOW" if slow else "100%"}'
        color, fx = "Blue", P.treatment_fx(s)
        if fx: color = "Cyan"; note += " | FX: " + "; ".join(fx)
        if c["category"] == "timelapse":
            color = "Yellow"; note += " | timelapse scaled to fill the frame, check framing"
        elif P.orientation_mismatch(c): color = "Yellow"; note += f" | {P.MISMATCH_LABEL} clip, check framing"
        if c["id"] in flags["check_releases"]: color = "Red"; note += " | CHECK RELEASES"
        fr = {k: p[k] for k in ("zoom", "pan", "tilt") if k in p}
        if c["category"] == "timelapse" and "zoom" not in fr: fr.update(expr.auto_framing(c))
        e.update(fr)
        if fr and c["category"] != "timelapse": note += f" | cropped in {fr.get('zoom', 1)}x"
        e["marker"] = {"color": color, "note": note}
    if s.get("inserted"): e["inserted"] = True
    if p.get("interview"): e["gap"] = True; e["interview"] = p["interview"]      # whatever was here is removed in the overlay layout; the interview picture shows instead
    out.append(e)
ivs = P.load_json(P.HISTORY / "interviews.json", {})
overlay = []
for iid, iv in ivs.items():
    pieces, cum, prev = [], 0, 0
    for src0, src1 in iv["pieces_src_frames"]:
        n = src1 - src0; cum += n; bound = round(cum / iv["source_fps"] * P.FPS)
        pieces.append({"src_in": src0, "src_n": n, "rec_off": prev, "T": bound - prev}); prev = bound
    overlay.append({"id": iid, "title": iv.get("title", iid), "source": P.source_path(iv["source"]), "source_fps": iv["source_fps"], "start_frame": iv["start_frame"], "length": prev,
                    "pieces": pieces, "video_track": iv.get("video_track", TL["a_roll_video_track"]), "audio_track": iv.get("audio_track", TL["a_roll_audio_track"]),
                    "b_roll_track": iv.get("b_roll_track", TL["b_roll_track"]), "spots": iv.get("spots", []),
                    "normalize": iv.get("normalize", {"mode": "True Peak", "target_dbtp": -2.0}), "measured": iv.get("measured"), "framing": iv.get("framing"), "background": iv.get("background"),
                    "grade": iv.get("grade"), "framing_pieces": iv.get("framing_pieces"), "gain_pieces_db": iv.get("gain_pieces_db"), "picture_override": iv.get("picture_override")})
total = out[-1]["b_next"]
music = P.abs_path(TL["music_file"]) if TL.get("music_file") else ""
plan = {"project": P.NAME, "fps": P.FPS, "width": P.W, "height": P.H, "start_timecode": TL["start_timecode"], "template_fps": P.TEMPLATE_FPS,
        "total_frames": total, "music": music, "reference": str(P.REFERENCE) if P.REFERENCE else "",
        "footage_roots": [str(r) for rs in P.ROOTS.values() for r in rs], "b_roll_track": TL["b_roll_track"], "overlay": overlay,
        "music_cfg": {"track": TL.get("music_track", 2), "level_db": TL.get("music_level_db", 0.0), "fade_out_frames": TL.get("music_fade_out_frames", 0), "picture_fade_frames": TL.get("picture_fade_to_black_frames", 0),
                      "outro_db": TL.get("music_outro_db"), "outro_ramp_frames": TL.get("music_outro_ramp_frames", 0),
                      "outro_start": -(-max(o["start_frame"] + o["length"] for o in overlay) // 5) * 5 if overlay else None}, "slots": out}
mcfg = plan["music_cfg"]
if mcfg.get("outro_db") is not None and music:
    # music with an outro swell = ONE clip with real level keyframes: an FCP7-XML timeline "music_swell_<frames>f..." (imported once by MODE music of
    # interview_overlay.resolve.py) that is appended as a nested clip on the music track. The fade-out is a keyframe ramp too (a nested clip has no
    # fade handles); the floor stays above 0 (a 0 keyframe silenced everything after the first key).
    import urllib.parse
    tb = int(round(P.FPS)); lo, hi = 10 ** (mcfg["level_db"] / 20), 10 ** (mcfg["outro_db"] / 20); sw, rp = mcfg["outro_start"], mcfg["outro_ramp_frames"]
    kx = "".join(f"<keyframe><when>{w}</when><value>{v:.5f}</value></keyframe>" for w, v in ((0, lo), (sw, lo), (sw + rp, hi), (total - mcfg.get("fade_out_frames", 0), hi), (total, 0.0003)))
    url = "file://localhost" + urllib.parse.quote(music)
    long_dur = max(total, tb * 180)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4"><sequence id="seq1"><name>music_swell</name><duration>{total}</duration><rate><timebase>{tb}</timebase><ntsc>FALSE</ntsc></rate>
<timecode><rate><timebase>{tb}</timebase><ntsc>FALSE</ntsc></rate><string>{TL["start_timecode"]}</string><frame>{P.START_FRAMES}</frame><displayformat>NDF</displayformat></timecode>
<media><video><format><samplecharacteristics><width>{P.W}</width><height>{P.H}</height><pixelaspectratio>square</pixelaspectratio><rate><timebase>{tb}</timebase><ntsc>FALSE</ntsc></rate></samplecharacteristics></format><track></track></video>
<audio><numOutputChannels>2</numOutputChannels><format><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics></format>
<track><clipitem id="clipitem-1"><name>music (level keyframes)</name><enabled>TRUE</enabled><duration>{long_dur}</duration><rate><timebase>{tb}</timebase><ntsc>FALSE</ntsc></rate>
<start>0</start><end>{total}</end><in>0</in><out>{total}</out>
<file id="file-1"><name>{os.path.basename(music)}</name><pathurl>{url}</pathurl><rate><timebase>{tb}</timebase><ntsc>FALSE</ntsc></rate><duration>{long_dur}</duration>
<media><audio><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics><channelcount>2</channelcount></audio></media></file>
<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>
<filter><effect><name>Audio Levels</name><effectid>audiolevels</effectid><effectcategory>audiolevels</effectcategory><effecttype>audiolevels</effecttype><mediatype>audio</mediatype>
<parameter><parameterid>level</parameterid><name>Level</name><valuemin>0</valuemin><valuemax>3.98109</valuemax><value>{lo:.5f}</value>{kx}</parameter></effect></filter>
</clipitem></track></audio></media></sequence></xmeml>"""
    name = f"music_swell_{total}f_{sw}_{rp}_fo{mcfg.get('fade_out_frames', 0)}b"
    swell_xml = os.path.join(os.path.dirname(a.out), name + ".xml"); os.makedirs(os.path.dirname(a.out), exist_ok=True); open(swell_xml, "w", encoding="utf-8").write(xml)
    mcfg["swell_xml"] = swell_xml; mcfg["swell_timeline"] = name
P.save_json(a.out, plan)
print(f"plan: {len(out)} slots ({sum(1 for e in out if e['kind'] == 'new')} footage/graphics, {sum(1 for e in out if e['kind'] == 'ref')} template), {total} frames, {len(overlay)} interviews -> {a.out}")

#!/usr/bin/env python3
"""Measure each interview's audio and store the exact gain for its True Peak target.
  python3 sb.py measure-interviews            # all interviews in history/interviews.json -> writes 'measured' into each entry
Cuts the interview pieces out of the source (same frames as the timeline), concatenates them and reads ffmpeg loudnorm's input true peak (2 decimals).
gain_db = target dBTP - measured true peak. Resolve's own normalizer rounds to 0.1 dB, so the overlay script sets this exact value afterwards.
For a loudness (LUFS) match across speakers use  sb.py measure-dialogue  instead (per piece, from a timeline dump)."""
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P
P.require_tools()
path = P.HISTORY / "interviews.json"
ivs = P.load_json(path, {})
if not ivs: sys.exit("no interviews defined (history/interviews.json)")
for iid, iv in ivs.items():
    src = P.source_path(iv["source"]); fps = iv["source_fps"]; pcs = iv["pieces_src_frames"]
    target = float(iv.get("normalize", {}).get("target_dbtp", -2.0))
    parts = [f"[0:a]atrim=start={a / fps:.6f}:end={b / fps:.6f},asetpts=PTS-STARTPTS[p{i}]" for i, (a, b) in enumerate(pcs)]
    fc = ";".join(parts) + ";" + "".join(f"[p{i}]" for i in range(len(pcs))) + f"concat=n={len(pcs)}:v=0:a=1,loudnorm=I=-16:TP=-2:LRA=11:print_format=json[o]"
    # audio only (-vn): a filter graph that also decodes the video of a long recording can buffer gigabytes of frames
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-vn", "-sn", "-dn", "-i", src, "-filter_complex", fc, "-map", "[o]", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m: print(iid, "measure failed"); continue
    j = json.loads(m.group(0)); tp = float(j["input_tp"])
    iv["measured"] = {"input_true_peak_dbtp": tp, "input_loudness_lufs": float(j["input_i"]), "gain_db": round(target - tp, 2),
                      "result_true_peak_dbtp": round(tp + round(target - tp, 2), 2), "result_loudness_lufs": round(float(j["input_i"]) + round(target - tp, 2), 1)}
    print(f'{iid}: true peak {tp} dBTP, {j["input_i"]} LUFS -> gain {iv["measured"]["gain_db"]} dB => {iv["measured"]["result_true_peak_dbtp"]} dBTP, ~{iv["measured"]["result_loudness_lufs"]} LUFS')
P.save_json(path, ivs)

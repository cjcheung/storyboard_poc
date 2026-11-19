#!/usr/bin/env python3
"""Fit the stacked words of every emphasis in config/effects.json to the screen and write size / cx / y into each word.
Each line is scaled so it spans the inner width (frame width - 2*(frame margin + pad)); if the stack is taller than the inner height all lines
shrink together. Text+ centres the text's line box on y, so y is corrected by the ink-vs-line-box offset measured with Pillow on the same font
file. Re-run after editing words/style, then rebuild with resolve/effects.resolve.py MODE emphasis.

  python3 sb.py fit-text [--font /path/to/Font-ExtraBold.ttf]     (default: config/effects.json style.font_file, relative to the project)
Needs Pillow."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_paths as P
from PIL import ImageFont

ap = argparse.ArgumentParser(); ap.add_argument("--font"); a = ap.parse_args()
cfgp = P.CONFIG / "effects.json"; fx = P.load_json(cfgp); S = fx["style"]
font_path = a.font or S.get("font_file")
if not font_path: sys.exit("set style.font_file in config/effects.json (the .ttf of the big text) or pass --font")
font_path = P.source_path(font_path)
W, H = P.W, P.H; pad = S.get("text_pad_px", 44); gap = S.get("line_gap_px", 34)
inner_w = W - 2 * (S["frame_margin_px"] + pad); inner_h = H - 2 * (S["frame_margin_px"] + pad)
for e in fx["emphasis"]:
    m = []
    for w in e["words"]:
        f = ImageFont.truetype(font_path, 200); l, t, r, b = f.getbbox(w["text"], anchor="ls")
        size = inner_w / (r - l) * 200; m.append({"w": w, "size": size, "ink_h": (b - t) / 200, "ink_c": (t + b) / 2 / 200})
    tot = sum(x["size"] * x["ink_h"] for x in m) + gap * (len(m) - 1); k = min(1.0, inner_h / tot) if tot else 1.0
    tot = sum(x["size"] * k * x["ink_h"] for x in m) + gap * (len(m) - 1); y = H / 2 - tot / 2
    f0 = ImageFont.truetype(font_path, 200); asc, desc = f0.getmetrics()
    for x in m:
        size = x["size"] * k; h = size * x["ink_h"]; ink_center_y = y + h / 2
        box_c_rel = (-asc + desc) / 2 / 200 * size              # line-box centre relative to the baseline (negative = above)
        delta = x["ink_c"] * size - box_c_rel                     # ink centre minus box centre (positive = ink lower than the box centre)
        x["w"].update(size=round(size, 1), cx=W / 2, y=round(ink_center_y - delta, 1)); y += h + gap
    print(e["id"], [(x["w"]["text"], x["w"]["size"], x["w"]["y"]) for x in m])
P.save_json(cfgp, fx)

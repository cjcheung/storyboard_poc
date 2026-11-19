"""Contact-sheet helpers. Pure Python + ffmpeg (no Pillow needed): frames are grabbed as raw RGB,
tiled into rows (one clip or slot per row, big white row number on the left) and written as PNG."""
import re, struct, subprocess, zlib

CW, CH = 288, 162          # frame cell size for landscape material
LABEL_W = 120              # label column width
GAP = 4
COLS = 8
ROWS_PER_SHEET = 5

FONT = {
 '0': ["01110","10001","10011","10101","11001","10001","01110"], '1': ["00100","01100","00100","00100","00100","00100","01110"],
 '2': ["01110","10001","00001","00010","00100","01000","11111"], '3': ["11110","00001","00001","01110","00001","00001","11110"],
 '4': ["00010","00110","01010","10010","11111","00010","00010"], '5': ["11111","10000","11110","00001","00001","10001","01110"],
 '6': ["00110","01000","10000","11110","10001","10001","01110"], '7': ["11111","00001","00010","00100","01000","01000","01000"],
 '8': ["01110","10001","10001","01110","10001","10001","01110"], '9': ["01110","10001","10001","01111","00001","00010","01100"],
}


def cell_size(portrait):
    """cell for a sheet: 16:9 cells for landscape material, 9:16 cells for vertical material"""
    return (CH, CW) if portrait else (CW, CH)


def grab(path, t, w=CW, h=CH):
    """One frame at time t (seconds) as raw RGB bytes, letter/pillar-boxed to w x h."""
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", str(path), "-frames:v", "1", "-an", "-sn", "-dn",
           "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if len(r.stdout) == w * h * 3:
            return r.stdout
    except Exception:
        pass
    return bytes([60]) * (w * h * 3)


def motion_ydif(path, dur):
    """Mean luma frame-to-frame difference over 1s mid-clip: ~0 = static, higher = movement."""
    t0 = max(0.0, dur / 2 - 0.5)
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", "1.0", "-i", str(path), "-an", "-sn", "-dn",
           "-vf", "scale=320:-2,signalstats,metadata=mode=print:key=lavfi.signalstats.YDIF:file=-", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        vals = [float(x) for x in re.findall(r"YDIF=([0-9.]+)", r.stdout)]
        return round(sum(vals) / len(vals), 3) if vals else None
    except Exception:
        return None


def write_png(path, w, h, rgb):
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def compose(sheet_rows, path, cw=CW, ch=CH, cols=COLS, marks=None):
    """sheet_rows: list of (label_digits, [frame_bytes, ...]) -> one PNG, one row per entry.
    marks: optional {row_index: [column, ...]} - a red bar is drawn on the LEFT edge of those cells (e.g. where a cut happens)."""
    w = LABEL_W + cols * cw
    row_h = ch + GAP
    h = len(sheet_rows) * row_h
    buf = bytearray(bytes([70]) * (w * h * 3))
    for ri, (label, frames) in enumerate(sheet_rows):
        y0 = ri * row_h
        bg = bytes([25, 25, 25]) if ri % 2 == 0 else bytes([45, 45, 45])
        for yy in range(ch):
            o = ((y0 + yy) * w) * 3
            buf[o:o + LABEL_W * 3] = bg * LABEL_W
            for ci in range(cols):
                x0 = LABEL_W + ci * cw
                src = frames[ci][yy * cw * 3:(yy + 1) * cw * 3] if ci < len(frames) else bytes(cw * 3)
                buf[((y0 + yy) * w + x0) * 3:((y0 + yy) * w + x0 + cw) * 3] = src
        for ci in (marks or {}).get(ri, []):
            x0 = LABEL_W + ci * cw
            for yy in range(ch):
                o = ((y0 + yy) * w + x0) * 3
                buf[o:o + 6 * 3] = bytes([230, 40, 40]) * 6
        sc = 6
        label = "".join(ch_ for ch_ in str(label) if ch_ in FONT)[:3]
        text_w = len(label) * 5 * sc + (len(label) - 1) * sc
        tx, ty = (LABEL_W - text_w) // 2, y0 + (ch - 7 * sc) // 2
        for di, chr_ in enumerate(label):
            for gy, line in enumerate(FONT[chr_]):
                for gxi, bit in enumerate(line):
                    if bit == "1":
                        for dy in range(sc):
                            o = ((ty + gy * sc + dy) * w + tx + di * 6 * sc + gxi * sc) * 3
                            buf[o:o + sc * 3] = bytes([255, 255, 255]) * sc
    write_png(path, w, h, bytes(buf))


def nframes(d):
    return 3 if d < 4 else 4 if d < 15 else 6 if d < 40 else 8

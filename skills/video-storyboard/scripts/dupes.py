"""Near-duplicate scene warning (warning only - never blocks a pick).
Two clips are 'possibly the same scene' if they sit in the same folder and were recorded within
`window_s` seconds of each other, or have consecutive file numbers (C0001 / C0002)."""
import re, itertools
from datetime import datetime

def _ts(c):
    s = c.get("created") or ""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None

def _num_key(c):
    stem = c["file"].rsplit(".", 1)[0]
    m = re.match(r"^(.*?)(\d+)(\D*)$", stem)
    return (m.group(1), m.group(3), int(m.group(2))) if m else None

def near_duplicate_pairs(clips, window_s=90):
    pairs = []
    for a, b in itertools.combinations(clips, 2):
        if a["folder"] != b["folder"] or a["id"] == b["id"]:
            continue
        ta, tb = _ts(a), _ts(b)
        close_time = ta is not None and tb is not None and abs(ta - tb) <= window_s
        ka, kb = _num_key(a), _num_key(b)
        consecutive = bool(ka and kb and ka[:2] == kb[:2] and abs(ka[2] - kb[2]) == 1)
        if close_time or consecutive:
            pairs.append((a["id"], b["id"]))
    return pairs

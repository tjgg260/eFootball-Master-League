#!/usr/bin/env python3
"""
seed_appearance.py — fill player_appearance in build/master.db for the whole universe.

  * eFootball natives: skin tone read straight from PlayerAppearance.bin ('bin').
  * Imported players with a portrait: tone sampled from their own portrait's face
    luminance, classified with thresholds fitted to the 1,029-player calibration set
    ('portrait').
  * Everyone else: left unseeded — the compile keeps the donor's appearance, and the
    academy can seed on intake later.

Idempotent: re-running only inserts missing rows (ON CONFLICT DO NOTHING keeps sources).
"""
from __future__ import annotations

import os
import sqlite3
import statistics
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
import wesys  # noqa: E402
from appearance import REC, SKIN_BIT  # noqa: E402

# Class boundaries between the six tones' mean luminances (165/162/158/137/118/97),
# midpoints used as thresholds — darkest first check.
THRESHOLDS = [(107.5, 6), (127.3, 5), (147.1, 4), (159.8, 3), (163.5, 2)]


def classify(lum: float) -> int:
    for cut, tone in THRESHOLDS:
        if lum <= cut:
            return tone
    return 1


def face_luminance(path: str):
    from PIL import Image
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    px = im.load()
    vals = []
    for x0, y0, x1, y1 in ((int(w*.30), int(h*.55), int(w*.42), int(h*.68)),
                           (int(w*.58), int(h*.55), int(w*.70), int(h*.68))):
        for x in range(x0, x1):
            for y in range(y0, y1):
                r, g, b, a = px[x, y]
                if a > 200:
                    vals.append(0.299*r + 0.587*g + 0.114*b)
    return statistics.mean(vals) if len(vals) >= 30 else None


def main() -> int:
    db = sqlite3.connect(REPO / "build" / "master.db")

    # natives from the bin
    payload = wesys.unpack_wesys_payload(
        (REPO / "build/tree_base/common/etc/appearance/PlayerAppearance.bin").read_bytes())
    tone_by_gpid = {}
    for i in range(len(payload) // REC):
        off = i * REC
        gpid = struct.unpack_from("<I", payload, off)[0]
        base = off * 8 + SKIN_BIT
        v = 0
        for k in range(3):
            b = base + k
            v |= ((payload[b // 8] >> (b % 8)) & 1) << k
        tone_by_gpid[gpid] = v

    n_bin = 0
    for pid, gpid in db.execute(
            "SELECT id, game_pid FROM players WHERE is_custom=0 AND game_pid IS NOT NULL"):
        tone = tone_by_gpid.get(gpid)
        if tone and 1 <= tone <= 6:
            db.execute("INSERT INTO player_appearance(player_id,skin_tone,source) "
                       "VALUES(?,?,'bin') ON CONFLICT(player_id) DO NOTHING", (pid, tone))
            n_bin += 1
    print(f"natives from bin: {n_bin:,}")

    # imported players from their own portraits
    n_port = skipped = 0
    for pid, path in db.execute(
            "SELECT id, portrait_path FROM players WHERE portrait_path IS NOT NULL "
            "AND id NOT IN (SELECT player_id FROM player_appearance)"):
        if not path or not os.path.exists(path):
            continue
        try:
            lum = face_luminance(path)
        except Exception:
            skipped += 1
            continue
        if lum is None:
            skipped += 1
            continue
        db.execute("INSERT INTO player_appearance(player_id,skin_tone,source) "
                   "VALUES(?,?,'portrait') ON CONFLICT(player_id) DO NOTHING",
                   (pid, classify(lum)))
        n_port += 1
        if n_port % 2000 == 0:
            print(f"  …{n_port:,} portraits sampled")
            db.commit()
    db.commit()
    print(f"from portraits: {n_port:,} (skipped {skipped})")
    for row in db.execute("SELECT source, skin_tone, COUNT(*) FROM player_appearance "
                          "GROUP BY source, skin_tone ORDER BY source, skin_tone"):
        print(" ", row)
    return 0


if __name__ == "__main__":
    sys.exit(main())

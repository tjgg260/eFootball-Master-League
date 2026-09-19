#!/usr/bin/env python3
"""
pesdb_locate.py — find which bits of a record hold a known quantity, by brute force.

Every field in Player.bin that anyone has ever decoded was found the same way: guess a bit
window, read it, see whether it reproduces a column of the editor's 42,369-player export.
This does that exhaustively instead of one guess at a time - every offset 0..nbits, every
width 1..W, scored against a target column, best windows reported.

Two scoring modes, because the targets come in two shapes:

    numeric      exact-match rate of (window value + bias) against the column, with the bias
                 chosen automatically from the most common difference. Abilities, height,
                 age and shirt numbers are all found this way.
    categorical  purity: group rows by window value, take the most common label in each
                 group, and report the fraction of rows that agree. A perfect enum scores
                 1.000 with as many groups as the column has labels.

Purity alone is a trap when one label dominates - 97.6% of players have max_level 1, so ANY
window "predicts" it at 0.976. Every score is therefore reported against the baseline (the
majority-class rate), and the ranking uses the lift over that baseline, not the raw score.

Usage
    python tools/pesdb_locate.py --csv <export.csv> --table <Player.bin> --stride 400 \
        --column max_level --mode numeric --top 10
    python tools/pesdb_locate.py ... --column position --mode categorical --width 6
"""
from __future__ import annotations

import argparse
import csv
import io
import struct
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
import wesys  # noqa: E402


def load_records(path: Path, stride: int) -> dict[int, bytes]:
    data = path.read_bytes()
    if len(data) >= 16 and data[3:8] == b"WESYS":
        data = wesys.unpack_wesys_payload(data)
    return {
        struct.unpack_from("<Q", data, i + 8)[0]: data[i : i + stride]
        for i in range(0, len(data), stride)
    }


def bits_of(recs: list[bytes], stride: int) -> np.ndarray:
    arr = np.frombuffer(b"".join(recs), np.uint8).reshape(len(recs), stride)
    return np.unpackbits(arr, axis=1, bitorder="little")


def windows(B: np.ndarray, width: int) -> np.ndarray:
    """All little-endian `width`-bit reads, one column per bit offset. Offsets that would run
    past the end of the record are filled from wrapped bits and must be ignored by the caller."""
    n, nb = B.shape
    V = np.zeros((n, nb), dtype=np.int64)
    for i in range(width):
        V[:, : nb - i] += B[:, i:].astype(np.int64) << i
    return V


def score_numeric(V: np.ndarray, target: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Best exact-match rate per offset, and the bias that achieves it."""
    n, nb = V.shape
    best = np.zeros(nb)
    bias_out = np.zeros(nb, dtype=np.int64)
    t = target[valid]
    for o in range(nb):
        v = V[valid, o]
        diffs = Counter((t - v).tolist())
        if not diffs:
            continue
        bias, _ = diffs.most_common(1)[0]
        best[o] = float(((v + bias) == t).mean())
        bias_out[o] = bias
    return best, bias_out


def score_categorical(V: np.ndarray, y: np.ndarray, n_lab: int, valid: np.ndarray, width: int):
    """Purity per offset, plus the number of distinct window values used."""
    nb = V.shape[1]
    purity = np.zeros(nb)
    groups = np.zeros(nb, dtype=np.int64)
    yv = y[valid]
    nv = yv.size
    span = 1 << width
    for o in range(nb):
        v = V[valid, o]
        key = v * n_lab + yv
        counts = np.bincount(key, minlength=span * n_lab).reshape(span, n_lab)
        purity[o] = counts.max(axis=1).sum() / nv
        groups[o] = int((counts.sum(axis=1) > 0).sum())
    return purity, groups


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--table", required=True)
    ap.add_argument("--stride", type=int, required=True)
    ap.add_argument("--column", required=True)
    ap.add_argument("--mode", choices=["numeric", "categorical"], required=True)
    ap.add_argument("--width", type=int, default=8, help="max field width to try")
    ap.add_argument("--min-width", type=int, default=1)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--variant-cut", type=int, default=2**31,
                    help="ignore PIDs at or above this (variant cards store things differently)")
    a = ap.parse_args()

    rows = list(csv.DictReader(io.StringIO(Path(a.csv).read_bytes().decode("utf-8-sig"))))
    CSV = {int(r["player_id"]): r for r in rows if r.get("player_id", "").isdigit()}
    R = load_records(Path(a.table), a.stride)
    pids = sorted(p for p in R if p in CSV and p < a.variant_cut)
    if not pids:
        print("no players joined")
        return 1
    B = bits_of([R[p] for p in pids], a.stride)
    raw = [CSV[p].get(a.column, "") for p in pids]
    print(f"{len(pids)} players joined; column {a.column!r}")

    if a.mode == "numeric":
        valid = np.array([s.strip().lstrip("-").isdigit() for s in raw])
        target = np.array([int(s) if v else 0 for s, v in zip(raw, valid)], dtype=np.int64)
        print(f"  {valid.sum()} rows have a numeric value; range {target[valid].min()}..{target[valid].max()}")
        base = Counter(target[valid].tolist()).most_common(1)[0][1] / valid.sum()
    else:
        labels = sorted(set(raw))
        lab_idx = {s: i for i, s in enumerate(labels)}
        y = np.array([lab_idx[s] for s in raw], dtype=np.int64)
        valid = np.array([s != "" for s in raw])
        y = np.where(valid, y, 0)
        print(f"  {valid.sum()} labelled rows; {len(labels)} distinct labels")
        base = Counter(np.array(raw)[valid].tolist()).most_common(1)[0][1] / valid.sum()
    print(f"  majority-class baseline = {base:.4f}  (a window must beat this to mean anything)\n")

    results = []
    for w in range(a.min_width, a.width + 1):
        V = windows(B, w)
        limit = a.stride * 8 - w + 1
        if a.mode == "numeric":
            s, bias = score_numeric(V[:, :limit], target, valid)
            for o in range(limit):
                results.append((s[o] - base, s[o], o, w, int(bias[o]), None))
        else:
            s, g = score_categorical(V[:, :limit], y, len(labels), valid, w)
            for o in range(limit):
                results.append((s[o] - base, s[o], o, w, None, int(g[o])))

    results.sort(reverse=True)
    print(f"{'bit':>6} {'width':>6} {'score':>8} {'lift':>8}  detail")
    seen = set()
    shown = 0
    for lift, s, o, w, bias, g in results:
        # Suppress near-duplicates: a good field also scores well at neighbouring widths.
        key = (o, w)
        if any((o, ww) in seen for ww in range(w - 2, w + 3)):
            continue
        seen.add(key)
        detail = f"bias={bias:+d}" if bias is not None else f"groups={g}"
        print(f"{o:>6} {w:>6} {s:>8.4f} {lift:>+8.4f}  {detail}")
        shown += 1
        if shown >= a.top:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

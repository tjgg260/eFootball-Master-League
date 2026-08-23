#!/usr/bin/env python3
"""
build_faces.py — space-efficient real faces for the world DB from the sortitoutsi cutout megapack.

We NEVER extract the whole 16GB pack. Instead:
  plan     -> find the faces we actually use (player UIDs that exist in the pack), write an
              extraction list + a uid->player_id map. Skips @2x retina variants.
  convert  -> after 7-Zip extracts that list, downscale each to 180px, encode WebP (with alpha so
              cutouts stay transparent), write facepack/webp/face_<uid>.webp, point real_face_path
              at it, and delete the transient PNG. ~28KB PNG -> ~5KB WebP, ~200k faces -> ~1GB.

    python tools/build_faces.py plan
    # then (bash):  7z e <rar> @scratchpad/face_extract_list.txt -o<tmp> -y
    python tools/build_faces.py convert --src <tmp>
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
SCRATCH = REPO / "scratchpad"
WEBP_DIR = REPO / "facepack" / "webp"
PACK_UIDS = REPO / "scratchpad_pack_uids.txt"
LIST_FILE = SCRATCH / "face_extract_list.txt"
MAP_FILE = SCRATCH / "face_uid_map.json"
SIZE = 180
QUALITY = 82


def player_uid_map(con) -> dict[int, list[int]]:
    """uid -> [player_ids] that should wear face_<uid>. net-new = id-1e10; plus any player already
    pointing at a face_<uid> path (natives/overlap)."""
    m: dict[int, list[int]] = {}
    for (pid,) in con.execute("SELECT id FROM players WHERE id>=10000000000"):
        m.setdefault(pid - 10_000_000_000, []).append(pid)
    for pid, fp in con.execute("SELECT id, real_face_path FROM players "
                               "WHERE real_face_path LIKE '%face_%'"):
        mt = re.search(r"face_(\d+)", fp or "")
        if mt:
            m.setdefault(int(mt.group(1)), []).append(pid)
    return m


def plan() -> int:
    con = sqlite3.connect(DB)
    pack = {int(x) for x in PACK_UIDS.read_text().split() if x.strip().isdigit()}
    umap = player_uid_map(con)
    matched = sorted(set(umap) & pack)
    SCRATCH.mkdir(exist_ok=True)
    with open(LIST_FILE, "w", encoding="utf-8") as f:
        for uid in matched:
            f.write(f"sortitoutsi/faces/face_{uid}.png\n")
    MAP_FILE.write_text(json.dumps({str(u): umap[u] for u in matched}))
    print(f"pack faces: {len(pack):,} | player uids: {len(umap):,} | MATCHED: {len(matched):,}")
    print(f"players that will get a face: {sum(len(umap[u]) for u in matched):,}")
    print(f"extraction list -> {LIST_FILE}")
    return 0


def convert(src: Path) -> int:
    from PIL import Image
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    umap = {int(k): v for k, v in json.loads(MAP_FILE.read_text()).items()}
    WEBP_DIR.mkdir(parents=True, exist_ok=True)
    done = skipped = 0
    updates = []
    for uid, pids in umap.items():
        png = src / f"face_{uid}.png"
        if not png.exists():
            skipped += 1
            continue
        out = WEBP_DIR / f"face_{uid}.webp"
        try:
            if not out.exists():
                im = Image.open(png).convert("RGBA")
                im.thumbnail((SIZE, SIZE), Image.LANCZOS)
                im.save(out, "WEBP", quality=QUALITY, method=4)
            for pid in pids:
                updates.append((str(out), pid))
            png.unlink(missing_ok=True)
            done += 1
        except Exception as e:  # noqa: BLE001
            print(f"  {uid}: {e}")
            skipped += 1
        if done % 20000 == 0 and done:
            print(f"  ...{done:,} converted")
    con.execute("BEGIN")
    con.executemany("UPDATE players SET real_face_path=? WHERE id=?", updates)
    con.commit()
    size_mb = sum(p.stat().st_size for p in WEBP_DIR.glob('*.webp')) / 1e6
    print(f"converted {done:,} faces ({skipped:,} skipped), linked {len(updates):,} players.")
    print(f"webp store: {size_mb:,.0f} MB in {WEBP_DIR}")
    return 0


def auto() -> int:
    """Batched extract -> convert -> delete, so 7z never chokes on a 200k-entry listfile and the
    transient PNGs never exceed one batch (~200MB). ~25 batches for the full set."""
    import subprocess
    from PIL import Image
    SEVENZ = r"C:\Program Files\7-Zip\7z.exe"
    RAR = REPO / "sortitoutsi_cutout_megapack_2026.08.rar"
    umap = {int(k): v for k, v in json.loads(MAP_FILE.read_text()).items()}
    uids = sorted(umap)
    tmp = SCRATCH / "faces_tmp"
    batch_list = SCRATCH / "batch_list.txt"
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    WEBP_DIR.mkdir(parents=True, exist_ok=True)
    BATCH, done = 8000, 0
    for start in range(0, len(uids), BATCH):
        chunk = uids[start:start + BATCH]
        # Resume fast-path: if every face in this batch is already converted, just (re)link — no
        # slow 7z extraction. Makes resuming an interrupted run near-instant for done batches.
        if all((WEBP_DIR / f"face_{u}.webp").exists() for u in chunk):
            updates = [(str(WEBP_DIR / f"face_{u}.webp"), pid) for u in chunk for pid in umap[u]]
            con.execute("BEGIN")
            con.executemany("UPDATE players SET real_face_path=? WHERE id=?", updates)
            con.commit()
            done += len(chunk)
            print(f"  batch {start // BATCH + 1}/{(len(uids) + BATCH - 1) // BATCH}: cached", flush=True)
            continue
        if tmp.exists():
            for p in tmp.glob("*.png"):
                p.unlink()
        tmp.mkdir(exist_ok=True)
        batch_list.write_text("".join(f"sortitoutsi/faces/face_{u}.png\n" for u in chunk))
        subprocess.run([SEVENZ, "e", str(RAR), f"@{batch_list}", f"-o{tmp}", "-y"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        updates = []
        for u in chunk:
            png = tmp / f"face_{u}.png"
            if not png.exists():
                continue
            out = WEBP_DIR / f"face_{u}.webp"
            try:
                if not out.exists():
                    im = Image.open(png).convert("RGBA")
                    im.thumbnail((SIZE, SIZE), Image.LANCZOS)
                    im.save(out, "WEBP", quality=QUALITY, method=4)
                for pid in umap[u]:
                    updates.append((str(out), pid))
                png.unlink(missing_ok=True)
                done += 1
            except Exception as e:  # noqa: BLE001
                print(f"  {u}: {e}")
        con.execute("BEGIN")
        con.executemany("UPDATE players SET real_face_path=? WHERE id=?", updates)
        con.commit()
        print(f"  batch {start // BATCH + 1}/{(len(uids) + BATCH - 1) // BATCH}: {done:,} faces linked",
              flush=True)
    size_mb = sum(p.stat().st_size for p in WEBP_DIR.glob('*.webp')) / 1e6
    print(f"DONE: {done:,} faces -> {size_mb:,.0f} MB in {WEBP_DIR}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    sub.add_parser("auto")
    cv = sub.add_parser("convert")
    cv.add_argument("--src", required=True, type=Path)
    args = ap.parse_args()
    if args.cmd == "plan":
        return plan()
    if args.cmd == "auto":
        return auto()
    return convert(args.src)


if __name__ == "__main__":
    raise SystemExit(main())

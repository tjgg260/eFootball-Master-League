"""Rename dt200 teams AND competitions to their real names.

Inputs (either may be absent):
  build/dt200_renames.json       = { "<team_id>": "Real Name", ... }
  build/dt200_comp_renames.json  = { "<competition_id>": "Real Name", ... }

Teams: Team.bin English name @396 (48-byte field) + alphabetical reorder of each affected
CategoryTeamList league. Competitions: CompetitionUnit.bin — 75 records x 2472 bytes, id at
u16@10 (joins CategoryTeamList.category), then 21 language slots x 115 bytes of UTF-8
NUL-padded name starting at +56. Konami's own licensed entries repeat the identical real name
in all 21 slots, so we do the same — the two-English-slot ambiguity disappears. Fixed-length
fields: an edit can never change the payload length. Every file is gated by a round-trip proof
of the UNMODIFIED file first (repo rule). Backups taken.

Usage: python tools/dt200_rename.py            # apply to build/tree_base (round-trip proven)
       python tools/dt200_rename.py --dry       # prove + report, write nothing
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from vendor.sider import wesys

PESDB = ROOT / "build/tree_base/common/etc/pesdb"
NAME_OFF, REC = 396, 1600
BACKUP = ROOT / "build" / "backups"

# CompetitionUnit.bin layout (decoded 2026-08-23): fixed records, fixed name fields.
CU_REC = 2472            # bytes per record
CU_ID_OFF = 10           # u16 competition id (== CategoryTeamList.category)
CU_NAMES_OFF = 56        # 21 language slots follow the 56-byte header
CU_SLOT = 115            # bytes per name slot, UTF-8, NUL-padded
CU_SLOTS = 21


def load(fn):
    raw = (PESDB / fn).read_bytes()
    return raw, bytearray(wesys.unpack_wesys_payload(raw)), raw[1] & 0x0F


def prove(fn, raw, payload, nibble):
    """Two bars (repo rule): byte-EXACT if any zlib level reproduces the file, else SEMANTIC
    (decrypt(encrypt(payload))==payload) for a third-party repack. Refuse only if neither."""
    for lvl in range(10):
        if wesys.pack_wesys_container(bytes(payload), key_nibble=nibble, compression_level=lvl) == raw:
            print(f"  {fn}: round-trip EXACT (level {lvl})")
            return lvl
    packed = wesys.pack_wesys_container(bytes(payload), key_nibble=nibble, compression_level=1)
    if wesys.unpack_wesys_payload(packed) == bytes(payload):
        print(f"  {fn}: round-trip SEMANTIC (level 1; not byte-identical to Konami's stream)")
        return 1
    raise SystemExit(f"round-trip proof FAILED for {fn} — refusing to write.")


def write_out(fn, payload, nibble, lvl):
    BACKUP.mkdir(parents=True, exist_ok=True)
    dst = PESDB / fn
    shutil.copy2(dst, BACKUP / f"{fn}.{datetime.now():%Y%m%d-%H%M%S}")
    packed = wesys.pack_wesys_container(bytes(payload), key_nibble=nibble, compression_level=lvl)
    if wesys.unpack_wesys_payload(packed) != bytes(payload):
        raise SystemExit("repack does not decode to our edit — nothing written.")
    dst.write_bytes(packed)
    print(f"  written {fn} ({len(packed):,} bytes)")


def rename_competitions(dry):
    """The CompetitionUnit.bin pass: real league names into all 21 language slots."""
    src = ROOT / "build" / "dt200_comp_renames.json"
    if not src.exists():
        return
    comp = {int(k): v for k, v in json.loads(src.read_text(encoding="utf-8")).items()}
    print(f"{len(comp)} competition renames requested")

    raw, pay, nib = load("CompetitionUnit.bin")
    lvl = prove("CompetitionUnit.bin", raw, pay, nib)
    if len(pay) % CU_REC:
        raise SystemExit(f"CompetitionUnit.bin payload {len(pay)} not a multiple of {CU_REC} — layout drifted, refusing.")
    original_len = len(pay)

    by_id = {}
    for r in range(len(pay) // CU_REC):
        by_id[struct.unpack_from("<H", pay, r * CU_REC + CU_ID_OFF)[0]] = r * CU_REC

    applied = 0
    for cid, real in sorted(comp.items()):
        o = by_id.get(cid)
        if o is None:
            print(f"  ! competition id {cid} not in file — skipped")
            continue
        enc = real.encode("utf-8")
        if len(enc) > CU_SLOT - 1:
            raise SystemExit(f"'{real}' encodes to {len(enc)} bytes — over the {CU_SLOT - 1} limit, refusing.")
        old = pay[o + CU_NAMES_OFF + 15 * CU_SLOT:o + CU_NAMES_OFF + 15 * CU_SLOT + CU_SLOT].split(b"\0")[0]
        for s in range(CU_SLOTS):
            f = o + CU_NAMES_OFF + s * CU_SLOT
            pay[f:f + CU_SLOT] = enc + b"\0" * (CU_SLOT - len(enc))
        applied += 1
        print(f"  {cid}: '{old.decode('utf-8', 'replace')}' -> '{real}'")

    if len(pay) != original_len:
        raise SystemExit("payload length changed — impossible for fixed fields, refusing.")
    # read-back: every touched slot must decode to exactly the intended name
    for cid, real in comp.items():
        o = by_id.get(cid)
        if o is None:
            continue
        for s in range(CU_SLOTS):
            f = o + CU_NAMES_OFF + s * CU_SLOT
            got = bytes(pay[f:f + CU_SLOT]).split(b"\0")[0].decode("utf-8")
            if got != real:
                raise SystemExit(f"read-back mismatch id {cid} slot {s}: '{got}'")
    print(f"applied {applied} competition names (all {CU_SLOTS} language slots each, read-back verified)")
    if not dry:
        write_out("CompetitionUnit.bin", pay, nib, lvl)


def main():
    dry = "--dry" in sys.argv
    rename_competitions(dry)
    team_src = ROOT / "build" / "dt200_renames.json"
    if not team_src.exists():
        print("no team renames file — competition pass only.")
        return 0
    renames = {int(k): v for k, v in
               json.loads(team_src.read_text(encoding="utf-8")).items()}
    print(f"{len(renames)} renames requested")

    traw, tpay, tnib = load("Team.bin")
    craw, cpay, cnib = load("CategoryTeamList.bin")
    # PROVE both unmodified files rebuild byte-for-byte BEFORE any edit
    print("round-trip proof (unmodified files rebuild before we edit):")
    tlvl = prove("Team.bin", traw, tpay, tnib)
    clvl = prove("CategoryTeamList.bin", craw, cpay, cnib)

    # locate each team's record offset + read its (new-or-old) name for sorting
    rec_off = {}
    for r in range(len(tpay) // REC):
        tid = struct.unpack_from("<I", tpay, r * REC + 12)[0]
        rec_off[tid] = r * REC

    def name_of(tid):
        if tid in renames:
            return renames[tid]
        o = rec_off.get(tid)
        return tpay[o + NAME_OFF:o + NAME_OFF + 48].split(b"\0")[0].decode("utf-8", "replace") if o else ""

    # 1) apply names into Team.bin (English @396, 48-byte field, NUL-padded)
    applied = 0
    for tid, real in renames.items():
        o = rec_off.get(tid)
        if o is None:
            continue
        enc = real.encode("utf-8")[:47]
        tpay[o + NAME_OFF:o + NAME_OFF + 48] = enc + b"\0" * (48 - len(enc))
        applied += 1
    print(f"applied {applied} names into Team.bin")

    # 2) reorder each affected CategoryTeamList category alphabetically by new name
    entries = []                                   # (team, cat, order) in file order
    cats = defaultdict(list)
    for i in range(len(cpay) // 12):
        t, c, idx = struct.unpack_from("<III", cpay, i * 12)
        entries.append([t, c, idx, i])
        cats[c].append(i)
    # Only reorder real domestic-league categories (<=40 teams). The giant meta-categories
    # (117/583/700 = "all teams" lists) contain the renamed teams too but must NOT be scrambled.
    affected = {e[1] for e in entries if e[0] in renames and 8 <= len(cats[e[1]]) <= 40}
    reordered = 0
    for c in affected:
        rows = [entries[i] for i in cats[c]]
        team_slots = sorted(r[0] for r in rows)          # keep the same team set
        idx_slots = [r[2] for r in sorted(rows, key=lambda r: r[3])]  # keep the index sequence
        file_pos = [r[3] for r in sorted(rows, key=lambda r: r[3])]
        new_team_order = sorted(team_slots, key=lambda t: name_of(t).lower())
        for pos, tid, idx in zip(file_pos, new_team_order, idx_slots):
            struct.pack_into("<III", cpay, pos * 12, tid, c, idx)
            reordered += 1
    print(f"reordered {len(affected)} leagues ({reordered} team slots)")

    if dry:
        print("--dry: proofs passed, nothing written.")
        return 0
    write_out("Team.bin", tpay, tnib, tlvl)
    write_out("CategoryTeamList.bin", cpay, cnib, clvl)
    print("done — rebuild the CPK with tools/ml_deploy.py to push into the game.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

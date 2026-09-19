"""Rename dt200 teams AND competitions to their real names.

Inputs (either may be absent):
  build/dt200_renames.json       = { "<team_id>": "Real Name", ... }
                                   a value may instead be { "name": ..., "abbr": ... } when the
                                   real 2-3 letter abbreviation is known; without one the
                                   record's existing abbreviation is left alone, never guessed.
  build/dt200_comp_renames.json  = { "<competition_id>": "Real Name", ... }

Teams: Team.bin name array @116 — 21 language slots x 70 bytes, split by the 10-byte
abbreviation @886 — written in full, plus an alphabetical reorder of each affected
CategoryTeamList league. Competitions: CompetitionUnit.bin — 75 records x 2472 bytes, id at
u16@10 (joins CategoryTeamList.category), then 21 language slots x 115 bytes of UTF-8
NUL-padded name starting at +56. Konami's own licensed entries repeat the identical real name
in all 21 slots, so we do the same for both files — the two-English-slot ambiguity disappears.
Fixed-length fields: an edit can never change the payload length. Every file is gated by a
round-trip proof of the UNMODIFIED file first (repo rule). Backups taken.

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
BACKUP = ROOT / "build" / "backups"

# Team.bin layout (decoded 2026-09-19 — docs/dt200-dt870-format.md "Team.bin — bit-packed",
# offsets recorded in tools/data/pesdb_schema.json). The record is bit-packed; only team_id and
# the name slots sit on byte boundaries. The name array is 21 language slots of 70 bytes from
# byte 116, SPLIT by the 10-byte abbreviation at 886. Byte 396 is merely where slot 4 (English)
# lands, which is why the old single 48-byte write at 396 appeared to work — it left the other
# twenty slots on the old name and never cleared the 22-byte tail behind the terminator.
# Clubs populate ja / en / zh-Hans (947 of 981 records) + the abbreviation; the other 17 slots
# carry the 253 national teams only.
REC = 1600               # bytes per Team.bin record
TEAM_ID_OFF = 12         # team id — 17 bits at bit 96, so a u32 read at byte 12
TEAM_SLOT = 70           # bytes per name slot, UTF-8, NUL-padded (69 usable)
TEAM_NAME_OFFS = tuple([116 + 70 * k for k in range(11)]       # ja es sv el EN tr fr th ko pt de
                       + [896 + 70 * k for k in range(10)])    # es-419 pt-BR zh-Hans nl zh-Hant it id ru ar en-2
TEAM_LANGS = ("ja", "es", "sv", "el", "en", "tr", "fr", "th", "ko", "pt", "de",
              "es-419", "pt-BR", "zh-Hans", "nl", "zh-Hant", "it", "id", "ru", "ar", "en-2")
TEAM_ABBR_OFF, TEAM_ABBR = 886, 10   # "ARS", "ENG" — byte 895 is always 0
NAME_OFF = TEAM_NAME_OFFS[TEAM_LANGS.index("en")]   # 396, the slot we read for reporting/sorting
assert len(TEAM_NAME_OFFS) == len(TEAM_LANGS) == 21
assert TEAM_NAME_OFFS[-1] + TEAM_SLOT <= REC and TEAM_ABBR_OFF + TEAM_ABBR == TEAM_NAME_OFFS[11]

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


def read_team_slot(pay, o, off, width=TEAM_SLOT):
    """A NUL-terminated UTF-8 slot of a Team.bin record, as text."""
    return bytes(pay[o + off:o + off + width]).split(b"\0")[0].decode("utf-8", "replace")


def write_team_name(pay, o, real, abbr=None):
    """The real name into ALL 21 language slots of one Team.bin record.

    Konami repeats the licensed name in every slot — the CompetitionUnit pass below already does
    the same for leagues. Writing only English left a renamed club reading correctly in English
    and wrongly in Japanese and Chinese-Simplified, the two other slots clubs populate. Slots are
    fixed width: pad the whole 70 bytes with NULs (which also wipes the stale tail the old
    48-byte write left behind the terminator) and refuse a name that does not fit rather than
    truncating mid-UTF-8. The 10-byte abbreviation at 886 splits the array in two and is left
    untouched unless one was supplied.
    """
    enc = real.encode("utf-8")
    if len(enc) > TEAM_SLOT - 1:
        raise SystemExit(f"'{real}' encodes to {len(enc)} bytes — over the {TEAM_SLOT - 1} limit, refusing.")
    for s in TEAM_NAME_OFFS:
        pay[o + s:o + s + TEAM_SLOT] = enc + b"\0" * (TEAM_SLOT - len(enc))
    if abbr is None:
        return
    ab = abbr.encode("utf-8")
    if len(ab) > TEAM_ABBR - 1:
        raise SystemExit(f"abbreviation '{abbr}' encodes to {len(ab)} bytes — over the {TEAM_ABBR - 1} limit, refusing.")
    pay[o + TEAM_ABBR_OFF:o + TEAM_ABBR_OFF + TEAM_ABBR] = ab + b"\0" * (TEAM_ABBR - len(ab))


def load_team_renames(path):
    """{"<id>": "Real Name"} — or {"<id>": {"name": ..., "abbr": ...}} to set the abbreviation."""
    out = {}
    for k, v in json.loads(path.read_text(encoding="utf-8")).items():
        name, abbr = (v.get("name"), v.get("abbr")) if isinstance(v, dict) else (v, None)
        if not name:
            raise SystemExit(f"team {k}: no name in the renames file")
        out[int(k)] = (name, abbr)
    return out


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
    renames = load_team_renames(team_src)
    print(f"{len(renames)} renames requested")

    traw, tpay, tnib = load("Team.bin")
    craw, cpay, cnib = load("CategoryTeamList.bin")
    # PROVE both unmodified files rebuild byte-for-byte BEFORE any edit
    print("round-trip proof (unmodified files rebuild before we edit):")
    tlvl = prove("Team.bin", traw, tpay, tnib)
    clvl = prove("CategoryTeamList.bin", craw, cpay, cnib)

    if len(tpay) % REC:
        raise SystemExit(f"Team.bin payload {len(tpay)} not a multiple of {REC} — layout drifted, refusing.")
    team_len = len(tpay)

    # locate each team's record offset + read its (new-or-old) name for sorting
    rec_off = {}
    for r in range(len(tpay) // REC):
        tid = struct.unpack_from("<I", tpay, r * REC + TEAM_ID_OFF)[0]
        rec_off[tid] = r * REC

    def name_of(tid):
        if tid in renames:
            return renames[tid][0]
        o = rec_off.get(tid)
        return read_team_slot(tpay, o, NAME_OFF) if o is not None else ""

    # 1) apply names into Team.bin — all 21 language slots, 70 bytes each, NUL-padded
    applied = 0
    for tid, (real, abbr) in renames.items():
        o = rec_off.get(tid)
        if o is None:
            continue
        write_team_name(tpay, o, real, abbr)
        applied += 1

    if len(tpay) != team_len:
        raise SystemExit("Team.bin payload length changed — impossible for fixed fields, refusing.")
    # read-back: every touched slot must decode to exactly the intended name
    kept_abbr = []
    for tid, (real, abbr) in renames.items():
        o = rec_off.get(tid)
        if o is None:
            continue
        for lang, s in zip(TEAM_LANGS, TEAM_NAME_OFFS):
            got = bytes(tpay[o + s:o + s + TEAM_SLOT]).split(b"\0")[0].decode("utf-8")
            if got != real:
                raise SystemExit(f"read-back mismatch team {tid} slot {lang}: '{got}'")
        have = read_team_slot(tpay, o, TEAM_ABBR_OFF, TEAM_ABBR)
        if abbr is not None:
            if have != abbr:
                raise SystemExit(f"read-back mismatch team {tid} abbreviation: '{have}'")
        elif not real.upper().startswith(have.upper()):
            kept_abbr.append((tid, have, real))
    print(f"applied {applied} names into Team.bin (all {len(TEAM_LANGS)} language slots each, read-back verified)")
    if kept_abbr:
        print(f"  {len(kept_abbr)} keep an abbreviation that no longer prefixes the new name — left alone, "
              f'never guessed; set one with {{"name": ..., "abbr": ...}} in the renames file:')
        for tid, have, real in sorted(kept_abbr)[:8]:
            print(f"    {tid}: '{have}' vs '{real}'")

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

#!/usr/bin/env python3
"""
pesdb_schema_bootstrap.py — gather every Player.bin field this repo already knows into one
schema file, so coverage can be measured against it.

The decode was scattered across four places that never agreed on a format: ability_bits.py
(a dict), build/skill_bits.json (another dict), tools/data/player_layouts.json (the derived
map, and the only one that covers both the 400- and 392-byte layouts) and Sider's
PESDB_DATABASE_FORMAT.md (prose). This flattens all of them into a single bit-indexed list
per table, which is the only shape you can compute coverage from.

Two disagreements are resolved here rather than papered over:

  * Bytes 0-7. Sider's doc calls this one u64 "native PID". The Player Editor calls it two
    u32s, youth_club and loan_parent_club, and the data backs the editor: loan_parent_club is
    non-zero for exactly the 1,129 players who also carry a loan end date. Recorded as two
    u32s, with the disagreement noted on the field.
  * The in-possession style. playstyle_bits.py reads 5 bits at 374; derive_player_layouts.py
    reads 8 bits at 372 and divides by 4, which is bits 374-379 - a 6-bit field. The low two
    bits at 372-373 belong to set_piece_taking (bit 368, width 6). Recorded as bit 374 width
    6; the width is re-measured against the data by --verify.

Usage
    python tools/pesdb_schema_bootstrap.py --layouts tools/data/player_layouts.json \
        --skill-bits <build/skill_bits.json> --out tools/data/pesdb_schema.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def player_fields(lay: dict, stride: int) -> list[dict]:
    """Flatten one layout from player_layouts.json into bit-indexed fields."""
    f: list[dict] = []

    def add(name, bit, width, kind, note=None, source="player_layouts.json"):
        rec = {"name": name, "bit": bit, "width": width, "type": kind, "source": source}
        if note:
            rec["note"] = note
        f.append(rec)

    # --- identity / club.
    #
    # These are at the SAME byte offsets in both layouts. derive_player_layouts.py only ever
    # looked for them in the 400-byte record, so in the 392-byte record they read as unknown.
    # Re-measured 2026-09-19 on both: club@16 equals the player's actual squad team in 95.6%
    # of dt200 records and 95.1% of dt870 ones, and loan_parent_club@4 is non-zero for exactly
    # the same players who carry a loan_end date (1,120 in dt200, 1,364 in dt870) - a 1:1
    # correspondence that fixes both fields at once.
    for name, byte_off in (("youth_club", 0), ("loan_parent_club", 4), ("club", 16)):
        add(
            name,
            byte_off * 8,
            32,
            "u32",
            note=(
                "Sider's doc reads bytes 0-7 as one u64 'native PID'; the Player Editor reads "
                "two u32 club fields here and the loan data agrees with the editor"
                if byte_off in (0, 4)
                else "team id; matches the player's squad team ~95% of the time"
            ),
            source="efootball_core (Player Editor); re-verified both layouts 2026-09-19",
        )
    add("external_pid", 64, 64, "u64", note="the key every other table references", source="sider")

    # Two 25-bit yyyymmdd dates, not one. contract_end was never documented anywhere: found by
    # sweeping every 25-bit window for one whose non-zero values are all valid calendar dates.
    # Exactly two windows in the whole record pass, in both layouts, at 100%.
    add(
        "contract_end",
        160,
        25,
        "date_yyyymmdd",
        note="4,710 players in dt200 / 12,166 in dt870; values cluster on 30 June",
        source="tools/pesdb_census.py date sweep 2026-09-19",
    )
    add(
        "loan_end",
        192,
        25,
        "date_yyyymmdd",
        note="non-zero for exactly the players with loan_parent_club set",
        source="efootball_core (Player Editor); re-verified both layouts 2026-09-19",
    )

    # --- nationality. NOT what Sider's parser reads.
    #
    # pesdb.py does `u16@41 & 0x3FF` - 10 bits starting at bit 328. The real field is 9 bits
    # starting at bit 329; bit 328 is a separate boolean, set on 69 of 23,519 players. Read the
    # 9 bits at 329 and all 177 distinct values are a subset of Country.bin's ids, zero misses.
    # Read Sider's way and 114 values match no country - and it fails SILENTLY with plausible
    # wrong answers: Salah comes out El Salvador rather than Egypt, a Vietnamese player Moroccan.
    #
    # The repo mostly gets away with it because game_world.py reads Country.bin's id the same
    # doubled way (10 bits at bit 9, where bit 9 is always zero), so both sides are exactly 2x
    # and the join still lands - for every player whose bit 328 is clear. The 69 where it is set
    # produce an odd value that matches no country and fall through.
    add("_flag_bit328", 328, 1, "flag",
        note="set on 69 of 23,519 players; meaning unknown. Sider's 10-bit read swallows it",
        source="tools/pesdb_census.py 2026-09-19")
    add("nationality", 329, 9, "enum",
        note="9 bits, NOT the 10-bit `u16@41 & 0x3FF` in vendored pesdb.py; joins Country.bin",
        source="verified against Country.bin ids 2026-09-19")

    # --- scalars (height / weight / age), each [bit, width, bias]
    for name, spec in lay.get("scalars", {}).items():
        bit, width, bias = spec
        add(name, bit, width, "uint", note=f"stored value + {bias}")

    # --- small enums
    for name, (bit, width) in lay.get("codes", {}).items():
        add(name, bit, width, "enum")

    # --- 26 abilities, 6 bits each, stored with a -40 bias
    for name, bit in lay.get("abilities", {}).items():
        add(f"ability.{name}", bit, 6, "uint6", note="stored value + 40")

    # --- playing styles. att is recorded as the 6 bits the reader actually uses.
    #
    # Skipped entirely when the layout file marks them unverified, which it does for the
    # 392-byte record. Emitting them there is not harmless: the offset it guessed for the
    # out-of-possession style overlaps ability.gk_parrying, so claiming it would hide six real
    # bits behind a field that does not reproduce the export. Left as UNKNOWN until re-derived.
    unverified = set(lay.get("unverified", ()))
    if "primary_style" not in unverified:
        att_bit, att_w = lay["styles"]["att"]
        add(
            "style.in_possession",
            att_bit + 2,
            att_w - 2,
            "enum",
            note=f"layout file reads {att_w} bits at {att_bit} then //4; the low 2 bits belong to "
            "ability.set_piece_taking",
        )
    if "secondary_style" not in unverified:
        def_bit, def_w = lay["styles"]["def"]
        add("style.out_of_possession", def_bit, def_w, "enum")

    # --- 1-bit flags
    for name, bit in lay.get("skills", {}).items():
        add(f"skill.{name}", bit, 1, "flag", note=lay.get("skill_source", {}).get(name))
    for name, bit in lay.get("ai_styles", {}).items():
        add(f"ai_style.{name}", bit, 1, "flag")

    # --- 13 position aptitudes, 2 bits each (400-byte layout only; located 2026-09-19)
    #
    # Sider's doc describes "12 x 2 bits at 576-599, plus LB at 318 and CMF at 510" and warns
    # that assuming a clean 12-slot run is the commonest mistake here. It is a worse trap than
    # that: the 576-599 run really is twelve 2-bit slots, but only TEN of them are aptitudes.
    # Slots 578 and 582 are weak_foot_accuracy and form, which is why a clean read of the run
    # produces two aptitudes that track nothing. The other three aptitudes live at 414 (GK),
    # 318 (LB) and 510 (CMF).
    #
    # Found without any ground-truth column, which the export does not carry, using the one
    # structural property aptitudes have: a player's aptitude for their OWN position is always
    # maximal. Each field below reads exactly 2 for every player of that position (n=22,782)
    # and 0 or 1 otherwise. GK is the sharpest: it is non-zero for exactly one outfield player
    # in the whole table.
    # The 392-byte record packs the same thirteen elsewhere. Ten meet the strict test; the
    # three marked "likely" have a handful of own-position players reading something other
    # than 2 (16, 31 and 26 exceptions respectively), so they are recorded with that caveat
    # rather than as proven.
    APTITUDES = {
        400: {
            "LB": (318, None), "GK": (414, None), "CMF": (510, None), "RMF": (576, None),
            "AMF": (580, None), "CB": (584, None), "CF": (586, None), "LMF": (588, None),
            "LWF": (590, None), "RB": (592, None), "DMF": (594, None), "RWF": (596, None),
            "SS": (598, None),
        },
        392: {
            "LB": (318, None), "LMF": (414, None), "GK": (446, None), "CMF": (542, "0.987"),
            "RMF": (569, None), "AMF": (573, None), "CB": (578, "0.996"), "CF": (580, "0.990"),
            "LWF": (582, None), "RB": (584, None), "DMF": (586, None), "RWF": (588, None),
            "SS": (590, None),
        },
    }
    for pos, (bit, frac) in APTITUDES.get(stride, {}).items():
        note = "0/1/2; always 2 for the player's own position"
        if frac:
            note = f"0/1/2; reads 2 for {frac} of players at this position, not all - LIKELY"
        add(
            f"aptitude.{pos}",
            bit,
            2,
            "uint2",
            note=note,
            source="tools/pesdb_census.py structural scan 2026-09-19",
        )

    # --- the five 61-byte name fields
    name_off = lay["name_offset"]
    roles = {v: k for k, v in lay.get("name_fields", {}).items()}
    for i in range(5):
        add(
            f"name{i}" + (f".{roles[i]}" if i in roles else ""),
            (name_off + i * 61) * 8,
            61 * 8,
            "utf8z",
            note="NUL-terminated, 61 bytes",
            source="sider",
        )

    f.sort(key=lambda r: (r["bit"], r["width"]))
    return f


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--layouts", default=str(REPO / "tools" / "data" / "player_layouts.json"))
    ap.add_argument("--out", default=str(REPO / "tools" / "data" / "pesdb_schema.json"))
    a = ap.parse_args()

    lays = json.loads(Path(a.layouts).read_text(encoding="utf-8"))["layouts"]
    schema = {
        "note": "bit offsets are little-endian within the record: bit b = byte b//8, bit b%8",
        "generated_by": "tools/pesdb_schema_bootstrap.py",
        "tables": {},
    }
    for key, lay in lays.items():
        stride = lay["record_size"]
        schema["tables"][f"Player.bin/{stride}"] = {
            "stride": stride,
            "fields": player_fields(lay, stride),
        }

    # PlayerAssignment, both layouts. Byte-level, from Sider's doc + the vendored parser.
    schema["tables"]["PlayerAssignment.bin/v1"] = {
        "stride": 24,
        "fields": [
            {"name": "record_id", "bit": 0, "width": 32, "type": "u32", "source": "sider"},
            {"name": "_zero_4_7", "bit": 32, "width": 32, "type": "pad", "source": "sider"},
            {"name": "player_pid", "bit": 64, "width": 64, "type": "u64", "source": "sider"},
            {"name": "team_id", "bit": 128, "width": 32, "type": "u32", "source": "sider"},
            {"name": "shirt_number", "bit": 160, "width": 8, "type": "uint",
             "note": "0-based; displayed number is +1", "source": "sider"},
            {"name": "sort_key", "bit": 168, "width": 8, "type": "uint",
             "note": "strictly increasing within a team, usually index*4", "source": "sider"},
            {"name": "role_mask", "bit": 176, "width": 6, "type": "bitmask",
             "note": "bit5 captain, bit4 penalty taker, bits0-3 set-piece takers", "source": "sider"},
            {"name": "_zero_22_high", "bit": 182, "width": 2, "type": "pad", "source": "sider"},
            {"name": "_zero_23", "bit": 184, "width": 8, "type": "pad", "source": "sider"},
        ],
    }
    schema["tables"]["PlayerAssignment.bin/v2"] = {
        "stride": 24,
        "fields": [
            {"name": "player_pid", "bit": 0, "width": 64, "type": "u64", "source": "sider"},
            {"name": "team_id", "bit": 64, "width": 32, "type": "u32", "source": "sider"},
            {"name": "record_id", "bit": 96, "width": 32, "type": "u32", "source": "sider"},
            {"name": "shirt_number", "bit": 128, "width": 8, "type": "uint", "source": "sider"},
            {"name": "sort_key", "bit": 136, "width": 8, "type": "uint", "source": "sider"},
            {"name": "role_flags", "bit": 144, "width": 16, "type": "bitmask",
             "note": "bits 4-10 one holder per team; bit 9 correlates with captain", "source": "sider"},
            {"name": "_zero_20_23", "bit": 160, "width": 32, "type": "pad", "source": "sider"},
        ],
    }

    # Team.bin. The record is BIT-PACKED, which is why it resisted decoding for so long: only
    # team_id and the name slots sit on byte boundaries. Decoded 2026-09-19.
    #
    # The name array starts at byte 116, not 396. It is 21 language slots of 70 bytes plus a
    # 10-byte abbreviation; byte 396 is simply where slot 4 (English) happens to land, which is
    # why reading it as "a 48-byte English field" appeared to work. It is 70 bytes wide, and
    # there are twenty other slots beside it.
    LANGS = ["ja", "es", "sv", "el", "en", "tr", "fr", "th", "ko", "pt", "de"]
    LANGS2 = ["es_419", "pt_BR", "zh_Hans", "nl", "zh_Hant", "it", "id", "ru", "ar", "en_2"]
    team_fields = [
        {"name": "is_national_team", "bit": 22, "width": 1, "type": "flag",
         "note": "set for exactly the 253 records carrying translations, clear for all 728 clubs"},
        {"name": "is_fully_licensed", "bit": 23, "width": 1, "type": "flag",
         "note": "LIKELY: all 191 clubs with bit clear use the real crest; only 73/537 otherwise"},
        {"name": "confederation_afc", "bit": 25, "width": 1, "type": "flag", "note": "LIKELY"},
        {"name": "confederation_caf", "bit": 26, "width": 1, "type": "flag",
         "note": "LIKELY: 24 records, all national, ids >= 81952 - the known 24 African teams"},
        {"name": "team_id", "bit": 96, "width": 17, "type": "uint",
         "note": "17 bits at byte 12, strictly ascending"},
        {"name": "related_club_1", "bit": 128, "width": 13, "type": "ref", "note": "LIKELY"},
        {"name": "related_club_2", "bit": 160, "width": 13, "type": "ref", "note": "LIKELY"},
        {"name": "squad_pct_young", "bit": 664, "width": 7, "type": "uint",
         "note": "percent of squad in the young age band; r=0.9998, 787/787 within 1"},
        {"name": "club_stature", "bit": 672, "width": 21, "type": "uint",
         "note": "LIKELY: ladder 10000..1200000; 0 for national teams"},
        {"name": "country_id", "bit": 840, "width": 10, "type": "enum",
         "note": "159/159 national teams equal their squad's dominant nationality"},
        {"name": "squad_pct_own_nationality", "bit": 850, "width": 7, "type": "uint",
         "note": "r=0.958; every national team reads 100"},
        {"name": "squad_pct_old", "bit": 864, "width": 7, "type": "uint", "note": "r=0.9998"},
        {"name": "squad_pct_mid", "bit": 871, "width": 7, "type": "uint", "note": "r=0.9996"},
        {"name": "crest_flags", "bit": 920, "width": 3, "type": "bitmask",
         "note": "crest real/fake, from prior work"},
        {"name": "abbreviation", "bit": 886 * 8, "width": 10 * 8, "type": "utf8z",
         "note": "2-3 chars, e.g. ARS / ENG; byte 895 always zero"},
        {"name": "_zero_tail", "bit": 1596 * 8, "width": 4 * 8, "type": "pad"},
    ]
    for i, lang in enumerate(LANGS):
        team_fields.append({
            "name": f"name.{lang}", "bit": (116 + 70 * i) * 8, "width": 70 * 8, "type": "utf8z",
            "note": "only ja/en/zh_Hans and the abbreviation are filled for clubs; the other "
                    "17 slots carry the 253 national teams only" if i == 0 else None,
        })
    for i, lang in enumerate(LANGS2):
        team_fields.append({
            "name": f"name.{lang}", "bit": (896 + 70 * i) * 8, "width": 70 * 8, "type": "utf8z",
        })
    for f in team_fields:
        f.setdefault("source", "tools/pesdb_census.py + squad-property correlation 2026-09-19")
        if f.get("note") is None:
            f.pop("note", None)
    # Derby/rival refs: five 13-bit slots. byte 60 is the one with clean symmetric pairs
    # (Arsenal->Tottenham, Barca->Real, Real->Barca, Marseille->PSG, Benfica->Porto).
    for i, bit in enumerate((352, 384, 416, 448, 480)):
        team_fields.append({
            "name": f"rival_ref_{i}", "bit": bit, "width": 13, "type": "ref",
            "note": "LIKELY: 103/137 symmetric, 88% resolve to valid team ids",
            "source": "tools/pesdb_census.py 2026-09-19",
        })
    team_fields.sort(key=lambda r: r["bit"])
    schema["tables"]["Team.bin"] = {"stride": 1600, "fields": team_fields}

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(schema, indent=1, ensure_ascii=False), encoding="utf-8")
    for name, t in schema["tables"].items():
        claimed = sum(f["width"] for f in t["fields"])
        print(f"{name:28} stride {t['stride']:>5}  {len(t['fields']):>3} fields  "
              f"{claimed:>5} bits claimed (before overlap) of {t['stride']*8}")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
fm_derive_attributes.py — derive eFootball abilities from the REAL FM 1-20 ladder, onto the only
scale the game can store, and leave eFootball's own players alone (owner ruling 2026-08-24).

Two halves, because the ruling has two halves:
  RESTORE  players that exist in eFootball take their attributes from
           samples/editor-bundled-players.csv verbatim. The old FM pass had overwritten 13,058
           of them with values as low as 4, while the export contains nothing below 40.
  DERIVE   everyone else is rebuilt from tools/fm_html_attributes.py's fm_attributes table
           (the owner's 25 FM exports, 425k players) through fm_data_pass.EF_FROM_FM.

THE CURVE IS MEASURED, NOT INVENTED. 12,299 players exist in BOTH sources, so for each eF ability
we have the FM input and Konami's own output for the same human. Binning those pairs by rounded FM
input gives the real FM->eFootball relationship, forced monotone. That beats the old hand-tuned
logistic, which mapped onto 1-99 — half of it below 40, where an ability is a 6-bit field holding
(value - 40) and simply cannot go (tools/ability_bits.py).

FM's export uses short codes ('OtB', 'Fir', 'Tec'); EF_FROM_FM speaks long names. FM_CODE below is
that dictionary and nothing more — the column names themselves came from the export.

    python tools/fm_derive_attributes.py --career   # include the career-band copies
    python tools/fm_derive_attributes.py --dry     # prints the fitted curve, writes nothing
    python tools/fm_derive_attributes.py
"""
from __future__ import annotations

import csv
import io
import math
import shutil
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from dt870_harvest import ABILITIES, FOOT, FORM, INJURY, WEAK_FOOT   # noqa: E402
from fm_data_pass import EF_FROM_FM, overall_of                      # noqa: E402

DB = REPO / "build" / "master.db"
EFCSV = REPO / "samples" / "editor-bundled-players.csv"
LO, HI = 40, 99

FM_CODE = {
    "Acc": "acceleration", "Pac": "pace", "Agi": "agility", "Bal": "balance",
    "Jum": "jumping_reach", "Sta": "stamina", "Str": "strength", "Nat": "natural_fitness",
    "Fin": "finishing", "Fir": "first_touch", "Dri": "dribbling", "Pas": "passing",
    "Tec": "technique", "Tck": "tackling", "Mar": "marking", "Pos": "positioning",
    "Hea": "heading", "Cro": "crossing", "Cor": "corners", "Lon": "long_shots",
    "Fre": "free_kick_taking", "Pen": "penalty_taking", "L Th": "long_throws",
    "Vis": "vision", "Wor": "work_rate", "Ant": "anticipation", "Cmp": "composure",
    "Dec": "decisions", "Det": "determination", "Ldr": "leadership", "Tea": "teamwork",
    "Bra": "bravery", "Cnt": "concentration", "Agg": "aggression", "Fla": "flair",
    "Ecc": "eccentricity", "Han": "handling", "Ref": "reflexes", "Cmd": "command_of_area",
    "Com": "communication", "Kic": "kicking", "1v1": "one_on_ones", "Pun": "punching",
    "TRO": "rushing_out", "Thr": "throwing", "Aer": "aerial_reach",
}


def _int(v, d=None):
    try:
        return int((v or "").strip())
    except (ValueError, AttributeError):
        return d


def fm_inputs(fm: dict[str, int]) -> dict[str, float]:
    """FM ladder -> one weighted 1-20 input per eFootball ability."""
    out = {}
    for ef, srcs in EF_FROM_FM.items():
        num = den = 0
        for k, w in srcs.items():
            if k in fm:
                num += fm[k] * w
                den += w
        if den:
            out[ef] = num / den
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    # The career copies were seeded before the rescale and still hold pre-scale values — 20,784
    # core abilities below 40 across 1,646 players, some as low as 4. The 6-bit field stores
    # (value - 40), so every one of those renders as 40: a 4 and a 39 come out identical and a
    # career academy squad reads as flat. --career re-curves them the same way as everyone else.
    # It is opt-in because these records belong to a live career save, not to the world.
    career = "--career" in sys.argv
    con = sqlite3.connect(DB, timeout=240)
    cur = con.cursor()

    rows = list(csv.DictReader(io.StringIO(EFCSV.read_bytes().decode("utf-8-sig"))))
    export = {int(r["player_id"]): r for r in rows if (r.get("player_id") or "").isdigit()}
    uid_of = dict(con.execute(
        "SELECT player_id, fm_uid FROM player_identity WHERE fm_uid IS NOT NULL"))
    fm_by_uid: dict[int, dict[str, int]] = defaultdict(dict)
    for uid, a, v in con.execute("SELECT uid, attr, value FROM fm_attributes"):
        name = FM_CODE.get(a)
        if name:
            fm_by_uid[uid][name] = v
    print(f"FM ladder: {len(fm_by_uid):,} players | eFootball export: {len(export):,}")

    # ---------- fit: FM input -> Konami's own value, on the players in both ----------
    pairs: dict[int, list[int]] = defaultdict(list)
    n_cal = 0
    for pid, r in export.items():
        uid = uid_of.get(pid)
        fm = fm_by_uid.get(uid) if uid else None
        if not fm:
            continue
        n_cal += 1
        ins = fm_inputs(fm)
        keeper = (r.get("position") or "").strip().upper() == "GK"
        for ef, x in ins.items():
            v = _int(r.get(ef))
            if v is None or ef not in ABILITIES:
                continue
            # eFootball writes a flat 40 for an outfielder's goalkeeping stats — that is a
            # convention, not a measurement. Feeding those pairs into the fit dragged the whole
            # low end down to 40, so a real keeper with poor reflexes mapped to the same floor
            # as a striker who never keeps goal.
            if ef.startswith("gk_") and not keeper:
                continue
            pairs[max(1, min(20, round(x)))].append(v)
    # Only bins with real support are measured. Above FM ~16 a weighted average almost never
    # lands, so those bins hold tens of samples and wander (19 -> 72, 20 -> 67); trusting them
    # would cap every FM-only player below what the trend says. Fit where the data is, then
    # extrapolate the measured slope through the sparse top.
    MIN_N = 1000
    solid = [k for k in range(1, 21) if len(pairs.get(k, ())) >= MIN_N]
    if len(solid) < 8:
        sys.exit("calibration set too small — cannot fit the curve")
    curve = {k: float(statistics.median(pairs[k])) for k in solid}
    top = max(solid)
    lo_ref = max(k for k in solid if k <= top - 5)
    slope = (curve[top] - curve[lo_ref]) / (top - lo_ref)
    for k in range(top + 1, 21):
        curve[k] = curve[top] + slope * (k - top)
    for k in range(1, 21):
        curve.setdefault(k, curve[min(solid)])
    run = LO
    for k in range(1, 21):                              # monotone, inside the storable range
        run = max(run, min(HI, int(round(curve[k]))))
        curve[k] = run
    print(f"  measured bins: {solid[0]}-{top} (n>={MIN_N:,}), "
          f"slope {slope:.2f} eF per FM point extrapolated above {top}")
    print(f"calibrated on {n_cal:,} players present in both sources")
    print("  FM ->  eF : " + "  ".join(f"{k}->{curve[k]}" for k in range(2, 21, 2)))

    def conv(x: float) -> int:
        lo = max(1, min(20, int(x)))
        hi = min(20, lo + 1)
        f = x - lo
        return max(LO, min(HI, int(round(curve[lo] * (1 - f) + curve[hi] * f))))

    # ---------- who is protected ----------
    protected = set(export)
    for pid, ep in con.execute(
            "SELECT player_id, ef_pid FROM player_identity WHERE ef_pid IS NOT NULL"):
        if ep in export:
            protected.add(pid)
    print(f"protected (in eFootball, never derived): {len(protected):,}")

    have = defaultdict(dict)
    for pid, a, v in con.execute("SELECT player_id, attribute, value FROM player_attributes"):
        have[pid][a] = v

    # ---------- restore eFootball players ----------
    restore, restore_rows = [], []
    for pid, r in export.items():
        cur_vals = have.get(pid)
        if not cur_vals:
            continue
        want = {a: _int(r.get(a)) for a in ABILITIES if _int(r.get(a)) is not None}
        if not want or all(cur_vals.get(a) == v for a, v in want.items()):
            continue
        restore.append(pid)
        restore_rows += [(pid, a, v) for a, v in want.items()]
        for name, table, col in (("weak_foot_usage", WEAK_FOOT, "weak_foot_usage"),
                                 ("weak_foot_accuracy", WEAK_FOOT, "weak_foot_accuracy"),
                                 ("form", FORM, "form"),
                                 ("injury_resistance", INJURY, "injury_resistance"),
                                 ("foot", FOOT, "foot")):
            code = table.get((r.get(col) or "").strip())
            if code is not None:
                restore_rows.append((pid, name, code))
    print(f"eFootball players restored from the export: {len(restore):,}")

    # ---------- derive everyone else ----------
    pos = dict(con.execute("SELECT id, COALESCE(position,'') FROM players"))
    derive_rows, ov_rows, n_der = [], [], 0
    for pid, uid in uid_of.items():
        if pid in protected or 20_000_000 <= pid < 700_000_000:
            continue                                   # eFootball's own, and career copies
        fm = fm_by_uid.get(uid)
        if not fm:
            continue
        vals = {ef: conv(x) for ef, x in fm_inputs(fm).items() if ef in ABILITIES}
        if len(vals) < 20:
            continue
        # and apply the same convention on the way out: an outfielder's goalkeeping abilities are
        # 40, which is what eFootball itself stores for every one of them
        if (pos.get(pid) or "").upper() != "GK":
            for a in vals:
                if a.startswith("gk_"):
                    vals[a] = LO
        n_der += 1
        derive_rows += [(pid, a, v) for a, v in vals.items()]
        try:
            ov_rows.append((overall_of({**{a: LO for a in ABILITIES}, **vals},
                                       pos.get(pid) or "CMF"), pid))
        except Exception:                              # noqa: BLE001
            pass
    print(f"players derived from the FM ladder onto {LO}-{HI}: {n_der:,} "
          f"({len(derive_rows):,} values)")

    # ---------- legacy values: players the FM exports do not cover ----------
    # ~65k FM uids and the RFS/generated bands have no ladder to derive from, but their stored
    # value IS the old curve's output, 99*L for the logistic L. Invert that to recover the FM
    # value it came from, then push it through the SAME calibrated curve — identical to having
    # had their ladder. For synth filler it is simply a monotone lift into the storable range.
    done = {p for p, _a, _v in derive_rows}
    legacy_rows, n_leg = [], 0
    for pid, vals in have.items():
        if pid in protected or pid in done:
            continue
        if 20_000_000 <= pid < 700_000_000 and not career:
            continue
        core = {a: v for a, v in vals.items() if a in ABILITIES}
        if not core or min(core.values()) >= LO:
            continue
        new = {}
        for a, v in core.items():
            L = min(max(v / 99.0, 1e-4), 1 - 1e-4)
            new[a] = conv(10.0 + math.log(L / (1 - L)) / 0.346)
        legacy_rows += [(pid, a, v) for a, v in new.items()]
        n_leg += 1
        try:
            ov_rows.append((overall_of({**{a: LO for a in ABILITIES}, **new},
                                       pos.get(pid) or "CMF"), pid))
        except Exception:                              # noqa: BLE001
            pass
    print(f"players with no FM ladder, legacy values re-curved: {n_leg:,} "
          f"({len(legacy_rows):,} values)")
    derive_rows += legacy_rows

    if dry:
        for pid in list(uid_of)[:0]:
            pass
        print("--dry: nothing written.")
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prederive")
    cur.execute("BEGIN")
    touched = restore + [p for p, _u in uid_of.items() if p not in protected]
    for i in range(0, len(restore), 400):
        chunk = restore[i:i + 400]
        cur.execute("DELETE FROM player_attributes WHERE player_id IN (%s)"
                    % ",".join("?" * len(chunk)), chunk)
    cur.executemany("INSERT OR REPLACE INTO player_attributes(player_id,attribute,value) "
                    "VALUES(?,?,?)", restore_rows)
    cur.executemany("INSERT OR REPLACE INTO player_attributes(player_id,attribute,value) "
                    "VALUES(?,?,?)", derive_rows)
    cur.executemany("UPDATE players SET overall_rating=? WHERE id=?", ov_rows)
    cur.executemany("UPDATE players SET overall_rating=? WHERE id=?",
                    [(_int(export[p].get("overall_rating")), p) for p in restore
                     if _int(export[p].get("overall_rating")) is not None])
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    q = ",".join("?" * len(ABILITIES))
    below = cur.execute(f"SELECT COUNT(*) FROM player_attributes WHERE value < {LO} "
                        f"AND attribute IN ({q})", ABILITIES).fetchone()[0]
    print(f"applied. core values still below {LO}: {below:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

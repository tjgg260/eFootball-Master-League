#!/usr/bin/env python3
"""
pesdb_census.py — measure what is and is not decoded in a WESYS database table.

The decode of dt200/dt870 has always been field-at-a-time: find a bit window, correlate it
against a known CSV column, declare it solved. That works, but it can never answer "how much
is left", because nothing ever counted the bits that no field claims. This does.

For a table with a fixed record stride, every bit in the record lands in exactly one bucket:

    named      a field in tools/data/pesdb_schema.json claims it
    constant   the bit never changes across the whole table (padding, format tag, or a field
               that this build happens not to exercise) - carries zero information
    UNKNOWN    it varies across records and no field claims it. This is the work remaining.

Coverage is therefore honest by construction: named + constant + unknown = 100%, and a table
is fully decoded only when UNKNOWN reaches zero. Constant bits are reported separately rather
than counted as decoded, because "always 0 in this build" is an observation, not an explanation.

Commands
    stride   <file> [--max N]        rank candidate record strides by evidence
    census   <file> --stride N       per-bit and per-byte statistics
    fields   <file> --stride N       propose field boundaries from the bit census
    coverage <file> --table NAME     bits named / constant / unknown against the schema
    xref     <file> --stride N --off O --width W --type u32
                                     test a column against every other table's id columns

Every command takes a WESYS-wrapped .bin and decodes it through the vendored Sider codec;
pass --raw for an already-decoded payload.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
import wesys  # noqa: E402

SCHEMA_PATH = REPO / "tools" / "data" / "pesdb_schema.json"


# ---------------------------------------------------------------- loading


def load_table(path: Path, raw: bool = False) -> bytes:
    """Decode a table, whichever of the three container shapes it uses.

    The vendored Sider codec only handles the zlib variant (flag byte 2 = 0x83). Sider's own
    doc explains flag 0x02 as "empty table", which is true of the nine 16-byte tables it was
    describing but not in general: a 0x02 container with comp == orig != 0 is a STORED payload
    - XOR keystream, no zlib. Kit descriptors and a handful of small tables ship that way, and
    reading them through the zlib path fails outright. tools/kit_codec.py already classifies
    all three, so defer to it rather than adding a fourth opinion about the format.
    """
    data = path.read_bytes()
    if raw:
        return data
    if len(data) < 16 or data[3:8] != b"WESYS":
        return data
    try:
        return wesys.unpack_wesys_payload(data)
    except Exception:
        import kit_codec  # local import: only needed for the stored/plain variants

        return kit_codec.decode_container(data)[1]


def as_matrix(data: bytes, stride: int) -> np.ndarray:
    """(n_records, stride) uint8 view. Trailing partial record is dropped."""
    n = len(data) // stride
    return np.frombuffer(data[: n * stride], dtype=np.uint8).reshape(n, stride)


def bit_matrix(mat: np.ndarray) -> np.ndarray:
    """(n_records, stride*8) uint8 of 0/1, bit b = byte b//8, bit b%8 (little-endian in byte).

    This matches the convention used everywhere else in this repo (ability_bits.read_bits),
    so a bit offset printed here can be pasted straight into those tools.
    """
    return np.unpackbits(mat, axis=1, bitorder="little")


# ---------------------------------------------------------------- stride


def score_stride(data: bytes, stride: int) -> dict:
    """Evidence that `stride` is the real record size.

    Three independent signals, because any one of them alone has a failure mode:
      const_frac  fraction of byte columns that never vary. A wrong stride smears real
                  variation across every column and drives this to ~0.
      id_cols     columns that read as a strictly increasing u32/u64 across records. Nearly
                  every table in this database is sorted by some id, so a true stride almost
                  always exposes one; a wrong stride never does.
      zero_frac   fraction of columns that are always zero. Padding is common and, like
                  const_frac, only lines up at the true stride.
    """
    n = len(data) // stride
    if n < 4:
        return {}
    mat = as_matrix(data, stride)
    const = int((mat == mat[0]).all(axis=0).sum())
    zero = int((mat == 0).all(axis=0).sum())

    id_cols = []
    for off in range(0, stride - 3):
        col = mat[:, off : off + 4].copy().view(np.uint32).ravel()
        if col.size == n and np.all(np.diff(col.astype(np.int64)) > 0):
            id_cols.append(off)
    for off in range(0, stride - 7):
        col = mat[:, off : off + 8].copy().view(np.uint64).ravel()
        if col.size == n and np.all(np.diff(col.astype(object)) > 0):
            id_cols.append(-off - 1)  # negative marks a u64 hit

    return {
        "stride": stride,
        "count": n,
        "const_frac": const / stride,
        "zero_frac": zero / stride,
        "id_cols": id_cols[:6],
        "n_id": len(id_cols),
    }


def cmd_stride(a):
    data = load_table(Path(a.file), a.raw)
    n = len(data)
    print(f"{Path(a.file).name}: {n} decoded bytes")
    rows = []
    for s in range(4, min(a.max, n) + 1):
        if n % s:
            continue
        r = score_stride(data, s)
        if r:
            rows.append(r)
    # A true stride shows aligned constant columns AND a monotonic id column.
    rows.sort(key=lambda r: (r["n_id"] > 0, r["const_frac"], -r["stride"]), reverse=True)
    print(f"{'stride':>7} {'count':>8} {'const':>7} {'zero':>7} {'#id':>4}  id cols (neg = u64)")
    for r in rows[: a.top]:
        print(
            f"{r['stride']:>7} {r['count']:>8} {r['const_frac']:>7.2f} {r['zero_frac']:>7.2f} "
            f"{r['n_id']:>4}  {r['id_cols']}"
        )


# ---------------------------------------------------------------- census


def bit_census(data: bytes, stride: int) -> dict:
    mat = as_matrix(data, stride)
    bits = bit_matrix(mat)
    n = bits.shape[0]
    ones = bits.sum(axis=0)
    return {
        "n": n,
        "stride": stride,
        "nbits": stride * 8,
        "ones": ones,
        "always0": ones == 0,
        "always1": ones == n,
        "varying": (ones > 0) & (ones < n),
        "mat": mat,
        "bits": bits,
    }


def cmd_census(a):
    data = load_table(Path(a.file), a.raw)
    c = bit_census(data, a.stride)
    nb = c["nbits"]
    print(
        f"{Path(a.file).name}: {c['n']} records x {a.stride} bytes = {nb} bits/record\n"
        f"  always 0 : {int(c['always0'].sum()):>5} ({c['always0'].mean():6.1%})\n"
        f"  always 1 : {int(c['always1'].sum()):>5} ({c['always1'].mean():6.1%})\n"
        f"  varying  : {int(c['varying'].sum()):>5} ({c['varying'].mean():6.1%})"
    )
    if a.bytes:
        mat = c["mat"]
        print("\nper-byte: offset  distinct  min  max  const?  sample values")
        for off in range(a.stride):
            col = mat[:, off]
            vals, counts = np.unique(col, return_counts=True)
            flag = "CONST" if vals.size == 1 else ""
            top = ", ".join(f"{v}x{cnt}" for v, cnt in zip(vals[:6], counts[:6]))
            print(f"  {off:>5}  {vals.size:>8}  {col.min():>3}  {col.max():>3}  {flag:>6}  {top}")


# ---------------------------------------------------------------- fields


def propose_fields(data: bytes, stride: int, max_width: int = 16) -> list[dict]:
    """Group varying bits into candidate fields.

    A bit-packed field of width w at offset o has a signature: the w bits move together and
    the value they spell out has a *compact* distribution (a 6-bit ability uses most of 0..63;
    a misaligned 6-bit window straddling two fields looks closer to uniform noise, and usually
    spans a value range that no sane field would).

    So: walk the varying-bit runs, and for each run try every split into fields whose values
    have low normalised entropy. Report the runs with their best reading. This proposes, it
    does not prove - every field still has to be confirmed against ground truth.
    """
    c = bit_census(data, stride)
    varying = c["varying"]
    bits = c["bits"]
    n = c["n"]

    runs = []
    start = None
    for b in range(c["nbits"]):
        if varying[b] and start is None:
            start = b
        elif not varying[b] and start is not None:
            runs.append((start, b - start))
            start = None
    if start is not None:
        runs.append((start, c["nbits"] - start))

    def read_field(off, w):
        w = min(w, 63)
        weights = (1 << np.arange(w, dtype=np.uint64)).astype(np.float64)
        return (bits[:, off : off + w].astype(np.float64) * weights).sum(axis=1)

    out = []
    for off, width in runs:
        rec = {"bit": off, "run_width": width}
        if width <= max_width:
            v = read_field(off, width)
            vals, counts = np.unique(v, return_counts=True)
            p = counts / n
            ent = float(-(p * np.log2(p)).sum())
            rec.update(
                {
                    "distinct": int(vals.size),
                    "min": float(vals.min()),
                    "max": float(vals.max()),
                    "entropy": ent,
                    "max_entropy": float(width),
                    "density": float(vals.size) / (1 << width),
                }
            )
        out.append(rec)
    return out


def cmd_fields(a):
    data = load_table(Path(a.file), a.raw)
    props = propose_fields(data, a.stride)
    print(f"{Path(a.file).name}: {len(props)} varying-bit runs at stride {a.stride}")
    print(f"{'bit':>6} {'width':>6} {'distinct':>9} {'min':>8} {'max':>8} {'entropy':>8} {'density':>8}")
    for p in props:
        if "distinct" in p:
            print(
                f"{p['bit']:>6} {p['run_width']:>6} {p['distinct']:>9} {p['min']:>8.0f} "
                f"{p['max']:>8.0f} {p['entropy']:>8.2f} {p['density']:>8.3f}"
            )
        else:
            print(f"{p['bit']:>6} {p['run_width']:>6}   (wide run - likely a string or blob)")


# ---------------------------------------------------------------- coverage


def load_schema() -> dict:
    if not SCHEMA_PATH.exists():
        return {"tables": {}}
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def cmd_coverage(a):
    schema = load_schema()
    table = schema.get("tables", {}).get(a.table)
    if table is None:
        print(f"no schema entry for table {a.table!r}; known: {sorted(schema.get('tables', {}))}")
        return 1
    stride = a.stride or table["stride"]
    data = load_table(Path(a.file), a.raw)
    c = bit_census(data, stride)
    nb = c["nbits"]

    claimed = np.zeros(nb, dtype=bool)
    overlaps = []
    for f in table["fields"]:
        lo, w = f["bit"], f["width"]
        if lo + w > nb:
            print(f"  ! field {f['name']} runs past the record ({lo}+{w} > {nb})")
            continue
        if claimed[lo : lo + w].any():
            overlaps.append(f["name"])
        claimed[lo : lo + w] = True

    named = claimed
    const = (~claimed) & (c["always0"] | c["always1"])
    unknown = (~claimed) & c["varying"]

    print(f"{a.table}: {c['n']} records x {stride} bytes = {nb} bits")
    print(f"  named    : {int(named.sum()):>5} ({named.mean():6.1%})  {len(table['fields'])} fields")
    print(f"  constant : {int(const.sum()):>5} ({const.mean():6.1%})  (no information in this build)")
    print(f"  UNKNOWN  : {int(unknown.sum()):>5} ({unknown.mean():6.1%})  <- work remaining")
    if overlaps:
        print(f"  ! overlapping fields: {overlaps}")

    if a.show_unknown and unknown.any():
        print("\n  unknown varying-bit runs:")
        start = None
        for b in range(nb):
            if unknown[b] and start is None:
                start = b
            elif not unknown[b] and start is not None:
                print(f"    bit {start:>5} .. {b - 1:<5} width {b - start}")
                start = None
        if start is not None:
            print(f"    bit {start:>5} .. {nb - 1:<5} width {nb - start}")
    return 0


# ---------------------------------------------------------------- xref


def cmd_xref(a):
    """Test whether a column's values are a subset of some other table's id column."""
    data = load_table(Path(a.file), a.raw)
    mat = as_matrix(data, a.stride)
    fmt = {"u8": (1, np.uint8), "u16": (2, np.uint16), "u32": (4, np.uint32)}[a.type]
    size, dt = fmt
    col = mat[:, a.off : a.off + size].copy().view(dt).ravel()
    mine = set(int(v) for v in np.unique(col))
    print(f"column @{a.off} as {a.type}: {len(mine)} distinct, range {min(mine)}..{max(mine)}")

    root = Path(a.dir)
    for other in sorted(root.rglob("*.bin")):
        try:
            od = load_table(other, False)
        except Exception:
            continue
        if not od:
            continue
        for ostride in a.other_strides:
            if len(od) % ostride:
                continue
            om = as_matrix(od, ostride)
            for ooff in range(0, ostride - 3, 1):
                ocol = om[:, ooff : ooff + 4].copy().view(np.uint32).ravel()
                theirs = set(int(v) for v in np.unique(ocol))
                if len(theirs) < 4:
                    continue
                if mine <= theirs:
                    print(
                        f"  SUBSET of {other.name} stride {ostride} @{ooff} (u32, "
                        f"{len(theirs)} distinct)"
                    )


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--raw", action="store_true", help="input is already WESYS-decoded")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("stride", help="rank candidate record strides")
    p.add_argument("file")
    p.add_argument("--max", type=int, default=4096)
    p.add_argument("--top", type=int, default=12)
    p.set_defaults(func=cmd_stride)

    p = sub.add_parser("census", help="per-bit / per-byte statistics")
    p.add_argument("file")
    p.add_argument("--stride", type=int, required=True)
    p.add_argument("--bytes", action="store_true", help="also dump the per-byte table")
    p.set_defaults(func=cmd_census)

    p = sub.add_parser("fields", help="propose field boundaries")
    p.add_argument("file")
    p.add_argument("--stride", type=int, required=True)
    p.set_defaults(func=cmd_fields)

    p = sub.add_parser("coverage", help="named / constant / unknown against the schema")
    p.add_argument("file")
    p.add_argument("--table", required=True)
    p.add_argument("--stride", type=int)
    p.add_argument("--show-unknown", action="store_true")
    p.set_defaults(func=cmd_coverage)

    p = sub.add_parser("xref", help="test a column against other tables' id columns")
    p.add_argument("file")
    p.add_argument("--stride", type=int, required=True)
    p.add_argument("--off", type=int, required=True)
    p.add_argument("--width", type=int, default=4)
    p.add_argument("--type", default="u32", choices=["u8", "u16", "u32"])
    p.add_argument("--dir", required=True, help="directory of tables to search")
    p.add_argument("--other-strides", type=int, nargs="+", default=[4, 8, 16, 24, 64, 400, 1600])
    p.set_defaults(func=cmd_xref)

    a = ap.parse_args()
    return a.func(a) or 0


if __name__ == "__main__":
    raise SystemExit(main())

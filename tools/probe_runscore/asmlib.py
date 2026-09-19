"""Minimal two-pass assembler: labels (@name / name:) + RIPREL_$cell."""
import re, keystone
_ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
MAGIC = 0x11223344
FAR = 0x1000000

LBLREF = re.compile(r"@(\w+)")
CELLREF = re.compile(r"RIPREL_\$(\w+)")

def assemble(src, base, cells):
    lines = [l.split(";")[0].strip() for l in src.splitlines()]
    lines = [l for l in lines if l]
    sizes, va = [], base
    for t in lines:
        if t.endswith(":"):
            sizes.append(0); continue
        s = CELLREF.sub(str(MAGIC), t)
        s = LBLREF.sub(str(base + FAR), s)
        try:
            code, _ = _ks.asm(s, va)
        except Exception as ex:
            raise SystemExit(f"pass1 {s!r}: {ex}")
        sizes.append(len(code)); va += len(code)
    labels, va = {}, base
    for t, n in zip(lines, sizes):
        if t.endswith(":"):
            labels[t[:-1]] = va
        va += n
    out, va = b"", base
    for t, n in zip(lines, sizes):
        if t.endswith(":"):
            continue
        s = CELLREF.sub(lambda m: str(cells[m.group(1)] - (va + n)), t)
        s = LBLREF.sub(lambda m: str(labels[m.group(1)]), s)
        try:
            code, _ = _ks.asm(s, va)
        except Exception as ex:
            raise SystemExit(f"pass2 {s!r}: {ex}")
        code = bytes(code)
        assert len(code) <= n, f"{t!r} grew {len(code)} > {n}"
        out += code + b"\x90" * (n - len(code)); va += n
    return out, labels

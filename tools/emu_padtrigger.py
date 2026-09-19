#!/usr/bin/env python3
"""Emulate eFootball's pad trigger layer with the REAL bytes.

Nothing touches the game: both images opened read-only, pages copied into Unicorn.

Proves, with numbers:
  * the PadTrigger struct built by each ctor,
  * what kinds 1/2/3/4/8 actually match over a synthetic 100-frame pad history,
  * that match::pad::ThinkUnitPassAndGo's own two trigger arrays fire on the
    SHOULDER BUTTON ALONE (no pass button anywhere in them),
  * that a TAP and a HOLD are separable in this framework.
"""
import struct, sys
sys.path.insert(0, r"C:/Users/tjgg2/Downloads/eFootball Master League/.claude/worktrees/dt270-full-decode-12718b/tools")
import cave_alloc
from emu_anticipation import Emu, STACK, HEAP, RET_MAGIC
import unicorn.x86_const as X

EXE = r"C:/Program Files (x86)/Steam/steamapps/common/eFootball/eFootball/Binaries/Win64/eFootball.exe"
PRIS = r"C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE"

CTOR = {"kind1_press": 0x14430edb0, "kind8_notpressed": 0x14430edf0,
        "kind2_hold": 0x14430ee30, "kind9": 0x14430ee80, "kind4_tap": 0x14430eec0}
EVAL = 0x14430fb40

RING = HEAP + 0x10000        # 100 * 0x40 + cursor
WRAP = HEAP + 0x8000         # wrapper: [0] -> RING
ARR  = HEAP + 0x1000         # PadTrigger array scratch

BIT_L1   = 18   # COMMON_L1
BIT_R2   = 19   # COMMON_R2  (dash)
BIT_L2   = 20   # OFFENCE_L2
BIT_R1   = 21   # OFFENCE_R1
BIT_Y, BIT_B, BIT_A, BIT_X = 22, 23, 24, 25


def new(img):
    e = Emu(img)
    from emu_anticipation import STACK_SZ, HEAP_SZ
    for lo, sz in ((STACK, STACK_SZ), (HEAP, HEAP_SZ), (RET_MAGIC & ~0xFFF, 0x1000)):
        for pg in range(lo, lo + sz, 0x1000):
            e.mapped.add(pg)
    e.setregs(rsp=STACK + 0x100000)
    return e


def call(e, fn, rcx=0, rdx=0, r8=0, r9=0, stack=()):
    sp = STACK + 0x100000 - 0x200
    e.uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
    for i, v in enumerate(stack):           # args 5.. at [rsp+0x20], +0x28, ...
        e.uc.mem_write(sp + 8 + 0x20 + 8 * i, struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF))
    e.setregs(rsp=sp, rcx=rcx, rdx=rdx, r8=r8, r9=r9)
    e.uc.reg_write(X.UC_X86_REG_XMM3, 0)
    e.run(fn, RET_MAGIC, count=200000)
    return e.uc.reg_read(X.UC_X86_REG_RAX)


def build(e, addr, ctor, bit, a=0, b=0):
    call(e, CTOR[ctor], rcx=addr, rdx=bit, r8=a, r9=b)
    return e.uc.mem_read(addr, 0x28)


def fmt(raw):
    mask, kind, p8, pc = struct.unpack_from("<IIII", raw, 0)
    flag = raw[0x10]
    f20, f24 = struct.unpack_from("<ff", raw, 0x20)
    bit = mask.bit_length() - 1 if mask else -1
    return f"mask={mask:#010x}(bit {bit:2}) kind={kind} +8={p8} +0xc={pc} flag={flag} f20={f20} f24={f24}"


def ring(e, frames):
    """frames[i] = button bitmask for i frames ago (0 = this frame). cursor = 99."""
    buf = bytearray(0x1904)
    cur = 99
    for i in range(100):
        v = frames[i] if i < len(frames) else (frames[-1] if frames else 0)
        idx = (cur - i) % 100
        struct.pack_into("<Q", buf, idx * 0x40, v)
    struct.pack_into("<I", buf, 0x1900, cur)
    e.uc.mem_write(RING, bytes(buf))
    e.uc.mem_write(WRAP, struct.pack("<Q", RING))


def held(bit, frames_ago_lo, frames_ago_hi, base=0):
    """bitmask list where `bit` is down for frames in [lo,hi]."""
    out = []
    for i in range(100):
        v = base
        if frames_ago_lo <= i <= frames_ago_hi:
            v |= 1 << bit
        out.append(v)
    return out


def evaluate(e, base, n):
    return call(e, EVAL, rcx=WRAP, rdx=base, r8=n, stack=(0, 0, 0x64, 0)) & 0xFF


def main():
    img = cave_alloc.Image(EXE)
    e = new(img)

    print("=== S1  PadTrigger ctors, real bytes ===")
    for name in CTOR:
        raw = build(e, ARR, name, BIT_R1, a=5, b=3)
        print(f"  {name:18} {fmt(raw)}")

    fps = 60.0
    tapwin = int(fps * 0.08 + 0.5)
    print(f"\n=== S2  ThinkUnitPassAndGo's OWN two arrays (fps={fps}, 0.08s = {tapwin} frames) ===")
    A = ARR
    build(e, A + 0x00, "kind8_notpressed", BIT_R2)
    build(e, A + 0x28, "kind4_tap", BIT_R1, a=tapwin)   # r8d -> [+0xc] for eec0
    print(f"  A[0] @0x1486b88d0  {fmt(e.uc.mem_read(A + 0x00, 0x28))}")
    print(f"  A[1] @0x1486b88f8  {fmt(e.uc.mem_read(A + 0x28, 0x28))}")
    B = ARR + 0x100
    build(e, B + 0x00, "kind8_notpressed", BIT_R2)
    build(e, B + 0x28, "kind1_press", BIT_R1, a=0)
    build(e, B + 0x50, "kind2_hold", BIT_R1, a=tapwin, b=0)
    print(f"  B[0] @0x1486b8930  {fmt(e.uc.mem_read(B + 0x00, 0x28))}")
    print(f"  B[1] @0x1486b8958  {fmt(e.uc.mem_read(B + 0x28, 0x28))}")
    print(f"  B[2] @0x1486b8980  {fmt(e.uc.mem_read(B + 0x50, 0x28))}")

    print("\n=== S3  pad histories -> does the array fire?  (A = TAP path, B = PRESS+HOLD path) ===")
    print("  'R1 down for f' means bit 21 set on frames-ago 0..f-1 (i.e. just released if lo>0)")
    cases = []
    for n in (0, 1, 2, 3, 5, 6, 10, 20, 40):
        cases.append((f"R1 held now, {n:2} frames so far", held(BIT_R1, 0, n - 1) if n else [0] * 100))
    for n in (1, 2, 3, 5, 6, 10, 20):
        # released this frame; was down for n frames ending 1 frame ago
        cases.append((f"R1 TAP of {n:2} frames, released 1 frame ago", held(BIT_R1, 1, n)))
    cases.append(("R1 held 40 + R2 (dash) also held", held(BIT_R1, 0, 39, base=1 << BIT_R2)))
    cases.append(("R1 tap 3 released + R2 also held", held(BIT_R1, 1, 3, base=1 << BIT_R2)))
    cases.append(("nothing pressed", [0] * 100))
    cases.append(("only the A / low-pass button", held(BIT_A, 0, 20)))
    for label, frames in cases:
        ring(e, frames)
        ra = evaluate(e, A, 2)
        rb = evaluate(e, B, 3)
        print(f"  {label:42} A(tap)={ra}  B(press+hold)={rb}  ->  PassAndGo fires: {bool(ra or rb)}")

    print("\n=== S4  TAP vs HOLD really are separable (kind4 alone vs kind2 alone, bit 21) ===")
    T = ARR + 0x200
    build(e, T, "kind4_tap", BIT_R1, a=tapwin)
    H = ARR + 0x240
    build(e, H, "kind2_hold", BIT_R1, a=int(fps * 0.25 + 0.5), b=0)
    print(f"  tap   : {fmt(e.uc.mem_read(T, 0x28))}")
    print(f"  hold  : {fmt(e.uc.mem_read(H, 0x28))}  (0.25 s = {int(fps*0.25+0.5)} frames)")
    for label, frames in [("nothing", [0] * 100),
                          ("R1 down 2 frames, still down", held(BIT_R1, 0, 1)),
                          ("R1 down 20 frames, still down", held(BIT_R1, 0, 19)),
                          ("R1 tapped 3f, released 1f ago", held(BIT_R1, 1, 3)),
                          ("R1 tapped 30f, released 1f ago", held(BIT_R1, 1, 30))]:
        ring(e, frames)
        print(f"  {label:34} tap={evaluate(e, T, 1)}  hold={evaluate(e, H, 1)}")

    print("\n=== S5  same on the PRISTINE image (no patches of ours anywhere near) ===")
    e2 = new(cave_alloc.Image(PRIS))
    build(e2, ARR + 0x00, "kind8_notpressed", BIT_R2)
    build(e2, ARR + 0x28, "kind4_tap", BIT_R1, a=tapwin)
    ring(e2, held(BIT_R1, 1, 3))
    print(f"  R1 tap 3f released: A(tap) = {evaluate(e2, ARR, 2)}")
    ring(e2, held(BIT_R1, 1, 3, base=1 << BIT_R2))
    print(f"  same but R2 held  : A(tap) = {evaluate(e2, ARR, 2)}")


main()

def dbg():
    import cave_alloc as ca
    img = ca.Image(EXE)
    e = new(img)
    T = ARR
    build(e, T, "kind4_tap", BIT_R1, a=5)
    build(e, T+0x28, "kind1_press", BIT_R1, a=5)
    build(e, T+0x50, "kind8_notpressed", BIT_R2)
    ring(e, held(BIT_R1, 1, 3))
    print("ring sample(0)=%#x sample(1)=%#x sample(4)=%#x" % tuple(
        struct.unpack("<Q", e.uc.mem_read(RING + ((99 - i) % 100) * 0x40, 8))[0] for i in (0, 1, 4)))
    for nm, fn, tr in (("kind3_release", 0x14430d980, T), ("kind1_press", 0x14430d830, T+0x28),
                       ("kind4_tap", 0x14430da30, T), ("kind8", 0x14430db10, T+0x50)):
        r = call(e, fn, rcx=WRAP, rdx=tr, r8=0, r9=0x64)
        print(f"  direct {nm:14} -> {r & 0xFFFFFFFF:#x} ({struct.unpack('<i', struct.pack('<I', r & 0xFFFFFFFF))[0]})")
    # handler expects rcx = pad RING pointer or the wrapper?
    for nm, fn in (("kind4_tap(ring)", 0x14430da30),):
        r = call(e, fn, rcx=RING, rdx=T, r8=0, r9=0x64)
        print(f"  direct {nm:14} rcx=RING -> {struct.unpack('<i', struct.pack('<I', r & 0xFFFFFFFF))[0]}")
    e.trace.clear()
    r = call(e, EVAL, rcx=WRAP, rdx=T, r8=1, stack=(0, 0, 0x64, 0))
    print("  EVAL ->", r & 0xFF, " trace len", len(e.trace));
    pass
    print("  faults", e.faults[:5])

dbg()

def s6():
    import cave_alloc as ca
    e = new(ca.Image(EXE))
    PRESS_EDGE = 0x14430f9b0      # ThinkUnitBase::vf17 single-press path
    DOUBLE_TAP = 0x144310490      # ThinkUnitBase::vf17 multi-press path (count, gap)
    print("\n=== S6  ThinkUnitCursorChange's ACTUAL pad test: 0x14430f9b0(pad, bit 18 = COMMON_L1, 0) ===")
    for label, frames in [("nothing", [0]*100),
                          ("L1 went down THIS frame (edge)", held(BIT_L1, 0, 0)),
                          ("L1 down, edge was 1 frame ago", held(BIT_L1, 1, 1)),
                          ("L1 held 10 frames, edge 9 ago", held(BIT_L1, 0, 9)),
                          ("L1 held forever (no edge in ring)", [1 << BIT_L1]*100),
                          ("L1 released this frame", held(BIT_L1, 1, 40))]:
        ring(e, frames)
        r = call(e, PRESS_EDGE, rcx=WRAP, rdx=BIT_L1, r8=0) & 0xFF
        print(f"  {label:34} pressedEdge={r}")
    print("  (CursorChange is constructed with +0x14 = 0, so vf17 takes ONLY this path)")
    print("\n=== S6b  the framework's double-tap detector 0x144310490(pad, bit, count=2, gap=6) ===")
    hist = [0]*100
    for i in (0, 3, 4):   # down now, up at 1..2, down at 3..4  -> two presses 3 frames apart
        hist[i] = 1 << BIT_L1
    for label, frames in [("single press now", held(BIT_L1, 0, 40)),
                          ("two presses 3 frames apart", hist)]:
        ring(e, frames)
        r = call(e, DOUBLE_TAP, rcx=WRAP, rdx=BIT_L1, r8=2, r9=6, stack=(0, 0, 0)) & 0xFF
        print(f"  {label:34} doubleTap={r}")

s6()

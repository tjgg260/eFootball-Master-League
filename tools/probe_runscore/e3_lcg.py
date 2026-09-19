"""E3: decode every entry point of the match LCG cluster by emulating it."""
import struct
from emu_lib import Emu, X

E = {
 "0x144345d90 rand_stream(state*, streamIdx)":            0x144345d90,
 "0x144345e00 rand_below_nostate(state*, bound, streamIdx)": 0x144345e00,
 "0x144345e50 rand_below_s1(state*, bound)":              0x144345e50,
 "0x1443461a0 advance_only(state*, streamIdx)":           0x1443461a0,
 "0x1443461c0 set_state(state*, streamIdx, value)":       0x1443461c0,
 "0x1443461d0 checksum(state*)":                          0x1443461d0,
}
BOUNDS = 0x146c34f20
e = Emu()
print("bound table 0x146c34f20 =", [e.r32(BOUNDS + 4*i) for i in range(4)])
print()

def fresh(seed=(1,1,1,1)):
    s = e.alloc(0x40)
    for i, v in enumerate(seed):
        e.w32(s + 4*i, v)
    return s

def state(s): return [e.r32(s + 4*i) for i in range(4)]

print("=== 0x144345d90(state*, idx): per-stream draw, bound from the global table ===")
for idx in range(4):
    s = fresh((12345, 12345, 12345, 12345))
    seq, st = [], []
    for _ in range(8):
        r, err = e.call(0x144345d90, rcx=s, rdx=idx)
        seq.append(r & 0xFFFFFFFF); st.append(state(s)[idx])
    print(f"  stream {idx} bound {e.r32(BOUNDS+4*idx):5d}: returns {seq}")
    print(f"            state after each: {st}")

print()
print("=== 0x144345e00(state*, bound, idx): draw scaled to an ARBITRARY bound ===")
for bound in (2, 3, 10, 100):
    s = fresh((999, 999, 999, 999))
    seq = []
    for _ in range(10):
        r, err = e.call(0x144345e00, rcx=s, rdx=bound, r8=1)
        seq.append(r & 0xFFFFFFFF)
    print(f"  bound {bound:4d} -> {seq}")
# off-by-one probe: force the state to the max 31-bit value the LCG can hold
s = fresh(); e.w32(s + 4, 0x7FFFFFFF)
# find a predecessor state whose successor is large
worst = 0
for pre in range(1, 200000):
    nxt = (0x4513 - pre * 0x2d22b2e3) & 0xFFFFFFFF
    nxt &= 0x7FFFFFFF
    worst = max(worst, nxt)
print(f"  max successor state seen in 200k predecessors: {worst:#x} ({worst/2**31:.9f} of 2^31)")
s = fresh(); e.w32(s + 4, 0)
# directly plant a state that yields the max
for pre in range(1, 400000):
    nxt = (0x4513 - pre * 0x2d22b2e3) & 0xFFFFFFFF & 0x7FFFFFFF
    if nxt >= 0x7FFFFF00:
        s = fresh(); e.w32(s + 4, pre)
        r, _ = e.call(0x144345e00, rcx=s, rdx=3, r8=1)
        print(f"  predecessor {pre} -> state {nxt:#x} -> 0x144345e00(bound=3) returns {r}"
              f"   {'<-- OUT OF RANGE (== bound)' if r >= 3 else ''}")
        break

print()
print("=== 0x144345e50(state*, bound): uses stream 1 only, clamped both ends ===")
for bound in (-5, 0, 1, 3, 11):
    s = fresh((7,7,7,7))
    seq = [e.call(0x144345e50, rcx=s, rdx=bound & 0xFFFFFFFF)[0] & 0xFFFFFFFF for _ in range(8)]
    print(f"  bound {bound:4d} -> {seq}")

print()
print("=== 0x1443461a0(state*, idx): ADVANCE ONLY, returns the raw 31-bit state ===")
s = fresh((12345,)*4)
seq = [e.call(0x1443461a0, rcx=s, rdx=0)[0] & 0xFFFFFFFF for _ in range(6)]
print(f"  raw states: {[hex(v) for v in seq]}")
print(f"  python model 's = (0x4513 - s*0x2d22b2e3) & 0x7fffffff':")
v = 12345; mod = []
for _ in range(6):
    v = (0x4513 - v * 0x2d22b2e3) & 0xFFFFFFFF & 0x7FFFFFFF
    mod.append(hex(v))
print(f"              {mod}   {'IDENTICAL' if mod==[hex(x) for x in seq] else 'DIFFERENT'}")

print()
print("=== 0x1443461c0 / 0x1443461d0 ===")
s = fresh()
e.call(0x1443461c0, rcx=s, rdx=2, r8=0xCAFE)
print(f"  set_state(s,2,0xCAFE) -> state {[hex(x) for x in state(s)]}")
r, _ = e.call(0x1443461d0, rcx=s)
print(f"  checksum(s) = {r:#x}  (xor of the four words = {0x1^0x1^0xCAFE^0x1:#x})")

print()
print("=== clobber survey (registers dirtied by each leaf) ===")
import unicorn
NAMES = [("rax",X.UC_X86_REG_RAX),("rcx",X.UC_X86_REG_RCX),("rdx",X.UC_X86_REG_RDX),
         ("rbx",X.UC_X86_REG_RBX),("rsi",X.UC_X86_REG_RSI),("rdi",X.UC_X86_REG_RDI),
         ("rbp",X.UC_X86_REG_RBP),("r8",X.UC_X86_REG_R8),("r9",X.UC_X86_REG_R9),
         ("r10",X.UC_X86_REG_R10),("r11",X.UC_X86_REG_R11),("r12",X.UC_X86_REG_R12),
         ("r13",X.UC_X86_REG_R13),("r14",X.UC_X86_REG_R14),("r15",X.UC_X86_REG_R15)]
XN = [("xmm%d"%i, getattr(X,"UC_X86_REG_XMM%d"%i)) for i in range(16)]
for label, fn in E.items():
    s = fresh((4321,)*4)
    MARK = 0x1111111100000000
    for i,(n,r) in enumerate(NAMES):
        if n in ("rsp",): continue
        e.uc.reg_write(r, MARK | i)
    for i,(n,r) in enumerate(XN):
        e.uc.reg_write(r, (0x2222222200000000 | i))
    e.call(fn, rcx=s, rdx=3, r8=2)
    dirty = [n for i,(n,r) in enumerate(NAMES)
             if n not in ("rcx","rdx","r8") and e.uc.reg_read(r) != (MARK | i)]
    xdirty = [n for i,(n,r) in enumerate(XN) if e.uc.reg_read(r) != (0x2222222200000000 | i)]
    print(f"  {label:52s} clobbers {sorted(set(dirty))} {xdirty}")

"""E1/E2: prove ATTR_get's flattened address formula, and that a 5-instruction
inline sequence returns the identical byte, on the game's own code."""
import struct, random
from emu_lib import Emu, X, BASE
import keystone

ATTR_get   = 0x143ea8cb0
GLOBAL_PTR = 0x1486bd888
STRIDE, TBL, ARR = 0x58, 0x55a8, 0x394

e = Emu()
# --- build a synthetic world -------------------------------------------------
G = e.alloc(0x8000)
e.w64(GLOBAL_PTR, G)
random.seed(7)
planted = {}          # (entity, idx) -> byte
recs = []
for ent in range(0x1f):
    rec = e.alloc(0x600)
    recs.append(rec)
    e.w64(G + ent * STRIDE + TBL, rec)
    for idx in range(0x40):
        v = random.randrange(40, 100)
        planted[(ent, idx)] = v
        e.w8(rec + ARR + idx, v)

# a "match player" object for each entity: only two fields matter
players = []
for ent in range(0x1f):
    p = e.alloc(0x5000)
    e.w8(p + 0x2bd8, ent)
    e.w64(p + 0x47c0, 0xDEADBEEF00)     # deliberately garbage: the chain must ignore it
    e.wf(p + 0x4f4, 10.0 + ent)
    players.append(p)

print("=== E1  ATTR_get(player, idx) vs the flattened formula ===")
bad = 0
for ent in (0, 1, 7, 10, 11, 21, 0x1e):
    for idx in (0x14, 0x15, 0x17, 0x28, 0x2c, 0x2e):
        rax, err = e.call(ATTR_get, rcx=players[ent], rdx=idx)
        got = rax & 0xFF
        want = planted[(ent, idx)]
        ok = (got == want and err is None)
        bad += not ok
        print(f"  ent {ent:2d} idx {idx:#04x}  ATTR_get -> {got:3d}   planted {want:3d}  {'OK' if ok else 'MISMATCH '+str(err)}")
print(f"  result: {'ALL MATCH' if bad==0 else f'{bad} MISMATCHES'}")

# out of range entity index
p = e.alloc(0x5000); e.w8(p + 0x2bd8, 0x1f); e.w64(p + 0x47c0, 0)
rec_fb = e.alloc(0x600)
e.w64(G + TBL, e.uc.mem_read(G + TBL, 8) and struct.unpack('<Q', e.uc.mem_read(G+TBL,8))[0])
rax, err = e.call(ATTR_get, rcx=p, rdx=0x14)
print(f"  ent 0x1f (out of range) -> {rax & 0xFF}  (= entity 0's value {planted[(0,0x14)]}) err={err}")
# NOTE: byte is SIGNED (movsx). test a negative entity byte
p2 = e.alloc(0x5000); e.w8(p2 + 0x2bd8, 0xFF); e.w64(p2 + 0x47c0, 0)
rax, err = e.call(ATTR_get, rcx=p2, rdx=0x14)
print(f"  ent 0xff (=-1 signed)   -> rax={rax:#x} err={err}   <-- NEGATIVE INDEX IS NOT GUARDED")

# --- E2 the inline sequence --------------------------------------------------
print()
print("=== E2  the 5-instruction inline, no call, run on the same world ===")
ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
CODE_BASE = 0x0CC00000
slot = [0]
for IDX in (0x14, 0x2c, 0x28):
    slot[0] += 1
    CODE_VA = CODE_BASE + slot[0]*0x10000
    src = f"""
        mov   rax, {GLOBAL_PTR}
        mov   rax, qword ptr [rax]
        test  rax, rax
        jz    skip
        movsxd r10, ebx
        cmp   r10d, 0x1f
        jae   skip
        imul  r10, r10, {STRIDE}
        mov   rax, qword ptr [rax + r10 + {TBL}]
        test  rax, rax
        jz    skip
        movzx eax, byte ptr [rax + {ARR + IDX}]
        jmp   done
     skip:
        mov   eax, 40
     done:
        hlt
    """
    code, _ = ks.asm(src, CODE_VA)
    code = bytes(code)
    mism = 0
    for ent in range(0, 22):
        e.run_block(CODE_VA, code, CODE_VA, CODE_VA + len(code) - 1,
                    regs={X.UC_X86_REG_RBX: ent})
        got = e.uc.reg_read(X.UC_X86_REG_RAX) & 0xFFFFFFFF
        want = planted[(ent, IDX)]
        mism += got != want
    print(f"  idx {IDX:#04x}: {len(code)} bytes of code, entities 0..21  -> "
          f"{'ALL MATCH ATTR_get' if mism==0 else f'{mism} mismatches'}")
    print(f"     sample ent 0..10: {[planted[(k,IDX)] for k in range(11)]}")

# null-global guard
e.w64(GLOBAL_PTR, 0)
e.run_block(CODE_VA, code, CODE_VA, CODE_VA + len(code) - 1, regs={X.UC_X86_REG_RBX: 3})
print(f"  global NULL -> eax={e.uc.reg_read(X.UC_X86_REG_RAX)} (guard returns the 40 floor, no fault)")
rax, err = e.call(ATTR_get, rcx=players[3], rdx=0x14)
print(f"  global NULL -> ATTR_get itself: rax={rax:#x} err={err}")

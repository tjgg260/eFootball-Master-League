#!/usr/bin/env python3
"""emu_contact_request.py - Unicorn proof of the FULL action-request chain in eFootball.exe.

Closes the question every earlier pass left open: WHO CALLS vf2 (canStart).

    match::AnimePlayer::tryStartAction  0x143eb4f40 (work, requestedKind)
        -> currentKind = byte [work+0xad0]
        -> if currentKind in {0,1}          : start immediately
        -> else action = registry[requestedKind]
               ok = action->vtable[0x10](action, work)      <-- vf2, canStart
               if ok: start
        -> start == call 0x143eb4fd0 (the current-kind setter)

This harness runs the REAL bytes of 0x143eb4f40, the REAL Move::vf2 / Dribble::vf2 /
Tackle::vf2 and the REAL Stagger::vf14 against a synthetic action registry and a
synthetic MbInfoManager, and reports whether a request STARTS or is DROPPED.

Images are opened READ-ONLY.  Every patch is an overlay inside the emulator only.

    python tools/emu_contact_request.py
"""
import struct, mmap, sys
from unicorn import *
from unicorn.x86_const import *

PRISTINE = r"C:\Users\tjgg2\Backups\eFootball\eFootball.exe.PRISTINE"
INSTALLED = r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe"


class Img:
    def __init__(s, p):
        s.f = open(p, 'rb')
        s.m = mmap.mmap(s.f.fileno(), 0, access=mmap.ACCESS_READ)
        d = s.m[:0x1000]
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        n = struct.unpack_from("<H", d, pe + 6)[0]
        o = struct.unpack_from("<H", d, pe + 20)[0]
        s.secs = []
        for i in range(n):
            x = d[pe + 24 + o + 40 * i: pe + 24 + o + 40 * (i + 1)]
            vs, va, rs, raw = struct.unpack_from("<IIII", x, 8)
            s.secs.append((va, vs, raw, rs))

    def off(s, rva):
        for va, vs, raw, rs in s.secs:
            if va <= rva < va + vs:
                d = rva - va
                return raw + d if d < rs else None
        return None

    def read(s, va, n):
        o = s.off(va - 0x140000000)
        return None if o is None else s.m[o:o + n]


PAGE = 0x1000
ARENA = 0x10000000
MGR = ARENA + 0x1000
TABLE = ARENA + 0x2000
KFPOOL = ARENA + 0x40000
VECPOOL = ARENA + 0x50000
VTPOOL = ARENA + 0x58000      # synthetic vtables
OBJPOOL = ARENA + 0x5c000     # synthetic action objects
WORK = ARENA + 0x60000        # match::AnimePlayer
STACK = 0x20000000
RETM = 0x7FFF0000

REQUEST = 0x143eb4f40         # tryStartAction(work, kind)
STARTER = 0x143eb4fd0         # the current-kind setter == "the action actually begins"

VF2 = {     # action kind -> its real canStart
    0x02: 0x143f688c0,        # Move
    0x04: 0x143f99eb0,        # Dribble
    0x07: 0x143f89ef0,        # Trap
    0x0b: 0x143f704f0,        # Sliding
    0x0d: 0x143f7ca30,        # Tackle
    0x0e: 0x143efb9a0,        # Block
    0x12: 0x143fabac0,        # Feint      (vtable slot 2, from build/exe_map.json)
    0x14: 0x143f6d870,        # Reaction
}
VF14 = {    # current action kind -> its real "may I be interrupted"
    0x0f: 0x143f00d00,        # Dive      (shares FallDown::vf14)
    0x10: 0x143f00de0,        # Stagger
    0x11: 0x143f00d00,        # FallDown
}
KINDNAME = {0x02: 'Move', 0x04: 'Dribble', 0x07: 'Trap', 0x0b: 'Sliding', 0x0d: 'Tackle',
            0x0e: 'Block', 0x12: 'Feint', 0x14: 'Reaction',
            0x0f: 'Dive', 0x10: 'Stagger', 0x11: 'FallDown'}


def f2i(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


class E:
    def __init__(s, img, patches=None):
        s.img = img
        s.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        s.mapped = set()
        s.uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED |
                      UC_HOOK_MEM_FETCH_UNMAPPED, s._miss)
        for a, n in ((ARENA, 0x70000), (STACK - 0x20000, 0x40000), (RETM, 0x1000)):
            s._map(a, n)
        for a in (REQUEST, STARTER, 0x143eee720,
                  0x143f00de0, 0x143f00d00, 0x143e99e20, 0x143e99b70, 0x143e9b220,
                  0x143e9a390, 0x143e9a1a0, 0x1443120f0, 0x144311e40):
            s._load(a, 0x700)
        for a in VF2.values():
            s._load(a, 0x300)
        if patches:
            for va, b in patches:
                s.uc.mem_write(va, b)
        s.cur = 0
        s.fps = 60.0
        s.started = False
        s.uc.hook_add(UC_HOOK_CODE, s._hook)
        s.uc.mem_write(RETM, b"\xcc" * 16)

    def _map(s, a, n):
        a0 = a & ~0xFFF
        e = (a + n + 0xFFF) & ~0xFFF
        for p in range(a0, e, PAGE):
            if p not in s.mapped:
                s.uc.mem_map(p, PAGE)
                s.mapped.add(p)

    def _miss(s, uc, t, addr, sz, v, u):
        p = addr & ~0xFFF
        if p in s.mapped:
            return True
        uc.mem_map(p, PAGE)
        s.mapped.add(p)
        b = s.img.read(p, PAGE)
        if b and len(b) == PAGE:
            uc.mem_write(p, b)
        return True

    def _load(s, va, n):
        s._map(va, n)
        b = s.img.read(va, n)
        if b:
            s.uc.mem_write(va, b[:n])

    def _ret(s):
        uc = s.uc
        sp = uc.reg_read(UC_X86_REG_RSP)
        r = struct.unpack("<Q", uc.mem_read(sp, 8))[0]
        uc.reg_write(UC_X86_REG_RSP, sp + 8)
        uc.reg_write(UC_X86_REG_RIP, r)

    def _hook(s, uc, addr, size, ud):
        if addr == 0x143e940a0:                       # MbInfoManager singleton
            uc.reg_write(UC_X86_REG_RAX, MGR)
            s._ret()
        elif addr == 0x14533ea80:                     # global anime speed / fps
            uc.reg_write(UC_X86_REG_XMM0, f2i(s.fps))
            s._ret()
        elif addr == 0x143ea9040:                     # current animation frame
            uc.reg_write(UC_X86_REG_RAX, s.cur)
            s._ret()
        elif addr == STARTER:                         # the action actually begins
            s.started = True
            uc.reg_write(UC_X86_REG_RAX, 0)
            s._ret()

    def world(s, curkind, kf3, kf5, motion, sub):
        uc = s.uc
        uc.mem_write(MGR, b"\0" * 0x40)
        rec = TABLE + motion * 0x1f8
        s._map(rec, 0x200)
        uc.mem_write(rec, b"\0" * 0x1f8)
        uc.mem_write(MGR + 8, struct.pack("<Q", TABLE))
        uc.mem_write(KFPOOL, b"\0" * 0x2000)
        uc.mem_write(VECPOOL, b"\0" * 0x2000)
        kp = [KFPOOL]
        vp = [VECPOOL]

        def enc(ch, frame):
            if ch == 3:
                return (frame // 2) & 0x1fff
            if ch == 5:
                return ((frame // 2 - 2) & 0x3ff) << 13
            raise ValueError(ch)

        def put(ch, fr):
            if fr is None:
                return
            base = vp[0]
            for v in fr:
                uc.mem_write(kp[0], struct.pack("<I", enc(ch, v)) + b"\0" * 12)
                uc.mem_write(vp[0], struct.pack("<Q", kp[0]))
                kp[0] += 16
                vp[0] += 8
            uc.mem_write(rec + 0x18 * ch, struct.pack("<Q", base))
            uc.mem_write(rec + 0x18 * ch + 8, struct.pack("<Q", vp[0]))
            uc.mem_write(rec + 0x18 * ch + 16, struct.pack("<Q", vp[0]))

        put(3, kf3)
        put(5, kf5)
        # AnimePlayer
        uc.mem_write(WORK, b"\0" * 0x5000)
        uc.mem_write(WORK + 0xad0, bytes([curkind]))
        uc.mem_write(WORK + 0xae8, struct.pack("<H", motion))
        uc.mem_write(WORK + 0x2bdc, bytes([sub]))
        # --- synthetic action registry at (WORK+0xd30) + 0x1b20 + kind*8 ---
        cont = WORK + 0xd30
        uc.mem_write(cont + 0x1b20, b"\0" * (0x71 * 8))
        vt = [VTPOOL]
        ob = [OBJPOOL]

        def mk(kind):
            v = vt[0]
            vt[0] += 0x200
            o = ob[0]
            ob[0] += 0x40
            uc.mem_write(v, b"\0" * 0x200)
            if kind in VF2:
                uc.mem_write(v + 0x10, struct.pack("<Q", VF2[kind]))
            if kind in VF14:
                uc.mem_write(v + 0x70, struct.pack("<Q", VF14[kind]))
            uc.mem_write(o, struct.pack("<Q", v))
            uc.mem_write(cont + 0x1b20 + kind * 8, struct.pack("<Q", o))

        for k in set(list(VF2.keys()) + list(VF14.keys()) + [curkind]):
            mk(k)

    def request(s, kind, curkind, frame, kf3=None, kf5=None, motion=0x221, sub=0):
        """Emulate tryStartAction(work, kind). Returns 'STARTED' or 'DROPPED'."""
        s.cur = frame
        s.world(curkind, kf3, kf5, motion, sub)
        s.started = False
        uc = s.uc
        uc.reg_write(UC_X86_REG_RSP, STACK)
        uc.mem_write(STACK, struct.pack("<Q", RETM))
        uc.reg_write(UC_X86_REG_RCX, WORK)
        uc.reg_write(UC_X86_REG_RDX, kind)
        try:
            uc.emu_start(REQUEST, RETM, count=500000)
        except UcError as ex:
            return "ERR:" + str(ex)
        return "STARTED" if s.started else "DROPPED"

    def first_frame(s, kind, curkind, **kw):
        for f in range(0, 200):
            if s.request(kind, curkind, f, **kw) == "STARTED":
                return f
        return None


def main():
    img = Img(PRISTINE)
    inst = Img(INSTALLED)
    KEYS = dict(kf3=[64], kf5=[16, 32, 48])

    out = []

    def P(*a):
        line = " ".join(str(x) for x in a)
        print(line)
        out.append(line)

    P("emu_contact_request - the FULL action-request chain, eFootball.exe PRISTINE")
    P("real bytes: 0x143eb4f40 (requester) -> <action>::vf2 -> Stagger/FallDown::vf14")
    P("synthetic motion: channel-5 cancel keys at frames 16/32/48, channel-3 end key at 64")
    P("")

    P("### 0. site bytes: INSTALLED vs PRISTINE (all must be SAME = still stock)")
    sites = [(0x143f00efa, 1, "Stagger::vf14 kind==4 jne (headline)"),
             (0x143f688de, 1, "Move::vf2 'sub ecx,7' imm8"),
             (0x143f00e13, 8, "Stagger::vf14 scale load"),
             (0x143f00d71, 2, "FallDown::vf14 sub==2 jne"),
             (0x143f7caee, 1, "Tackle::vf2 table[Stagger]"),
             (0x143f7caef, 1, "Tackle::vf2 table[FallDown]"),
             (0x143f99f6f, 1, "Dribble::vf2 table[FallDown]"),
             (0x143f99f6d, 1, "Dribble::vf2 table[Dive]"),
             (0x143f00af8, 8, "Stagger::vf32 K load (balance term)"),
             (0x143f7037d, 3, "Sliding::vf14 refuse default")]
    for va, n, lab in sites:
        a = img.read(va, n)
        b = inst.read(va, n)
        P("  %-12s %-40s pristine=%-18s installed=%-18s %s" %
          (hex(va), lab, a.hex().upper(), b.hex().upper(),
           "SAME" if a == b else "*** DIFFERS ***"))
    P("")

    P("### 1. THE REQUESTER IS REAL: request(kind) while the player is in a STAGGER")
    P("    STARTED = the action begins;  DROPPED = vf2 refused, input is thrown away")
    e = E(img)
    P("    %-10s %-12s %-12s %-12s" % ("request", "cur=Move(2)", "cur=Stagger", "cur=FallDown"))
    for k in (0x02, 0x04, 0x07, 0x0d, 0x0b, 0x12, 0x14):
        row = []
        for cur in (0x02, 0x10, 0x11):
            r = e.request(k, cur, 120, **KEYS)      # frame 120 = long past every cancel key
            row.append(r)
        P("    %-10s %-12s %-12s %-12s" % (KINDNAME[k], row[0], row[1], row[2]))
    P("")
    P("    Read the Stagger column: at frame 120, LONG after every cancel key has passed,")
    P("    Move / Tackle / Sliding / Feint / Reaction are STILL dropped. That is the")
    P("    eligibility filter, not a timing window - waiting does not help.")
    P("")

    P("### 2. HEADLINE LEVER - Stagger::vf14 0x143f00efa 75->EB (Dribble uses the FIRST key)")
    ed = E(img, patches=[(0x143f00efa, b"\xeb")])
    P("    first frame at which the request STARTS, current action = Stagger:")
    P("    %-10s %-10s %-10s" % ("request", "stock", "patched"))
    for k in (0x04, 0x07):
        P("    %-10s %-10s %-10s" % (KINDNAME[k], e.first_frame(k, 0x10, **KEYS),
                                     ed.first_frame(k, 0x10, **KEYS)))
    for kf5, lab in (([16], "1 cancel key"), (None, "no cancel key"), ([8, 40], "keys 8/40")):
        KK = dict(kf3=[64], kf5=kf5)
        P("    Dribble, %-14s stock=%-6s patched=%-6s" %
          (lab, e.first_frame(0x04, 0x10, **KK), ed.first_frame(0x04, 0x10, **KK)))
    P("")

    P("### 3. ALTERNATIVE LEVER - Move::vf2 0x143f688de 07->BA ('sub ecx,7' -> 'sub ecx,-0x46')")
    P("    moves Move's three delegate slots from current kinds 0x5d/0x5e/0x5f to 0x10/0x11/0x12")
    em = E(img, patches=[(0x143f688de, b"\xba")])
    P("    %-22s %-12s %-12s" % ("current action", "stock", "patched"))
    for cur in (0x10, 0x11, 0x0f):
        P("    %-22s %-12s %-12s" % ("Move while " + KINDNAME[cur],
                                     e.request(0x02, cur, 120, **KEYS),
                                     em.request(0x02, cur, 120, **KEYS)))
    P("    first frame Move STARTS out of a Stagger, patched: %s  (stock: never)" %
      em.first_frame(0x02, 0x10, **KEYS))
    P("    first frame Move STARTS out of a FallDown, patched: %s  (stock: never)" %
      em.first_frame(0x02, 0x11, **KEYS))
    P("")

    P("### 4. COMBINED - headline + alternative together, current action = Stagger")
    eb = E(img, patches=[(0x143f00efa, b"\xeb"), (0x143f688de, b"\xba")])
    for k in (0x02, 0x04, 0x07):
        P("    %-10s first START frame = %s" % (KINDNAME[k], eb.first_frame(k, 0x10, **KEYS)))
    P("")

    P("### 5. ELIGIBILITY LEVERS - one table byte each, frame 120 (long past every cancel key)")
    P("    each switch byte-table is indexed by (currentKind - 2); Stagger 0x10 -> +0x0e,")
    P("    FallDown 0x11 -> +0x0f.  Candidate values swept, stock value marked.")
    for tbl, kind, lab, cur, idx in ((0x143f7cae0, 0x0d, "Tackle from Stagger", 0x10, 0x0e),
                                     (0x143f7cae0, 0x0d, "Tackle from FallDown", 0x11, 0x0f),
                                     (0x143f70590, 0x0b, "Sliding from Stagger", 0x10, 0x0e),
                                     (0x143fabb44, 0x12, "Feint from Stagger", 0x10, 0x0e),
                                     (0x143f6d8e0, 0x14, "Reaction from Stagger", 0x10, 0x0e),
                                     (0x143f99f60, 0x04, "Dribble from FallDown", 0x11, 0x0f)):
        va = tbl + idx
        stock = img.read(va, 1)[0]
        res = []
        for v in range(0, 5):
            ee = E(img, patches=[(va, bytes([v]))])
            r = ee.request(kind, cur, 120, **KEYS)
            if r != "STARTED":
                tag = "no"
            else:
                ff = ee.first_frame(kind, cur, **KEYS)
                # frame 0 == allowed outright (no gate, NO WEIGHT);
                # frame >0 == the cancel gate is still enforced (WEIGHT KEPT)
                tag = "GO@%d%s" % (ff, "!" if ff == 0 else "")
            res.append("%d=%-7s%s" % (v, tag, "(stock)" if v == stock else ""))
        P("    %-24s %s -> %s" % (lab, hex(va), " ".join(res)))
    P("")
    P("    GO@0!  = allowed OUTRIGHT, the cancel gate is never consulted -> NO WEIGHT, do not use")
    P("    GO@16  = routed to the cancel gate, opens at the first cancel key -> WEIGHT KEPT")
    P("")

    P("### 6. WEIGHT CHECK - the patched gates are still GATES, not open doors")
    P("    Dribble out of a Stagger with the headline byte, by frame:")
    row = []
    for f in (0, 4, 8, 12, 15, 16, 17, 32):
        row.append("%d:%s" % (f, "GO" if ed.request(0x04, 0x10, f, **KEYS) == "STARTED" else "no"))
    P("      " + "  ".join(row))
    P("    -> still refused for the first 16 frames. The stagger keeps its weight;")
    P("       it stops being 3x longer for the ball carrier than for everyone else.")
    P("")

    P("### 7. THE EXACT SHIPPING COMBINATIONS (first frame the request STARTS)")
    SPECS = {
        "contact-dribble-cancel-early":   [(0x143f00efa, b"\xeb")],
        "contact-move-out-of-stagger":    [(0x143f688de, b"\xba")],
        "contact-fight-back-from-stagger": [(0x143f7caee, b"\x01"),
                                            (0x143fabb52, b"\x00"),
                                            (0x143f6d8ee, b"\x00")],
        "contact-getup-from-falldown":    [(0x143f00d71, b"\x66\x90"),
                                           (0x143f99f6f, b"\x02"),
                                           (0x143f99f6d, b"\x02")],
    }
    CASES = [(0x04, 0x10, "Dribble out of a Stagger"),
             (0x07, 0x10, "Trap    out of a Stagger"),
             (0x02, 0x10, "Move    out of a Stagger"),
             (0x0d, 0x10, "Tackle  out of a Stagger"),
             (0x12, 0x10, "Feint   out of a Stagger"),
             (0x14, 0x10, "Reaction out of a Stagger"),
             (0x04, 0x11, "Dribble off the FLOOR"),
             (0x07, 0x11, "Trap    off the FLOOR")]
    names = ["stock"] + list(SPECS)
    engines = [E(img)] + [E(img, patches=p) for p in SPECS.values()]
    P("    %-26s %s" % ("", "  ".join("%-10s" % n[8:18] for n in names)))
    for k, cur, lab in CASES:
        cells = []
        for en in engines:
            ff = en.first_frame(k, cur, **KEYS)
            cells.append("%-10s" % ("never" if ff is None else str(ff)))
        P("    %-26s %s" % (lab, "  ".join(cells)))
    P("")
    P("    ('never' = the eligibility filter drops it at every frame - the lockout the")
    P("     owner is describing.  A number = the frame the cancel gate opens.)")
    P("")
    P("### 8. STACKING CHECK - do not apply these two together without meaning to")
    for combo, lab in (([(0x143f00efa, b"\xeb"), (0x143f00e13, None)], "headline + scale x2"),):
        pass
    def reaim(va, tgt):
        b = bytearray(img.read(va, 8))
        b[4:8] = struct.pack("<i", tgt - (va + 8))
        return (va, bytes(b))
    e_scale = E(img, patches=[reaim(0x143f00e13, 0x147850490)])
    e_both = E(img, patches=[(0x143f00efa, b"\xeb"), reaim(0x143f00e13, 0x147850490)])
    P("    Dribble out of a Stagger:")
    P("      stock                                  %s" % e.first_frame(0x04, 0x10, **KEYS))
    P("      contact-cancel-window-x2 alone         %s" % e_scale.first_frame(0x04, 0x10, **KEYS))
    P("      contact-dribble-cancel-early alone     %s" % ed.first_frame(0x04, 0x10, **KEYS))
    P("      BOTH together                          %s   <- 6x, too far" %
      e_both.first_frame(0x04, 0x10, **KEYS))

    with open("build/emu_contact_request_proof.txt", "w") as f:
        f.write("\n".join(out) + "\n")
    print("\nwritten: build/emu_contact_request_proof.txt")


main()

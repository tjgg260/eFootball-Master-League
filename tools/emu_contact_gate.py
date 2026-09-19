#!/usr/bin/env python3
"""
emu_contact_gate.py - EMULATION PROOFS for the "I get tackled and then I cannot do anything"
work. READ-ONLY on the game: nothing here writes eFootball.exe.

The model it proves (see docs/exe-gameplay-map.md):

  * match::AnimePlayer holds the CURRENT action kind in one byte at +0xad0 and the action
    registry (match::anime::ActionManager) at +0xd30; registry entry = pool[0x1b20 + kind*8],
    fetched by 0x143eee720.
  * every action class X has TWO gates:
        X::vf2 (vtable slot 2)  "may I START, given the current action kind?"
            -> ALLOW outright | DELEGATE to currentAction->vf14(kind) | REFUSE
        X::vf14 (vtable slot 14) "may I be interrupted by action <kind>?"
            -> default in match::anime::action::Base is 'xor al,al' = NEVER
  * Stagger::vf14 (0x143f00de0) and FallDown::vf14 (0x143f00d00) answer by comparing the
    animation's current frame against a key frame taken from the animation's own type-5 event
    data: 1 iff currentFrame >= keyFrame AND keyFrame > 0.  keyFrame == 0 => never.

    python tools/emu_contact_gate.py        # runs all three proofs, in order:
                                            #  1. X::vf2 start-permission matrix
                                            #  2. Stagger/FallDown::vf14 truth tables + patch diff
                                            #  3. Move::vf2 one-byte re-aim differential

Needs: unicorn, capstone.  Reuses the lazy-mapping harness in tools/emu_spin.py.
"""



# ======================================================================================
# from emu_vf2.py
# ======================================================================================
#!/usr/bin/env python3
"""EMULATED probe: for each anime::action class X and each CURRENT action kind K,
run X::vf2(this, ctx) on the game's own bytes and record whether the start is
ALLOWED outright, DELEGATED to currentAction->vf14(kind), or REFUSED."""
import sys, json, struct
sys.path.insert(0,'tools')
sys.path.insert(0,'.')
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED, UcError
from unicorn import x86_const as X
import importlib.util
spec=importlib.util.spec_from_file_location("emu_spin","tools/emu_spin.py")
es=importlib.util.module_from_spec(spec); spec.loader.exec_module(es)

img=es.Image()
B=img.base
mp=json.load(open('build/exe_map.json',encoding='utf-8'))

SENT_VF14 = 0x7FFD00001000
SENT_OTHER= 0x7FFD00002000

def probe(vf2_rva, kind, vf14_answer=1, fn_span=0x600):
    e=es.Emu(img)
    uc=e.uc
    uc.mem_map(0x7FFD00000000, 0x10000)
    ctx = e.alloc(0x8000)
    uc.mem_write(ctx, b"\x00"*0x8000)
    e.w8(ctx+0xad0, kind)
    e.w8(ctx+0x2bd8, 0)
    pool = ctx+0xd30
    fakevft = e.alloc(0x400)
    uc.mem_write(fakevft, b"\x00"*0x400)
    fakeact = e.alloc(0x40)
    e.w64(fakeact, fakevft)
    for s in range(0x40):
        e.w64(fakevft+8*s, SENT_OTHER)
    e.w64(fakevft+0x70, SENT_VF14)   # vf14
    e.w64(fakevft+0xe8, SENT_OTHER)  # vf29 getKind
    for k in range(0x71):
        e.w64(pool+0x1b20+8*k, fakeact)
    this = e.alloc(0x400); uc.mem_write(this, b"\x00"*0x400)
    thisvft = e.alloc(0x400); uc.mem_write(thisvft, b"\x00"*0x400)
    for s in range(0x40): e.w64(thisvft+8*s, SENT_OTHER)
    e.w64(this, thisvft)

    state={'vf14':None,'kindarg':None}
    lo, hi = B+vf2_rva, B+vf2_rva+fn_span
    REG_LO, REG_HI = B+0x3eee720, B+0x3eee760
    def code(uc_, addr, size, ud):
        if addr==SENT_VF14:
            state['vf14']=True
            state['kindarg']=uc_.reg_read(X.UC_X86_REG_R8) & 0xFFFFFFFF
            uc_.reg_write(X.UC_X86_REG_RAX, vf14_answer)
            e.ret(); return
        if addr==SENT_OTHER:
            uc_.reg_write(X.UC_X86_REG_RAX, 0)
            e.ret(); return
        if lo<=addr<hi: return
        if REG_LO<=addr<REG_HI: return
        if addr==es.RET_MAGIC: return
        # unexpected callee -> stub it out returning 0
        uc_.reg_write(X.UC_X86_REG_RAX, 0)
        e.ret()
    uc.hook_add(UC_HOOK_CODE, code)
    try:
        r=e.call(B+vf2_rva, rcx=this, rdx=ctx, max_insn=200000)
    except Exception as ex:
        return ('ERR:'+str(ex)[:60], None)
    al = uc.reg_read(X.UC_X86_REG_RAX) & 0xFF
    if state['vf14']:
        return ('ASK', state['kindarg'], al)
    return ('ALLOW' if al else 'REFUSE', None, al)

CUR = {0x10:'Stagger',0x11:'FallDown',0x0f:'Dive',0x0b:'Sliding',0x0d:'Tackle',0x54:'Jostle',0x02:'Move',0x04:'Dribble',0x07:'Trap',0x14:'Reaction'}
want = ['Move','Dribble','Trap','Kick','Feint','BodyFeint','Dodge','Sliding','Tackle','Jostle','Contact','StepMove','Reaction','Block','RecieveBall','CarryBall','ComeBack','ResetIdle']
cls={}
for c,lst in mp['classes'].items():
    if '::anime::action::' not in c: continue
    n=c.split('::')[-1]
    if n in want and '::goal_keeper::' not in c:
        cls[n]=lst[0]['methods'][2]

print(f"{'requested action':16} " + " ".join(f"{CUR[k]:>10}" for k in sorted(CUR)))
for n in want:
    if n not in cls: continue
    row=[]
    for k in sorted(CUR):
        r=probe(cls[n], k)
        if r[0]=='ASK': row.append(f"ask({r[1]:#x})")
        else: row.append(r[0])
    print(f"{n:16} " + " ".join(f"{x:>10}" for x in row))



# ======================================================================================
# from emu_vf14.py
# ======================================================================================
#!/usr/bin/env python3
"""EMULATED: Stagger::vf14 / FallDown::vf14 - 'may action <kind> interrupt me?'
Runs the game's own bytes with the six anime-data callees stubbed."""
import sys, json, struct
sys.path.insert(0,'tools')
from unicorn import UC_HOOK_CODE
from unicorn import x86_const as X
import importlib.util
spec=importlib.util.spec_from_file_location("emu_spin","tools/emu_spin.py")
es=importlib.util.module_from_spec(spec); spec.loader.exec_module(es)
img=es.Image(); B=img.base

# stubs (VA -> returns)
MOTION_MGR = 0x600000010000
def run(fn, kind, motion, keyA, keyB, keyC, curframe, evt5, evt5b, overlay=None, span=0x400):
    e=es.Emu(img, overlay or {})
    uc=e.uc
    ctx=e.alloc(0x9000); uc.mem_write(ctx, b"\0"*0x9000)
    uc.mem_write(ctx+0xae8, struct.pack('<H', motion))
    e.w8(ctx+0x2bdc, 0)
    this=e.alloc(0x200); uc.mem_write(this, b"\0"*0x200)
    log=[]
    lo,hi=B+fn, B+fn+span
    STUBS={
      0x143e940a0: ('mgr', lambda: MOTION_MGR),
      0x14533ea80: ('flt', None),
      0x143e99e20: ('keyA', None),
      0x143e99b70: ('keyB', None),
      0x143e9b220: ('keyC', None),
      0x143e9a390: ('evt', None),
      0x143ea9040: ('cur', lambda: curframe),
    }
    def code(uc_, addr, size, ud):
        if lo<=addr<hi: return
        nm=None
        if addr in STUBS: nm=STUBS[addr][0]
        if nm=='mgr': uc_.reg_write(X.UC_X86_REG_RAX, MOTION_MGR)
        elif nm=='flt': uc_.reg_write(X.UC_X86_REG_XMM0, 0)
        elif nm=='keyA':
            r9=uc_.reg_read(X.UC_X86_REG_R9)&0xFFFFFFFF
            uc_.reg_write(X.UC_X86_REG_RAX, keyA if r9==0 else keyC)
            log.append(('keyA',r9))
        elif nm=='keyB': uc_.reg_write(X.UC_X86_REG_RAX, keyB); log.append(('keyB',))
        elif nm=='keyC': uc_.reg_write(X.UC_X86_REG_RAX, keyC); log.append(('keyC',))
        elif nm=='evt':
            r8=uc_.reg_read(X.UC_X86_REG_R8)&0xFFFFFFFF
            uc_.reg_write(X.UC_X86_REG_RAX, evt5 if r8==5 else evt5b); log.append(('evt',r8))
        elif nm=='cur': uc_.reg_write(X.UC_X86_REG_RAX, curframe)
        elif 0x144311000 <= addr < 0x144313000: return   # let the real flag-bit helpers run
        else: uc_.reg_write(X.UC_X86_REG_RAX, 0)
        e.ret()
    uc.hook_add(UC_HOOK_CODE, code)
    e.call(B+fn, rcx=this, rdx=ctx, r8=kind, max_insn=200000)
    return uc.reg_read(X.UC_X86_REG_RAX)&0xFF, log

KINDS={2:'Move',4:'Dribble',7:'Trap',0xb:'Sliding',0xd:'Tackle',0xe:'Block',0x10:'Stagger',0x12:'Feint',0x14:'Reaction',0x15:'Dodge',0x54:'Jostle',0x44:'gk.Catch'}
STAG=0x3f00de0
PATCH={0x143f00e03: bytes.fromhex('40B701')}   # xor dil,dil -> mov dil,1
print("Stagger::vf14(0x143f00de0)  motion=0x221 (normal stagger), keyFrame=20, eventCount(type5)=1")
print(f"{'requesting action':18} {'stock@f=0':>10} {'stock@f=10':>11} {'stock@f=19':>11} {'stock@f=20':>11} {'stock@f=40':>11} | {'PATCHED@f=0':>12}")
for k,nm in KINDS.items():
    row=[]
    for cf in (0,10,19,20,40):
        r,_=run(STAG,k,0x221,20,20,20,cf,1,1)
        row.append(r)
    p,_=run(STAG,k,0x221,20,20,20,0,1,1,overlay=PATCH)
    print(f"{nm:18} " + " ".join(f"{v:>11}" for v in row) + f" | {p:>12}")
print()
print("keyFrame == 0 (animation has no type-5 cancel event):")
for k,nm in [(4,'Dribble'),(7,'Trap'),(0x12,'Feint')]:
    row=[run(STAG,k,0x221,0,0,0,cf,1,1)[0] for cf in (0,10,40,120)]
    p=run(STAG,k,0x221,0,0,0,120,1,1,overlay=PATCH)[0]
    print(f"  {nm:10} stock f=0,10,40,120 -> {row}   PATCHED f=120 -> {p}")
print()
print("FallDown::vf14 (0x143f00d00) motion=0x221 keyFrame=30:")
FD=0x3f00d00
for k,nm in KINDS.items():
    row=[run(FD,k,0x221,30,30,30,cf,1,1)[0] for cf in (0,10,29,30,60)]
    print(f"  {nm:12} f=0,10,29,30,60 -> {row}")



# ======================================================================================
# from emu_move_vf2.py
# ======================================================================================
import sys, json, struct
sys.path.insert(0,'tools')
from unicorn import UC_HOOK_CODE
from unicorn import x86_const as X
import importlib.util
spec=importlib.util.spec_from_file_location("emu_spin","tools/emu_spin.py")
es=importlib.util.module_from_spec(spec); spec.loader.exec_module(es)
img=es.Image(); B=img.base
SENT_VF14=0x7FFD00001000; SENT_OTHER=0x7FFD00002000
def probe(vf2_rva, kind, vf14_answer=1, overlay=None, span=0x600):
    e=es.Emu(img, overlay or {}); uc=e.uc
    uc.mem_map(0x7FFD00000000,0x10000)
    ctx=e.alloc(0x9000); uc.mem_write(ctx,b"\0"*0x9000); e.w8(ctx+0xad0,kind)
    pool=ctx+0xd30
    fv=e.alloc(0x400); uc.mem_write(fv,b"\0"*0x400)
    fa=e.alloc(0x40); e.w64(fa,fv)
    for s in range(0x40): e.w64(fv+8*s,SENT_OTHER)
    e.w64(fv+0x70,SENT_VF14)
    for k in range(0x71): e.w64(pool+0x1b20+8*k,fa)
    this=e.alloc(0x400); uc.mem_write(this,b"\0"*0x400)
    tv=e.alloc(0x400); uc.mem_write(tv,b"\0"*0x400)
    for s in range(0x40): e.w64(tv+8*s,SENT_OTHER)
    e.w64(this,tv)
    st={'ask':False,'k':None}
    lo,hi=B+vf2_rva,B+vf2_rva+span
    RL,RH=B+0x3eee720,B+0x3eee760
    def code(uc_,addr,size,ud):
        if addr==SENT_VF14:
            st['ask']=True; st['k']=uc_.reg_read(X.UC_X86_REG_R8)&0xFFFFFFFF
            uc_.reg_write(X.UC_X86_REG_RAX,vf14_answer); e.ret(); return
        if addr==SENT_OTHER: uc_.reg_write(X.UC_X86_REG_RAX,0); e.ret(); return
        if lo<=addr<hi or RL<=addr<RH or addr==es.RET_MAGIC: return
        uc_.reg_write(X.UC_X86_REG_RAX,0); e.ret()
    uc.hook_add(UC_HOOK_CODE,code)
    e.call(B+vf2_rva,rcx=this,rdx=ctx,max_insn=200000)
    al=uc.reg_read(X.UC_X86_REG_RAX)&0xFF
    return ('ask' if st['ask'] else ('ALLOW' if al else 'refuse')), st['k']
MOVE=0x3f688c0
PATCH={0x143f688de: bytes.fromhex("BA")}   # sub ecx,7 -> sub ecx,-0x46
names={0x00:'(0)',0x02:'Move',0x03:'(kind3)',0x04:'Dribble',0x07:'Trap',0x0b:'Sliding',0x0d:'Tackle',0x0f:'Dive',0x10:'Stagger',0x11:'FallDown',0x12:'Feint',0x14:'Reaction',0x15:'Dodge',0x17:'CarryBall',0x54:'Jostle',0x56:'DemoMove',0x5c:'InplayDemoContact',0x5d:'InplayDemoKickFail',0x5e:'InplayDemoFatInj',0x5f:'InplayDemoMove'}
print("Move::vf2 (0x143f688c0) - may a plain locomotion action barge in on the current action?")
print(f"{'current action':22} {'STOCK':>10}   {'1-BYTE RE-AIM':>14}")
for k in sorted(names):
    a,_=probe(MOVE,k)
    b,bk=probe(MOVE,k,overlay=PATCH)
    mark='   <==' if a!=b else ''
    print(f"{names[k]+' ('+hex(k)+')':22} {a:>10}   {b:>14}{mark}")

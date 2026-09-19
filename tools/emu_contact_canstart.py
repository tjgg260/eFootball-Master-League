#!/usr/bin/env python3
"""emu_contact_canstart.py - which actions may even be STARTED while a
contact action (Stagger/FallDown/Dive) is running.  Emulates every
match::anime::action::*::vf2 (canStart) with the current action kind forced, and reports
REFUSE / ALLOW / GATED(vf14).  READ-ONLY on the exe images.

    python tools/emu_contact_canstart.py
"""
"""For each anime::action class, ask vf2(canStart) with the player's CURRENT action kind
   set to Stagger(0x10) / FallDown(0x11) / Dive(0x0f), and report whether it
   (a) refuses outright, (b) allows outright, or (c) consults the current action's vf14 gate."""
import struct, mmap, json
from unicorn import *
from unicorn.x86_const import *
PR=r"C:\Users\tjgg2\Backups\eFootball\eFootball.exe.PRISTINE"
REPO=r"C:/Users/tjgg2/Downloads/eFootball Master League/.claude/worktrees/dt270-full-decode-12718b"
class Img:
    def __init__(s,p):
        s.f=open(p,'rb'); s.m=mmap.mmap(s.f.fileno(),0,access=mmap.ACCESS_READ)
        d=s.m[:0x1000]; pe=struct.unpack_from("<I",d,0x3C)[0]
        n=struct.unpack_from("<H",d,pe+6)[0]; o=struct.unpack_from("<H",d,pe+20)[0]
        s.secs=[]
        for i in range(n):
            x=d[pe+24+o+40*i: pe+24+o+40*(i+1)]
            vs,va,rs,raw=struct.unpack_from("<IIII",x,8); s.secs.append((va,vs,raw,rs))
    def read(s,va,n):
        r=va-0x140000000
        for va0,vs,raw,rs in s.secs:
            if va0<=r<va0+vs:
                d=r-va0
                if d<rs: return s.m[raw+d:raw+d+n]
        return None
img=Img(PR)
ARENA=0x10000000; WORK=ARENA+0x10000; FAKEACT=ARENA+0x1000; FAKEVT=ARENA+0x2000
MARK14=0x60000000; MARK29=0x60001000
STACK=0x20000000; RETM=0x7FFF0000
class E:
    def __init__(s):
        s.uc=Uc(UC_ARCH_X86,UC_MODE_64); s.mapped=set()
        s.uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED|UC_HOOK_MEM_WRITE_UNMAPPED|UC_HOOK_MEM_FETCH_UNMAPPED,s._m)
        for a,n in ((ARENA,0x20000),(STACK-0x20000,0x40000),(RETM,0x1000),(MARK14,0x2000)):
            s._map(a,n)
        s.uc.mem_write(MARK14,b"\xc3"*16); s.uc.mem_write(MARK29,b"\xc3"*16)
        s.uc.mem_write(RETM,b"\xcc"*16)
        s.hit=[]
        s.uc.hook_add(UC_HOOK_CODE,s._h)
        s.kind=0x10
    def _map(s,a,n):
        a0=a&~0xFFF;e=(a+n+0xFFF)&~0xFFF
        for p in range(a0,e,0x1000):
            if p not in s.mapped: s.uc.mem_map(p,0x1000); s.mapped.add(p)
    def _m(s,uc,t,addr,sz,v,u):
        p=addr&~0xFFF
        if p in s.mapped: return True
        uc.mem_map(p,0x1000); s.mapped.add(p)
        b=img.read(p,0x1000)
        if b and len(b)==0x1000: uc.mem_write(p,b)
        return True
    def _ret(s,rax=None):
        uc=s.uc; sp=uc.reg_read(UC_X86_REG_RSP)
        r=struct.unpack("<Q",uc.mem_read(sp,8))[0]
        uc.reg_write(UC_X86_REG_RSP,sp+8)
        if rax is not None: uc.reg_write(UC_X86_REG_RAX,rax)
        uc.reg_write(UC_X86_REG_RIP,r)
    def _h(s,uc,addr,size,ud):
        if addr==0x143eee720: s._ret(FAKEACT)
        elif addr==0x1442f5070: s._ret(0)
        elif addr==MARK14: s.hit.append('ASK-vf14'); s._ret(1)
        elif addr==MARK29: s._ret(s.kind)
        elif addr in (0x144312110,0x1443121b0,0x144311b70): pass
    def run(s,vf2,curkind):
        uc=s.uc; s.hit=[]; s.kind=curkind
        uc.mem_write(WORK-0x1000,b"\0"*0x8000)
        uc.mem_write(FAKEACT,struct.pack("<Q",FAKEVT)+b"\0"*0x200)
        vt=bytearray(0x200)
        for i in range(0x40): struct.pack_into("<Q",vt,8*i,MARK14 if i==14 else (MARK29 if i==29 else MARK14+0x800))
        uc.mem_write(FAKEVT,bytes(vt))
        uc.mem_write(WORK+0xad0,bytes([curkind]))
        uc.reg_write(UC_X86_REG_RSP,STACK); uc.mem_write(STACK,struct.pack("<Q",RETM))
        uc.reg_write(UC_X86_REG_RCX,FAKEACT); uc.reg_write(UC_X86_REG_RDX,WORK)
        try: uc.emu_start(vf2,RETM,count=200000)
        except UcError as ex: return 'ERR '+str(ex)[:40]
        r=uc.reg_read(UC_X86_REG_RAX)&0xff
        return ('GATED(vf14)' if s.hit else ('ALLOW' if r else 'REFUSE'))
m=json.load(open(REPO+"/build/exe_map.json"))
e=E()
rows=[]
for name,vts in m['classes'].items():
    if not name.startswith("match::anime::action::"): continue
    meth=vts[0]['methods']
    if len(meth)<3: continue
    vf2=meth[2]+0x140000000
    if vf2 in (0x140c83810,0x140c853c0,0x140c83910,0x140c837d0): continue
    r={}
    for k in (0x10,0x11,0x0f,0x02,0x04):
        r[k]=e.run(vf2,k)
    rows.append((name.replace("match::anime::action::",""),r))
print("%-34s %-12s %-12s %-12s %-12s %-12s"%("candidate action","cur=Stagger","cur=FallDown","cur=Dive","cur=Move","cur=Dribble"))
for n,r in rows:
    if all(v=='REFUSE' for v in r.values()): continue
    print("%-34s %-12s %-12s %-12s %-12s %-12s"%(n,r[0x10],r[0x11],r[0x0f],r[0x02],r[0x04]))

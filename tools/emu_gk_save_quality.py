#!/usr/bin/env python3
"""Emulate match::anime save-quality selector 0x144032870 on the game's own bytes."""
import struct, mmap, sys
from unicorn import *
from unicorn.x86_const import *
PRISTINE=r"C:\Users\tjgg2\Backups\eFootball\eFootball.exe.PRISTINE"
INSTALLED=r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe"
class Img:
    def __init__(s,p):
        s.f=open(p,'rb'); s.m=mmap.mmap(s.f.fileno(),0,access=mmap.ACCESS_READ)
        d=s.m[:0x1000]; pe=struct.unpack_from("<I",d,0x3C)[0]
        n=struct.unpack_from("<H",d,pe+6)[0]; o=struct.unpack_from("<H",d,pe+20)[0]
        s.secs=[]
        for i in range(n):
            x=d[pe+24+o+40*i:pe+24+o+40*(i+1)]
            vs,va,rs,raw=struct.unpack_from("<IIII",x,8); s.secs.append((va,vs,raw,rs))
    def off(s,rva):
        for va,vs,raw,rs in s.secs:
            if va<=rva<va+vs:
                d=rva-va
                return raw+d if d<rs else None
        return None
    def read(s,va,n):
        o=s.off(va-0x140000000); return None if o is None else s.m[o:o+n]
def f2i(v): return struct.unpack("<I",struct.pack("<f",v))[0]
START=0x144032870; STOP=0x144032a74
ATTR=0x143ea8cb0; FLAG=0x143eadbe0
SPEED_CALLS={0x1442d6c50:'obj',0x144307000:'speed',0x14533ea80:'fps',0x1442d6fe0:'obj2',0x1442eaba0:'rec'}
def run(img, attrs, action, sub, kmh=200.0, flag=False, rec1c=0, verbose=False):
    uc=Uc(UC_ARCH_X86,UC_MODE_64); mapped=set()
    def mp(a,n=0x1000):
        for p in range(a&~0xFFF,(a+n+0xFFF)&~0xFFF,0x1000):
            if p in mapped: continue
            uc.mem_map(p,0x1000); mapped.add(p)
            b=img.read(p,0x1000)
            if b and len(b)==0x1000: uc.mem_write(p,b)
    def miss(u,t,addr,sz,v,x):
        mp(addr&~0xFFF); return True
    uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED|UC_HOOK_MEM_WRITE_UNMAPPED|UC_HOOK_MEM_FETCH_UNMAPPED,miss)
    mp(START,0x400)
    uc.mem_map(0x20000000-0x20000,0x40000)   # stack
    uc.mem_map(0x30000000,0x10000)           # fake player / records
    PLAYER=0x30001000; REC=0x30002000
    uc.mem_write(PLAYER+0x47c0, struct.pack("<Q",0x30003000))
    uc.mem_write(REC+0x1c, struct.pack("<I",rec1c))
    trace=[]
    def code(u,addr,size,x):
        b=img.read(addr,size)
        if b and b[0]==0xE8 and size==5:
            tgt=addr+5+struct.unpack("<i",b[1:5])[0]
            if tgt==ATTR:
                idx=u.reg_read(UC_X86_REG_EDX)
                v=attrs.get(idx,40)
                trace.append(('attr',hex(idx),v))
                u.reg_write(UC_X86_REG_RAX,v); u.reg_write(UC_X86_REG_RIP,addr+5); return
            if tgt==FLAG:
                idx=u.reg_read(UC_X86_REG_EDX); trace.append(('flag',hex(idx),flag))
                u.reg_write(UC_X86_REG_RAX,1 if flag else 0); u.reg_write(UC_X86_REG_RIP,addr+5); return
            if tgt in (0x1442d6c50,0x1442d6fe0):
                u.reg_write(UC_X86_REG_RAX,0x30003000); u.reg_write(UC_X86_REG_RIP,addr+5); return
            if tgt==0x1442eaba0:
                u.reg_write(UC_X86_REG_RAX,REC); u.reg_write(UC_X86_REG_RIP,addr+5); return
            if tgt==0x144307000:
                # returns |v| per tick; we want fps*3.6*|v| == kmh -> set |v| = kmh/(3.6*fps), fps=1
                u.reg_write(UC_X86_REG_XMM0,f2i(kmh/3.6)); u.reg_write(UC_X86_REG_RIP,addr+5); return
            if tgt==0x14533ea80:
                u.reg_write(UC_X86_REG_XMM0,f2i(1.0)); u.reg_write(UC_X86_REG_RIP,addr+5); return
            trace.append(('UNHOOKED CALL',hex(tgt)))
            u.reg_write(UC_X86_REG_RAX,0); u.reg_write(UC_X86_REG_RIP,addr+5); return
    uc.hook_add(UC_HOOK_CODE,code)
    uc.reg_write(UC_X86_REG_RSP,0x20000000)
    uc.reg_write(UC_X86_REG_RCX,PLAYER)
    uc.reg_write(UC_X86_REG_EDX,action)
    uc.reg_write(UC_X86_REG_R8D,sub)
    uc.emu_start(START,STOP,count=20000)
    r=uc.reg_read(UC_X86_REG_EAX)&0xffffffff
    if verbose: print(trace)
    return r

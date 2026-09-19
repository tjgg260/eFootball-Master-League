#!/usr/bin/env python3
"""emu_contact_lock.py - Unicorn proof of the CONTACT LOCKOUT in eFootball.exe.

Runs the game's own bytes for match::anime::action::Stagger::vf14 (0x143f00de0),
FallDown/Dive::vf14 (0x143f00d00) and Sliding::vf14 (0x143f70360) against a synthetic
MbInfoManager, and reports the frame at which each action-kind request is allowed to
cancel the contact animation.  Images are opened READ-ONLY; patches are overlaid in the
emulator only.  Sections A-F mirror build/emu_contact_lock_proof.txt.

    python tools/emu_contact_lock.py
"""
#!/usr/bin/env python3
"""Emulate the contact-cancel gate vf14 with the game's own bytes. READ-ONLY on the images."""
import struct, mmap
from unicorn import *
from unicorn.x86_const import *
PR = r"C:\Users\tjgg2\Backups\eFootball\eFootball.exe.PRISTINE"
class Img:
    def __init__(s,p):
        s.f=open(p,'rb'); s.m=mmap.mmap(s.f.fileno(),0,access=mmap.ACCESS_READ)
        d=s.m[:0x1000]; pe=struct.unpack_from("<I",d,0x3C)[0]
        n=struct.unpack_from("<H",d,pe+6)[0]; o=struct.unpack_from("<H",d,pe+20)[0]
        s.secs=[]
        for i in range(n):
            x=d[pe+24+o+40*i: pe+24+o+40*(i+1)]
            vs,va,rs,raw=struct.unpack_from("<IIII",x,8)
            s.secs.append((va,vs,raw,rs))
    def off(s,rva):
        for va,vs,raw,rs in s.secs:
            if va<=rva<va+vs:
                d=rva-va
                return raw+d if d<rs else None
        return None
    def read(s,va,n):
        o=s.off(va-0x140000000)
        return None if o is None else s.m[o:o+n]
img=Img(PR)
PAGE=0x1000
ARENA=0x10000000
MGR   = ARENA+0x1000
TABLE = ARENA+0x2000
KFPOOL= ARENA+0x40000
VECPOOL=ARENA+0x50000
WORK  = ARENA+0x60000
STACK = 0x20000000
RETM  = 0x7FFF0000
def f2i(v): return struct.unpack("<I",struct.pack("<f",v))[0]

class E:
    def __init__(s, patches=None):
        s.uc=Uc(UC_ARCH_X86,UC_MODE_64); s.mapped=set()
        s.uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED|UC_HOOK_MEM_WRITE_UNMAPPED|UC_HOOK_MEM_FETCH_UNMAPPED, s._miss)
        for a,n in ((ARENA,0x70000),(STACK-0x20000,0x40000),(RETM,0x1000)):
            s._map(a,n)
        for a in (0x143f00de0,0x143f00d00,0x143f70360,0x143e99e20,0x143e99b70,0x143e9b220,
                  0x143e9a390,0x143e9a1a0,0x1443120f0,0x144311e40,0x143f007b0):
            s._load(a,0x700)
        if patches:
            for va,b in patches: s.uc.mem_write(va,b)
        s.cur=0; s.fps=60.0
        s.uc.hook_add(UC_HOOK_CODE, s._hook)
        s.uc.mem_write(RETM, b"\xcc"*16)
    def _map(s,a,n):
        a0=a&~0xFFF; e=(a+n+0xFFF)&~0xFFF
        for p in range(a0,e,PAGE):
            if p not in s.mapped: s.uc.mem_map(p,PAGE); s.mapped.add(p)
    def _miss(s,uc,t,addr,sz,v,u):
        p=addr&~0xFFF
        if p in s.mapped: return True
        uc.mem_map(p,PAGE); s.mapped.add(p)
        b=img.read(p,PAGE)
        if b and len(b)==PAGE: uc.mem_write(p,b)
        return True
    def _load(s,va,n):
        s._map(va,n); b=img.read(va,n)
        if b: s.uc.mem_write(va,b[:n])
    def _ret(s,val=None):
        uc=s.uc; sp=uc.reg_read(UC_X86_REG_RSP)
        r=struct.unpack("<Q",uc.mem_read(sp,8))[0]
        uc.reg_write(UC_X86_REG_RSP,sp+8); uc.reg_write(UC_X86_REG_RIP,r)
    def _hook(s,uc,addr,size,ud):
        if addr==0x143e940a0:
            uc.reg_write(UC_X86_REG_RAX,MGR); s._ret()
        elif addr==0x14533ea80:
            uc.reg_write(UC_X86_REG_XMM0,f2i(s.fps)); s._ret()
        elif addr==0x143ea9040:
            uc.reg_write(UC_X86_REG_RAX,s.cur); s._ret()
    def world(s,kf3,kf5,kf6,motion,sub):
        uc=s.uc
        uc.mem_write(MGR,b"\0"*0x40)
        rec=TABLE+motion*0x1f8
        s._map(rec,0x200); uc.mem_write(rec,b"\0"*0x1f8)
        uc.mem_write(MGR+8,struct.pack("<Q",TABLE))
        uc.mem_write(KFPOOL,b"\0"*0x2000); uc.mem_write(VECPOOL,b"\0"*0x2000)
        kp=[KFPOOL]; vp=[VECPOOL]
        def enc(ch, frame):
            if ch==3: return (frame//2) & 0x1fff
            if ch==5: return ((frame//2 - 2) & 0x3ff) << 13
            if ch==6: return ((frame//2 - 2) & 0xff) << 21
            raise ValueError(ch)
        def put(ch,fr):
            if fr is None: return
            base=vp[0]
            for v in fr:
                uc.mem_write(kp[0],struct.pack("<I",enc(ch,v))+b"\0"*12)
                uc.mem_write(vp[0],struct.pack("<Q",kp[0])); kp[0]+=16; vp[0]+=8
            uc.mem_write(rec+0x18*ch,struct.pack("<Q",base))
            uc.mem_write(rec+0x18*ch+8,struct.pack("<Q",vp[0]))
            uc.mem_write(rec+0x18*ch+16,struct.pack("<Q",vp[0]))
        put(3,kf3); put(5,kf5); put(6,kf6)
        uc.mem_write(WORK,b"\0"*0x5000)
        uc.mem_write(WORK+0xae8,struct.pack("<H",motion))
        uc.mem_write(WORK+0x2bdc,bytes([sub]))
    def call(s,fn,reqkind,cur,kf3=None,kf5=None,kf6=None,motion=0x221,sub=0,fps=60.0):
        s.cur=cur; s.fps=fps
        s.world(kf3,kf5,kf6,motion,sub)
        uc=s.uc
        uc.reg_write(UC_X86_REG_RSP,STACK)
        uc.mem_write(STACK,struct.pack("<Q",RETM))
        uc.reg_write(UC_X86_REG_RCX,ARENA+0x200)
        uc.reg_write(UC_X86_REG_RDX,WORK)
        uc.reg_write(UC_X86_REG_R8,reqkind)
        try: uc.emu_start(fn,RETM,count=500000)
        except UcError as ex: return "ERR:"+str(ex)
        return uc.reg_read(UC_X86_REG_RAX)&0xff


if __name__ == '__main__':
    import struct
    
    S=0x143f00de0; F=0x143f00d00; SL=0x143f70360
    def gate(e,fn,k,**kw):
        for c in range(0,400):
            if e.call(fn,k,c,**kw)==1: return c
        return None
    def reaim(va,tgt):
        b=bytearray(img.read(va,9)); ln=9 if (b[0]==0xf3 and b[1]==0x44) else 8
        b[ln-4:ln]=struct.pack("<i",tgt-(va+ln)); return (va,bytes(b[:ln]))
    # frames now given directly (at speed 60)
    END=64              # channel 3 key  = "the action is over"
    print("model check: ch3=[64] ch5=[16,32,48] ch6=[24]  (frames at speed 60)")
    e=E()
    K=dict(kf3=[END],kf5=[16,32,48],kf6=[24])
    print(" stock Stagger : Move=%s Dribble=%s Tackle=%s"%(gate(e,S,2,**K),gate(e,S,4,**K),gate(e,S,0xd,**K)))
    print()
    print("== A. stock Stagger gate, channel-5 layouts ==")
    for kf5,lab in (([16,32,48],'3 keys'),([16],'1 key'),(None,'no keys'),([10,20,30,40,50],'5 keys')):
        KK=dict(kf3=[END],kf5=kf5,kf6=[24])
        print("  ch5=%-9s %-16s Move->%-5s Dribble->%-5s" % (lab,kf5,gate(e,S,2,**KK),gate(e,S,4,**KK)))
    print()
    print("== B. one byte 0x143f00efa 75->EB (Dribble takes the FIRST cancel key) ==")
    ec=E(patches=[(0x143f00efa,b"\xeb")])
    for kf5 in ([16,32,48],[16],None,[10,20,30,40,50]):
        KK=dict(kf3=[END],kf5=kf5,kf6=[24])
        print("  ch5=%-16s Move->%-5s Dribble->%-5s" % (kf5,gate(ec,S,2,**KK),gate(ec,S,4,**KK)))
    print()
    print("== C. scale re-aim at 0x143f00e13 (Stagger::vf14), ch5=[16,32,48] ch3=[64] ==")
    for tgt,name in ((0x1478502b8,'1.0f STOCK'),(0x147850340,'1.5f'),(0x147850490,'2.0f'),(0x1478504e8,'3.0f')):
        ep=E(patches=[reaim(0x143f00e13,tgt)])
        print("  scale=%-11s Move->%-5s Dribble->%-5s" % (name,gate(ep,S,2,**K),gate(ep,S,4,**K)))
    print()
    print("== D. FallDown::vf14 stock vs 0x143f00d71 jne->nop ==")
    es=E(); ed=E(patches=[(0x143f00d71,b"\x66\x90")])
    for sub in (0,1,2,3,4):
        print("  sub=%d  stock Move->%-5s Dribble->%-5s | patched Move->%-5s Dribble->%-5s" %
              (sub,gate(es,F,2,sub=sub,**K),gate(es,F,4,sub=sub,**K),gate(ed,F,2,sub=sub,**K),gate(ed,F,4,sub=sub,**K)))
    print()
    print("== E. FallDown scale re-aim (0x143f00d4e and 0x143f00d86 -> 2.0f) ==")
    ef=E(patches=[reaim(0x143f00d4e,0x147850490),reaim(0x143f00d86,0x147850490)])
    for sub in (0,2):
        print("  sub=%d  Move->%-5s Dribble->%-5s" % (sub,gate(ef,F,2,sub=sub,**K),gate(ef,F,4,sub=sub,**K)))
    print()
    print("== F. Sliding::vf14 (for reference, same shape, sub byte compared to 4) ==")
    esl=E()
    for sub in (0,4):
        print("  sub=%d  contact-can-interrupt-slide opens at frame %s" % (sub,gate(esl,SL,0x10,sub=sub,**K)))
    
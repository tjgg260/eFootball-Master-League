import sys, json
sys.path.insert(0,'tools')
import bpx, exe_funcs_chained as fc
def D(va, end=None, n=None):
    print(bpx.dump(va, n=n, end=end))
def FULL(va):
    r = fc.func_root(va)
    if r is None:
        print("no root for", hex(va)); return
    for b,e in sorted(fc.func_chunks(r)):
        print(f"--- chunk {b:#x}..{e:#x} ---")
        print(bpx.dump(b, end=e))
def X(va):
    for a in bpx.xrefs(va) if hasattr(bpx,'xrefs') else []:
        print(hex(a))

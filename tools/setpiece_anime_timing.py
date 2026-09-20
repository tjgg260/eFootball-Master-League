"""Durations and cancel windows of the restart/set-piece animation family, in seconds.

Frame unit 1/60 s.  AnimationData.bin: end_frame = (packed & 0x1FFF) * 2, anim id = packed >> 13.
CancelData.bin (12-byte records): anim id = packed & 0x1FFF, frame = (((packed>>13)&0x3FF)+2)*2.
Both rules are the exe's own getters (see tools/anime_motion_tables.py in the tool worktree).
Read-only.
"""
import json, os, struct, sys, zlib, collections

TOOLREPO = r"C:/Users/tjgg2/Downloads/eFootball Master League/.claude/worktrees/dt270-full-decode-12718b"
ANIME = (r"C:/Users/tjgg2/AppData/Local/Temp/claude/"
         r"C--Users-tjgg2-Downloads-eFootball-Master-League--claude-worktrees-"
         r"efootball-player-executors-decode-bcd546/"
         r"1f9a8ffe-843a-47bc-adf0-4304d87742c4/scratchpad/anime/Mbinfo/bin")

def unwrap(blob):
    if blob[:3] == b'\xff\x20\x81' and blob[4:9] == b'WESYS':
        return zlib.decompress(blob[17:])
    if b'WESYS' in blob[:32]:
        i = blob.index(b'WESYS')
        return zlib.decompress(blob[i + 13:])
    return blob

def tables(d):
    cancel = collections.defaultdict(list)
    raw = unwrap(open(os.path.join(d, 'CancelData.bin'), 'rb').read())
    for i in range(len(raw) // 12):
        v = struct.unpack_from('<I', raw, 12 * i)[0]
        cancel[v & 0x1FFF].append((((v >> 13) & 0x3FF) + 2) * 2)
    end = {}
    raw = unwrap(open(os.path.join(d, 'AnimationData.bin'), 'rb').read())
    for i in range(len(raw) // 36):
        v = struct.unpack_from('<I', raw, 36 * i)[0]
        end.setdefault(v >> 13, (v & 0x1FFF) * 2)
    return cancel, end

def main():
    names = json.load(open(os.path.join(TOOLREPO, 'tools/data/ef_anime_names.json')))['body']
    cancel, end = tables(ANIME)
    groups = {
        'WALL':        lambda s: s.startswith('wall_'),
        'QUICK RESTART': lambda s: s.startswith('quick_restart'),
        'THROW-IN':    lambda s: s.lower().startswith('throwin'),
        'KICK-OFF':    lambda s: s.startswith('kickoff'),
        'FREE KICK':   lambda s: s.lower().startswith('freekick'),
        'GK GOAL KICK': lambda s: s.startswith('gkgoalkick'),
        'PK':          lambda s: s.startswith('pk_'),
        'GK SETPLAY':  lambda s: 'setplay' in s,
        'FK TAKER':    lambda s: s.startswith('fk_'),
        'CORNER/FK DELIVERY': lambda s: s.endswith('_ck') or s.endswith('_fk') or 'placekick' in s,
    }
    for label, pred in groups.items():
        rows = [(i, s) for i, s in enumerate(names) if pred(s)]
        print(f"\n== {label}  ({len(rows)} motions)")
        for i, s in sorted(rows, key=lambda r: r[1]):
            e = end.get(i)
            cs = sorted(set(cancel.get(i, [])))
            if e is None and not cs:
                continue
            dur = f"{e/60:6.3f}s ({e:4d}f)" if e is not None else "   n/a      "
            if cs:
                cc = ", ".join(f"{c/60:.3f}s" for c in cs[:6])
                first = cs[0]
                lock = f"  committed {first/60:.3f}s" if e is None else f"  committed {first/60:.3f}s of {e/60:.3f}s"
            else:
                cc, lock = "none", "  NO cancel key -> committed for the whole clip"
            print(f"  {i:5d} {s:<44} {dur}  cancel@[{cc}]{lock}")

if __name__ == '__main__':
    sys.exit(main())

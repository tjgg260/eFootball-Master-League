#!/usr/bin/env python3
"""Rebuild build/anime_names.json and build/anime_motion_tables.json.

Motion id -> {name, end_frame, cancel_frames}, decoded with the EXE's OWN getters.

Where each piece comes from (all VAs at base 0x140000000, read from the PRISTINE image):

  names        A table of 7,883 char* at VA 0x148027310, one per motion id, in motion-id
               order, every entry distinct.  7,883 == 0x1ecb, the hard bound every MbInfo
               accessor checks (`cmp edx,0x1ecb` in 0x143e9a390 / 0x143e99e20 / 0x143ea9040).
               Cross-check: the two motion ids the exe hard-codes in Stagger::vf14's special
               block, 3255 and 3259, come out as stagger_upbody_3_3_090_pulled and
               stagger_upbody_4_4_090_pulled -- the shirt-pull staggers.

  MbInfo       MbInfoManager holds `mgr+8` = an array of 7,883 records of 0x1f8 bytes.
  layout       0x1f8 == 21 * 0x18: each record is 21 std::vector<Event*>, one per channel,
               begin at record+0x18*c, end at +0x18*c+8 (switch at 0x143e9a1a0, 21 arms).
               The 21 channels are the 21 `cpk_dat/common/anime/Mbinfo/bin/*.bin` paths in
               the literal pool at 0x146b45470..0x146b45890, in that order, so
               channel 3 = AnimationData.bin and channel 5 = CancelData.bin.

  cancel       CancelData.bin, 12-byte records {u32 packed, f32, f32}; 68,952/12 = 5,746.
  (channel 5)  Getter 0x143e99e20 does `shr ebx,0xd / and ebx,0x3ff / add ebx,2 / cvtdq2ps /
               addss xmm1,xmm1`, i.e.
                   anim_index = packed & 0x1FFF          (13 bits, max seen 7,872 < 7,883)
                   frame      = (((packed >> 13) & 0x3FF) + 2) * 2
               Bits 23..31 are zero in every record, so the word is fully accounted for.
               Under this rule all 4,295 per-animation groups are in ascending frame order;
               under the 12-bit reading only 2,739 of 3,339 are, and a 14-bit index puts
               2,372 records past the exe's own bound.

  end          AnimationData.bin, 36-byte records, 254,628/36 = 7,073 (== CategoryData's
  (channel 3)  record count).  Getter 0x143e99b70 does `movzx ebx, word[rax] / and bx,0x1fff
               / cvtdq2ps / addss xmm1,xmm1`, i.e.
                   end_frame  = (packed & 0x1FFF) * 2
                   anim_index =  packed >> 13          (index is in the HIGH bits here --
                                                        the opposite order to CancelData)

  units        Both getters finish `/ scale * (R/60) + 0.5`, truncated, where R is the global
               float at 0x148c22abc (0x14533ea80 returns it) and `scale` is the playback-speed
               argument, a literal 1.0f at every contact-gate call site.  The current frame
               (0x143ea9040) is `R * t_layer`, so gate and key are in the same unit and the
               numbers here are directly comparable frame counts.  They read as 60 fps frames.

Inputs: an extracted `.../common/anime/Mbinfo/bin` directory (from dt230) and the PRISTINE exe.
Nothing here writes to the game.
"""
import json, os, struct, sys, zlib, collections

NAME_TABLE_VA = 0x148027310
NAME_COUNT    = 7883

def _pe_sections(data):
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    nsec   = struct.unpack_from('<H', data, pe + 6)[0]
    optsz  = struct.unpack_from('<H', data, pe + 20)[0]
    base   = struct.unpack_from('<Q', data, pe + 48)[0]
    secs, off = [], pe + 24 + optsz
    for _ in range(nsec):
        vs, va, rs, ra = struct.unpack_from('<IIII', data, off + 8)
        secs.append((va, vs, ra, rs)); off += 40
    return base, secs

def read_names(exe_path):
    data = open(exe_path, 'rb').read()
    base, secs = _pe_sections(data)
    def off(va):
        rva = va - base
        for sva, vs, ra, rs in secs:
            if sva <= rva < sva + max(vs, rs):
                o = ra + (rva - sva)
                if o < ra + rs:
                    return o
        return None
    names = []
    for i in range(NAME_COUNT):
        q = struct.unpack_from('<Q', data, off(NAME_TABLE_VA + 8 * i))[0]
        o = off(q)
        names.append(data[o:data.index(b'\0', o)].decode('latin1'))
    return names

def unwrap(blob):
    """WESYS + zlib (eFootball) or raw (PES 2014)."""
    if blob[:3] == b'\xff\x20\x81' and blob[4:9] == b'WESYS':
        return zlib.decompress(blob[17:])
    if b'WESYS' in blob[:32]:
        i = blob.index(b'WESYS')
        return zlib.decompress(blob[i + 13:])
    return blob

def read_tables(mbinfo_bin_dir):
    cancel = collections.defaultdict(list)
    raw = unwrap(open(os.path.join(mbinfo_bin_dir, 'CancelData.bin'), 'rb').read())
    for i in range(len(raw) // 12):
        v = struct.unpack_from('<I', raw, 12 * i)[0]
        cancel[v & 0x1FFF].append(((((v >> 13) & 0x3FF) + 2) * 2))
    end = {}
    raw = unwrap(open(os.path.join(mbinfo_bin_dir, 'AnimationData.bin'), 'rb').read())
    for i in range(len(raw) // 36):
        v = struct.unpack_from('<I', raw, 36 * i)[0]
        end.setdefault(v >> 13, (v & 0x1FFF) * 2)
    return cancel, end

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        print('usage: anime_motion_tables.py <PRISTINE exe> <.../Mbinfo/bin> [out_dir]')
        return 2
    exe, mb = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else 'build'
    names = read_names(exe)
    cancel, end = read_tables(mb)
    motions = {}
    for i, n in enumerate(names):
        e, c = end.get(i), cancel.get(i, [])
        if e is None and not c:
            continue
        motions[i] = {'name': n, 'end': e, 'cancel': c}
    os.makedirs(out, exist_ok=True)
    json.dump(names, open(os.path.join(out, 'anime_names.json'), 'w'))
    json.dump({'count': len(motions), 'motions': motions},
              open(os.path.join(out, 'anime_motion_tables.json'), 'w'), indent=0)
    print(f'{len(names)} names, {len(motions)} motions with MbInfo data')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

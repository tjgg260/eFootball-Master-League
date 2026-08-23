# Kit descriptor bins — format, gate, authoring

Status: **gate PROVEN 2026-08-23** over the full shipped set (2,907 files, zero failures).
Tools: [`tools/kit_codec.py`](../tools/kit_codec.py) (codec + gate),
[`tools/kit_author.py`](../tools/kit_author.py) (writer). Background:
memory note *kits-logos-evomod* — dt200 holds kit **config** only; all pixels
(kit textures, crests) live pak-side.

## Where they live

```
common/etc/uniform/team/<teamId>/<teamId>_<comp>_<kit>[_realUni].bin
```

- `<comp>`: `DEF` (default), plus competition variants (`WCA`, `ANC`, …).
- `<kit>`: `1st`, `2nd`, `GK1st`.
- `_realUni`: licensed real-uniform variant of the same payload format.
- Shipped set: `bins-evomod-full/common/etc/uniform/team/` (914 team dirs);
  our deployable tree `build/tree_base/common/etc/uniform/team/` is byte-identical content.
- Non-team files in the same dir are **out of scope** for the codec:
  `UniColor.bin`, `RefereeColor.bin`, `UniNameFontPermissions.bin`, `referee/*`.

## Three container variants, two payload species

| Container | Header | Files | Decode path |
|---|---|---|---|
| raw plaintext | none (payload is the file) | 153 | passthrough |
| WESYS zlib | `ff 22 83 "WESYS" csize osize` | 1,104 | vendored Sider `wesys.py` (XOR keystream + inflate) |
| WESYS stored | `ff 22 02 "WESYS" csize osize` | 1,650 | **own** XOR-only path in `kit_codec.py` — flag bit `data[2]&0x80` clear means *no zlib*; the vendored unpack raises on these because it insists a current-format payload must inflate |

The stored cipher is the same current-format xorshift keystream (key nibble
`data[1]&0x0F` = 2), seeded `w = (original_size << 16) | compressed_size`;
for stored files `csize == osize == len(payload)`. XOR is symmetric, so the
same routine encrypts. Reimplemented in `kit_codec.crypt_current` after
studying the vendored file (which stays untouched, per the vendor rule).

| Payload | Meaning | Handling |
|---|---|---|
| **92 bytes** | texture-ref kit descriptor | fully decoded (`KitDescriptor`) |
| **96 bytes** | parametric editor-config (in-game kit editor output) | opaque passthrough; container decode proven, fields not needed for our pipeline |

Family × payload matrix from the gate: plain/92B=153, zlib/92B=1,089,
zlib/96B=15, stored/96B=1,650.

## The 92-byte descriptor field map

Proven byte-exact on all 1,242 shipped 92-byte payloads. Unknown regions are
carried verbatim as bytes so serialization can never drift.

| Offset | Size | Field | Observed values |
|---|---|---|---|
| 0x00 | 3 | header bytes (verbatim) | `01 90 3e` (308), `01 90 bb` (917), `01 90 3f` (1), `01 a0 3e` (16) |
| 0x03 | 1 | design id | 1–18 (1 dominates: 920) |
| 0x04 | 3 | shirt RGB24 | |
| 0x07 | 3 | trim RGB24 | |
| 0x0a | 3 | shorts RGB24 | |
| 0x0d | 3 | socks RGB24 | |
| 0x10 | 3 | trim2 RGB24 | |
| 0x13 | 1 | enum | 2–10 (10 dominates) |
| 0x14 | 2 | pair (usually equal bytes) | `01 01` most common, 84 distinct |
| 0x16 | 30 | **opaque block, kept verbatim** — undeciphered | |
| 0x34 | 24 | six float32 — name/number placement | e.g. `12.6, 10.4, 16.21, 62.89, 89.45, 16.2` |
| 0x4c | 12 | texture-set ref, NUL-padded ASCII | `u0101p1` outfield, `…p2` 2nd, `…g1` GK; also `a…`/`wa…` namespaces |
| 0x58 | 4 | tail (verbatim) | all zero in every shipped file |

The ref names pak-side texture sets (`T_<ref>_Uni_D/N/M` + fonts). Cross-team
ref reuse is a shipped pattern (~262 of 6,243 u-ids in use); EvoMod invented
its own `a0157+` namespace, so unused ids are fair game once matching pak
textures exist.

## The gate

```
python tools/kit_codec.py --prove          # default root: bins-evomod-full
python tools/kit_codec.py --prove --root build/tree_base/common/etc/uniform/team
python tools/kit_codec.py --dump <file>    # pretty-print one bin
```

For every team `*.bin`: container decode must succeed, and every 92-byte
payload must satisfy `serialize(parse(payload)) == payload` **byte-exact**.
This is the payload-level reframe of the repo's round-trip rule: Konami's
zlib encoder is not reproducible (0/400 repacks matched), so the proof is at
the payload layer, which is what we actually rewrite. Output on 2026-08-23:

```
team descriptor bins: 2907
families (container, payload bytes):
   plain  92B :   153  (decoded KitDescriptor)
  stored  96B :  1650  (opaque passthrough)
    zlib  92B :  1089  (decoded KitDescriptor)
    zlib  96B :    15  (opaque passthrough)
92B payloads round-tripped byte-exact : 1242
96B payloads container-decoded (opaque): 1665
PROVEN: 1242 descriptors byte-exact + 1665 opaque containers decoded
        (plain/92B=153, stored/96B=1650, zlib/92B=1089, zlib/96B=15)
```

If a future field decode ever breaks byte-exactness, demote that region back
to opaque bytes rather than shipping a lossy writer.

## Writing kits: `kit_author.py`

Emits **raw plaintext** descriptors — the game accepts them (51 vanilla teams
ship exactly that), which sidesteps re-encryption entirely. Safe defaults
(header, design id, enum/pair, opaque block, placement floats) are cloned
from team 173's shipped plaintext trio, embedded as constants and re-verified
through `kit_codec.parse` on every run. Only colors and refs change.

```
python tools/kit_author.py --team 5001 --colors CC0000,FFFFFF,CC0000,CC0000,FFFFFF
python tools/kit_author.py --team 5001 --colors CC0000 --colors2 1A1A1A --gk-colors 00AA55
python tools/kit_author.py --team 5002 --from-logo assets/dvx_logos/1001.webp
python tools/kit_author.py --team 5002 --ref u0101p1 --gk-ref u0101g1 --colors ...
```

- Colors are `shirt,trim,shorts,socks,trim2`; 1–5 accepted, gaps auto-filled.
- 2nd kit auto-derived when `--colors2` absent (light 1st → darkened, dark
  1st → inverted); GK auto-derived to clash with neither shirt.
- `--from-logo` samples the image's dominant palette (Pillow median-cut on
  opaque pixels; near-white demoted): shirt = dominant, trim = second,
  shorts = third or darkened shirt.
- Default refs are the donor's `u6058p1/p2/g1` (guaranteed to exist);
  `--ref uNNNNp1` derives `p2`/`g1` siblings. Refs must exist in the
  installed paks — the descriptor only *points* at textures.
- Writes to `--out` (default `build/tree_base`) under
  `common/etc/uniform/team/<id>/` as `<id>_DEF_1st|2nd|GK1st.bin`;
  refuses to overwrite without `--force`.
- **Never** rebuilds a CPK or touches the game install. Deployment stays with
  the proven tree_base → cpkmakec align=512 rebuild path (and remember the
  standing note: strip the two stray `.bak` files from tree_base before any
  rebuild).

## How play_match uses this (just-in-time per-fixture authoring)

The game has 981 Team.bin slots; a career renders one match at a time. So
kits for arbitrary ML clubs are a per-fixture projection, not a bulk import.
When `play_match` stages a fixture:

1. Look up both clubs' colors in master.db (club identity / DVX logo via
   `team_identity.fm_club_id`); fall back to `--from-logo` extraction from
   `assets/dvx_logos/<id>.webp`.
2. Call `kit_author.author_team_kits()` for the two dt200 slots the fixture
   occupies, writing plaintext descriptors into the tree (`--force`, since
   slots are reused between fixtures).
3. Rebuild + install dt200 via the existing proven deploy path, alongside the
   crest override pak (step 2 of the kit pipeline — the IoStore writer is the
   missing capability there).
4. After the match, the slots simply get re-authored for the next fixture;
   the DB remains the single source of truth, the tree is a render target.

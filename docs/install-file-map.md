# eFootball install folder — complete file map

Every file/dir in `steamapps/common/eFootball`, what it is, and whether it's moddable by us.
Evidence-based: CPK contents were read with cricodecs; the UE5 pak side is AES-encrypted so
those rows are characterised by size/naming, not by reading them. Captured 2026-08-20 against
the post-EvoMod install (base family: dt200 8.88 MB, dt270 family 9968).

Legend for **Mod**: ✅ we mod this today · 🔵 readable, not yet used · 🔒 encrypted/protected,
no practical path · ⬛ system/engine, do not touch.

## Root

| File | Size | What it is | Mod |
|---|---|---|---|
| `eFootball/Binaries/Win64/eFootball.exe` | 352 MB | Main game binary (UE5 + Konami match engine). **VM-protected**: sections `.xcode` 94 MB, `.impdata` 183 MB, `.text` 14 MB virtual / 4.9 MB on disk — code is encrypted on disk, decrypts in memory at runtime. The AI/match-engine logic lives here as native C++. | 🔒 |
| `eFootball/Binaries/Win64/eFootballcop.exe` | 352 MB | Copy-protection variant Steam actually launches. | 🔒 |
| `eFootball/Binaries/Win64/steam_api64.dll`, `sdkencryptedappticket64.dll` | — | Steamworks. | ⬛ |
| `Settings.exe` + `Settings_b.dll` | 516 KB | Standalone graphics/config launcher (resolution, quality). Not gameplay. | ⬛ |
| `InstallScript.vdf` | — | Steam install script (redist/registry). | ⬛ |
| `Engine/Binaries/ThirdParty/**` | ~15 MB | UE5 middleware DLLs: PhysX3 (physics), Vorbis/Ogg (audio codecs), XAudio2, Steamworks, NVIDIA Aftermath, DbgHelp. Stock engine, no game logic. | ⬛ |

**Bottom line on the exe — the honest feasibility gradient** (corrected: an offline-only patch
already works on this install, so the exe demonstrably *is* patchable — "unpatchable" was wrong):

- **Flipping a known check** (e.g. the online gate → offline-only): small, surgical, community-
  documented — a handful of bytes at a known location. Proven doable; it's done here.
- **Finding + rewriting AI game-management logic** ("when leading late, drop deeper"): the same
  binary, but now you must *locate* un-symboled decision code inside 352 MB of VM-protected
  native C++, understand it, and alter it without breaking the protector's integrity checks.
  That's not the same task — it's orders of magnitude harder, and there's no map to it.

So the exe isn't a closed door; it's a very long corridor. The realistic first step isn't a
patch, it's **reconnaissance**: figure out how the offline patch was made (which tells us what's
already been unpacked/reachable), then look for whether match state (scoreline, clock) even flows
through code we can find. Worth a scoped look, not a promise.

## cpk/ — the CriWare DATA layer (this is what our whole app targets)

Legacy PES/eFootball data tables. We read/write these with cricodecs + vendored Sider (WESYS).
`_all` = all platforms, `_win` = PC, `_eng/_jpn/_ind/_use` = language/region.

| File | Size | Contents (read) | What it is | Mod |
|---|---|---|---|---|
| `dt200_console_all.cpk` | 8.9 MB | `etc/` 2986×.bin | **The squad/player/team database.** Player.bin, Team.bin, PlayerAssignment.bin, Derby.bin, Coach.bin, PlayerAppearance.bin. | ✅ our core target |
| `dt270_console_all.cpk` | 103 KB | `match/constant/` 11×.bin | **Match gameplay constants** (Q2.14 tempo/pressing/physicality/ball scalars). The only gameplay-behaviour lever in CPK. | ✅ gameplay tune |
| `dt000_console_all.cpk` | 833 MB | `sound/` .acb+.awb, `etc/` | Core audio banks (SFX, crowd, UI) + some data. | 🔵 |
| `dt220_console_all.cpk` | 3 MB | `demo/` 221×.gani | Attract-mode / demo animation (.gani) + .ask/.frig rigs. | 🔵 |
| `dt230_console_win.cpk` | 203 MB | `anime/` .bin+.mtar | Motion/animation archives (.mtar = motion archive). | 🔵 |
| `dt240_console_all.cpk` | 5.9 MB | `render/` .geom+.cloth | Render geometry + cloth sim (kit/net physics meshes). | 🔵 |
| `dt250_console_all.cpk` | 2.3 MB | 1094 hash-named | Content-addressed chunk store (edit-data / DLC content). | 🔵 |
| `dt251_console_all.cpk` | 92 KB | 42 hash-named | Same, smaller chunk set. | 🔵 |
| `dt260_console_win.cpk` | 78 KB | `string/` .str + credit | Base UI strings + credits. | 🔵 |
| `dt261_eng/ind/use_console_win.cpk` | 250 KB ea | `string/` .str | Per-region localized UI strings. | 🔵 |
| `dt500_console_all.cpk` | 257 MB | `sound/` .acb+.awb+.tlb | Audio banks (chants / player calls). | 🔵 |
| `dt510_eng_console_all.cpk` | 1.24 GB | `sound/` 5×.acb+.awb | **English match commentary audio.** | 🔵 (see note) |
| `dt510_jpn_console_all.cpk` | 1.5 GB | `sound/` 6×.acb+.awb | **Japanese match commentary audio.** | 🔵 |
| `dt520_console_all.cpk` | 176 KB | `sound/` .xml+.bin | Audio cue-sheet metadata (which line plays when). | 🔵 |
| `dt530_eng/jpn_console_all.cpk` | 266 KB ea | `sound/` .xml+.bin | Commentary trigger/cue metadata per language. | 🔵 |
| `dt540_console_all.cpk` | 957 MB | `sound/` 31×.acb+.awb | Large audio set (music / stadium / second commentary set). | 🔵 |
| `dt870_console_win.cpk` | 5 MB | `etc/` 48×.bin + .csv | Config/lookup tables. | 🔵 |

## pak/ — the UE5 IoStore ASSET layer (44 GB, AES-encrypted)

Unreal Engine 5 packaged assets: 3D models, face scans, textures, stadiums, animations, maps,
Blueprints. Each title ships as a triple: tiny `.pak` (365 B mount stub) + `.ucas` (the data
container) + `.utoc` (directory index). **Every `.utoc` index reads as zero asset paths — the
whole set is AES-encrypted.** Reading any of it needs the game's AES key + UE5 tooling
(retoc/ZenTools). Naming: `pc<chunk>_console_win`.

| File(s) | Size | Likely contents | Mod |
|---|---|---|---|
| `global_console_win.*` | 1.9 MB | UE5 global shader / name map | 🔒 |
| `pc0000/0010/0100/0102` | 1.3–3.3 GB ea | Base game: maps, UI, core Blueprints | 🔒 |
| `pc1000_console_win.*` | 2.3 GB | Asset chunk | 🔒 |
| `pc3000–pc3610` (the big series) | 0.3–7.5 GB ea | Player face scans, 3D models, stadiums, kit/boot textures — the visual bulk | 🔒 |
| `pc3099/3200/3400/4000/7000` | 0.1–1 GB ea | Further asset chunks | 🔒 |

### PesConsole/Content/Paks/~mods/ — the UE5 mod loader (active)

The supported override folder: any `*_P.pak` here loads on top of the base game.
**Non-destructive — drop a file in, delete it to revert.** Currently installed:

| Mod | What it is |
|---|---|
| `EvoMod_BASE_P` + `EvoMod_ADB_P` + `EvoMod_ADB_CFG_P` | EvoMod. `ADB_P.pak` is a 118 MB **encrypted** UE4 pak (zero readable strings, AES index). Per the user, EvoMod is **graphical** — earlier guess that it was gameplay was wrong and is retracted. |
| `RealGrade_Toriga_P`, `Turf3D_Toriga_P`, `DirtyStains_Toriga_P` | Toriga graphics packs (pitch grade, turf 3D, dirt/wear). |
| `pc9999_console_win_P.pak` | High-chunk override slot (mod/sider content). |

## What this means for the "AI plays the same all game" goal

- **The only behaviour lever we can actually touch is `dt270`** (CPK, family 9968, decrypted,
  proven write path). It holds global Q2.14 scalars — tempo, pressing, physicality, ball feel.
  Scaling them changes the *overall feel* for both sides, but they are almost certainly **not**
  state-dependent: there is no evidence of a "when leading, drop deeper" table in there.
- **State-dependent game management is in the exe**, as VM-protected native code. Not reachable.
- **The UE5 paks won't help** — they're encrypted, and (per user) the pak-moddable content is
  graphical, not match-AI.
- **Therefore the realistic levers are:**
  1. `dt270` global feel (calibration evenings — slower tempo / heavier ball presets).
  2. What *we* compile into `dt200` per match: the opponent's formation, playstyle and mentality.
     Static within a match, but we can pick it by context (a defensive-minded opponent setup, a
     park-the-bus variant) — the closest we can get to "game management" without the exe.
  3. Our own match sim (fully ours) can model game state however we like.

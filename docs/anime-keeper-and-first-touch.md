# `match::anime` — the goalkeeper save family and first touch (2026-09-20)

Probe **keeper-saves-and-first-touch** against the `match::anime` subsystem.
Decoded from `C:\Users\tjgg2\Backups\eFootball\eFootball.exe.PRISTINE`, base `0x140000000`.
**Every address range quoted below was diffed PRISTINE vs INSTALLED and is byte-identical**
(14 ranges, 0 differing — see *Provenance*). Nothing here is one of our own patches.

Evidence labels: **[a]** emulated on the game's bytes, **[b]** disassembly, **[c]** inferred.

---

## TL;DR

1. **The six save types are six classes with a hard-coded action id, and each reads a different
   goalkeeping attribute.** `Catch`=0x44→GK Catching, `Punch`=0x45→GK Parrying,
   `Deflect`=0x46→GK Reflexes *or* GK Reach, `SnapUnder`=0x47→GK Catching,
   `ScoopOut`=0x48→GK Reach, `Block`=0x49→GK Reach. Proven from the six constructors. [b]
2. **The whole goalkeeping-attribute system collapses into a multiplier between 0.90 and 1.40.**
   `0x144032870` turns an attribute into a 40..120 "save quality", and `0x143f31470` turns that
   into a float. A 40-rated keeper gets 0.90–1.00; a 99-rated keeper gets 1.12–1.30. [a]
3. **Nothing decides *which* save at this layer.** The type arrives as an action id from
   `match::player`. The anime layer decides the *quality*, the *motion* and the *frame budget*.
4. **The save is very nearly deterministic.** The only randomness inside the save family is a
   centimetre-scale positional jitter (≤ 0.09 m, ≤ 0.04 m for a Deflect, a 0.20 m span on a
   third branch) drawn from a per-player stream at `player+0x3bb4`. **Zero** RNG call sites
   inside any of the 114 `goal_keeper::` method bodies. [b]
5. **`ballControlRate` is `trap.ballControlRate` in dt270, it is `1.0` in stock (CORRECTED
   2026-09-20 — `0.80` was OUR `loose-realism-v1.json` value read from a stale dump), and the
   attribute it scales is Tight Possession (0x19) and Aggression (0x1f) — *not* Ball Control
   (0x18).** Ball Control has 25 read sites image-wide and **not one is in the trap family**;
   it is a *dribbling* attribute. [b]
6. **CPU difficulty never reaches `match::anime`.** 0 of the 90 difficulty-table call sites lie
   in any `match::anime` method body. Saves and first touches are level-independent. [b]
7. **The ball never collides with a body.** The ball's own integrator has a forward closure of
   **15 functions** and reaches no attribute getter, no collision system, no RNG and no dt270
   read; its bounce table has exactly six *surface* entries and no body entry. [b]

---

## 1. The 50-slot contract

`goal_keeper::SavingBase` (vft `0x146b58840`) = `action::Base`'s 29 slots + **21 of its own**.
Seven classes share it: `SavingBase`, `Block`, `Catch`, `Deflect`, `Punch`, `ScoopOut`,
`SnapUnder`. `SavingBase::SavingBase(this, actionId)` is `0x143f2ec90`; it calls `Base`'s ctor
`0x143ef54a0` and then **`mov dword ptr [rdi+0x30], ebx`** — so `saving+0x30` is the action id,
and `Base` itself has no id field (`Base` is 0x30 bytes). [b]

### Slots 0–28: inherited `action::Base`

| slot | SavingBase | what |
|---|---|---|
| 2 | `0x143f34320` | `canStart` (overrides Base's stub) |
| 4 | `0x143f305c0` | **the save body** — calls `0x143f46370` (1,735 lines) |
| 5 | `0x143f2fca0` | per-frame step |
| 6 | `0x143f2fc00` | SnapUnder overrides: `0x143f4ec30` |
| 13 | `0x143f32880` | **trajectory walk** — reads the 250-entry prediction (`dword[0x148080f50]`=250) |
| 14 | `0x143f32410` | `canCancel` |
| 17 | `0x143f30e40` | `movzx eax, byte [rdx+0x4452]; ret` — a one-byte flag read |
| 23 | `0x143f30f30` | returns a float constant |
| 24 | `0x143f31bd0` | motion placement (its `0x144346360` call is a vector rotate, **not** RNG) |

Slots 1, 3, 7, 8, 10, 11, 16, 19–22, 27, 28 are shared stubs (`0x140c83910`, `0x140c853c0`,
`0x140c837d0`); 9, 12, 15, 25, 26 are inherited from `Base` unchanged.

### Slots 29–49: SavingBase's own contract

| slot | SavingBase | meaning |
|---|---|---|
| **29** | `0x144f83074` (thunk) | **pure — all six override.** Returns a **frame budget** |
| **30** | `0x144032400` | **all six override.** `bool` "may I run this save now" |
| 31 | `0x143f34110` | Punch and SnapUnder stub it out |
| 32 | `0x143f34270` | reads `player+0x48bc` (a vec4) |
| 33 | `0x143f34220` | reads `player+0x48b0` |
| 34 | `0x143f34090` | motion id `0x75d` |
| 35 | stub | Deflect overrides (`0x143f4add0`) — **reads GK Reach 0x26 at `0x143f4ae0b`** |
| **36** | `0x144f83074` (thunk) | **pure — all six override** |
| **37** | `0x144039230` | small int tier 0/1/2; all six override |
| 38 | `0x144038c00` | |
| 39 | `0x140e41ea0` | `mov eax,1; ret` (Catch overrides) |
| 40 | `0x143f30f10` | `max(xmm1, xmm3)` |
| 41 | `0x143f30f40` | seconds→frames via the frame-rate global `0x14533ea80` |
| 44 | `0x144031cc0` | ScoopOut and SnapUnder override |
| 46 | `0x143f3bc40` | |
| **47** | `0x143f30f90` | `mov eax, 0xb9c; ret` — **default motion id**; every class overrides |
| 49 | `0x144043da0` | tests motion id `0x1ecb` |

**Slot 29 — the per-save frame budget** (values read out of the image): [b]

| class | slot 29 | value (frames) | at 60 fps |
|---|---|---|---|
| `Catch` / `Punch` / `Block` | `0x143f4a5c0` | **60.0** (`[0x145a8dd84]`) | 1.00 s |
| `Deflect` | `0x143f4ad80` | **90.0** if `[rdx+0x54]==4`; **48.0** if `==0 && [rdx]!=2`; else 60.0 | 1.50 / 0.80 / 1.00 s |
| `ScoopOut` | `0x143f4b1d0` | **30.0** if `[rdx]<=2 && [rdx+4]<=1`, else 60.0 | 0.50 / 1.00 s |
| `SnapUnder` | `0x143f4fb70` | **15.0** (`[0x145c0b000]`) | 0.25 s |

`SnapUnder` (smothering at a striker's feet) gets a quarter of a second of lead time; a diving
`Deflect` in its widest case gets a second and a half.

### Slot 37 — and a dead multiply

| class | slot 37 | body |
|---|---|---|
| `Block`, `Catch` | `0x143f4a590` | `if (byte[arg+3] & 0x10) return 2; if (xmm1 < 0.5*x) return 1; return 0` |
| `Punch` | `0x143f4b830` | `mulss xmm0, 1.5` (`[0x147850340]`) then compare |
| `ScoopOut` | `0x143f4b190` | `mulss xmm0, -0.5` (`[0x147850558]`) then compare |
| `Deflect` | `0x143f4ad50` | **`xorps xmm0,xmm0 ; mulss xmm2,xmm0`** — input multiplied by **zero** |
| `SnapUnder` | `0x143f4fb50` | same zero multiply |

> **`Deflect::vf37` and `SnapUnder::vf37` multiply their float argument by a freshly-zeroed
> register.** The comparison degenerates to `0 > xmm1`. Whatever that argument is, it has no
> effect for those two save types. Anyone hooking slot 37 to tune parry behaviour would be
> tuning a term that is already dead on half the family. [b]

---

## 2. `0x144032870` — the save-quality selector, decoded properly

Signature `int SaveQuality(matchPlayer* rcx, int actionId edx, int sub r8d)`.
Three chunks: `0x144032870..0x1440328a8`, `..0x1440328f2`, `..0x144032a90`.
Attribute getter is `0x143ea8cb0(player, idx)`.

### The action-id → class binding is PROVEN, not guessed

Each concrete class's constructor passes its id to `SavingBase`'s ctor: [b]

| id | ctor | class | ActionManager offset |
|---|---|---|---|
| `0x44` | `0x143f4a7c0` `mov edx,0x44` | `goal_keeper::Catch` | `+0xef0` |
| `0x45` | `0x143f4b800` `mov edx,0x45` | `goal_keeper::Punch` | `+0xf28` |
| `0x46` | `0x143f4ad20` `mov edx,0x46` | `goal_keeper::Deflect` | `+0xf60` |
| `0x47` | `0x143f4ec00` `mov edx,0x47` | `goal_keeper::SnapUnder` | `+0xf98` |
| `0x48` | `0x143f4b140` `mov edx,0x48` | `goal_keeper::ScoopOut` | `+0xfd0` |
| `0x49` | `0x143f4a520` `mov edx,0x49` | `goal_keeper::Block` | `+0x1008` |

All six are constructed consecutively at `0x143f9f424..0x143f9f471`, stride `0x38`; the
`ActionManager` ctor is `0x143e9eb00` and builds 96 action objects at fixed offsets.

The jump table is at **`0x144032a78`**, six entries, base `0x140000000`, raw bytes
`79 29 03 04 | 80 29 03 04 | 87 29 03 04 | 79 29 03 04 | b5 29 03 04 | de 29 03 04`
→ `0x144032979, 0x144032980, 0x144032987, 0x144032979, 0x1440329b5, 0x1440329de`. **0x44 and
0x47 share a target**, which is why Catch and SnapUnder both read GK Catching. [b]

### The arithmetic

```
ebx = attr(0x23 Catching)                       ; always read first, 0x144032891

if actionId == 0x44 and speed_kmh < 50.0:       ; 0x144032898 / threshold 50.0f @0x145ae7580
    v = max(Catching, Reflexes, Reach)          ; 0x1440328f2..0x14403292c
    if 40 <= v <= 90:  q = (v-40)/3 + 73        ; 0x14403292c..0x144032943   -> 73..89
    else:              q = v                    ;                            -> 91..99 unchanged
    q = min(q,120); q = max(q,40)               ; SKIPS the x0.98 tail entirely
    return q

switch (actionId):                              ; 0x144032958, table 0x144032a78
  0x44, 0x47:  q = attr(0x23 Catching)
  0x45:        q = attr(0x24 Clearances)
  0x46 & sub in {1,4,5}:                        ; cmp esi,1 / lea eax,[rsi-4]; cmp eax,1
               r = attr(0x25 Reflexes)
               q = 40<=r<=90 ? (r-40)/2 + 65 : r        ; lea ebx,[rax+0x41] @0x1440329b0
  0x46 (other), 0x48:
               r = attr(0x26 Reach)
               q = 40<=r<=90 ? (3*(r-40))/4 + 52 : r    ; add ebx,0x34 @0x1440329d9
  0x49:        q = attr(0x26 Reach)              ; raw
  anything else (e.g. 0x51): q = Catching        ; falls through with ebx from step 1

if q < 90:  q = floor(q * 98 / 100)             ; 0x1440329ed..0x144032a06
if q > 100: q = 100 + (q-100)/2                 ; 0x144032a08..0x144032a15
if flagQuery(player,0x1e) && situation[+0x1c]==6: q += 5    ; 0x144032a18..0x144032a45
q = clamp(q, 40, 120)
```

The speed gate is `|v_ball| * fps * 3.6 < 50.0`. Constants `60.0 @0x145a8dd84` (twice),
`1000.0 @0x145a8dd88`, threshold `50.0 @0x145ae7580` (shared cell, **503 referrers** — not
privately editable). `fps` is the `.bss` float returned by `0x14533ea80`. [b]

### Emulated output (game's own bytes, unicorn, PRISTINE) [a]

```
attr:              40  45  50  55  60  65  70  75  80  85  88  89  90  91  92  95  99
0x44 Catch fast    40  44  49  53  58  63  68  73  78  83  86  87  90  91  92  95  99
0x45 Punch         40  44  49  53  58  63  68  73  78  83  86  87  90  91  92  95  99
0x46 sub0 Deflect  50  53  57  61  65  68  72  76  80  83  86  86  87  91  92  95  99
0x46 sub1 Deflect  63  65  68  70  73  75  78  80  83  85  87  87  90  91  92  95  99
0x47 SnapUnder     40  44  49  53  58  63  68  73  78  83  86  87  90  91  92  95  99
0x48 ScoopOut      50  53  57  61  65  68  72  76  80  83  86  86  87  91  92  95  99
0x49 Block         40  44  49  53  58  63  68  73  78  83  86  87  90  91  92  95  99
0x44 SLOW(20km/h)  73  74  76  78  79  81  83  84  86  88  89  89  89  91  92  95  99
```

Attribute isolation (all others pinned at 40, one raised to 99): [a]

| action | base at 40 | Catching | Clearances | Reflexes | Reach |
|---|---|---|---|---|---|
| 0x44 Catch (fast) | 40 | **+59** | 0 | 0 | 0 |
| 0x45 Punch | 40 | 0 | **+59** | 0 | 0 |
| 0x46 sub0 Deflect | 50 | 0 | 0 | 0 | **+49** |
| 0x46 sub1 Deflect | 63 | 0 | 0 | **+36** | 0 |
| 0x47 SnapUnder | 40 | **+59** | 0 | 0 | 0 |
| 0x48 ScoopOut | 50 | 0 | 0 | 0 | **+49** |
| 0x49 Block | 40 | 0 | 0 | 0 | **+59** |
| **0x44 SLOW** | **73** | **+26** | 0 | **+26** | **+26** |

The `+5` bonus fires **only** when `flagQuery(player,0x1e)` is true **and**
`situationRecord[+0x1c] == 6`; neither alone does anything (all four combinations emulated). [a]
Speed sweep: 49.9 km/h → 83, 50.0 km/h → 68. The gate is exact and hard. [a]

### What the number is actually for — `0x143f31470`

`0x144032870`'s four callers are `0x143f3149e`, `0x143f36f32`, `0x14402a68c`, `0x144037bed`,
all under `SavingBase::vf4` / `vf13`. The cleanest is
**`0x143f31470(saving, player, sub)`**, which reads `saving+0x30` for the action id, calls the
selector, and converts: [b]

```
q  = SaveQuality(player, this->actionId, sub)
id == 0x49 (Block):        BASE = 1.00, C = 0.40, ramp = clamp01((q-40)/80)
id == 0x44 (Catch):        BASE = 0.95, C = 0.30, ramp = clamp01((q-40)/80)
id == 0x46 && sub == 1:    BASE = 0.90, C = 0.32, ramp = clamp01((q-20)/110)
everything else:           BASE = 0.90, C = 0.30, ramp = clamp01((q-40)/80)
return ramp * C + BASE
```

Constants, all read out of the image: `1.0 @0x1478502b8`, `0.40 @0x145b2a690`,
`0.95 @0x145e8788c`, `0.30 @0x145b28a88`, `0.90 @0x145b56e08`, `0.32 @0x145e8786c`,
`40.0 @0x145d58ec8`, `20.0 @0x145a8aa44`, `120.0 @0x145b530b0`, `130.0 @0x146b18f78`,
`80.0 @0x145a8aa48`, `110.0 @0x145c7e428`. [b]

**Composing the two — the number that matters** [a, from the emulated q above]:

| save | attr 40 | attr 99 | total spread |
|---|---|---|---|
| Catch, fast ball | **0.950** | **1.171** | 23 % |
| Catch, slow ball (< 50 km/h) | **1.074** | **1.171** | **9 %** |
| Punch | 0.900 | 1.121 | 25 % |
| Deflect (Reflexes branch) | 1.025 | 1.130 | 10 % |
| Deflect / ScoopOut (Reach branch) | 0.938 | 1.121 | 20 % |
| SnapUnder | 0.900 | 1.121 | 25 % |
| Block | 1.000 | 1.295 | 30 % |

The result is consumed in `0x143f3c1f0` (reached from `vf13`), where it is combined with
per-motion caps selected by the save's **animation id** `[rbx+0x90]` (`0x799`, `0x62f`,
`0x53e`, `0x227`, `0x1ecb` are compared) and capped — e.g. `minss xmm6, 1.19 @0x143f3c580`,
plus per-case ceilings `0.80 @0x145b2a694`, `0.85 @0x1462bbed4`, `0.95 @0x145e8788c`. [b]

### What this means for editing keeper attributes in master.db

* **GK Catching and GK Parrying (Clearances) are linear and fully useful** — the whole 40..99
  range maps 1:1 (×0.98 below 90). Editing them does what you expect.
* **GK Reflexes is compressed to 63..99** — the bottom 23 points of the scale are unreachable.
  Dropping a keeper from 70 to 40 buys only 15 quality points, not 30.
* **GK Reach is compressed to 50..99 on Deflect/ScoopOut** but is **linear on Block**. The same
  attribute behaves differently depending on which save the keeper plays.
* **On any ball under 50 km/h the game takes `max(Catching, Reflexes, Reach)`** and remaps
  40..90 into 73..89. **A single-attribute nerf is invisible here** — lower all three together,
  or the max picks up whichever you left high.
* **91 is a cliff.** Attributes 91..99 skip the remap entirely: Reach 90 → 87, Reach 91 → 91.
  For a smooth roster keep GK Reflexes and GK Reach **at or below 90**.
* The end-to-end effect of the whole goalkeeping block is a **0.90–1.30 multiplier**. You cannot
  make a keeper bad by lowering attributes alone: the worst keeper in the world is ~70–75 % as
  good as the best, per save.

---

## 3. Is the save outcome random?

**Closure saturation warning first.** A plain forward closure from `SavingBase::vf4` or `vf13`
explores **33,188–33,354 functions** and returns the same RNG answer for almost any root
(`0x14401a900`, the kick builder, gives 33,116 and the identical set). **That result is an
artefact of a merged SCC and is not reported as a finding.** The bounding controls:

| root | explored | true RNG reached |
|---|---|---|
| `SavingBase::vf2` (`canStart`) | 15 | NONE |
| `SavingBase::vf14` (`canCancel`) | 48 | none (its `0x144345c10` hit is an angle helper) |
| `Block::vf30` | 1 | NONE |
| `0x144032870` selector | 19 | NONE |
| `0x143f31470` skill scale | 20 | NONE |
| **POS CTRL** `0x144228170` (keeper standing error) | 34 | **`0x144345e50` at depth 1** |
| **NEG CTRL** `0x143ea8cb0` attribute getter | 5 | NONE |

**The true RNG entry points** are the five functions that touch the LCG multiplier `0x2d22b2e3`:
`0x144345d90`, `0x144345e00`, `0x144345e50`, `0x144345eb0`, `0x1443461a0` (171 direct call sites
image-wide). The other 15 functions in the `0x144345c00..0x144346400` band are vector/angle math
and must not be counted — an earlier pass of this probe mis-classified `0x144346360` (a vector
rotate called from `SavingBase::vf24`) as RNG. [b]

**In-body test.** Direct RNG call sites inside method bodies: [b]

| namespace | methods | RNG sites in body |
|---|---|---|
| `goal_keeper::` (14 classes) | 114 | **0** |
| `match::anime::action::` (all) | 593 | **0** |
| `match::player::ActionKeeper*` | 93 | **0** |
| `match::player::` (all) | 450 | 12 (all in `ActionShoot::vf6`) |
| `match::ai::bp::` | 237 | 8 |

The `ActionKeeper*` zero is a **lower bound**, not a proof of determinism: the keeper's known
standing-error roll lives in the non-virtual helper `0x144228170`, not in a vtable body.

**Bounded BFS.** From `SavingBase::vf4 + vf13`, depth ≤ 2 explores 264 functions and reaches no
RNG; depth 3 explores 437 and reaches **exactly one**: [b]

```
0x143f305c0 (SavingBase::vf4)
  -> 0x143f46370   @ 0x143f307a8      the save body, 1,735 lines
    -> 0x143ea9260 @ 0x143f47bee / 0x143f47c26
      -> 0x144345d90 @ 0x143ea9274
```

`0x143ea9260(player, N)` = `RandInt(player+0x3bb4, stream 2) % N`. Its three uses in the save
body: [b]

| site | draw | result |
|---|---|---|
| `0x143f47be6` (`flag[rbp-0x4c] & 8`) | `RandInt % 10` | `-r * 0.01` → **0 to −0.09 m** |
| `0x143f47c0d` (`saving->actionId == 0x46`) | `RandInt % 5` | `-r * 0.01` → **0 to −0.04 m** |
| `0x143f47c1e` | `RandInt % 21` | `r * 0.01 − offset` → a 0.20 m span |

**Answer: the save outcome is essentially deterministic.** There is no dice roll that decides
save-vs-goal. The only randomness at this layer is a centimetre-scale offset on the save's
target point — largest span 0.20 m, and only 0.04 m for a diving parry. Everything else
(reach, timing, quality) is a pure function of attributes, geometry and the animation table.
The stream is `player+0x3bb4` index 2, so it is per-player and re-rolled per save.

---

## 4. First touch and the trap family

### Ball Control is not the first-touch attribute

**`0x18` = `DATA_PARAMETER_TRAP`, UI name "Ball Control"** — despite the name, its **25 read
sites image-wide contain no trap function at all**: [b]

```
0x143f939c7  Dribble::vf6      0x143f99612  Dribble::vf29     0x143f99721  Dribble::vf30
0x1456c7fd4  bp::DribbleImageTrapThrough::vf2
+ 0x143f93b90 x3, 0x143f9c560 x2, 0x143faa0d0 x4, 0x144082060 x2, 0x143ec8410, 0x143ee47c0,
  0x143ef3cf0, 0x143f0e790, 0x143f15300, 0x143f9ea50, 0x143fac980, 0x145663920 x2, 0x145668460
```

Every one is in the dribble/carry band. **The attribute the trap family reads is `0x19` =
`BALL_TOUCH`, UI name "Tight Possession"** — `Trap::vf22` (`0x143f876a6`), `Trap::vf19`
(`0x143f87851`), the trap-info builders `0x143f834b0` / `0x143f83ac0` / `0x143f840d0` /
`0x143f84530`, `Feint::vf8`, and the ball-control term below. [b]

### The `ballControlRate` term the owner's ruling refers to

**It is `trap.ballControlRate`, dt270 object `trap` (idx 111,
`DevelopData/common/match/constant/player/trap.json`), float.
Stock value = `1.0`.** [a — `dt270_objects.py get trap ballControlRate` returns **1** against the
installed pack *and* against `Backups/eFootball/dt270_console_all.PRISTINE.cpk`; `gameplay_tune diff`
shows 7 differing params, all `basePosition.*`, none in `trap`. The `0.80` printed in the first
version of this chapter is **our own** tuning value — `tools/data/tunings/loose-realism-v1.json`
carries `{"object":"trap","path":"ballControlRate","value":0.8,"was":1}` — read out of an Aug-23
`build/dt270_json` dump of an older patch family. Never read a dt270 value from `build/dt270_json/`.]
Addressing note: the `56` used below is `dt270_liveness.json`'s `soff`, i.e. the runtime struct
offset the readers use (`[rax+0x38]`); `dt270_schema.json` gives `off` 16 on a different basis.
Three readers, all `mulss`: [b, `build/dt270_liveness.json`]

```
0x144079c38  mulss xmm12, [rax+0x38]   in 0x144079a70
0x144079dc3  mulss xmm10, [rax+0x38]   in 0x144079a70
0x14407aab5  mulss xmm0,  [rax+0x38]   in 0x14407a9f0
```

Both functions sit under **`match::anime::action::Trap::vf4`** (`0x143f86d50`);
`0x144079a70` is also reached from `Feint::vf4`.

**`0x14407a9f0(ctx)` decoded** [b]:

```
0x1442bfae0(&lo, &hi, idx)        ; attribute range table at 0x146c00860, 2 bytes per idx
                                  ; idx 0x19 -> lo = 40, hi = 99  (table read out of the image)
a   = ATTR_get(player, 0x19)                       ; Tight Possession        @0x14407aa23
if  0x144306be0(ball, slot):  a += 6               ;                         @0x14407aa49
cap = 0x144079020(player)                          ; weak-foot reduction, 0 on the strong foot
x   = a - min(a, cap)                              ; = max(0, a - cap)       @0x14407aa84
t   = (x <= 40) ? 0 : (x >= 99) ? 1.0 : (x - 40) / 59
return t * trap.ballControlRate                    ;                         @0x14407aab5
```

**That is the ruling's term.** `t` is a clamp01 normalisation of Tight Possession over the
attribute's own 40..99 range; `trap.ballControlRate` is the ceiling. At `ballControlRate = 1.0`
a Tight-Possession-99 player's term is **exactly 1.0**, which is what makes him mathematically
incapable of the error the term sizes. **Stock IS 1.0** — so the shipped game sits exactly on the
saturation the owner's ruling forbids, and **lowering this field is the lever**, not protecting it.
At 0.80 a TP99 player tops out at 0.80 while a TP40 player stays at 0; 0.80 and 0.65 are the values
this project has already tried. (The first version of this chapter said the opposite, on a stale
value — see above.) [a/b]

`0x144079a70` computes **two** such terms and they use **different attributes**: [b]

* **contested branch** (gated at `0x144079b2b..0x144079b98` on a situation kind in
  `{1,2,3,0xd,6,7}` and the player's role byte `player+0x2bd8`) → **Aggression (`0x1f`)**,
  read at `0x144079bba` and `0x144079c6c`;
* **uncontested branch** (`0x144079cf4`) → calls `0x14407a9f0`, i.e. **Tight Possession
  (`0x19`)**, plus a second read at `0x144079d30`.

In both branches the second term uses the *level-up* range table `0x146c008e0`
(`0x1442bfb10`), whose entry for 0x19 and 0x1f is `lo=40, hi=120`, with `hi` then forced to
`0x63 = 99` by `mov byte ptr [rbp+0x40], 0x63`. Both terms are multiplied by
`trap.ballControlRate`. The squared form `term²` is kept at `[rbp+0x58]`; both feed a reach/time
budget (`… * 1000 / v`, compared against a distance at `0x143f... 0x144079ef3`) — i.e. **how far
ahead of the ball the player may take his first touch.** [b]

`0x144079020` — the weak-foot cap — reads **STRONGER_FOOT (`0x35`)** at `0x144079037`, resolves
the contact foot via `0x143e948c0`, returns **0** on the strong foot, and otherwise runs a
second normalisation over **Weak Foot Accuracy (`0x27`, range 0..3)** scaled by
**`trap.ballControlWeekFootDownLimit` = 20.0** (`mulss xmm7, [rax+0x3c] @0x144079163`). [b]

### How a trap type is chosen

`0x143f834b0` is the trap-info builder. It: [b]

1. reads **Tight Possession** (`mov edx,0x19 @0x143f8351a`) and passes it as an **int in `r8d`**
   into `0x143f87ad0(ctx, player)` — so TP is a direct input to the candidate build;
2. constructs the candidate `CTrap*AnimeInfo` objects — `CTrapAnimeInfo` ×4,
   `CFastTrapAnimeInfo`, `CCancelTrapAnimeInfo`, `CStaggerAnimeInfo`, `CTrapAnimePlayer` ×2;
3. references **`match::MbInfoManager`** (`0x143e940dd`) and `match::MbInfoLoadThread` — i.e.
   this is where the `cpk_dat/common/anime/Mbinfo/*` tables of GIVEN #1/#2 are consulted;
4. reads `trap.staggerTrapHeight` at `0x143f83848` (and again in the sibling `0x143f83ac0`).

The eight `CTrap*AnimeInfo` classes share a **24-slot** contract (`CTrapAnimeInfo` vft
`0x146b62118`); the per-class overrides are slots 2, 3, 5, 7, 9–14, 16, 22, 23 — the rest are
identical, so the "types" are variants of one evaluator, not separate algorithms.
`CTrapAnimePlayer` is a **1-slot** class (destructor only, vft `0x146b622a8`): it holds data,
it has no behaviour.

### dt270 `trap` liveness — what is and is not tunable

`trap` has **126 fields, 94 read, 32 unread**, 46 get-sites, and the liveness note says *every
tracked pointer was followed to the end*. Notable: [b]

| field | offset | status | note |
|---|---|---|---|
| `ballControlRate` | 56 (`soff`; schema `off` 16) | **read ×3** | stock **`1.0`** — the ruling's term, and it **saturates as shipped** |
| `ballControlWeekFootDownLimit` | 60 | **read ×1** | stock `20.0` |
| `staggerTrapHeight` | 448 | read ×2 | in the trap chooser |
| `trapCutFrame.default` / `.fast` | 484 / 488 | read | stock `8` / `0` |
| `animeCancelFrame.*` | 28–40 | read, all in `Trap::vf14` | the trap's own cancel window |
| `hitAfterCancel.*` | 272–292 | read, `0x143f8da40` | |
| **`trapLoss`** | 492 | **UNREAD** | stock `true` — **a dead switch** |
| **`trapLossDashOnly`** | 493 | **UNREAD** | stock `false` — **a dead switch** |
| `reachOut.ballSpeed` / `.reach` | 312 / 316 | **UNREAD** (though `reachOut.use` at 320 *is* read) | |
| `autoR2.*` | 44–52 | UNREAD | |

> **`trapLoss` is inert.** The one dt270 field actually *named* "lose the ball on a trap" has no
> reader anywhere. Turning it on or off changes nothing. Item 3's looseness must come from
> `ballControlRate` and the attribute spread, not from this flag.

---

## 5. Does the ball deflect off non-tackling players?

**Settled, negative, with numbers.**

The ball's own motion integrator is `0x14408d0f0` (49 call sites; reached at depth 1 from
`action::Restart::vf8`, depth 2 from `RecieveBall::vf4`, `Kick::vf8`, `MatchControl::vf20`,
`BallControl::vf1`, depth 3 from `SavingBase::vf30`). Its **forward closure is 15 functions**
and it reaches: [b]

| target | reached? |
|---|---|
| attribute getter `0x143ea8cb0` | **no** |
| collision check `0x14512fe90` | **no** |
| collision request builder `0x145130710` | **no** |
| any true RNG | **no** |
| dt270 `get()` `0x145348d70` | **no** |

15 functions is a healthy non-degenerate closure (the failure mode for a broken graph is 1), and
the same machinery reaches all five targets from other roots, so the graph is sound.

Every dt270 `ball` field that mentions bouncing (`boundRate[]`, `boundCheckBoundAddRate[]`,
`boundCheckFrictionAddRate[]`, `natualBoundA[]`, `boundToRotationAddRateXZ[]`, …) is an array of
**exactly 6 entries**, and every one is read in that same single function. The values —
`boundRate = [0.77, 0.77, 0.77, 0.55, 0.77, 0.77]`,
`natualBoundA = [0.155, 0.155, 0.155, 0.155, 0.055, 0.055]`,
`boundCheckFrictionAddRate = [0, 0, 0, 0, 7.5, 0]` — are **ground-surface** variants. There is
no body entry. [b]

**CORRECTED 2026-09-20 — `collision::Human` is NOT dead.** vft `0x147484f80` (one method
`0x145130620`) has two code referrers, `0x1451305f3` / `0x145130640`, the ctor/dtor pair; the ctor
is `0x1451305f0` (not `0x1451305f1`) and it has **one** direct caller, `0x143ff224d`, inside the
factory `0x143ff2210` — which stamps vftable `0x146b6fb48` = **`match::AnimeCollision`**, news 0x28
bytes and stores the object at `+8`. That factory has **three** call sites (`0x14410ba5d`,
`0x14410bb37`, `0x14410bbe7`), each attaching the result at `AnimePlayer+0x47a8`. So a **per-player
collision body exists** and was never followed; the ricochet negative in `anime-actions.md` is
downgraded to one-sided on the strength of this. [b] The `collision::` stack that
*is* live in a match (`collision::Manager`, reached from `match::Match::vf1` and
`match::CollisionInitListener::vf1`) is a static-geometry service; the ball never enters it.
`0x144fa58d0`, the per-frame physics filter-group setter, is called from `match::Human::vf9` /
`match::Player::vf9` and writes a 16-bit group/mask — it is the **ragdoll** association, which
only matters once a body is already a physics object. [b]

**Conclusion — WEAKENED 2026-09-20 to match the correction above it.** What is proven is the
*positive* half: every ball↔player contact this probe followed is initiated by a player-side
**action** writing the ball (`Trap`, `Kick`, `Block`, `Tackle`, the six saves, `RecieveBall`,
`CarryBall`), and **the ball's integrator never consults a player body** [b]. What is **not** proven
is the flat negative "the ball cannot ricochet off a player as physics": the correction immediately
above found a **per-player collision body** (`match::AnimeCollision`, factory `0x143ff2210`, three
call sites, attached at `AnimePlayer+0x47a8`) that **was never followed**. Until it is, the negative
is one-sided — the ball model does not reach for a player, but nothing here rules out that object
reaching for the ball.

So item 3's "ricochets" is **still open**, not closed. The route this probe *can* support is making
an action fire that would not otherwise fire (code, not data); whether `AnimeCollision` offers a
second route is the first thing the next pass should settle.

**What is *not* settled:** whether any of those actions can auto-fire on proximity without the
player having chosen it (a "he couldn't get out of the way" block). That needs the action
selector in `match::player` / `match::ai`, not this subsystem, and I did not test it.

---

## 6. Input census for this probe

### Attributes (index → site → effect)

| idx | UI name | sites in this probe's classes | effect |
|---|---|---|---|
| `0x18` | Ball Control (`TRAP`) | **none** | *not* a first-touch attribute — see §4 |
| `0x19` | Tight Possession (`BALL_TOUCH`) | `Trap::vf22 0x143f876a6`, `Trap::vf19 0x143f87851`, trap builders `0x143f83522` / `0x143f83b32` / `0x143f8414c` / `0x143f845ac`, `0x143f89242`, `0x143f896e5`, `0x143f89a4d`, `0x143f8edfa`, `Feint::vf8 0x143f9fded`, `0x14407aa23`, `0x144079d30` | first-touch reach/time budget, ×`ballControlRate` |
| `0x1f` | Aggression | `0x144079bba`, `0x144079c6c` | the contested-first-touch variant of the same term |
| `0x23` | GK Catching | `0x144032891` (selector), `0x143e3a7ac`, `0x143e433dc`, `0x143fe53d6` | Catch (0x44) and SnapUnder (0x47) quality |
| `0x24` | GK Parrying (`CLEARANCES`) | `0x1440420ac` (in `0x144040730`), `0x143fe3056`/`0x143fe314a`/`0x143fe372b` (in `0x143fe2410`), `0x143fe8245` | Punch (0x45) quality |
| `0x25` | GK Reflexes (`COLLAPSING`) | `0x144032907`, `0x14403299c` (selector), `0x143f28d4e`, `0x143e3cac4`, `0x14421ff95` (`ActionKeeperBlockLate::vf6`) | Deflect (0x46) when `sub ∈ {1,4,5}` |
| `0x26` | GK Reach (`DEFLECTING`) | `0x144032916`/`0x1440329bd`/`0x1440329e6` (selector), **`0x143f4ae0b` in `Deflect::vf35`**, `0x143f368da`, `0x143f28c6c` | Deflect (other subs), ScoopOut, Block |
| `0x27` | Weak Foot Accuracy | `0x1440790fc` in `0x144079020` | the weak-foot first-touch penalty |
| `0x2a` | Balance | `0x143f28d95` (alongside Reflexes + Reach in `0x143f28c10`) | a keeper function using all three |
| `0x35` | Stronger Foot | `0x144079037` | selects the weak-foot branch |
| `0x16` | GK Awareness | 12 sites, of which **5 are in the anime band**: `0x143f2c5a9` (`0x143f2b590`), `0x143f4238a` (`0x143f41b80`), `0x143f4a224` (`0x143f49550`), `0x143e4140d`, `0x143e43855` | — |

### dt270

* **`goal_keeper::` method bodies contain ZERO dt270 `get()` sites** (0 of 268 image-wide). The
  save family reads no game-constant data at all in its own code. [b]
* `match::anime` **class method bodies** contain **9**: `0x143f889df` + `0x143f88ae8`
  (`Trap::vf14` → `trap`), `0x14404e36c` (`CTrapAnimeInfo::vf5` → `trap`), `0x143f0522b`
  (→ `ball`), `0x143fbd332`, `0x143fbdbe7`, `0x143f091f8`, `0x143fce329`, `0x143fc84fb`.
* The **anime address band** `0x143e90000..0x144090000` holds **83** get-sites across **60**
  functions — the big ones are `0x14405cc60` (×8, `trap.ballForceDirect.*`), `0x14404bf80` (×3),
  `0x143fef370` (×3), **`0x144079a70` (×3 — the ball-control term)**.
* Objects reaching this probe: **`trap`** (126 fields, 94 read) and **`ball`** (66 fields,
  55 read, `unread_confidence: reduced`).

### CPU difficulty

**None.** 0 of 24 `AiLevelUnit::GetParam(0x1442e48f0)` sites, 0 of 46
`Team::GetCurrentLevel(0x1442ee570)` sites and 0 of 20 `IsEnabled(0x1442e4c00)` sites lie inside
any `goal_keeper::`, trap-family or **any** `match::anime` method body — and none lies in the
anime address band. **Save quality and first-touch quality are identical on Beginner and
Legend.** [b]

### Motion assets

Animation / motion ids named in this probe's code, for whoever reads `Animation.bin`
(36 B × 4,345, 13-bit index) and `CancelData.bin` (12 B × 5,746): [b]

| id | where |
|---|---|
| `0xb9c` (2972) | `SavingBase::vf47` default motion; also written into `Sliding` at `0x143e9ebae` |
| `0x75d` (1885) | `SavingBase::vf34` `0x143f34090` |
| `0x1ecb` (7883) | `SavingBase::vf49` `0x144043da0`; `vf13` writes it to `[rdi+0x3c]` and `[rdi+0x40]` at `0x143f329fe`/`0x143f32a05` |
| `0x799`, `0x62f`, `0x53e`, `0x227` | per-motion caps in `0x143f3c1f0` (`[rbx+0x90]` compares) |
| `0x82b` | `Tackle` ctor `0x143e9ec5e` |

**Caveat:** `0x1ecb = 7883` exceeds `Animation.bin`'s 4,345 records, so at least that id is
**not** an `Animation.bin` row index — it belongs to a wider id space (the 11,096-name pool at
`0x6a7a4e4..0x6bb3510`). Do not assume one id space. [c]

---

## Corrections to finished chapters

### To `docs/player-executors.md` (§ The goalkeeper)

1. **"They all converge on `0x144032870`" is too strong.** GK Reach (`0x26`) is also read at
   **`0x143f4ae0b`, inside `goal_keeper::Deflect::vf35` (`0x143f4add0`)**, outside the selector.
   GK Parrying (`0x24`) is read at `0x143fe3056`/`0x143fe314a`/`0x143fe372b` (all in
   `0x143fe2410`) and `0x143fe8245`; GK Catching at `0x143e3a7ac`, `0x143e433dc`, `0x143fe53d6`;
   GK Reflexes at `0x143e3cac4` and `0x143f28d4e`. The selector is the *main* consumer, not the
   only one. [b]
2. **"floors Reach at an output 50 and Reflexes at 63" is right but incomplete.** Those are the
   minima at attribute 40. The chapter's table omits the **discontinuity at 91**: attributes
   above 90 skip the remap, so Reach 90 → 87 but Reach 91 → **91**, and slow-ball Catch 90 → 89
   but 91 → **91**. [a]
3. **The chapter never says what the number is for.** It stops at the 40..120 quality. The
   consumer is `0x143f31470`, which converts it to a **0.90–1.40 multiplier**; the
   keeper-attribute spread over the whole 40..99 roster is only **9–30 %** depending on the save
   type. That is the actionable figure and it was missing. [a]
4. The chapter's tunables row says the selector "is in the **animation** layer, subsystem 3" —
   confirmed and now located: the four callers are all under `goal_keeper::SavingBase::vf4`
   (`0x143f305c0`) and `::vf13` (`0x143f32880`).
5. **`0x1440374b0`'s apparent caller `fox::nio::impl::TcpSocketImpl::vf13` at depth 1 is an
   identical-code-folding artefact**, not a real edge. Do not build on it.

### To `docs/pes2014-vs-efootball-contact.md`

6. **"`Jostle*` action classes: PES 2014 **9** → eFootball **0**" is WRONG.**
   `match::anime::action::Jostle` **exists in eFootball**: vftable `0x146b4a3b8`, 29 slots,
   bases `Base` + `JostleRetryWork`, constructed by the `ActionManager` ctor at
   **`ActionManager+0x1360`** (`0x143e9f65b`), alongside `Trap`, `Contact` and `Tackle`. What
   eFootball dropped is the **eight concrete variants** (`JostleHighballBack/Front/SideEarly/
   SideLate`, `JostleIdleBack/Front`, `JostleMoveBack/Front`). The correct row is **9 → 1**, and
   the surviving class is live, not vestigial. [b]
7. **"`*RetryWork` classes: ~22 → 0" is WRONG, and backwards.** eFootball's RTTI carries **78**
   `RetryWork` types to PES 2014's **52** — *more*, not fewer. 45 are under `match::anime`,
   including `ContactRetryWork`, `TackleRetryWork`, `SlidingRetryWork`, `TrapRetryWork`,
   `JostleRetryWork`, `goal_keeper::PreSavingRetryWork`, `goal_keeper::AfterCatchRetryWork`,
   `goal_keeper::SeeOffRetryWork`.
   **Why the earlier count said zero:** they are declared `struct`, so their RTTI descriptors are
   `.?AU…@@`, and a scan for `.?AV…@@` (class) misses all of them; `tools/exe_map.py grep` also
   misses them because they carry no vftable of their own. Both games counted with the same
   `.?A[UV]` regex. [b]
   The chapter's conclusion — "the contest was restructured, not deleted" — survives and is
   strengthened: the retry mechanism it called "the quiet one" was **never removed**.
   `PairAnime` really is gone (0 occurrences in eFootball, 10 in PES 2014). [b]

### To `docs/anime-actions.md`

8. GIVEN #5's "38 dt270 call sites in 17 `match::anime` functions" counts **address-band**
   functions. Inside actual `match::anime` **class method bodies** there are **9**; inside the
   band `0x143e90000..0x144090000` there are **83 across 60 functions**. Both are useful numbers
   but they are not the same population, and **0** of either lands in a `goal_keeper::` body.
   The answer to the chapter's open question 6, for this probe's classes, is **parameters, not
   decisions** — and for the save family, not even parameters. [b]
9. Open question 5 ("the `goal_keeper::` 50-method save family") is answered in §1 above.

---

## Negatives (things that are NOT there)

* No RNG decides a save. No difficulty term reaches a save or a first touch.
* No dt270 field reaches any `goal_keeper::` method body.
* Ball Control (`0x18`) does not touch the trap family.
* `trap.trapLoss` and `trap.trapLossDashOnly` have no readers — dead switches.
* `trap.reachOut.ballSpeed` and `.reach` have no readers, although `reachOut.use` does.
* The ball's integrator never consults a player body [b]. ~~there is no generic ricochet~~ — that stronger claim is **withdrawn**; `match::AnimeCollision` (per-player, attached at `AnimePlayer+0x47a8`) was never followed, so the negative is one-sided.
* `Deflect::vf37` and `SnapUnder::vf37` multiply their float input by zero.
* The 50 km/h save-speed threshold cell `0x145ae7580` has **503 referrers** — it is the generic
  `50.0f` constant and must not be edited in place.

---

## Provenance

`emu_gk.py` (this session's scratchpad) emulates `0x144032870` from its first instruction to the
instruction before its `ret` at `0x144032a74`, on bytes mapped straight out of PRISTINE, with
`0x143ea8cb0` (attributes), `0x143eadbe0` (flag `0x1e`), `0x1442d6c50`/`0x1442d6fe0`/
`0x1442eaba0` (object lookups), `0x144307000` (ball speed) and `0x14533ea80` (frame rate)
stubbed at their call sites. The emulator logs the attribute indices it is asked for, and they
match the disassembly on every path.

PRISTINE vs INSTALLED, all identical:
`0x144032870..0x144032a90`, `0x143f31470..0x143f3157a`, `0x143f305c0..0x143f30900`,
`0x143f32880..0x143f32b70`, `0x143f4a520..0x143f4ec40`, `0x143f3c1f0..0x143f3caf0`,
`0x14407a9f0..0x14407aad0`, `0x144079a70..0x14407a600`, `0x143f834b0..0x143f83ab0`,
`0x144079020..0x144079180`, `0x146c00860..0x146c008e0`, `0x14408d0f0..0x14408e000`,
`0x143e9eb00..0x143e9f940`, `0x143f30e40..0x143f34400`.

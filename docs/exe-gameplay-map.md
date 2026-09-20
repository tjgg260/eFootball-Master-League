# eFootball.exe gameplay map (2026-08-23)

Static reverse-engineering map of `eFootball.exe` (352 MB, MSVC x64, **RTTI intact**, Denuvo
Anti-Tamper; no anti-cheat module shipped). Produced by five explorer agents + two independent
skeptics over `tools/exe_map.py` (RTTI → vftables → 64,158 virtual methods, disassembly, xrefs).
All addresses are virtual addresses at the preferred base `0x140000000` (the PE has no
dynamic-base flag; `tools/live_patch.py probe` verifies the runtime base).

> **SUPERSEDED 2026-09-19 — this document's "never touch the exe on disk" premise is wrong in
> practice and the owner has ruled it out of scope as a constraint.** See § Constraints below.

Confidence: **proven** = the code was followed instruction by instruction (and, for the
`dt270-consumers` and `decision-units` areas, re-derived by a second agent); **likely** =
structural/naming evidence; **guess** = hypothesis. Skeptic corrections are listed per area.

## What this enables

| want | where | how |
|---|---|---|
| more pass/shot error for everyone | kick-miss builder `0x14401a900`: max angle error `(1−f)·22.5°`, speed error `30%`, Gaussian σ `0.75+4.25·p·(1−f)` | repoint the `22.5f` / `4.25f` operand (RIP disp32) at a bigger float cell, or patch the ability→factor curve `0x143ed71d0` |
| weaker CPU at SUPERSTAR | level table B `0x146c06f40` (44 rows × 10 cols, row 0 = reaction-delay frames 30…0) | write a TOPPLAYER/REGULAR column value into the SUPERSTAR column for the rows that matter |
| a hidden harder level | LEGEND (6) + sub-levels exist at runtime (`AiLevelUnit`, XOR-obfuscated) | set `TmpDb+0x94/+0x9c = 6`, `+0x98/+0xa0 = 2` before kickoff |
| CPU shooting/passing choices | `match::ai::ActionSelector*` (e.g. `ActionSelectorScore::vf2 0x143df1080`), `match::ai::Judge`, `PlayerOffence` | next mapping target — thresholds not yet traced |
| confirm a dt270 field is live | `ConstantManager` `0x148c22b98` → `get(idx)` `0x145348d70`; consumers read struct offsets | see the consumer table; three tuning levers found inert |

## The baseline: `eFootball.exe.PRISTINE` is NOT stock (found 2026-09-20)

Every chapter uses "verified against PRISTINE" as a synonym for "stock". It is very slightly false.
`C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE` differs from the untouched Konami binary
by **2 bytes**, and the untouched binary is on disk next to the live one as
`Binaries/Win64/eFootballonlinevanilla.exe`.

The edit is a hostname: `pes22-game.cs.konami.net` -> **`pes99-`**, at `0x146e6fae3`. `pes99-` does
not resolve, so it severs matchmaking. It is present in PRISTINE, in the live `eFootball.exe` and in
`eFootballhi.exe`; only `eFootballonlinevanilla.exe` retains the original.

**Impact on the decode work: none.** It is a string in a data region, not gameplay code, and no
chapter's claim touches it. But when a truly clean reference is needed, use
`eFootballonlinevanilla.exe`, not PRISTINE.

**Impact on anything you BUILD from PRISTINE: it inherits the matchmaking block.** Confirmed
2026-09-20 by building `variants/eFootball.exe.difficulty-variance-v1` from PRISTINE and diffing it
against `eFootballonlinevanilla.exe`: **5 bytes** — the 3 intended gameplay edits at `0x6c0635f`,
`0x6c06ac2`, `0x6c06ac3`, plus the 2 inherited hostname bytes at `0x6e6eee3`, `0x6e6eee4`. For an
offline Master League build that is harmless and arguably wanted (it enforces the standing "keep
modified builds away from online" rule). Just never ship a PRISTINE-derived exe to someone
expecting online play, and state the inheritance whenever handing one over.

**The block is narrower than it looks.** Only 1 of the 11 Konami hostnames in the image was changed.
`https://info.service.konami.net`, `ntl/ntleu/ntljp/ntlus.service.konami.net` (http and https) and
`pesam.stun.service.konami.net` are all intact. This stops you joining matches; it does not stop the
install talking to Konami.

**File census (2026-09-20), all 352,409,088 bytes:**

| file | vs PRISTINE | what it is |
|---|---|---|
| `eFootballonlinevanilla.exe` | 2 bytes / 1 run | the untouched original (19 Aug) |
| `eFootballhi.exe` | 104 bytes / 38 runs | **a mod build**, not a backup (25 Aug) — edits in `ActionSelectorCounterSpaceRun::vf4`, `AnimePlayer::vf3`, `anime::action::Kick::vf19` x2, `Sliding::vf5`, `Injury::vf4` x2 and the kick-builder band. Consistent with the August hyper-realism build that was wiped to stock ~09-13 |
| `eFootball.exe` (live) | ~~909 bytes / 105 runs~~ **do not quote this number** | the current build — see `realism-todo.md` for the inventory |

**The live-exe byte count is not a fact you can write down.** Measured three times on 2026-09-20 it
read **909**, then **63**, then **157** — it moves within a session because patches are applied and
reverted continuously, sometimes by a concurrent session working in another worktree (the game dir
also accumulates `eFootball.exe.V*` variants as that happens). **Always measure, never cite:**

```bash
python tools/exe_patch.py diff      # byte count vs PRISTINE
python tools/exe_patch.py status    # per-spec applied / pristine / OTHER
```

`OTHER` means a site holds neither the original nor that spec's patched bytes — i.e. something else
overwrote it. Several specs read `OTHER` on 2026-09-20. The catalogue makes the same point in
`catalogue-notes.md` § "Applied right now" is measured, not looked up.

`eFootballhi.exe` shares some sites with the live exe (`AnimePlayer::vf3`, the kick-builder cluster)
and not others, so it is a **different** edit set, not an ancestor of it.

## Constraints

- **Denuvo / disk patching — CORRECTED 2026-09-19.** This section used to read "exe on disk is
  sacred; every patch is an in-memory write". That is **contradicted by the installed image**: a
  byte diff of INSTALLED against `eFootball.exe.PRISTINE` gives **909 differing bytes in 105
  contiguous runs, 100 of them in the match band `0x143000000`–`0x144800000`**, at an unchanged
  file size — i.e. this project has been shipping on-disk code patches for some time and the game
  runs with them. The feared integrity trip has not been observed. **OWNER RULING 2026-09-19: "I
  don't mind changing the exe" — on-disk patching is the default route, not a last resort.**
  `live_patch.py` remains available for cases where a runtime-only write is preferable.
  What this ruling does NOT change: the physical limits below and in `match-ai-decoded.md`
  § The cave allocator. Permission was never the binding constraint on those.
- All `match::` code lives in the plaintext `.xcode` section; `.impdata` (183 MB) is the Denuvo
  blob and holds no gameplay code.
- Many float constants are **shared `.tls$` cells** (e.g. `0.5f`, `22.5f`). Never change the
  cell; change the instruction's disp32 to point at another existing cell with the wanted value,
  or a private cell.
## Kick error / accuracy model

The kick error model is fully in the exe (no dt270 field). A single kick-execution function 0x144016a70 converts the intended kick velocity into (angleXZ, angleY, speed), calls 0x14401a900 to build a 0x3c-byte "kick miss parameter" struct (per-axis max error, sign probability, Gaussian sigma, miss type), then applies the deviation with one of three randomizers: 0x14401a060 (normal kicks, type 4), 0x144019e40 (types 1/3) or 0x144019320 (type 0). Randomness comes from an LCG RandInt 0x144345e00 (seed = (0x4513 - seed*0x2d22b2e3) & 0x7fffffff) and a Box-Muller Gaussian 0x144345eb0 that returns an int 0..99 around mean 50 (|g-50|/50 scales the error). Player ability enters via 0x143ed71d0 -> 0x143ed7440: effective ability = SHOT(0x1b)/SHORT_PASS(0x1c)/LONG_PASS(0x1d)/HEADING(0x1e) byte from the match ability array + 6/7 for matching skill cards + 5 for a team flag, minus a weak-foot penalty 3+12*(1-norm(WEAK_FOOT_ACC 0x27)) (3+22 for kick type 4, 1+6 for headers) when kicking foot != STRONGER_FOOT (0x35); that is piecewise-mapped to a 0..1 factor (<60: 0..0.1, 60-90: 0.1..0.9, >90: 0.9..1.0). Five situational sub-functions (0x144020d00, 0x14401eb40, 0x14401bdb0, 0x14401ca10, 0x14401f770; body balance, ball height/speed, facing angle, kick type, skills) each return per-axis factors that 0x144021780 folds together; the final angleXZ error magnitude = (1-combined)*22.5 deg (0x14401b3df), angleY error = (..)*22.5 deg (0x14401b423), speed error = (..)*0.3 (30%) (0x14401b474), Gaussian sigma = max(0.1, 0.75 + 4.25*signProb*(1-..)). The sign probabilities default 0.5 and are biased per animation/kick type by 0x144021870. Best runtime patch lever: the two 22.5f multiplies in 0x14401a900 (RIP-relative reads of shared constant 0x14676e980; repoint the disp32 at a different existing float cell such as 45f @0x145b1d910 or 15f @0x145c0b000), or the 4.25f sigma scale at 0x146b3cfb0 (only 4 xrefs).

| conf | kind | address | finding | evidence | patch idea |
|---|---|---|---|---|---|
| proven | function | `0x144345e00` | Match RNG: LCG RandInt(state*, max, slot) | imul eax,[rcx+r9*4],0x2d22b2e3; r8d=0x4513-eax; btr r8d,31; store; result = int(seed * 2^-31 * max) (mulss by 4.65661e-10 @0x1466dc660). 76 direct callers. Wrappers: 0x143ea9260 = RandInt(player->ctx+0x3bb4, max) via 0x144345d90 slot 2; 0x143eafd30(player, pct) = (rand%100) < pct (imul 0x51eb851f/shr 5 = /100). |  |
| proven | function | `0x144345eb0` | Gaussian random 0..99 (Box-Muller) used for kick error | Two LCG draws from [rdi+8]; u1 -> log table lookup (512 entries @0x146c34f30, scaled 0.000244141 * -2, sqrt @0x140a229f0), u2*360 -> cos via 0x144345b50; result = cos*sqrt(-2ln u1)*sigma(xmm1)/3.53223 + mean(xmm2), *50 +0.5, retry until 0..99 (cmp eax,0x63). Returns int in eax; callers use \|g-50\|/50. 21 callers incl. 0x14401a0e1/0x14401a1f4/0x14401a503 (kick error), 0x144019f4e/0x144019fc3 and ActionShoot[6] 0x1441b536e.. (shot target choice). | Divisor 3.53223f @0x146c35734 scales every Gaussian sigma globally (check xrefs before touching; affects all 21 users). |
| proven | function | `0x144016a70` | Kick execution: intended velocity -> (angleXZ, angleY, speed) -> miss params -> randomized kick | Single caller 0x143ed10f1 (function 0x143ed0f80, player kick dispatcher). Computes \|v\| (sqrt), asin-ish elevation via 0x144345c10, atan2(x,z) via 0x143ba63a0 (*57.2958 deg), normalizes with 0x144345ae0 (wrap 0..360). 0x144016d3d call 0x14401a900 (miss params copied to rbp+0xc4..0x108, type at rbp+0x104 = r12). Switch on type: 1/3 -> 0x144019e40 (0x144016df1), 0 -> 0x144019320 (0x144016e49), 4 (default) -> 0x14401a060 (0x144016e90). Inputs: r8=rsp+0x58 (angleXZ, angleY, speed), r9=out. | Forcing the type byte to a fixed value or NOP-ing the three call sites removes all kick deviation (runtime only, Denuvo). |
| proven | function | `0x14401a900` | Kick miss parameter builder (the accuracy model) | Output struct rsi (0x3c bytes): +0 angleXZ errMax = (1-combinedXZ)*22.5f (0x14401b3df mulss [0x14676e980]); +4 signProb (from 0x144020d00 via rbp+0x120, default 0.5); +8 sigma = max(0.1, 0.75 + 4.25f(@0x146b3cfb0)*signProb*(1-..)); +0x10 angleY errMax = (..)*22.5f (0x14401b423); +0x14/+0x18 prob/sigma; +0x20 speed errRate = (..)*0.3f (0x14401b474, const 0x145b28a88); +0x24/+0x28; +0x30 =1.0; +0x34 type (r15: 0..4, 0x14401e5b0/0x14401fc80/0x144020450 checks pick special miss types 0/1/2, 0x14401b7be sets 3 if speed factor > threshold, then 0x143eafd30(player, int(x*100)) gates it). Ability factor from 0x143ed71d0(player,1) stored at rsp+0x40 and passed as r8 to the five factor sub-functions and used at 0x14401b72f. Distance/kick-speed factor switch at 0x14401acea (65..85, 60..75, 50..60 ranges *0.9). Five factor sources: 0x144020d00 (sign bias), 0x14401eb40 (body balance [player+0x34ac], ball height, body part [player+0x2bdc]), 0x14401bdb0 (kick type table, facing-angle diff [r8+0x40], skill 0x35), 0x14401ca10, 0x14401f770 (skills, abilities 0x1e/0x2d/0x32 at 0x144020a38..). Combined per component by 0x144021780 (sort-and-fold of 4 factors with 0x143b45ce0 sort). | Runtime patch: at 0x14401b3df bytes F3 0F 59 05 99 35 75 02 (mulss xmm0,[rip+0x2753599]=22.5f). Replace disp32 with 0x1B02529 to read 45.0f @0x145b1d910 (double angular error) or 0x1BEFC19 to read 15.0f @0x145c0b000 (less error). Same for 0x14401b423 (disp 0x1B024E5 -> 45f). Do NOT edit 0x14676e980 itself: 22.5f there has dozens of xrefs. |
| proven | function | `0x143ed71d0` | Player ability -> 0..1 kick accuracy factor | Calls 0x143ed7440(player, kickInfo, flag=1, abilityId=0x71(auto), 0x14(auto)) returning int ability; piecewise: <60: (ab-40)*0.1/20; 60..90: 0.1+(ab-60)*0.8/30; >90: 0.9+(ab-90)*0.1/9; clamped >=0. Constants 40/60/90/0.1/0.8/0.9 are shared .tls$ cells (0x145d58ec8, 0x145a8dd84, 0x145b52b90, 0x145a8dd68, 0x145b2a694, 0x145b56e08). | Patch the code (not the shared constants): e.g. replace 'maxss xmm1,xmm0' tail to return a constant (movss xmm0,[1.0f cell]) to make every player a perfect kicker, or change the 0x8/0x1e breakpoints via the immediates' disp32. |
| proven | function | `0x143ed7440` | Effective kick ability selection, skill bonuses, weak-foot penalty | 0x143ed74b0: if id==0x71 use action id [player+0xad0]; jump table on action picks ability 0x1b (0x143ed74fc), 0x1c (0x143ed751b/0x143ed7540), 0x1d (0x143ed7539/0x143ed7547), header path 0x143ed79d8 uses 0x1e. 0x143ea8cb0(player,id) -> 0x1442dd650(env, playerIdx, id) -> byte[id] of per-player ability array (0x1441172b0). Skill checks 0x143eadbe0(player, skillId) for ids 0xe,7,0x21,8,0x22,0x1f,0x2a,0x2b,0xa,9,0x2c,0x34 -> counters; 0x143ed77fb/0x143ed780d: +7 or +6; 0x143ed781d: +5 if [teamCtx+0x5098]!=0. 0x143ed787a: ability 0x35 (stronger foot) vs kicking foot [player+0x2bf6]; if mismatch: range of ability 0x27 via 0x1442bfae0, penalty = 3 + 12*(1-norm) (0x143ed78fd, 12f), 3+22*(1-norm) for kick type 4 (0x143ed7907, 22f), 1+6*(1-norm) for header-like types (0x143ed79bf). Result = ability - penalty. | The 12f/22f/6f penalty scales are shared constants; patch the disp32 of the movss at 0x143ed78fd/0x143ed7907 to another cell (e.g. 0 -> no weak-foot penalty). |
| **WRONG — off by one, superseded 2026-09-18** | mechanism | `0x1471d0690` | ~~Match ability array index = dt200 field order + 0x15~~. The real alignment is **DATA_PARAMETER enum + 7**: offensive awareness 0x14, **defensive awareness 0x15**, GK awareness 0x16, dribbling 0x17, shot 0x1a, short_pass 0x1b, long_pass 0x1c, heading 0x1d, intercept 0x1e, r_foot_acc 0x27, speed 0x28, jump 0x2d, form 0x2f, injury-res 0x30, stronger_foot 0x35. Proven by emulating the game's own enum registrar (`0x1409f5043`) and its field-range table (`0x1442bfae0`): only +7 puts the 0..3 / 0..7 / 0..2 ranges at 0x27 / 0x2f / 0x30. See the anticipation section below and `tools/data/attr_index_map.json`. | Header string list at 0x1471d0690: offense_decision(0) speed(1) defense_decision(2) gk_decision(3) dribble(4) trap(5) shot(6) short_pass(7) long_pass(8) heading(9) intercept(10) place_kicking(11) ball_spin_control(12) catching(13) clearances(14) collapsing(15) deflecting(16) r_foot_acc(17) body_balance(18) body_control(19) kick_power(20) agility(21) jump(22) stability(23) durability(24) r_foot_frequency(25) cool(26) star(27). Ids seen at 0x143ea8cb0 call sites span 0x15..0x37; shot/pass/header selection (0x1b/0x1c/0x1d/0x1e), weak-foot accuracy (0x27) and kick power (0x29 at 0x144016f7f vs 0x143ea8cb0(..,0x29)) all fit offset 0x15. 0x35 (=32, beyond the 28 listed) compared against kicking foot -> stronger foot. |  |
| proven | function | `0x14401a060` | Normal kick randomizer (miss type 4) | 0x14401a0e1 Gaussian sigma=[params+0x18]; dev = \|g-50\|/50 * [params+0x10]*(1-[params+0x48]) + [params+0x10]*[params+0x48]; sign by 0x143eafd30(player, [params+0x14]*100) -> angleY. 0x14401a4c0 loop (max 6 draws) for angleXZ using [params+0x0c]*[params+4] and Gaussian with [params+0x18]; 0x14401a1f4 speed with [params+0x20..0x28]; special branch 0x14401a2d1 for shots (action 0xa) using body balance [player+0x34ac] and ball speed windows 30000/3600..50000/3600. Results written to out (r9): out[0]=angleXZ (wrapped 0x144345ae0), out[4]=angleY, out[8]=speed. Second caller 0x142171d1b (outside match, likely a test/preview). |  |
| proven | function | `0x144019e40` | Alternate kick randomizers (miss types 1/3 and 0) | 0x144019e40: angleXZ dev = max(params[0],8)*cos(90+(0.5-rand(1000)*0.5/1000)*90) with sign from prob params[4]; angleY = \|G(sigma params[0x18])-50\|*params[0x10]/50 signed by params[0x14]; speed *= 1 + sign*( \|G(params[0x28])-50\|/50 * params[0x20]*(1-params[0x38]) + params[0x20]*params[0x38] ). 0x144019320 (type 0) called at 0x144016e49 with an extra out flag at rbp+0x70; if flag stays 0 the type is forced to 4 (0x144016e54) and 0x14401a060 runs instead. |  |
| proven | function | `0x144021870` | Sign-probability bias per kick animation/type | Adjusts params+4 / params+0x14 / params+0x24 (via rbx/r14/rsi out pointers): e.g. 0x14402192c *0.1 and set 0.5 when 0x144311e40(action) false; jump tables on anim id [player+0xae8] (0x1440219a4 range 0x822..0x1093, 0x144021afd 0x97c+0xd7); skill 0x18 with body part 8 -> 1.0 (0x144021abc); skill 9 -> 0.7 (0x144021ae6) else 0.8; [player+0x362c]&1 -> r14[0]=0. |  |
| proven | constant | `0x146b3cfb0` | Gaussian sigma scale 4.25f (kick error) - patchable cell | movss xmm3,[0x146b3cfb0] at 0x14401b3a7; sigma = max(0.1, 0.75 + 4.25*signProb*(1-factor)) for all three axes (0x14401b3fb..0x14401b49f). Only 4 xrefs: 0x143e36b27, 0x14401b3ab, 0x1440bf9d5, 0x1453c391e. | Lowering 4.25 -> e.g. 2.0 narrows the Gaussian (tighter, more consistent error); raising widens. Verify the other 3 users before a global value change, or repoint the 0x14401b3a7 disp32. |
| likely | function | `0x1441b4f60` | CPU shot target selection uses the same Gaussian (aim error at decision level) | match::player::ActionShoot vftable[6] (0x146bcbe98). Calls 0x144345eb0 five times (0x1441b536e, 0x1441b53c8, 0x1441b5414, 0x1441b5483, 0x1441b55f1) with sigma/mean built from 100f, 1.5f, 10f, 0.8f and goal geometry constants (70/90/-20/180/360/260/280 deg); degree-clamps via 0x144345ae0; per-player table read 0x143c71ee0. This is the decision-level aim spread, separate from the physical kick error above. |  |
| proven | negative-result | `n/a` | No dt270 constant feeds the kick error | 0x14401a900 and its five sub-functions reference only immediate .tls$ float cells and player/team struct fields; no call to the dt270 helpers (get 0x144f84830 / asDouble 0x144f84d00) and no read of the shoot/grounderpass factory globals. The 'kickMissSituation' string (0x145c8c9f0) is a tutorial tip id (table at 0x147e74640), not a parameter. |  |

_Not independently re-derived by a skeptic (explorer evidence only)._

Open questions:

- Where does CPU difficulty (match level) enter? Nothing in 0x14401a900's tree reads an obvious level; candidates are the per-team table read 0x143c71ee0(teamCtx+0x228d4+team*0xc8+0x1840, playerIdx) compared with 1.0 at 0x144016f6f (kick-power 0x29 branch) and the [teamCtx+0x5098] +5 flag in 0x143ed7440 — need the writer of those tables.
- Exact meaning of miss types 0..3 (0x14401e5b0 / 0x14401fc80 / 0x144020450 predicates) — likely 'shank', 'mis-kick', 'under-hit' variants; follow-on 0x144018c10 after the kick may add curl/spin.
- Confirm the match ability enum by finding the roster->match copy loop that fills the byte array returned by 0x144301840 (0x35 presumed stronger foot, 0x2d/0x32 used by 0x14401f770 unknown).
- 0x142171d1b also calls 0x14401a060 — identify that caller (non-match context, e.g. training/preview).

## CPU difficulty (match level) tables

The CPU level is NOT driven by dt270 JSON constants; it is hard-coded in the exe as a 44-row x 10-column float table (two variants, selected by a platform-class global) read through AiLevelUnit::GetParam(0x1442e48f0). Level enum (PROVEN from the string decoder 0x144312d30): BEGINNER=0, AMATEUR=1, REGULAR=2, PROFESSIONAL=3, TOPPLAYER=4, SUPERSTAR=5, plus LEGEND=6 at runtime (menu enum EMenuCpuLevel VERYEASY..LEGEND has 7 entries). Each level also has a subLevel (0 = exact column, 1 = half-step down / 'minus' column, 2 = half-step up / 'plus' column). The runtime level is an XOR-obfuscated 12-byte AiLevelUnit {enc, key, sub} (value = enc ^ key, key = low 32 bits of QueryPerformanceCounter), held in a 0x3c-byte AiTeamLevel {attack@0, defence@0xc, attackCoach@0x18, defenceCoach@0x24, extra@0x30} reachable from global [0x1486bd888]+0x528, and copied per team into Team+0x8f2c (attack) / Team+0x8f38 (defence); Team::GetCurrentLevel (0x1442ee570) picks attack or defence by the team's possession flag Team+0x28d and returns level 0 if Team+0x8f48 is set. The plain (non-obfuscated) source values live in the tmpdb match record at TmpDbMatch+0x94.. (TmpDbMatch = *([0x1486e0de8]+0x48) + 0x6c310), applied at match init by 0x145403c90. 43 call sites consume the table: indices 0/3/43 are reaction delays in frames, 2 a press-timing multiplier, 12/18/27-30 probabilities/rates, 11/14/15/17 distances/time offsets, flag rows 4-10,13,16,19-22,31-42 gate AI abilities (bp::ThinkUnitShoot uses 32/33, ThinkUnitDribbleChallenge 26, ActionShoot 30, ActionDelay 15/16/17, ActionPress 2). Best patch points: (a) in-memory edit of the active table 0x146c06f40 (e.g. copy the LEGEND+ column into the SUPERSTAR column), (b) write TmpDbMatch+0x94/+0x9c = 6 and +0x98/+0xa0 = 2 (LEGEND, sub 2) before match start, (c) hook 0x144a18160 (tmpdb level setter from menu).

| conf | kind | address | finding | evidence | patch idea |
|---|---|---|---|---|---|
| proven | function | `0x144312d30` | MATCH_LEVEL string->enum decoder (level numbering) | Function compares a C string against "MATCH_LEVEL_BEGINNER"(->0), "MATCH_LEVEL_AMATEUR"(->1), "MATCH_LEVEL_REGULAR"(->2), "MATCH_LEVEL_PROFESSIONAL"(->3), "MATCH_LEVEL_TOPPLAYER"(->4), "MATCH_LEVEL_SUPERSTAR"(->5, via `mov ecx,5; cmove ebx,ecx` at 0x144312e2f); null/empty -> 0. Strings at 0x146c15fe8.. (three copies, used by tutorial/pathToGlory/sugoroku JSON matchLevelHome/matchLevelAway fields). Callers 0x143cb2f43/0x143cb2f82 feed the result into 0x1442e47f0 (AiLevelUnit ctor) then setters 0x144313d10 (home, field +0xcca0) / 0x144313cf0 (away, +0xccac) of a match-settings object. Menu enum strings EMenuCpuLevel::CPU_LEVEL_VERYEASY..CPU_LEVEL_LEGEND (7 values) at 0x1460dbeb0 and UI strings Level_Beginner..Level_Legend at 0x145d01398 show a 7th level LEGEND=6 exists at runtime. |  |
| proven | mechanism | `0x1442e47f0` | AiLevelUnit: XOR-obfuscated level value {enc,key,subLevel} | ctor(out, level, sub): `call 0x143b37540` (QueryPerformanceCounter low dword via import 0x1459fc9d0) -> key; stores [out+8]=sub, [out+4]=key^out?? (eax=key xor rdi-low), [out]=eax^level. Getter 0x1442e48a0: `mov eax,[rcx+4]; xor eax,[rcx]; ret` => level = enc ^ key. Comparators: 0x1442e4860 (==), 0x1442e4870 (!=), 0x1442e48b0 (<), 0x1442e48c0 (<=), 0x1442e48d0 (>=). Default ctor 0x1442e4830 = level 0, sub 0. Struct is 12 bytes. | To live-patch a level value: read key=[unit+4], write [unit]=key^newLevel (0..6) and [unit+8]=sub (0,1,2). No checksum beyond the XOR. |
| proven | function | `0x1442e48f0` | AiLevelUnit::GetParam(idx 0..43) -> float: the per-level parameter lookup | `cmp edi,0x2b; ja ->0.0`; `call 0x14533eb60` selects table: r8 = 0x146c067b0 (table A) or 0x146c06f40 (table B) if platform class in {1,2,3}. level = [rbx+4]^[rbx]; clamped <0 ->0, >6 -> case 6. Row = r8 + idx*0x2c; row byte[0] = 'discrete' flag (no half-step interpolation); floats at row+4..+0x28 = columns c0..c9. Jump table 0x1442e4bd8: level0 -> c0 (sub2&&!flag: mid(c0,c1)); level1 -> c1 (sub1: mid(c0,c1), sub2: mid(c1,c2)); level2 -> c2 (sub1: mid(c1,c2), sub2: mid(c2,c3)); level3 -> c3 (sub1: mid(c2,c3), sub2: mid(c3,c4)); level4 -> c4 (sub1: mid(c3,c4), sub2: mid(c4,c6)); level5 SUPERSTAR -> c6 (sub1: c5 'SUPERSTAR-', sub2&&!flag: mid(c6,c8)); level6+ LEGEND -> c8 (sub1: c7, sub2: c9). mid = a + (b-a)*50/100 (constants 0x145ae7580=50f, 0x145a8aa4c=100f). 0x1442e4c00(unit,idx) = \|GetParam\| > 1.19e-7 (boolean 'IsEnabled' wrapper, used for flag rows). | Column mapping for edits: c0 BEGINNER, c1 AMATEUR, c2 REGULAR, c3 PROFESSIONAL, c4 TOPPLAYER, c5 SUPERSTAR(sub1), c6 SUPERSTAR, c7 LEGEND(sub1), c8 LEGEND, c9 LEGEND(sub2). Hooking this function (ret xmm0) gives a single choke point to rescale any level. |
| proven | data-table | `0x146c06f40` | Level parameter table B (active on PC; platform class 3) — 44 rows x (flag + 10 floats) | Row stride 0x2c, byte0=discrete flag, floats c0..c9. Contents (row: flag \| c0..c9): 0: 0 \| 30 28 24 16 8 6 4 4 0 0 (reaction delay frames; used at 0x143d7a56b, ActionWaitTimer 0x1442119c7) 1: 0 \| 4 3 2.25 2 1.6 1.6 1.5 1 0.5 0 2: 0 \| 3 2 1.8 1.5 1.2 1.2 0.6 0.6 0.3 0 (multiplier in ActionPress fn 0x144193150 @0x144193a22) 3: 0 \| 30 18 8 4 2 2 0 0 0 0 (extra delay frames, cvttss2si at 0x143e192d4) 4: 1 \| 1 1 1 1 1 1 1 1 1 1 (IsEnabled @0x143d62817) 5: 1 \| 0 1 1 1 1 1 1 1 1 1 (IsEnabled @0x143e19ed8) 6: 1 \| 0 0 0 1 1 1 1 1 1 1 7: 1 \| 0 0 1 1 1 1 1 1 1 1 (IsEnabled @0x143d6a331) 8: 1 \| 0 0 0 1 1 1 1 1 1 1 (IsEnabled @0x143e15e28, 0x143e2be1b) 9: 1 \| 0 0 0 1 1 1 1 1 1 1 (PassGetRouteBallFollow region @0x1441a657c,0x1441aa41f) 10: 1 \| 0 0 1 1 1 1 1 1 1 1 (@0x14427a4db) 11: 1 \| 1 1 1 0.8 0.8 0.8 0.6 0.6 0.4 0.2 (fn 0x14427a7e0 @0x14427b754) 12: 0 \| 0 0 0 0 0.3 0.4 0.5 0.5 0.75 1 (rate, @0x14427b892) 13: 1 \| 0 1 1 1 1 1 1 1 1 1 (@0x1441a08ae) 14: 0 \| 4 3 2 1.5 1 0.5 0 0 0 0 (added to a distance at 0x143e15893) 15: 0 \| 6.5 4 3 1.5 0.5 0.5 0.5 0.5 -0.5 -1 (ActionDelay fn 0x144196990: addss @0x144197b61) 16: 1 \| 0 0 1 1 1 1 1 1 1 1 (ActionDelay IsEnabled @0x144197b7f) 17: 0 \| 3 1.8 2 1.5 1.5 1.5 1 0.7 0.4 0.2 (ActionDelay: seconds*frameRate @0x144197bb9) 18: 0 \| 30 70 85 90 95 100 100 100 100 100 (percent, compared at 0x143e12c6d) 19: 1 \| 0 1 1 1 1 1 1 1 1 1  20: 1 \| 0 0 0 1 1 1 1 1 1 1  21: 1 \| 0 0 0 1 1 1 1 1 1 1  22: 1 \| 0 1 1 1 1 1 1 1 1 1 (fn 0x143df0080 @0x143df026f..02c6) 23: 0 \| 60 40 22 12 8 8 6 4 2 0 (bp ThinkUnit fn 0x145652570) 24: 0 \| 60 35 30 16 8 8 6 4 0 0 25: 0 \| 60 35 25 20 12 10 10 10 10 0 26: 0 \| 60 35 18 13 4 0 0 0 0 0 (bp::ThinkUnitDribbleChallenge @0x1456ab268) 27: 0 \| 0 0.2 0.4 0.55 0.7 0.7 0.75 0.8 0.85 1 28: 0 \| 0 0.2 0.4 0.55 0.7 0.7 0.7 0.9 0.9 1 29: 0 \| 0 0.2 0.4 0.55 0.7 0.8 0.8 0.8 0.9 1 30: 0 \| 0 0.2 0.4 0.55 0.7 0.7 0.8 0.9 1 1 (27-30: bp fn 0x145653850; 30 also ActionShoot vf6 @0x1441b5714) 31: 1 \| 0 0 1 1 1 1 1 1 1 1 32: 1 \| 0 0 0 1 1 1 1 1 1 1 (bp::ThinkUnitShoot @0x145685d40) 33: 1 \| 0 0 1 1 1 1 1 1 1 1 (bp::ThinkUnitShoot @0x145685e6c) 34: 1 \| 0 0 0 0 1 1 1 1 1 1 35: 1 \| 0 0 0 1 1 1 1 1 1 1 36: 1 \| 0 0 1 1 1 1 1 1 1 1 37: 1 \| 0 1 1 1 1 1 1 1 1 1 38: 1 \| 1 1 1 1 1 1 1 1 1 1 39: 1 \| 0 0 1 1 1 1 1 1 1 1 40: 1 \| 1 1 1 1 1 1 1 1 1 1 41: 1 \| 0 0 0 1 1 1 1 1 1 1 42: 1 \| 0 0 0 1 1 1 1 1 1 1 (@0x1456b0ea2) 43: 0 \| 10 10 5 3 2 1 0 0 0 0 (alt reaction delay frames, @0x143d7930f/0x143d7a54f) Only xref to the table is 0x1442e491d (lea rcx,[rip+..] inside GetParam). | In-memory (VirtualProtect) edit of rows: e.g. raise SUPERSTAR error/delay by copying c0..c2 values into c6 (row0 delay 24 instead of 4, row18 85% instead of 100%), or make SUPERSTAR = LEGEND+ by copying c9 into c6 for all 44 rows. Rows are 0x2c apart, value for level L column at row+4+4*col. |
| proven | data-table | `0x146c067b0` | Level parameter table A (mobile/platform class 0) | Same layout as table B, selected when 0x14533eb60 returns 0. Differences vs B e.g. row0: 32 28 20 12 4 2 0 0 0 0; row1: 4 3 2 1.8 1.4 1.2 1 0.5 0.2 0; row2: 3.6 2.5 1.5 1.2 0.7 0.5 0.3 0.3 0 0; row3: 60 40 20 8 4 2 0 0 0 0; row12: 0 0 0 0.2 0.4 0.5 0.5 0.7 1 1; row15: 6 4 3 1.5 0 0 0 0 -0.5 -1; row17: 3 2.5 1.8 1.8 1.5 1.5 1 0.7 0.4 0.2; row18: 30 70 85 90 95 95 100 100 100 100; row23: 60 40 22 12 6 5 3 2 0 0; row24: 60 35 18 10 8 6 4 4 2 0; row25: 60 35 40 30 25 22 20 10 0 0; row26: 60 35 18 13 5 0 0 0 0 0; rows 27-30: 0 .2 .4 .55 .7 .7 .8 .9 1 1 / 0 .2 .4 .55 .6 .6 .7 .8 .9 1 / 0 .2 .4 .55 .75 .75 .8 .9 .9 1 / 0 .2 .4 .55 .75 .8 .85 .85 1 1; row41: 0 0 1 1 1 1 1 1 1 1; flag rows otherwise identical. Only xref 0x1442e4913. | Not active on PC unless the platform-class global is lowered to 0 (see 0x148c22ab8). |
| proven | global | `0x148c22ab8` | Platform-class global selecting the table (and AI tick 27/54) | int32 in writable .text data. Initialised from const 0x1482578f4 (=3) at 0x140a14db0 and 0x14533eb80; 0x14533eb60 returns true for value in {1,2,3} -> table B. 0x14533ec30(kind) lowers it to min(map[kind]) over match members (loop at 0x1453f76a0 over 0x18 member records, platform kind at member+0x78, map 0x14533ecb4: kinds 0-2,15,16 -> 0; 11-13 -> 1; 4,6,8-10,17 -> 2; 3,5,7 -> 3; 14 -> 4). Companion globals: 0x148c22ac0 = 0x1b (27) if class<=1 else 0x36 (54) and 0x148c22abc = same as float (returned by 0x14533ea80, used as frame-rate scale for delay rows). | Setting it to 0 switches CPU to table A (mobile tuning, 27-tick AI). |
| proven | struct-field | `0x1443273d0` | AiTeamLevel runtime object (0x3c bytes) and its accessors | Default ctor 0x1443273d0: attack@+0 = defence@+0xc = attackCoach@+0x18 = defenceCoach@+0x24 = level 2 (REGULAR), extra@+0x30 = level 5, all sub 0; every setter validates level < 7 (`cmp eax,7; jge skip`). Getters: 0x144327370 attack, 0x144327390 defence, 0x144327350 defenceCoach, 0x1443273b0 extra. Setters: 0x144327580(attack,defence), 0x144327520(attackCoach,defenceCoach), 0x1443275e0(extra). Global accessor 0x1442d6da0: `mov rax,[0x1486bd888]; mov rax,[rax+0x528]` returns the AiTeamLevel* used by match AI (e.g. 0x143def78c reads attack+defence and requires both >= 5 (SUPERSTAR) to enable a behaviour). | Live patch: p = *(u64*)(*(u64*)0x1486bd888 + 0x528); for each unit at p+0, p+0xc, p+0x18, p+0x24: [unit]=[unit+4]^6, [unit+8]=2 (LEGEND+). Must also patch the per-team copies (next finding) since teams copy at init. |
| proven | struct-field | `0x1442ee570` | Per-team level copy: Team+0x8f2c (attack) / Team+0x8f38 (defence), GetCurrentLevel and disable flag +0x8f48 | 0x1442ee570(team,out): if byte [team+0x8f48] != 0 -> returns AiLevelUnit(0,0) (BEGINNER); else if byte [team+0x28d] (team in possession flag) -> copy [team+0x8f2c..0x8f37] else [team+0x8f38..0x8f43]. Setter 0x1442f14f0(team,&attack,&defence) writes +0x8f2c/+0x8f38; 0x1442f1860 sets +0x8f48. Team ctor 0x1442efda0 defaults both to level 5 sub 0. 46 call sites of the getter (list: 0x143d04795, 0x143d614f4, 0x143d62808, 0x143d6a324, 0x143d77761, 0x143d792fd, 0x143d7a48c, 0x143d7a503, 0x143de98fa, 0x143df0260, 0x143e10013, 0x143e12c5c, 0x143e137a8, 0x143e15886, 0x143e15e17, 0x143e192c3, 0x143e19ecb, 0x143e1ca80, 0x143e26f2a, 0x143e28721, 0x143e2be0e, 0x143e34dad, 0x143e816e2, 0x143e87799, 0x143ea4cf3, 0x144193898, 0x144197b52, 0x1441a08a0, 0x1441a656e, 0x1441aa410, 0x1441b530c (ActionShoot), 0x1441b5705, 0x1442119bb (ActionWaitTimer), 0x14427a4cc, 0x14427b6e8, 0x14428900b, 0x1456529f6, 0x145653d6e, 0x14565494c, 0x1456996c9, 0x1456999a6, 0x1456999cd, 0x1456999f4, 0x1456a8e38, 0x1456ab1fa (bp::ThinkUnitDribbleChallenge), 0x1456b0e95). Threshold gates seen: 0x143d047a1 `cmp eax,5; jge` (SUPERSTAR+), 0x143d61500 `cmp eax,2; jl` (REGULAR+), 0x143def7b3 both >= 5. | Hook 0x1442ee570 and overwrite the returned unit (write [out]=[out+4]^L, [out+8]=sub) — a single 14-byte function that every AI consumer goes through; or poke Team+0x8f2c/+0x8f38 for the CPU team. |
| proven | function | `0x1453e8b90` | Match init applies levels: tmpdb record -> AiTeamLevel -> each Team | At 0x1453e92dd: `call 0x145403c90(dst=[Scene+0x27330] AiTeamLevel*, src=TmpDbMatch)`; TmpDbMatch = *(*(u64*)0x1486e0de8 + 0x48) + 0x6c310 (0x1453e8bd1 call 0x144a20e40 = `mov rax,[0x1486e0de8]`, then `mov rax,[rax+0x48]; lea r13,[rax+0x6c310]`). 0x145403c90 reads plain ints via 0x144a14400.. (all `add rcx,0x94`): attack.level @TmpDb+0x94, attack.sub @+0x98, defence.level @+0x9c, defence.sub @+0xa0, attackCoach.level/sub @+0xa4/+0xa8 (value 7 = 'same as attack', 0x144a2b560), defenceCoach @+0xac/+0xb0 (7 = same as defence), extra level @+0xb4 (0x144a161a0); levels >6 are replaced by 2 (`cmp r9d,6; ja -> mov r9d,2`), subs outside {0,1,2} -> 0; then 0x144327580/0x144327520/0x1443275e0. Per-team loop at 0x1453e94d1..0x1453e95c3: reads attack/defence via 0x144327370/0x144327390 (or extra unit 0x1443273b0 when byte [rsp+0x60] set; or 0x144269850/defenceCoach when [rsp+0x20] set), calls 0x1442f14f0(team,...), 0x1442f15d0(team, controlType from TmpDb+0xda78+team*4 via 0x144a14990) and 0x1442f1860(team,0). tmpdb setter from menu: 0x144a18160(TmpDb, level) -> 0x144a2b5a0 writes attack=defence=level, subs=0 (callers 0x1443b66f0, 0x14496451f, 0x14496569a, 0x14496715b, 0x144984149, 0x144987d44, 0x1453f49b7, 0x1453f502d); 0x144a13d20 resets all four to 7. | Simplest robust patch: before kickoff write int32 6 to TmpDb+0x94 and +0x9c and int32 2 to +0x98 and +0xa0 (LEGEND, sub2 = strongest column c9), or hook 0x144a18160 to substitute the level argument. Everything downstream derives from these plain ints. |
| likely | struct-field | `0x144313d10` | Match-settings object home/away level fields (+0xcca0 / +0xccac) used by tutorial/PathToGlory/Sugoroku | Setters 0x144313d10 (home -> [rcx+0xcca0..0xccab]) and 0x144313cf0 (away -> [rcx+0xccac..0xccb7]) of a large settings struct (ctor 0x144312460: 0x28 entries of 0x514 bytes at +0x10, then 20 12-byte units at +0xcba0, AiLevelUnits at +0xcc90/+0xcca0/+0xccac; defaults via 0x1442e4830 = level 0). Getters 0x144312750 (jmp 0x15334eed0, home) and 0x144312730 (away). Consumers 0x143c97c70 / 0x143cdaff9 push them into AiTeamLevel objects (0x144327580) and team infos (0x1442f14f0) for tutorial-style modes that carry matchLevelHome/matchLevelAway in JSON. | Not the normal-match path; only relevant for tutorial/PathToGlory/Sugoroku modes. |
| proven | mechanism | `0x146dd2b28` | tmpdb serialize classes naming the level model | RTTI: tmpdb::AiLevelUnit::MakeSerializeInfo::_m_level (vft 0x146dd2b28) / _m_subLevel (0x146dd2b50); tmpdb::AiTeamLevel::_m_attack (0x146dd2b88), _m_defence (0x146dd2bc0), _m_attackCoach (0x146dd2bf8), _m_defenceCoach (0x146dd2c30); onlinemode::MatchConfig::Settings::_m_aiTeamLevel (0x146dd2c68); JSON keys "m_offenseComLevel"/"m_offenseSubComLevel"/"m_defenseComLevel"/"m_defenseSubComLevel" under tmpobj__CpuLevelInfo (0x1477f4e58); "m_cpuLevel", "m_bossMatchCpuLevel", "m_minimumCpuLevel", "m_conditionCpuLevel" (0x1478xxxx) are server/event config fields. These confirm the attack/defence x level/subLevel split seen in code. |  |
| proven | negative-result | `n/a` | dt270 match constants carry no per-level tables | tools/data/dt270_schema.json: the only 'level' fields are tutorial/PathToGlory/Sugoroku MatchLevel enum arrays (6 strings) and matchLevelHome/Away, plus attackLevel/passAssistLevel (tactics/assist, not difficulty). No 6/7/10-wide float arrays keyed by CPU level exist in any object; the 6-arrays in ball.o/shoot.o are bounce/gauge tables. The difficulty curve is entirely in the exe tables above. | Do not look for difficulty levers in the CPK; patch memory or hook instead. |

_Not independently re-derived by a skeptic (explorer evidence only)._

Open questions:

- Exact semantic names of the 44 parameter rows (only ~25 call sites were classified; rows 1, 6, 19-22, 24, 25, 31, 34-41 need their consumers read to name them).
- Whether [0x1486bd888]+0x528 is literally the same AiTeamLevel object as Scene+0x27330 (LIKELY: both are the single AiTeamLevel created for the match; not traced through the registry copy).
- Which of the two per-team units (attack vs defence) is the 'coach' level path and when the [rsp+0x60] 'extra level (+0x30)' branch in match init is taken (probably event/boss matches: "m_bossMatchCpuLevel").
- Meaning of Team+0x8f44 (set to 4 at ctor, read by 0x1442ee560) and Team+0x8f48 (level-disable flag written by 0x1442f0170/0x1442f1862 outside init).
- Whether the .tls$ page holding the tables is mapped read-only at runtime (needs VirtualProtect for an in-memory edit).

## dt270 constant consumers (what the decoded fields do)

Located the runtime path from the dt270 registration table to the code that reads the decoded fields. Every constant object is created by ConstantManager (singleton pointer @0x148c22b98; holder vector; get(idx) @0x145348d70 / static wrapper @0x145349560) and consumers call get() with the registration-table index (trap=0x6f, shoot=0x6d, passget=0x6c, ball=0x4d, basePosition=0xe2). Struct offsets were re-derived with the JsonEmu (trap.ballControlRate=+0x38, ballControlWeekFootDownLimit=+0x3c; shoot.normal_dy.gageMax=+0x15c, gage tables +0x20..+0x1f4; ball.airRegistNormal=+0x8, boundRate[6]=+0x58, magnusRate=+0x208, nonSpinRate=+0x24c; basePosition.forceDashDistDefence=+0x184, pressRate=+0x2bc, spaceCoverRate=+0x318, adjustSpaceCoverRate=+0x60; passget.defence.secMax=+0x40, secMin=+0x44). PROVEN semantics: trap.ballControlRate multiplies the normalised (40..99) Ball-Control attribute (after a weak-foot deduction driven by ballControlWeekFootDownLimit) and the product feeds a 'controllable ball speed' threshold (15+20f^2+3f km/h) and a trap-error angle that grows when the incoming ball exceeds it; shoot gage tables are shot speed in km/h interpolated over attribute (rows 40/99) and DISTANCE-TO-GOAL bands of 5 m (the [6] index is floor(dist/5), not pitch condition), with gauge picking Min(0.25)/Mid(0.6)/Max(0.95) via a quadratic; normal_dy.gageMax/gageMin/interpolateRate define the launch elevation: dy = gageMin + gauge^(rate+1)*(gageMax-gageMin), then asin(dy/speed); ball.magnusRate is a linear multiplier on the Magnus acceleration (omega x v) in the air-force routine 0x144089620 (also nonSpinRate/nonSpinMin/Max for knuckle shots), ball.airRegistNormal is the linear multiplier on the drag acceleration (-0.5*1.293*0.0371105*|v|*v), ball.boundRate[cond] is the restitution coefficient at ground contact (scaled by boundCheckBoundAddRate by impact speed) in the shared ball integrator 0x14408d0f0 (49 callers, includes the prediction classes match::BallInfoUpdateFutureData*). basePosition.forceDashDistDefence/Offence are compared against a distance in 0x143da92c0 (team-shape runner: distance beyond which the player must dash). spaceCoverRate is consumed LIKELY in the ActionSelectorGoalGet/zone-cover code as spaceCoverRate + k*adjustSpaceCoverRate (+0.15 variant) times a per-role table. NEGATIVE: no reader of basePosition.pressRate nor of passget.defence.secMin/secMax was found by SSE/int scans of the whole .xcode (the only +0x2bc writer is the loader) — those two tuning edits are probably inert. Direction check of loose-realism-v1: ballControlRate 0.8 (looser touch: correct), shot tables x0.95 (slower shots: correct), normal_dy.gageMax 28->31 (higher elevation: correct), magnusRate 0.035->0.045 and nonSpinRate 1.2 (more curl/knuckle: correct), airRegistNormal 1.12 (more drag: correct), boundRate +10% (livelier bounce: correct), forceDashDistDefence 9->12 (later dash -> slower shape: correct), pressRate/spaceCoverRate/passget.defence: pressRate and secMin/Max unverifiable (no consumer), spaceCoverRate 0.43->0.35 plausible-correct.

| conf | kind | address | finding | evidence | patch idea |
|---|---|---|---|---|---|
| proven ✔ | data-table | `0x1475d2ba0` | dt270 registration table (245 entries x 16 bytes: {char* json path, factory fn}) | Scanned .tls$ for pairs whose first qword points at a 'DevelopData/...' string and second at code; contiguous run 0x1475d2ba0..0x1475d3af0 = 245 entries. Index = (entry-0x1475d2ba0)/16: ball=0x4d, rating=0x51, modeMatchup=0x50, centering=0x68, flypass=0x69, grounderpass=0x6a, moveMatching=0x6b, passget=0x6c, shoot=0x6d, throughpass=0x6e, trap=0x6f, basePosition=0xe2. Accessor 0x145349a40: 'cmp ecx,0xf5; movsxd rax,ecx; lea rcx,[0x1475d2ba0]; shl rax,4; add rax,rcx'. Count getter 0x145349a60 returns 0xf5. |  |
| proven ✔ | global | `0x148c22b98` | ConstantManager singleton + get(index) -> object pointer | 0x145349560: 'mov rcx,[0x148c22b98]; test rcx,rcx; je ret0; jmp 0x145348d70'. 0x145348d70(mgr, idx): bounds-checks idx against 0xf5, rax=[mgr+0]; rax=[rax+idx*8] (holder, 0x18 bytes: +8 object, +0x10 index, +0x14 refcount); returns [holder+8]. Creation 0x145349ab0(idx,data,size): allocs holder, calls table[idx].factory, then vtable[2] (loadBin) on the data. Consumers do 'mov rcx,[0x148c22b98]; mov edx,IDX; call 0x145348d70' (211 refs to the global, 67 direct calls of 0x145349560). | Runtime patch hook: replace the object pointer in holder[idx]+8 (or patch fields of the object it points to) after load; every consumer re-fetches through get() each call, so in-memory edits of the loaded struct take effect immediately without touching the CPK. |
| proven ✔ | struct-field | `0x1475e4130` | Struct layout of constant::Trap (vtable +0): ballControlRate=+0x38, ballControlWeekFootDownLimit=+0x3c | Re-derived with dt270_schema_gen.JsonEmu on loadJson 0x145356e30 (factory 0x145356770 allocs 0x1f0 bytes, vtable 0x1475e4130 = constant::Trap [dtor, loadJson, loadBin=0x1453567a0]). JsonEmu field map: ballControlRate off 0x38 float, ballControlWeekFootDownLimit off 0x3c float. |  |
| proven ✔ | function | `0x144079a70` | trap.ballControlRate consumer: multiplies normalised Ball Control into the trap 'controllable speed' / error-angle model | 0x144079bba call 0x143ea8cb0(player, 0x1f) -> attribute value (edi); 0x144079bc5 call 0x144079020 -> weak-foot deduction (ebx); 'cmp ebx,edi; cmovl ecx,ebx; sub edi,ecx' => attr' = attr - min(attr,deduct). 0x1442bfae0(&hi,&lo,0x1f) gives attribute range bytes; t = clamp((attr'-lo)/(hi-lo),0,1). 0x144079c38 'mulss xmm12,[rax+0x38]' (rax = get(0x6f)) => f = t*ballControlRate; xmm6 = f^2. Again at 0x144079dc3 'mulss xmm10,[rax+0x38]'. Then 0x144079e8e..0x144079eee: threshold = (20*f^2 + 15) km/h + 3*f km/h, converted to m/s (*1000/3600); 0x144079ef3 'comiss xmm13(ball speed), xmm8(threshold)'; if above: excess/(35 km/h) clamped to 1, multiplied by 10 or 15 and added to xmm7 (base 5/10) which is then used as an angle tolerance in degrees (180/360 wrap at 0x144079f82..). Second consumer 0x14407a980 (0x14407aa63) reads +0x38 the same way. Callers: 0x144077cc3 (trap animation/decision code, near match::anime::action::CTrapAnimeInfo). | loose-realism-v1 sets ballControlRate 1.0->0.8: lowers f for every player by 20% -> lower controllable-speed threshold (e.g. BC 99: 38->29.8 km/h) -> more traps exceed it -> larger error angle. Direction INTENDED (looser first touch). Note it scales all players equally (multiplicative), it does not widen the gap between good and bad controllers. |
| proven ✔ | function | `0x144079020` | trap.ballControlWeekFootDownLimit: weak-foot deduction from Ball Control (integer points) | 0x144079032 get attr 0x35 (weak-foot usage/flag path via 0x143e948c0 switch); for the weak-foot case 0x1440790c1..0x144079135: attr 0x27 normalised over its range -> u; 'subss xmm7(1.0),xmm6' ; 0x144079163 'mulss xmm7,[rax+0x3c]' (rax=get(0x6f)); cvttss2si -> returns (int)((1-u)*ballControlWeekFootDownLimit), else 0. Result is subtracted from Ball Control in 0x144079a70. | Raising ballControlWeekFootDownLimit makes weak-foot traps worse for players with low attr 0x27 (LIKELY Weak Foot Accuracy). Not touched by the current tuning. |
| proven ✔ | struct-field | `0x1475e16e0` | Struct layout of constant::Shoot: gage tables and *_dy records | JsonEmu on loadJson 0x1453546d0 (factory 0x145354190, size 0x1f8): advanceLoop +0x8..0x1c; controlShootGageMax40 +0x20, Max99 +0x38, Mid40 +0x50, Mid99 +0x68, Min40 +0x80, Min99 +0x98; control_dy {gageMax +0xb0, gageMin +0xb4, interpolateRate +0xb8}; loop {angleY +0xbc, manualRate +0xc0, speedForGageMax +0xc4, speedForGageMin +0xc8}; normalShootGageMax40 +0xcc, Max99 +0xe4, Mid40 +0xfc, Mid99 +0x114, Min40 +0x12c, Min99 +0x144; normal_dy {gageMax +0x15c, gageMin +0x160, interpolateRate +0x164}; powerfullShootGageMax40 +0x168 ... Min99 +0x1e0. |  |
| proven ✔ | function | `0x143eeed40` | Shot-speed gauge function: tables are km/h, indexed by attribute (40..99) and DISTANCE-TO-GOAL band (5 m), not pitch condition | 0x143eeedbc 'cvtdq2ps xmm7,edx; subss xmm7,40.0; divss xmm7,59.0' => attribute fraction a in [0,1]. 0x143eeedd4 get(0x6d) -> rbx. 0x143eee73..0x143eeeaa: distance from player to goal (sqrt), 0x143eeef1b 'divss xmm0,5.0; cvttss2si edx' => band idx=floor(dist/5), 'cmp edx,5; jg/je -> 0x143eef36c' (>=25 m uses element [5]); frac=(dist-5*idx)/5. Per table: v = lerp(T40[idx],T99[idx],a) and lerp again to idx+1 by frac (e.g. 0x143eeef80 [rbx+rdx*4+0x1e0]/[+0x1c8] = powerfullShootGageMin99/Min40; 0x143eef226 [rbx+rdx*4+0x144]/[+0x12c] = normalShootGageMin99/Min40; 0x143eef07b/0x084 [+0x180]/[+0x168] = powerfullMax99/Max40). Table family chosen by flags: [rsp+0xd8]!=0 -> powerfull (+0x168..), r10b!=0 -> control (+0x20..), else normal (+0xcc..). 0x143eef48c..0x143eef517: gauge g=clamp(xmm10,0.25,0.95); speed = quadratic through (0.25,Min),(0.6,Mid),(0.95,Max) (constants -0.35,-0.7,-0.08575). Then skill/attr bonuses (skill 7 at 0x143eef563, attr 0x2b). | loose-realism-v1 multiplies every *ShootGage* table by 0.95 -> shot speed -5% at every distance/attribute/gauge. Direction INTENDED. Correction to docs/dt270-gameplay.md: the [6] index of the shoot tables is the 5 m distance band (0-5,5-10,...,>=25 m), so e.g. normalShootGageMax99[5]=112.5 km/h is the long-range maximum. |
| proven ✔ | function | `0x143fdf0c0` | shoot.normal_dy / control_dy: launch elevation model (gageMin + gauge^(interpolateRate+1) * (gageMax-gageMin), then asin(dy/speed)) | 0x143fdf160 get(0x6d) -> rbp. 0x143fdfab2: if control shot (sil) xmm15=[rbp+0xb4] control_dy.gageMin else [rbp+0x160] normal_dy.gageMin; 0x143fdfad3 xmm6=[rbp+0x15c] normal_dy.gageMax (used for both; for control: max += clamp((dist-15)/10,0,1)*0.95-0.2 and rate=[rbp+0xb8] control_dy.interpolateRate, else rate=[rbp+0x164] normal_dy.interpolateRate). 0x143fdfb74 'subss xmm7,xmm15' => range=max-min. 0x143fdfc45 'addss xmm9(rate),1.0'; 0x143fdfc51 call powf(gauge, rate+1); 0x143fdfc5e 'mulss xmm6,xmm7; addss xmm6,xmm15' => dy. 0x143fdfc76..0x143fdfc9f: dy -= (ballY-0.1087)/(dy/9.8); dy /= shotSpeed; asinf -> *57.2958 => launch angle in degrees (later scaled by distance factor 0x143fdfcb0.. and 0.4..0.8 gauge factor). | loose-realism-v1: normal_dy.gageMax 28->31, control_dy.gageMax 26.5->29.5 => higher vertical component at full gauge -> higher launch elevation (more shots over the bar at high power). Direction INTENDED. |
| proven ✔ | struct-field | `0x1475ecda8` | Struct layout of constant::Ball; consumers receive (struct+8) as 'BallParam' pointer | JsonEmu on loadJson 0x145366900 (factory 0x145366110 size 0x2f0): airRegistNormal +0x8, boundBoundSpeedMin +0x18, boundCheckBoundAddRate[6] +0x34, boundFrictionSpeedMax +0x50, boundRate[6] +0x58, dragSpeedMax +0x148, dragSpeedMin +0x14c, frictionRoll* +0x150..0x1c8, grounderBoundYAdd +0x1f8, grounderCTan +0x1fc, magnusRate +0x208, nonSpinMax +0x244, nonSpinMin +0x248, nonSpinRate +0x24c. All callers pass object+8 (e.g. 0x14408ce70 'lea r9,[rbx+8]', 0x14408e955 'lea rax,[rsi+8]', 0x14408a9d2 'add r15,8') so callee offsets are struct offset - 8. |  |
| proven ✔ | function | `0x144089620` | Ball air-force routine: drag = airRegistNormal * (-0.5*1.293*0.0371105) * f(\|v\|) * v ; Magnus = magnusRate * spinFactor * pi^2 * 0.0118126 * 0.108686 * (omega x v) | rcx = BallParam (6th arg [rsp+0x108]); rdi = ball state (v at +0xc..0x14, spin flag +0x90, spin kind +0x91). 0x1440897bb: [rcx+0x140]/[rcx+0x144] (= dragSpeedMax/Min, km/h -> m/s via *1000/3600) shape f(\|v\|) piecewise around those speeds; 0x144089808 'movss xmm7,[rcx]' (airRegistNormal) 'mulss -0.5; mulss 1.293 (air density); mulss 0.0371105 (pi*r^2, r=0.1087)'; mulss f; then *vx,*vy,*vz added to accel [rbx]. Magnus: 0x1440898d1 if state+0x90==0: spinFactor=min(\|v\|,23.61 m/s) else uses nonSpinMax [rcx+0x240], nonSpinMin [rcx+0x23c], nonSpinRate [rcx+0x244]; 0x14408994a 'mulss xmm5,[rcx+0x200]' (= struct +0x208 magnusRate); *pi*pi*0.0118126*0.108686; multiplied into the cross product (omega x v) computed at 0x14408986a..0x1440898cc and added to the drag accel. Only caller: 0x14408d2aa inside the ball integrator 0x14408d0f0. | loose-realism-v1: magnusRate 0.035->0.045 (+29% Magnus acceleration => more curl/dip), nonSpinRate 1.0->1.2 (knuckle shots wobble more), airRegistNormal 1.0->1.12 (+12% drag => shots/passes lose speed faster, long balls drop shorter). All three move in the INTENDED direction. Caution: drag applies to every airborne ball incl. goal kicks/crosses. |
| proven ✔ | function | `0x14408d0f0` | Shared ball integrator (ground/bounce/roll phase): boundRate[cond] is the restitution coefficient | Args: xmm0=dt, r9=ball state, [rsp+0x20]=BallParam, bools. r15d=[r9+0x94] (pitch-condition style index; 'cmp r15d,5; cmova r15d,1'). Height test 0x14408d242 'comiss [r9+4], 0.108686' -> air phase calls 0x144089620 else ground. 0x14408d57e 'movss xmm6,[rdi+r15*4+0x50]' = boundRate[r15] (struct +0x58); 0x14408d7d5..0x14408d842: xmm6 *= (1 + boundCheckBoundAddRate[r15]/100 * t(impact speed between boundBoundSpeed min/max)); stored [rbp+0x138] and later applied to the vertical velocity at contact (0x14408dffe/0x14408e00d divss by it for the rebound-time solve). Friction tables frictionRoll{Speed,Rate}{Min,Max,Stop}[r15] at 0x14408d5c7..0x14408d652 shape the rolling deceleration. 49 call sites (xrefs) incl. match::BallInfoUpdateFutureDataAll/Last (prediction) and 0x143f05377 (set-piece actions) — same integrator for live ball and predictions. | loose-realism-v1 boundRate +10% (0.7->0.77, 0.5->0.55 for cond 3): higher restitution => livelier, higher bounces. Direction INTENDED. Because predictions use the same routine, CPU/auto-positioning stays consistent with the new physics. |
| proven ✔ | struct-field | `0x1475eaa58` | Struct layout of constant::BasePosition: forceDashDistDefence +0x184, forceDashDistOffence +0x188, pressRate +0x2bc, spaceCoverRate +0x318, adjustSpaceCoverRate +0x60 | JsonEmu on loadJson 0x145362470 (factory 0x145361a80 size 0x368). Neighbours: forceJogDist +0x18c, forceWalkDist +0x190; player_count_* +0x2b0..0x2b8, pushUpSide +0x2c0; slowDownPassFrame +0x314, speedDownRunDist +0x31c. |  |
| proven ✘ | function | `0x143da92c0` | basePosition.forceDashDistDefence/Offence consumer: distance threshold selecting dash in the base-position runner | 0x143da932c 'mov edx,0xe2; call 0x145348d70' -> r12; 0x143da9414 'movss xmm7,[r12+0x188]' (forceDashDistOffence) on one branch, 0x143da9420 'movss xmm7,[r12+0x184]' (forceDashDistDefence) on the other (branch on team attack/defence state), xmm7 then compared with the player's distance to its base-position target to force dash locomotion. Same function also reads slowDownPassFrame (+0x314 at 0x143daa3a4). Other basePosition readers: 0x144184490 (match::player::ActionBasePosition method 13: +0x314, +0x30c, +0x5c, +0x40, +0x234), 0x14417df90 (+0x20c), 0x1441832db (+0x44 adjustEnemyZ), 0x14418900e (+0x208). | loose-realism-v1 forceDashDistDefence 9->12 m: players only break into a dash toward their defensive base position when further than 12 m away (was 9) => slower/less perfect defensive shape recovery. Direction INTENDED. |
| likely ✔ | function | `0x143e85de0` | basePosition.spaceCoverRate consumer (LIKELY): cover weight = spaceCoverRate + k*adjustSpaceCoverRate [+0.15], times per-role table | 0x143e8608b 'mov rax,[rsi+0xf0]; movss xmm1,[rax+0x318]; test ebx,ebx; jne; mulss xmm6,[rax+0x60]; addss xmm1,xmm6; addss xmm1,0.15'. Companion 0x143e85559 (in 0x143e84d90): 'mov rax,[r13+0xf0]; movss xmm15,[rax+0x318]; ... mulss xmm1,[rax+0x60]; addss xmm15,xmm1; mulss xmm11(xmm15),[rbp+r12*4+0x2a0]'. The +0x318/+0x60 pairing matches spaceCoverRate/adjustSpaceCoverRate exactly; the object at [ctx+0xf0] is the per-team bp context's cached BasePosition pointer (ctx also holds +0x1940/+0x1950 team pointers, same object type as 'this' of 0x143d4ac40 which receives the basePosition const from 0x143d02c80). The store into +0xf0 was not located, hence LIKELY not PROVEN. Region: match::ai::ActionSelectorGoalGet / zone-cover selection (0x143e80d0c caller). | loose-realism-v1 spaceCoverRate 0.43->0.35 lowers the space-cover weighting => defenders less eager to shift into uncovered space. Direction plausible-INTENDED, pending confirmation of the +0xf0 cache. |
| likely ✔ | negative-result | `n/a` | basePosition.pressRate: NO consumer found | Whole-.xcode byte scans for SSE ops (movss/mulss/comiss/...) and integer mov/cmp/movd with disp32 0x2bc found 83+51 hits; none has a preceding get(0xe2)/[ctx+0xf0] load or lies in a basePosition consumer; the only write is the loader (0x145363d50 inside loadJson 0x145362470; loadBin copies bytes wholesale). Function-level scans of 0x143c00000-0x144500000 and the match::ai::bp region 0x145600000-0x145800000 show no read of +0x2bc from a register derived from the constant. Possibly dead in this build or read through an unrecognised copy. | loose-realism-v1 pressRate 0.5->0.4 is probably inert; do not attribute in-game changes to it. |
| likely ✔ | negative-result | `n/a` | passget.defence.secMin/secMax: NO consumer found (struct +0x44 / +0x40) | JsonEmu: passget.defence {paraMax +0x38, paraMin +0x3c, secMax +0x40, secMin +0x44} (factory 0x1453532d0, size 0xb8, index 0x6c). 31 get(0x6c) call sites traced (0x14415f8e4 ... 0x144250fda, mostly match::player::PassGetRoute* classes); register tracking shows reads of +0x29/+0x2a/+0x48..+0x50/+0x68/+0x74/+0x80..+0x88/+0x94/+0xa8 but never +0x38..+0x44, and a windowed scan of the PassGet code ranges for the paraMin/paraMax/secMin/secMax lerp pattern found nothing. Several call sites discard the get() result (e.g. 0x14424b1a4), suggesting the defence block is only consulted by code compiled out or inlined elsewhere. | loose-realism-v1 passget.defence.secMax 0.4->0.3 / secMin 0.4->0.5 ('defender reaction spread') is probably inert. |
| likely ✔ | function | `0x143ea8cb0` | Attribute accessor used by trap/shoot code (player, attrIndex) -> value; indices seen: 0x1f (trap Ball Control path), 0x27/0x35 (weak foot), 0x2b (shoot bonus) | Called as 'mov rcx,[rsi+8] (player); mov edx,0x1f; call 0x143ea8cb0' at 0x144079bba and 'mov edx,0x35'/'mov edx,0x27' in 0x144079020; 0x1442bfae0(&hi,&lo,idx) returns the attribute's byte range used for normalisation. Attribute enum mapping to UI names not derived (0x1f=Ball Control is an inference from the trap context). |  |

**Skeptic verdict:** Re-derived every cited address. 15 of 16 findings hold with the quoted instructions and loader-confirmed struct offsets (schema 'off' values are .o-template offsets, not struct offsets; the explorer's +vtable struct offsets are right). Two corrections: (1) in the air-force routine the nonSpinMax/nonSpinMin operand labels are swapped ([rcx+0x23c]=nonSpinMax +0x244, [rcx+0x240]=nonSpinMin +0x248); (2) the forceDashDistDefence claim is refuted: in 0x143da92c0 the [r12+0x184] load at 0x143da9420 is dead — the defence branch overwrites xmm7 at 0x143da9553 with 19 - 0.1*attr(0x17) (+0..5) before the only comparison at 0x143da95a3, and no other reader of +0x184 exists after get(0xe2) or via the [ctx+0xf0] cache. So loose-realism-v1's forceDashDistDefence 9->12 is most likely inert, like pressRate and passget.defence; only forceDashDistOffence is live at that site. spaceCoverRate stays LIKELY, with added support (the same [ctx+0xf0] pointer is used to read +0x218/+0x284, which are basePosition length/minWidth fields). Shot-speed band finding holds, with the note that distance is first blended with a per-player table value at 0x143eeeef2 before /5 banding.

Refuted / corrected:

- `0x143da92c0` basePosition.forceDashDistDefence/Offence consumer in 0x143da92c0: Half refuted. The loads exist (0x143da9414 'movss xmm7,[r12+0x188]' if [r14+0x28d]!=0, else 0x143da9420 'movss xmm7,[r12+0x184]'), but on the defence branch xmm7 is overwritten before any use: 0x143da9540 'cmp byte [r14+0x28d],0; jne 0x143da95a3' then 0x143da9553 'movss xmm7,19f'; 0x143da955e 'mulss xmm0(attr 0x17 as float),0.1f'; 0x143da956d 'subss xmm7,xmm0' (+ optional 'addss xmm7,xmm8*5' at 0x143da959f), and only then 0x143da95a3 'comiss xmm9(dist),xmm7'. No instruction between 0x143da9420 and 0x143da9553 reads xmm7. So at this site only forceDashDistOffence reaches the comparison; the defensive threshold is 19 - 0.1*attr(0x17) [+0..5], and forceDashDistDefence is a dead load. A whole-.xcode scan for SSE reads of disp32 0x184 preceded (within 4 KB) by 'mov edx,0xe2' found only 0x143da9420; scans for '[reg+0xf0]'-cached reads of +0x184 found none. Conclusion: loose-realism-v1's forceDashDistDefence 9->12 is most likely INERT, not 'direction intended'. (Only the Offence field is live here.)

Open questions:

- Which per-team object field holds the cached BasePosition pointer read as [ctx+0xf0] in 0x143e84d90/0x143e85de0, and where is it stored (would upgrade spaceCoverRate to PROVEN)?
- Is basePosition.pressRate really unread in this build, or is it consumed via a code path outside the scanned idioms (e.g. copied into a team-strategy struct by a memcpy-like loader)?
- Same for passget.defence.{paraMin,paraMax,secMin,secMax}: a consumer with the classic lerp pattern was not found in the PassGetRoute* code.
- Exact meaning of ball state +0x94 (index into the [6] ball arrays; values >5 map to 1): pitch condition vs. weather/surface id.
- Map the internal attribute enum (0x1f, 0x27, 0x2b, 0x35, and the index passed to the shot-speed function) to UI attribute names to confirm 'Ball Control', 'Weak Foot Accuracy', 'Kicking Power'.

## Controller input units (match::pad) — and where CPU decisions really are

The task premise is falsified: match::pad::ThinkUnit* are NOT CPU decision units. They are the controller-input interpreter owned by match::CommandPlayer (one per player slot, 24 instances): each unit watches one pad button (+8 = PadId) or one stick (+0xc = StickKind 0/1) in a 100-frame pad-history ring buffer and converts presses/holds/double-taps/gauge charge into a player command id (0x3d Shoot, 0x3a ShortPass, 0x3b ThroughPass, 0x33 Dribble, 5 Press ...). The history buffers are only ever filled from physical pad devices 0..7 (0x143c639a0 loop -> 0x14431a710 early-outs for idx>=8) or with empty frames (0x1440d40b0 -> 0x14431aca0), so COM-controlled players see no input here; there is no evaluator, no difficulty read and no RNG in any of the five units (the only no-arg float getter they call, 0x14533ea80, returns the frame-rate global at 0x148c22abc). The shared vf[8] (0x1440d7bd0) is a press-state machine over +0x1c (0 idle,1 pressed,2 held,3 released) and the per-unit hooks only set flag bits in +0x19 and pick the command id. The real CPU decision code is match::ai::* (ActionSelector*, Judge, PlayerOffence/Defence) — e.g. ActionSelectorScore::vf2 at 0x143df1080 (410 ins) — and the match RNG is an inlined MT19937 (tempering constant 0x9908b0df at 0x14445c401, seeding 0x6c078965 at 0x14445cbb7). Concrete human-input tunables that ARE in these units: kick-gauge fill rates (0.25 s shoot / 0.3 s pass / 0.6 s, mode-3 variants 0.38/0.42/1.0) in 0x1440d8070, stick dead-zones 0.1/0.05 (base) and 0.2 (Dribble), double-tap window = fps*0.04+1 frames, button-analog 'full press' threshold 1.0.

| conf | kind | address | finding | evidence | patch idea |
|---|---|---|---|---|---|
| proven ✔ | struct-field | `0x1440e0c70` | ThinkUnitBase object layout (size 0x48, units embedded in CommandPlayer at +0x40+0x1a0...) | Container ctor 0x1440e0c70 builds every unit in place: mov [rbx],vftable; mov dword [rbx+8],PadId; mov dword [rbx+0xc],2 (button) or 0/1 (stick kind); [rbx+0x10]=category; [rbx+0x14]=press-kind; call Reset 0x1440d7b30; [rbx+0x1c]=0 state; byte [rbx+0x18]=1 enabled. Reset 0x1440d7b30 zeroes +0x1c..+0x38, sets word [+0x28]=1, byte [+0x19]=0. Fields proven from use: +0x19 flag bits (1 modifier/L-trigger btn 0x12, 2 double-tap, 8 btn 0x15 held, 0x10 btn 0x12 held, 0x20 shoot-loft ctx, 0x40 special-pass), +0x1c press state 0..3, +0x20 float gauge 0..1, +0x29 byte press-count (inc at 0x1440d7e98, saturates 0xff), +0x2c/+0x30 pending command, +0x34 frame counter (inc 0x1440d71ea), +0x38 saved match-time ([env+0x3318]), +0x48 per-unit bool (Shoot/ThroughPass/LongPass). |  |
| proven ✔ | data-table | `0x1440e0d80` | Per-unit construction table (PadId, kind, category) for the 5 requested units | 0x1440e0db7 ShortPass @+0x1a0: PadId 0x18, +0xc=2, cat 4, kind 1. 0x1440e0e47 ThroughPass @+0x238: PadId 0x16, cat 4, kind 1. 0x1440e0e91 Shoot @+0x288: PadId 0x19, cat 4, kind 2 (hold/gauge). 0x1440e0f1b Press @+0x320: PadId 0x21 (=none, reads btn 0x1e directly), cat 1, kind 0. 0x1440e10d7 Dribble @+0x520: +0xc=0 (left stick), PadId 0x21, cat 0. Also LongPass 0x17, Clear 0x19, PressGK 0x1c, Tackle 0x21, Shoulder 0x1f, Sliding 0x1d, FriendPress 0x1b, CursorChange 0x12, CursorChangeManual stick 1. | Button remap without touching the game's config: change the PadId immediate (e.g. mov dword [rbx+8],0x19 at 0x1440e0e6b) in memory at runtime. |
| proven ✔ | function | `0x1440d7bd0` | Shared state-machine dispatcher ThinkUnitBase::vf[8] (Think) — not an evaluator | Args (this, ctx, r8d=currentCommand). Returns command id in eax. If byte [this+0x18]==0 -> 0. If [this+0xc]!=2 (stick unit) calls vf[16] (0x80) = stick edge detector; else reads [this+0x1c]: 0 -> vf[17] (0x88, IsPressed) sets state 1; 1 -> 'pressed' checks btn still held (0x144310750) else state 3; 2 -> held, if gauge [this+0x20]>=1.0 (0x1478502b8) -> state 3 and save [env+0x3318] to +0x38. Then per state calls vf[12](0x60) idle, vf[13](0x68) held/charge, vf[14](0x70) release -> command id, vf[15](0x78). Release path validates the command: category table 0x144318200 (5 dwords/entry at 0x146c19004) must be 3, then 0x143e9df80(env, playerIdx, gauge, stickvec, ...) 'can kick' check; ids 0x3b/0x3f pass r12=1. | No threshold here except gauge full=1.0; ignore for CPU behaviour. |
| proven ✔ | function | `0x1440d7190` | ThinkUnitBase::Run wrapper (calls Think then OnBegin/OnUpdate hooks) | 0x1440d71bf call [rax+0x40] (vf8); state==1 -> call [rax+0x48] (vf9 OnPress); state 0/2/3 or pending -> call [rax+0x50] (vf10 OnUpdate); inc [this+0x34]. Called only from CommandPlayer update loop at 0x1440dd460 (xrefs). |  |
| proven ✔ | mechanism | `0x1440dd750` | Owner is match::CommandPlayer, 24 instances (one per player slot), units reached via pointer array at +0x40+0x17b0 | 0x1440dd750 ctor: vftable match::CommandPlayer at 0x1440dd7ec, calls 0x1440e0820 which calls 0x1440e0c70 and fills [+0x17b0..] with addresses of the embedded units. Allocated 0x18 times (0x1c10 bytes each) in loop at 0x1440d4a80 inside match::Command (vftable 0x146b9e7d8). Output registry type UCommandOutput (vftable at 0x1440dd815). |  |
| proven ✔ | negative-result | `0x14431a710` | ThinkUnit input source is the pad-history ring buffer; only physical pads 0..7 ever write real frames -> CPU players get no input through this path | ctx struct built by 0x1440d70f0: [0]=env, [8]=pad history (24 x 0x1908 bytes: 100 frames x 64 bytes, index at +0x1900, 0x14431a5b0 returns frame n-ago; frame: u64 button mask at +0, float analog per button at +0xc+id*8), [0x10]=team, [0x1c]=player index. Button query 0x144310750 = bt mask,id; analog 0x14430f750. Writer 0x14431a710 returns early unless idx<8 and device enabled ([pool+0x258c0+idx]); its caller loop 0x143c639a0 is the MatchCollisionEnd/Parallel listener reading VPadInputRef::ScopedWrite (0x143c6392e). The only other writer 0x14431aca0 pushes an EMPTY frame (mask 0x100000000) for all 24 (0x1440d4120 loop). No match::ai code writes into these histories (byte scan of all stores to +0x1900 in .xcode: 0x14431a796, 0x14431acb6/cc1, 0x1442a5b36 copy, rest unrelated). | Do not patch ThinkUnits to change COM behaviour; target match::ai::ActionSelector*/Judge instead. |
| proven ✔ | function | `0x1440e6230` | ThinkUnitShoot hooks: vf9 OnPress 0x1440e63d0, vf10 OnUpdate 0x1440e6690, vf13 Charge 0x1440e5cb0, vf14 Release->0x3d, vf17 IsPressed 0x1440e6230 | vf17 0x1440e6230: returns 0 (no shoot) if 0x144300990(env)==0 AND [env+0x3308]==1 AND (int8)[team+0x28c]*[player+0x4f4] < 0 (0x1440e62d4..62f1) else ThinkUnitBase::vf17 0x1440d8000 (kind 2 + presscount>1 -> combo 0x144310490(pad,id,2,6); else edge 0x14430f9b0). vf9: maps player index via [env] table (0xd0-byte entries, cmp [rcx+r9+0x10]) and sets flag 1 if 0x144118580==2; double-tap via 0x1440e5d50 sets flag 2 and +0x48=0; btn 0x15 -> flag 8. vf10: when btn 0x19 analog edge (0x14430f9b0) and mode [env+0x3308]==3 && [env+0x34a0]==5, computes int((u16[p+0x1e]-u16[p+0x1a])*48/fps+0.5) and requires 0 < n < 30 (0x146b9f20c=30f) and playstyle 0x1442c0000(p,8)\|\|(p,0x21) and n <= 8 (0x145b52fbc=8f) to set flag 0x20 (loft/finesse context). vf13 calls gauge charger 0x1440d8070 with cmd 0x3d. vf14 0x1440e2070 returns 0x3d. | Shoot gauge speed: see gauge-rate table finding. To make 'flag 0x20' (special shot context) always available, nop the jb at 0x1440e6858 (in memory only). |
| proven ✔ | function | `0x1440e68a0` | ThinkUnitShortPass hooks: vf9 0x1440e64a0, vf10 0x1440e68a0, vf13 0x1440e21c0 (cmd 0x3a), vf14 0x1440e5d10 (0x3a, or 0x0a when flag 0x40) | vf9: flag1 if 0x1443084d0(team+0x5c)==0 or (0x1442c7f30(env.team) && btn 0x12); double-tap 0x1440e5e90(ctx, PadId, 1) && presscount<=1 -> flag 2; mode3/34a0==5 && 0x1440dfe00(ctx)==2 && btn 0x12 -> flag 0x40. vf10 0x1440e68a0: btn held & no double-tap yet & presscount<=1 -> retry double-tap; then reads player attrs u16[p+0x1e] vs u16[p+0x1a] gated by 0x144311e40(pos) and 0x1442e1050; btn 0x12 -> flag 0x10, btn 0x15 -> flag 8. vf14 0x1440e5d10: test [this+0x19],0x40 -> eax=0x0a else 0x3a. | Command swap: patch 'mov eax,0x3a' at 0x1440e5d15 to another category-3 id. |
| proven ✘ | function | `0x1440e69b0` | ThinkUnitThroughPass hooks: vf8 override 0x1440e5fb0, vf9 0x1440e6560, vf10 0x1440e69b0, vf13 0x1440e5cd0 (cmd 0x3b), vf14 0x1440e5d30 (0x3b), vf1 0x1440e5d40 | vf8 0x1440e5fa0: 'cmp r8d,0x51; jne base' -> returns 0 when current command is 0x51 (none), else jumps to 0x1440d7bd0. vf10: if btn held: if !(player flag byte [p+8] bit5) and (0x144311e40(pos) && u16[p+0x1e]!=0 && u16[p+0x1e]>u16[p+0x1a]) is false, btn 0x12 -> flag 0x40; then double-tap (0x1440e5e90) -> flag 2 unless +0x48; btn 0x15 -> flag 8 gated by 0x144300990==0. vf1 resets +0x48. |  |
| proven ✔ | function | `0x1440e5730` | ThinkUnitDribble (stick unit): vf16 stick edge detector 0x1440e5730 with 0.2 dead-zone; vf10 0x1440e58f0; vf12/13 return 0x33 | 0x1440e5766 call 0x14430f750(pad, stickKind=[this+0xc], 0) -> magnitude; comiss vs 0x1478501c0 (=0.2f): state 0->1 when >=0.2, state 2->3 when <0.2. vf10: clears flags; btn 0x14 held -> compares 0x1442eaba0(team,side)->[+4] vs side to set flag 2; btn 0x12 or 0xd -> flag 1 (sprint/modifier). vf12/vf13 0x1440e5560: mov eax,0x33. | Dribble stick dead-zone: the 0.2f at 0x1478501c0 is a shared .tls$ constant — do not edit the data; instead in-memory patch the RIP-relative displacement at 0x1440e576b/0x1440e5790 to point at another float (e.g. 0.1f @0x145a8dd68 or 0.05f @0x145b5588c). |
| proven ✔ | function | `0x1440e9570` | ThinkUnitPress: vf8 override 0x1440e9570 — returns command 5 while button 0x1e is held | call 0x144310750(pad, 0x1e, 0); if set: [this+0x1c]=2, eax=5; else [this+0x1c]=0, eax=0. No other hooks (vf9/10/11 are 0x140c83910 stubs). |  |
| proven ✔ | constant | `0x1440d8070` | Kick-gauge charger 0x1440d8070 (vf13 of Shoot/ShortPass/ThroughPass/LongPass): fill-rate table = the only float thresholds in these units | gauge[+0x20] += 1/(fps*T), clamped to 1.0 (0x1440d8280..8291). T from jump table at 0x1440d82c4 indexed by cmd-0x30 and mode [env+0x3308]: cmd 0x3d/0x3e (shoot): T=0.25s (0x1478501fc), mode3: 0.38s (0x146b31dd4); cmd 0x38/0x3a/0x3b/0x3c (passes): T=0.3s (0x145b28a88), mode3: 0.42s (0x1466af68c); cmd 0x30/0x37: T=0.6s (0x147850258), mode3: 1.0s; default 0.3s. Charge skipped if kind/presscount gate fails (0x1440d81da..81e6) or gauge already >=1. In mode 3 with [env+0x34a0]!=1, a pre-pass over the two cursor players [env+0x41d8+i*4] (0x1440d8126 loop) recomputes kind from attr delta (u16[p+0x1e]-u16[p+0x1a])*48/fps < 30. | Faster/slower human shot power build-up: in memory, redirect the movss at 0x1440d824a (0.25f) to a different .tls$ float, or write a private float and fix the RIP displacement. Shared-constant caveat applies. |
| proven ✔ | constant | `0x1440d7ef0` | Stick edge thresholds in base stick detector ThinkUnitBase::vf16 0x1440d7ef0 (0.1 / 0.05) | state 0: magnitude 0x14430f750(pad,[this+0xc],0) >= 0.1f (0x145a8dd68) and previous frame (r8=1) < 0.1 -> state 1; state 2: magnitude < 0.05f (0x145b5588c) -> state 3; state 1: similar 0.05 hysteresis at 0x1440d7fb3. |  |
| proven ✔ | constant | `0x1440e5e90` | Double-tap detector helpers 0x1440e5d50 / 0x1440e5e90 — window = int(fps*0.04+0.5)+1 frames | 0x1440e5ec4 call 0x14533ea80 (fps global 0x148c22abc); mulss 0.04f (0x1463336c8); addss 0.5; cvttss2si; +1 -> passed as window to 0x14430fb40(pad, patternbuf, 2, xmm3=0, ...). Patterns built by 0x14430f2d0/0x14430f300 for button 0x13 (when r8b=1) or the unit's PadId. Gated by 0x1440d7b60(playerIdx) (reads global 0x1486bd888->+0x580->[0x3308]==1 and player flag byte[p+8] bit5 / 0x1442c7f30). | Wider double-tap window: change the 0.04f multiplier reference (shared constant caveat). |
| proven ✔ | negative-result | `0x14533ea80` | Frame-rate getter 0x14533ea80 is the only no-arg float callee — there is no RNG in ThinkUnit code | 0x14533ea80: movss xmm0,[0x148c22abc]; ret. Every 'mul 0.04 / div by it' use in units is a seconds->frames conversion. No call in 0x1440d7bd0, 0x1440e5cb0..0x1440e6ae5, 0x1440d8070 returns an untyped value in eax/xmm0 without args other than this one; no MT/xorshift constants in the pad region 0x1440d7000-0x1440f0000. |  |
| likely ✘ | mechanism | `0x14445c3c0` | Match RNG candidate: inlined MT19937 (for the real CPU decision code in match::ai) | 0x14445c3c6 cmp ecx,0x270; twist loop with 'and edx,0x9908b0df' at 0x14445c401 (state array pointer [rdi], index at [state+0]); init_genrand 'imul eax,edx,0x6c078965' at 0x14445cbb7 with 624-word state on stack. Second MT copy at 0x1414a5763 (engine-level). Not yet tied to a specific match::ai caller. | Hooking the tempered output (after the >>18 xor) would make CPU decisions deterministic; callers must be mapped first. |
| likely ✔ | function | `0x143df1080` | Where CPU decisions actually live: match::ai::ActionSelector* evaluators (e.g. ActionSelectorScore::vf2) | match::ai::ActionSelectorScore vftable 0x146b26a20; vf2 0x143df1080 (410 ins, 22 calls) scans team AI tables [r8+0x8f4c..0x8f74], compares player indices <0x16/0xb, calls 0x1443376f0/0x1443376e0 (registry getters), 0x143b45ce0, 0x1442e1e70, 0x1442f11f0, 0x1442e0360, uses FLT_EPSILON 0x145b26c08; siblings: ActionSelectorGoalGet 0x146b26ba0, LineBreak 0x146b26b20, ChanceSpaceRun 0x146b26a60, Judge 0x146b21380, PlayerOffence 0x147724408 (ctor referenced from 0x145655410), ZoneDefenceManager 0x146b25898. | Retarget the 'decision-units' task to these classes; thresholds for COM shooting/passing will be there and in match::ai::Judge, not in match::pad. |
| proven ✔ | data-table | `0x146c19004` | Command id vocabulary recovered from the units | 0x144318200(id) = dword table at 0x146c19004 stride 20 bytes (category; dispatcher requires 3 for kicks); ids: 0x3d Shoot (0x1440e2070), 0x3a ShortPass, 0x0a ShortPass-special(flag 0x40), 0x3b ThroughPass, 0x33 Dribble, 0x05 Press, 0x51 = none (init at 0x1440dd793), 0x3c excluded at 0x1440d7df5, 0x44/0x3b pairing at 0x1440dd4e9, 0x23 special-cased with 0x1f at 0x1440dd508. |  |

**Skeptic verdict:** The explorer's central thesis survives scrutiny: match::pad::ThinkUnit* are per-slot controller-input interpreters owned by match::CommandPlayer (24 x 0x1c10-byte instances), driven solely by the pad-history ring buffers that only physical devices 0..7 (0x14431a710, guarded by idx<8 and the enable byte at pool+0x258c0) or the empty-frame pusher (0x14431aca0) ever fill. Every cited constant was re-read from the binary and holds: gauge fill times 0.25/0.3/0.6 s (mode 3: 0.38/0.42/1.0 s) via the jump table at RVA 0x40d82c4, stick dead-zones 0.1/0.05/0.2, double-tap window int(fps*0.04+0.5)+1, 30/8 gates in Shoot vf10, and the category table at 0x146c19004. Three corrections matter: (1) ThinkUnitThroughPass::vf8 (0x1440e5fb0) does not early-return on command 0x51 — it calls the base dispatcher first and then latches [this+0x48]=1; (2) the category-3 / 0x143e9df80 'can kick' validation in the base dispatcher lives in the HELD branch (auto-fire while charging), not the release branch, and state 1 maps to vf12 while state 0 calls nothing; (3) the 'match RNG candidate' MT19937 is refuted — a whole-image scan of the MT constants places every instance in menu/onlinesystem/crypto code (nearest methods menu::MyClubProxyTeamSelect, onlinesystem::MatchCommandObserveSessionBufferingControl, CommandObjectWatchGrpc, PlatformSessionManager, kps/ncl), none in match::ai, so the match simulation's RNG is something else. Minor patch-idea address slips: Shoot PadId store is at 0x1440e0e64 (not 0x1440e0e6b); ShortPass 'mov eax,0x3a' is at 0x1440e5d14 (not 0x1440e5d15). The ActionSelector* redirection remains structurally plausible but untraced.

Refuted / corrected:

- `0x1440e69b0` ThinkUnitThroughPass hooks: vf8 override 0x1440e5fb0, vf9 0x1440e6560, vf10 0x1440e69b0, vf13 0x1440e5cd0, vf14 0x1440e5d30, vf1 0x1440e5d40: vf8 override is misdescribed. 0x1440e5fb0 (the explorer also cites a non-existent 0x1440e5fa0) does NOT early-return 0 on cmd 0x51: it calls ThinkUnitBase::vf8 0x1440d7bd0 FIRST, then 'cmp edi,0x51; je exit; cmp edi,2; je exit; comiss [rbx+0x20],0; jbe exit; mov byte [rbx+0x48],1' — i.e. it sets the +0x48 latch when a real command other than 0x51/2 is current and the gauge is charging, and returns the base result unchanged. vf10 (flag 0x40 via btn 0x12 after attr gate, double-tap -> flag 2 gated by +0x48, btn 0x15 -> flag 8 after 0x144300990), vf13 (0x3b), vf14 (0x3b) and vf1 ('mov byte [rcx+0x48],0; jmp 0x1440d7b30') are confirmed.
- `0x14445c3c0` Match RNG candidate: inlined MT19937 (for the real CPU decision code in match::ai): The MT19937 code is real (twist loop with 'and edx,0x9908b0df' at 0x14445c401, init_genrand 'imul eax,edx,0x6c078965' at 0x14445cbb7 into a 624-word stack array), but it is not a match RNG candidate. 0x14445c3c0 is a loop label inside the function starting at 0x14445c360; its callers are 0x14445cc06 (same function family, stack-local mt19937 seeded per call = a std::shuffle/std::mt19937 instantiation), 0x14472c3d6, 0x1447d233f, 0x14486b688. A whole-image scan of every 0x9908b0df/0x6c078965 site, bucketed by the nearest preceding vftable method, places ALL of them in menu::MyClubProxyTeamSelect, onlinesystem::MatchCommandObserveSessionBufferingControl (the 0x1414a5763 copy), onlinesystem::CommandObjectWatchGrpc, onlinesystem::PlatformSessionManager, kps::lltcp, ncl::* crypto and Iex regions — none in match::ai. The explorer's labels are inverted/unsupported: the 'engine-level' 0x1414a5763 copy is in onlinesystem code too. Conclusion: the match simulation does not use MT19937; its RNG must be found by other means (e.g. an LCG/xorshift in match::ai callers).

Open questions:

- What does match-mode [env+0x3308] encode (1 vs 3)? The mode-3 variants (slower gauges 0.38/0.42/1.0, [env+0x34a0]==5 sub-mode) look like online/Dream-Team rules; confirm by xref to the writer of +0x3308.
- Does any COM-assist path (e.g. 'Auto' cursor player, CPU teammate of a human team) ever synthesise pad frames into the 24-slot history pool? Byte scan found no other +0x1900 writer, but a memcpy-style writer (0x1442a5b00 copies slots 0x18e4..0x1944 during a reorder) should be confirmed to be a reshuffle only.
- Map the match::ai evaluators (ActionSelector*::vf2, Judge, PlayerOffence non-virtual update) and their difficulty reads (the six match levels) — that is where the requested 'should I shoot now' thresholds will be.
- Tie the MT19937 at 0x14445c3c0 to its match::ai callers (xrefs not run; each query ~1-2 min).

## Runtime patch path (tools/live_patch.py)

Wrote tools/live_patch.py: an external-process (no injection, no CE) patcher/prober for eFootball.exe reusing the proven OpenProcess/EnumProcessModules/ReadProcessMemory path from mem_probe.py. It has probe (read-only attach+relocation proof — run first), info (pid/base/slide + Denuvo survey), apply (verify-expected -> VirtualProtectEx+WriteProcessMemory+restore, journaled), restore (undo from journal), and wait (poll for launch, optional auto-apply). Writes are gated behind --i-understand-denuvo; dry-run and probe never write. Denuvo survey from the PE: the exe carries the full anti-tamper/anti-debug import toolkit and its real code lives in obfuscated executable sections, so code-page writes may trip an integrity CRC and crash (offline, no ban) while data-page writes are the safer first test. Static syntax/logic verified; live probe/apply degrade cleanly with the game not running (as required). Cannot test against the running game.

| conf | kind | address | finding | evidence | patch idea |
|---|---|---|---|---|---|
| proven | mechanism | `n/a` | tools/live_patch.py created: probe-first external patcher with guarded writes and a restore journal | New file. Commands: probe (READ-ONLY; reads vftable[0] at base+rva and checks it equals base+method0_rva), info, apply (2-pass: verify every expect first, abort on any mismatch, then write+journal), restore (reverse-order, restores original bytes), wait. write_mem does VirtualProtectEx(PAGE_EXECUTE_READWRITE)->WriteProcessMemory->FlushInstructionCache->restore old protect. Verified: python -c ast.parse ok; probe with game down prints 'not running' rc=2; apply w/o flag refuses; --dry-run and length-mismatch/exec-page guards fire. | spec JSON {name,module_offset(RVA),expect(hex),patch(hex),kind:code\|data}; e.g. flip a dt270 gameplay data value at its writable struct offset (kind:data) — safest first write. |
| proven | mechanism | `0x146ba33a0` | probe relocation proof anchored on match::pad::ThinkUnitShoot vftable | Default probe args: --vftable 0x146ba33a0 (rva 0x6ba33a0, confirmed inside .tls$ 0x59fc000..0x7e41000 where vtables live) and --method0 0x1440e1fb0 (rva 0x40e1fb0, confirmed inside executable .xcode 0x1000..0x59fc000). exe_map class match::pad::ThinkUnitShoot lists vftable 0x146ba33a0 with methods[0]=0x1440e1fb0. probe reads the live qword at base+0x6ba33a0 and asserts == base+0x40e1fb0, proving attach and relocation for any ASLR slide. | Run `python tools/live_patch.py probe` before any write; a mismatch means the map is stale or memory is masked — do not patch. |
| proven | constant | `0x140000000` | DYNAMIC_BASE is OFF: image normally loads at preferred base 0x140000000, slide usually 0 | pefile: DllCharacteristics 0x8120 -> DYNAMIC_BASE(0x40)=False, HIGH_ENTROPY(0x20)=True; reloc directory reports None. So RVA==VA at runtime in the common case, but the tool never assumes it: module_base() reads the real base via GetModuleInformation and computes slide, and probe validates it. | If slide!=0 the tool relocates automatically; module_offset in specs is always an RVA (VA-0x140000000). |
| likely | mechanism | `0x1459fc520` | Denuvo anti-tamper import surface present — code-page writes risk an integrity crash | IAT imports: KERNEL32 VirtualProtect@0x1459fc520, VirtualQuery@0x1459fc938, AddVectoredExceptionHandler@0x1459fc3b0, CreateThread, IsDebuggerPresent@0x1459fc760, GetThreadContext@0x1459fc6a8, QueryPerformanceCounter@0x1459fc9d0, GetTickCount/64; ntdll NtProtectVirtualMemory@0x1554a85b0, NtQueryVirtualMemory@0x1554a85c0, NtQuerySystemInformation. Real code is in .xcode (0x1000, ~0x59fb000, EXEC) and .impdata (0x939e000, ~0xae9f5b4, EXEC — the Denuvo VM blob); the section literally named .text is READ\|WRITE data (char 0xc0000040). This is the classic Denuvo self-CRC + anti-debug + timing toolkit. | Prefer kind:data writes (gameplay tuning values in writable structs) over code NOPs; keep any code patch tiny and keep the journal so restore can revert while the process still lives. A tripped CRC crashes offline play — no ban. |
| likely | negative-result | `n/a` | Exact CRC/integrity loops are not statically enumerable (obfuscated inside .impdata VM) | .impdata is a ~183MB executable blob (Denuvo VM); integrity checks are virtualized there, not plain IAT-call loops over .xcode we can point to. No fixed 'CRC over section X' function was located to disable. Reads remain safe and proven (docs/live-stats-extraction.md: mem_probe read 40 real regions; CE is singled out, plain external RPM is not). | Treat every code write as 'may crash'; validate empirically with a small reversible data write first, watching for a delayed crash which would indicate a periodic integrity sweep. |

_Not independently re-derived by a skeptic (explorer evidence only)._

Open questions:

- Whether a data-page write to a per-frame gameplay value survives (not under integrity hash) vs a code-page NOP that trips a CRC — needs one live test with the game running.
- Whether Denuvo runs a PERIODIC integrity sweep (delayed crash after a code write) vs only at load — observable only live.
- Whether module_base()/probe succeed against the live process exactly as designed — could not be tested because the game must not be launched here.

## Tooling

```bash
python tools/exe_map.py build                       # RTTI -> vftables -> methods (build/exe_map.json, 3 s)
python tools/exe_map.py grep 'ActionSelector'       # find classes
python tools/exe_map.py class ActionSelectorScore   # vftable + methods
python tools/exe_map.py disasm 0x14401a900          # annotated disassembly
python tools/exe_map.py xrefs 0x144345eb0           # callers (slow)
python tools/live_patch.py probe                    # READ-ONLY attach + relocation proof (game running)
python tools/live_patch.py apply spec.json --i-understand-denuvo   # journaled in-memory patch
python tools/live_patch.py restore
```

Raw findings with full evidence: `build/exe_map_findings.json`.
## On-disk hex patching (tools/exe_patch.py) + the slices/scuffs pack

`tools/exe_patch.py` edits `eFootball.exe` on disk (same spec format as `live_patch.py`). First
apply copies a byte-exact pristine exe to `~/Backups/eFootball/eFootball.exe.PRISTINE` and records
its sha1; `restore` puts it back. A patch writes only if every `expect` byte still matches, so a
spec built for another game version can't corrupt anything. `status` / `diff` show what's applied.
Specs take `va` (VA) or `module_offset` (RVA) — **not** a file offset; the tool does the section
math. Steam "verify integrity of game files" reverts the exe; keep the game closed while patching.

### Kick miss-type model (verified, extends the kick-error section)

The miss magnitude (angle/speed) is one thing; **which** mis-kick fires is another. Builder
`0x14401a900` computes five candidate probabilities and keeps the best:
- **type 0 over-hit** `0x14401e5b0` (too much power for the situation; speed-ramp thresholds per
  kick category, e.g. cat-0 65/75 km/h at `0x14401e846`)
- **type 1 awkward body angle** `0x14401fc80`
- **type 2 closed-down** `0x144020450` (nearest 3 opponents, ground kicks only)
- **type 3 behind-the-body** inline `0x14401b640` (class/situation tables)
- else **type 4 normal** Gaussian miss `0x14401a060`.

Gate `0x14401b7c9` (`test r15d,0xfffffffd; je`): types **0 and 2 are applied unconditionally**;
types **1 and 3 are rolled** against `int(best*100)` at `0x14401b7d8` (helper `0x143eafd30` =
`rand%100 < pct`). Types 0/2 are separately gated *inside* `0x144019320` by a `100f` roll at
`0x144019a50`. So raising slice frequency needs **both** roll sites. Ability factor `f`
(`0x143ed71d0`, `<60→0..0.1`, `60–90→0.1..0.9`, `>90→0.9..1`) suppresses every probability, so
flattening that curve (G1/G2) makes even elite players mis-hit. Correction to the earlier
section: σ = `0.75 + 4.25·(1−c)²` (not `·p·(1−f)`); builder `+0` (`0x14401b3df`) is the horizontal
error for normal kicks too (caller copies the struct to `rbp+0xd0`, randomizer reads `+0x10`).
Caveat: `[player+0x362c]&1` (assisted-pass/locked-target flag) zeroes type-4 horizontal error, so
the type 0-3 probability boosts are what move assisted passing.

### Patch packs (all disp32 repoints to existing .tls$ cells; float values verified)

- `tools/data/patches/slices-scuffs.json` — **APPLIED 2026-08-23** (conservative). 9 edits:
  mis-type rolls ×1.3 (A `0x14401b7d8`, A2 `0x144019a50`), speed error 30→40% (B), horizontal
  shank 22.5→30° (C), type-1/3 floor 8→15° (D), σ 4.25→6 (E), elevation 22.5→30° (F), ability
  curve flattened (G1 slope 0.8→0.6, G2 base 0.9→0.7). `diff`: 30 bytes vs pristine.
- `tools/data/patches/slices-scuffs-aggressive.json` — 11 edits: ×2 rolls, 45°/45°, floor 20°,
  50% power, σ 8, harder flatten, plus H (`cos(90+x)→cos(135+x)`: awkward/behind-body kicks always
  visibly shank) and I (cat-0 over-hit thresholds 65/75→50/60 km/h). Not applied.
- `tools/data/patches/slices-scuffs-max.json` — **APPLIED 2026-08-23** (max). The aggressive
  set plus **K**: `0x14401a175` `je`→`jmp`, forcing the normal kick-error path even for
  fully-assisted locked-on passes (stock game zeroes their horizontal error via `xorps xmm7` at
  `0x14401a17b` when `[player+0x362c]&1`). Result: slices and mishit passes are near-universal.
  `diff`: 48 bytes vs pristine. Supersedes the conservative pack (restore, then apply).
- `kick-error-x2.json` / `superstar-reaction-professional.json` — earlier single-purpose specs;
  kick-error-x2 overlaps slices/scuffs C/F, so don't stack them.

```bash
python tools/exe_patch.py status                              # what's applied
python tools/exe_patch.py apply tools/data/patches/slices-scuffs.json [--dry-run]
python tools/exe_patch.py apply tools/data/patches/slices-scuffs-aggressive.json
python tools/exe_patch.py restore                             # byte-exact pristine exe back
```

## Coverage — what's mapped vs still open

**NOT a full map of the exe.** There are 782 `match::` classes with vftables; the sections above
deeply map ~5 subsystems. Mapped in full (followed the code, verified): the **kick error /
accuracy model** (magnitude + miss-type selection + ability curve), **CPU difficulty** (44×10
level table, hidden LEGEND, runtime level object), and the **dt270 ConstantManager** path
(which decoded fields are live/inert). Located but **not traced to thresholds**: CPU
decision-making (`match::ai::ActionSelector*`, `Judge`, `PlayerOffence`) — this is *whether* the
CPU shoots/passes/presses, as opposed to the execution error we did map. Identified only:
human controller-input units (gauge fill, dead-zones).

Still unmapped (each is a focused `exe_map.py` session — the tooling reaches them all):
- CPU decision thresholds — when to shoot / pass / press / tackle / dribble, and target selection
- the match-simulation RNG (MT19937 was refuted as the match RNG; the real one isn't found yet)
- player physical model — sprint speed, acceleration, stamina / fatigue curves
- goalkeeper behaviour (`match::player::ActionKeeper*`, ~30 classes)
- dribbling / skill-move execution, tackling, fouls, referee strictness, cards
- collisions / physicality / jostling / shielding, offside logic, injuries, condition / form

## Mod browser

`tools/gameplay_catalog.py` merges the dt270 schema + current values + these exe findings + the
patch packs into `build/gameplay_catalog.json` and a self-contained HTML browser
(`build/gameplay-catalog.html`, published as the "eFootball Mod Deck" artifact). `build` /
`html` / `search <term>`. Re-run after a Konami patch (regenerate the schema + exe map first).

## Mishit spin — slices / shanks / scuffs (2026-08-23, applied)

> **CORRECTED 2026-09-17 — the spin claims in this section and in "Code caves → slice-cave" are
> WRONG. See "Kick spin — emulated ground truth" at the end of this file before touching spin.**

Why mishits looked like plain misdirections, not slices: the kick-miss code (`0x14401a900`)
only bends **direction/power** and never touches spin. Spin is built separately in
`0x144018c10` (called by the dispatcher `0x143ed0f80` right after the kick), which derives the
spin axis from the *already-deviated* travel direction — so a shank curls exactly like a clean
kick aimed at that wrong spot. Mishits are **not** spinless (there's a speed-proportional floor),
but nothing adds sidespin *proportional to the miss*. The one coupling — spin-axis lean toward
travel-vs-facing — is **clamped at 45°**. Unclamping it is the true "slice" lever.

`tools/data/patches/mishit-spin.json` — **APPLIED** (stacks on slices-scuffs-max), all bytes
independently verified + skeptic-verified:
- **P1** `0x144018df0` sidespin lean cap **45°→90°** (repoint disp32 to the 90f cell) — sidespin
  now scales with the horizontal miss; shanks/slices curl away. 180f = near-unclamped.
- **P2b** `0x14401914c` assisted-kick spin scale **50→80** (= manual) — assisted passes/shots
  build real spin, so their mishits curl instead of drifting flat.
- **P2** `0x144019177` spin-magnitude cap **0.9→1.0** — mild overall curl/dip bump.
- Amplifier: dt270 **`ball.magnusRate` 0.045→0.07** (loose-realism-v1) — scales all curl,
  including the now-leaning mishit spin. magnusRate alone can't bias the axis (that's P1's job).

Tool note: fixed a `gameplay_tune.py --stack` bug (it wrote dt270 edits into pristine instead of
the stacked base, so the container slot wasn't found); stacking dt270 edits now works.

## Injuries (2026-08-23) — deterministic, no probability roll

Two rounds of tracing: contact injury is decided by `0x143fbf7f0` (called from the Contact and
fatigue anime handlers; returns 2 → transition to injury demo id 99 via `0x143eb4fd0`). It has
**no RNG** — an injury fires when the playing tackle/contact animation carries a "type-7" event
whose severity code is 2/3 and the current frame is inside the event window
`[start, start+round(fps·3/60)]`, gated by the injury-enable (modeMatchup idx 0x50 obj+8) and
anti-double-injure context. So injury frequency = enabled × (clip is injury-tagged) × context.
**Durability (attr 0x2d) does NOT gate injury chance** (confirmed both rounds — its reads feed a
reach/interception predictor, not an injury compare). The fatigue "OVER_DAMAGE" tokens are
telemetry strings, not a numeric threshold.

Exe levers to raise contact injuries (verified byte-exact, held for the realism preset):
- **A** `0x143fbfa51` `75 0d`→`90 90` — NOP the severity filter so any windowed type-7 event injures.
- **B** `0x143fbf973` repoint `movss xmm8,[3f]`→`[30f @0x145a8dd80]` — injury window covers most of
  the clip instead of a 3-frame spike.
Ceiling: only injury-tagged clips can injure; more than A+B requires editing the anime `.bin`
event tables (CPK/anime data at `[0x14868aba0]` stride 0x1f8), not an exe immediate.

## loose-realism-v2 (2026-08-23, APPLIED) — the coherent realism preset

Assembled by a 5-pillar design workflow + synthesis, replacing the arcade-extreme stack. Key
insight: **patch L (accuracy factor → 0) also killed spin magnitude** (spin builder 0x144018c10
reads the same factor at 0x14401912d), so mishits flew clean-but-wrong. The fix is to **remove L**
(restore) and rely on a *mild* ability flatten (G1 0.6 / G2 0.7) — everyone still errs, elites err
less, and spin returns so mishits curl.

- **EXE**: `tools/data/patches/loose-realism-v2.json` (32 patches, all byte-verified on pristine):
  kick angle error 45→30°, mis-type freq ×2→×1.3, mild ability flatten, spin (P1 90° lean / P2b
  assisted 80 / P2 cap / K), scuff skids low (angleY sign 100f→50f), gauss σ 8→6, slice floor 15°;
  fouls (card 30→40%, advantage 0.3–2 s), physicality (contact clamp 35→42 km/h, mistimed slides);
  CPU per-level reaction (SUPERSTAR/LEGEND 4→7/6/5/5 frames) + commit% 100→90–95; varied
  counter-runs (40→28); injuries maxed within the anime-tag ceiling (A NOP severity filter, B
  window 3f→30f). Apply on a **pristine** exe (`exe_patch.py restore` first — the expect bytes are
  pristine).
- **dt270**: `tools/data/tunings/loose-realism-v2.json` (165 edits): magnusRate 0.13→0.06,
  knuckle/bobble (nonSpinMin 30, nonSpinRate 1.35), free ball (touch0 carry 0.15/0.26, grounder/
  roll friction, reachOut 0.7/42), smarter shape (spaceCoverRate 0.45, marginPredictionFrameBase 6,
  jogMfLineScore 45, slowDownFw off), boundRate 0.72.

Revert everything: `exe_patch.py restore` + `gameplay_tune.py restore`.

## Code caves (2026-08-24)

> **Superseded in part, 2026-09-18** — "largest single run ~91 B" was measured on PRISTINE, and
> both big runs are occupied on the installed image. Chaining is now automatic; see
> [Chained code-cave allocator](#chained-code-cave-allocator-2026-09-18--toolscave_allocpy) below.

Assembler: keystone. On-disk caves live in `.xcode` int3 padding (executable already — NO section
permission change / no W^X bypass); largest single run ~91 B, so >~90 B caves must chain across
runs. Hook = overwrite the stolen instruction(s) with `jmp rel32` into the cave; the cave runs
the relocated stolen bytes + its logic, then `jmp` back. All via `exe_patch.py` (pristine backup
+ restore). `xmm6-xmm15` are nonvolatile — a cave may only scratch `xmm0-5` unless it saves them.

- **slice-cave.json (APPLIED on v2)** — the shank/slice fix. Hooks the spin builder
  `0x144018c10` at its last omega write (`0x1440192fb`), cave @ `0x14105ed20` (49 B): adds
  `hdelta = azimuth[rbp+0x57] − facing[rbx+0xc98]` × `K_SIDE(0.01)` into `omega.y` (the curl
  axis). `hdelta` already scales with the miss (and thus with `1−ability`), so slices grow with
  pass difficulty + poor passers, for free — no accuracy-fn call needed. K_SIDE is one tunable
  immediate (`mov eax, <float bits>` at cave+0x13). Verified: hook→cave→back all disassemble.
- **Designed, not yet built** (`build/rng_cave_design.txt`, `build/spin_cave_design.json`):
  RNG jitter cave (hook `0x143df127b`, ×[0.8,1.2] on CPU candidate scores, own seed buffer);
  the full spin cave also adds topspin/backspin from the vertical velocity error (scuff/skied) —
  ~261 B, to be chained across padding.

Player-stat extraction map: `build/ratings_stats_map.json` — rating compute `0x14429ea40`,
per-player record `container+0x65C0+team*0x38238+player*0x13E8`, stat rows `record+0x10`
(0x77×9 int32; made=c0+c1+c2, attempted=c3+c4+c5 → completion%), rating float
`RecordSlot+0x1c4+(team*0x28+player)*0x10`. Read-only via ReadProcessMemory; a value-scan on the
rating float array (3.0–10.0, stride 0x10) locates RecordSlot without the one live-only pointer.

## Match ratings & per-player stats (2026-08-24) — FULLY MAPPED

**The rating formula is dt270 DATA, not compiled code.** `rating.o`'s four strings
(`df_rate`/`mf_rate`/`fw_rate`/`gk_rate`) are not documentation — a compiler at match init
(`0x1442a45d0` → `0x1456cd0b0`) turns each into a 0xC04-byte program inside RecordSlot, and
`0x1442a0f90` → evaluator `0x1456cc690` runs the one matching the player's position (jump table
`0x1442a11f8`: 0=GK, 1-2=DF, 3-6=MF, 7-9=FW). Its result is the raw score that the scorer
`0x14429ea40` normalises into 0-10. **So ratings are retuned by editing dt270 strings — no exe
patch, patch-proof.** Names resolve through the game's own registry at `0x147735d00` (89 entries
`{const char* name; accessor}`); each `StatsPlayer*` accessor is a thunk `mov edx,<ROW>; call
0x1456d1050`, which reads that row with **mode 5**. Fail-safe to respect: an unparseable formula
compiles to zero instructions and the evaluator returns 0.0 — flat-lining every rating.

Tool: `tools/rating_weights.py show | set <pos>.<Stat>=<w> --apply | restore`. Strings are
patched in place so a replacement must be **same-or-shorter**; the tool minifies first, freeing
~170 B per formula. Only names already present in the shipped formulas are accepted.

Corrections to earlier notes: getter `0x1443378c0` **mode 5 = c0+c1+…+c7** (eight columns, not
c6+c7); **attempts and completions are SEPARATE ROWS** (0x1a `pass_short` vs 0x1b
`pass_short_success`), so completion% = success.total / attempt.total. `ratingMax` is at the
lower struct offset than `ratingMin` — the schema names and the code agree (our 0.5/10.0 edit is
correct).

**Row map:** 46 rows proven from the registry, ~76 named overall (`build/rating_weights_rows.json`)
— goal/own-goal/FK-goal/PK-goal/assist, shots (+on-target, +PK, +scored), pass & pass-success in
short/through/long/cross variants, tackle(+success), dispossess delay/press, clear, foul,
offside, cards, FK/corner taken, dribble(+success), ball touches, balls won by
interception/tackle/block/wedge, balls lost while dribbling/passing, GK shots faced/on
target/saves/PA saves.

**Extraction:** superseded 2026-09-14. The external ReadProcessMemory reader that walked this
record (`tools/stats_read.py`) was deleted, along with the other memory scanners. Per-player
counters now come from efootball-re's stats host, which runs inside the game and exports every
finished match to `ml_stats\match_*.json` (see `ML.Ingest`). The layout notes above still
describe what the engine keeps.

### Rating internals — two corrections that matter (2026-08-24)

**`subValue*percent` is SUBTRACTIVE, not additive** — it is a penalty applied just before the
clamp, and the scorer *discards any entry <= 0.0* (`0x14429f443 comiss / jbe`), so it can never
be used to grant a bonus. Raising an entry makes those performances score LOWER.

**The clamp was never the binding constraint — `baseRating*` was.** The base rating is
`baseRatingMin + 0.5*floor(2*(baseRatingMax-baseRatingMin)*norm)`, i.e. with the shipped 5.0/7.0
exactly **five** discrete steps {5.0,5.5,6.0,6.5,7.0} — the real reason every player clusters.
`norm` comes from rate = rawScore / minutes-played (minutes floored to 45), min/max/mean taken
over **all 80 slots of both teams** (no position grouping). Players with <5 minutes are forced
to 0.0. Also dead-on-arrival: `baseRatingMedian` and `addPoint.assist_over4` are never read.

Applied in loose-realism-v2: `baseRatingMin 5->3`, `baseRatingMax 7->9` (5 steps -> 13), ladder
respread `0/0.3/0.7/1.1/1.5/1.9/2.3/2.7/3.1/3.5`, clamp `0.5/10.0`.

**Fouls are already tracked — no cave needed.** Row `0x3c` (`StatsPlayerFoul`) is incremented for
every whistled infringement *including mistimed tackles/slides*, credited to the OFFENDER, by a
single unconditional writer `0x1442a31f9` (the only site in the whole exe passing row 0x3c;
handler `0x1442a3020` for match-event type `0x1d`, emitted by `match::record::ObserverFoul::update`
`0x1442932a0` on "play stopped AND restart == free kick" — it never inspects *how* the foul
happened). Offsides increment `0x3d` *in addition to* `0x3c`, which is exactly why Konami's
formula reads `(Foul - OffSide)`. Victim rows are `0x40`/`0x41`. Set to **-8** in df/mf/fw
(= cancels a successful tackle). GK has no foul term; adding one needs a new term, not a weight.
Caveat: fouls in a penalty shootout land in column 8, which mode-5 does not sum.

### Is reading memory safe? (why `stats_read.py` cannot crash the game)

The process is opened with `PROCESS_QUERY_INFORMATION | PROCESS_VM_READ` only — deliberately
**not** `VM_WRITE` / `VM_OPERATION`. No injection, no debugger attach, no thread suspend, no
`VirtualProtectEx`. `ReadProcessMemory` has the kernel copy pages out; the target is neither
modified nor paused and does not observe it. A failed read just returns false and is handled.
This is the same read-only path `mem_probe.py` / `mem_scan.py` proved on this game (2026-08-20)
and that `read_match_memory.py` (already wired into `ML.App/SessionMatchMemory.cs`) uses at the
full-time screen. Writing is the risky class, and none of the stats path writes.

The scan is vectorised with numpy (cumsum window test over stride-0x10 float phases); a
pure-Python loop over every 16-byte candidate would take hours on a 350 MB+ process. Scan math is
unit-tested against a synthetic planted rating array (finds the exact RecordSlot, values read
back identical).

## Kick spin — emulated ground truth (2026-09-17)

Every line here is a number produced by running the game's own code in Unicorn:
`python tools/emu_spin.py all` (read-only; `--exe <PRISTINE>` gives identical output).

- **Ball physics is Y-UP** (X, Z horizontal). Air-force routine `0x144089620` writes gravity
  `-9.80665` to component `[1]`; Magnus = `k·(ω × v)`, `k = magnusRate·π²·0.0118·0.1087·min(horizontal
  speed, 23.6 m/s)`. Only ω about the **vertical (Y)** axis curls the ball, and to first order it gives zero
  lift; ω horizontal and across the travel = lift/dip. If `[state+0x90] != 0` (knuckle / non-spin
  program) the routine ignores its ω argument and uses the keyframe table (`0x1440a1460`).
- **`0x144018c10` is NOT a spin builder.** Its `r8` is the ball **velocity** (m/frame): it splits it
  into azimuth / elevation / speed, clamps the azimuth to ±45° of body facing (`0x144018df0`; 90/180
  for some kick types), clamps speed, and recomposes it. `r9` is never touched. So the old P1 (45→90)
  only widened the allowed kick direction, the old P2/P2b were **speed** edits (more `vy` =
  ballooning), and the old slice caves (`r14+4` / `r14+8` at `0x1440192fb`) were adding numbers to the
  **velocity** — hence passes leaving at the wrong speed and direction.
- **The mishit master is `0x144016a70`** (`match::anime::action::Kick::vf8 0x143ed0f80` → here, then
  `0x144018c10`). Args: `r8`=velocity (→`r14`), `r9`=**local spin vec3, rev/s** (→`r15`),
  `rdx`=kick record (→`r13`). It calls the miss builder `0x14401a900`, then the per-type randomiser
  (`0x144019e40` types 1/3, `0x144019320` types 0/2, `0x14401a060` type 4: input triple read-only,
  output triple = deviated az/elev/speed), rebuilds `r14`, and — for types 0-3 only — runs a foot/ball
  **contact model** (`0x143edad30` → `0x143edae20`) that re-solves velocity **and writes spin** to
  `r15`. Type 4 (the ordinary random error) never touches spin: that is the real gap.
  It then stores the miss in the kick record (`+0x148` horizontal deg, `+0x14c` vertical deg, `+0x150`
  speed) and simulates intended vs actual flight itself via `0x14408ac90(state, 0, obj, &pos,
  &vel·fps, &spin, 1)` + integrator `0x14408d0f0`.
- **Local spin convention** (`0x14408ac90`, cross-checked with the solver's `0x14408c7e0`):
  `(x = top(+)/back(−), y = SIDE, z = rifle)` in rev/s; world `ω = Ry(azimuth)·2π·(x, −y, −z)`, so
  `ω.y = −2π·spin.y` whatever the azimuth. `spin.y < 0` curls toward increasing azimuth.
- **Live launch path** (`emu_spin.py live`; stages emulated, glue from disassembly). Per-tick handler
  `0x143eb2190` → finalise `0x143ea46c0`: ctx `0x14408eaa0` → solver `0x14408ed10(ctx, &vel, &spin)` →
  `Kick::vf8` (mishit) → tail `0x143ea480e`: `record.mode[+0x8c] = 4` (`0x143eb69d0`), velocity →
  `+0xd0..`, spin → `+0x114/+0x11c/+0x120`, valid flags `+0x110 = +0x118 = 1`. Ball side
  `0x143c59350` (the real launch) runs the **same solver** on each kicking player's record: its first
  act is the seed `0x144098cd0` (reads the spin back when the flags are set), mode 4 copies `+0xd0..`
  to the out velocity — emulated: velocity and spin come back unchanged, x/y/z order kept — then
  averages over players and calls `0x14409d710` → `0x14408ac90(state, kickinfo = record, obj, &pos,
  &vel, &spin)` at `0x14409da15`. With record `+0x124`/`+0x140` = 0 (no first-touch deflection) the
  init gives the same ω as with `kickinfo = NULL`. Record reset `0x143c58ea0` (mode `0xc`, flags 0)
  runs right before the handler at 2 of its 3 call sites (`0x14410fdb1`, `0x1441116fb`); the third
  (`0x144241b8a`, external record `[rsi+0x15a28]`) has no visible reset.
- Ball motion state: `+0x00` **position** (y initialised to the radius 0.108686), `+0x0c` velocity m/s,
  `+0x18` world ω rad/s, `+0x24` heading, `+0x90` non-spin flag. The stepper `0x14408d0f0` calls the
  air-force routine on the ground too, so ground passes curl; its `dl` arg becomes the routine's
  `r8b`, which skips Magnus — who sets it in the live update is unknown.
- `tools/data/patches/linked-spin.json` (**authored, NOT applied, never run in game**; revised after
  two adversarial reviews): hook `0x1440187b4` (`movss [r13+0x148], xmm6`, xmm6 = signed horizontal
  miss) → `movaps xmm0,xmm6; jmp 0x14105ed1e; nop`; cave = 85 B of the 86-byte int3 run:
  `spin.y' = clamp(spin.y + GAIN·miss, min(spin.y, −CAP), max(spin.y, +CAP))`, NaN miss → no change,
  GAIN `−0.15` rev/s/deg at `0x14105ed30`, CAP `±3` at `0x14105ed43` / `0x14105ed56`. Never cuts the
  game's own spin; re-entry saturates at CAP. Differential emulation vs stock: only `rax/xmm0/xmm1`
  (proven dead) and `[r15+4]` change. Stepper-measured drift at GAIN 0.15: 10° miss on a 30 m pass
  ≈ +1.1 m ground / +1.8 m lofted (miss itself 5.2 m); first-order lift 0, ≤ 1 cm apex change on
  8 rev/s backspin. Retune only via `emu_spin.py spec --gain <positive> --cap <positive>`. With
  scuff-wobble / knuckle-mishit installed, types 0-3 fly the knuckle program, so the cave acts on
  type-4 kicks only.


## Sprint-exertion meter and the "fatigue" cave — emulated ground truth (2026-09-18)

Every number here comes from the game's own code under Unicorn: `python tools/emu_kickerror.py`
(read-only, PRISTINE by default, sections S1–S10; `--exe <live>` also passes).

- **`[player+0x30f4]` is sprint exertion, not tiredness** (S10, updater `0x143eb84c0`). It rises 40/s only
  while the action id satisfies `0x144311bf0` (flag table `0x146c14e80` bit 3 → ids **4/5/6** only; names
  unproven, very probably on-ball dribbling) *and* speed `[player+0xb38]` ≥ 17.5 km/h (25 without the
  `[arg2+0x570] ≥ 0.9` flag). Full in 2.5 s, back to 0 within 0.5 s below the gate, frozen during kick ids
  8/9/0xa (or −500/s when `[player+0x2bdc]==0x10` and the action counter > fps/6). Identical in minute 1
  and minute 90. `technique-realism.json` re-aims the gate to 11 km/h, so jogging fills it (13/s at 14 km/h).
- **The stock game already spends it on the horizontal axis** (S9). Of the six readers, exactly one sits in
  a c-factor function: `0x14401c143` in `0x14401bdb0` → slot 0 (horizontal c) `*= 1 − clamp(0.1+0.6(1−f))·ramp`.
  Full meter: ×0.36 at f=0.1 (14.4° ceiling), ×0.72 at f=0.7 (6.3°); nothing below meter ≈ 65. The other five
  (`0x14401d4f0`, `0x14401fc80`) are mishit-TYPE odds called after `0x14401b5d5`. **No meter term exists on
  the vertical or power c.**
- **"A clean kick has c == 1.0" is false for the horizontal axis**: `0x14401bdb0` first scales slot 0 by a
  kick-class constant (class = byte 13 of the 16-byte record `0x14804e0e0[kick id]`, via `0x143eda730`):
  class 0 ×0.90, 1 ×0.88, 2/3 ×0.86, 4 ×1.0 — 172 of 176 kick ids are class 0–3.
- **`tools/data/patches/cave-fatigue.json` (authored, NOT applied, never run in-game)** is therefore a
  *sprint-exertion → vertical + power error* cave, not a fatigue layer: hook `0x14401b3a7` → cave
  `0x1438b4835` (86 B of 91), `S = max(0, min(1, 1 − gain·meter/100·(1−f)))`, `xmm12 *= S; xmm6 *= S`,
  `xmm3 = K` immediate (K 6.0 @ `0x1438b4836`, gain 0.5 @ `0x1438b483f`). S is clamped both ways and
  NaN-safe; horizontal (`xmm1`) is untouched. It occupies the sigma-K site, so it *includes* and excludes
  `error-sigma.json`. `cave-fatigue-weakfoot.json` is the optional two-part variant (weak-foot floor).
- **Match-long stamina is still NOT located.** `0x145614eb0` is the gauge's world anchor (vec3), the HUD
  byte `uiData+slot·0x1c+0x14c` arrives by struct copy (the only indexed byte stores at `+0x14c` in `.xcode`
  are zero-stores in the unrelated `0x143c60dd0`), and no `match::` RTTI class names stamina. A real fatigue cause stays blocked on that.

## Chained code-cave allocator (2026-09-18) — `tools/cave_alloc.py`

Supersedes the chaining note in **Code caves (2026-08-24)**. A payload no longer needs one
contiguous int3 run: it is split across many small runs, each chunk ending in a 5-byte `jmp rel32`
to the next. `.xcode` spans 0x140001000–0x1459fc000 (94 MB), worst-case displacement 0x59faffa
against a ±2^31 range — **reach is a non-issue** (b-disassembly).

**The pool and its safety oracle.** `tools/cave_scan.py scan` → `build/caves.json`. The EXCEPTION
data directory is RVA `0x154ac000` size `0x4b180c`, i.e. the whole `.trace` section — so `.pdata`
*is* `.trace`, 410,113 `RUNTIME_FUNCTION` entries merging to 253,886 ranges over 84.3% of `.xcode`
(b-disassembly). Of 547,254 int3 runs, 106,874 fall **inside** a function body and are permanently
rejected. **Tier A** = a run that starts exactly at one function's `EndAddress` and ends exactly at
the next function's `BeginAddress`, 16-aligned, with no `.pdata` overlap, no absolute 8-byte pointer
into it, and no rel32/rel8 branch target in it that a `.pdata`-anchored linear sweep proves to be a
real instruction start. Corroboration: of 97,074 sweepable candidates, 96,926 (99.85%) end on a
function terminator — ret x75,981, jmp x20,647, nop x271, ud2 x26. A bare "some u32 equals this RVA"
test is worthless here (514,886 hits, vetoes the whole pool); it must be jump-table-aware.

Pool at `--min 12`: **42,494 caves / 362,214 B of payload capacity**, mean length 13.5.
**The largest tier-A cave in the whole image is 21 B** (MSVC 16-aligns function entries, so genuine
inter-function padding caps at 15), so no instruction longer than 16 B can ever be placed and ~40%
of a payload's written bytes are chain jumps. The pool is edit-invariant — scanning PRISTINE and
INSTALLED yields the identical 97,590-cave tier-A list.

**Mechanism.** One instruction per source line, never joined, so a chunk is a run of whole
instructions by construction. Sizing is **address-independent**: every label is sized against a far
dummy (forcing rel32, the maximum form) and every rip-relative operand against a disp32, so one pass
suffices — no fixpoint. Emit re-assembles each line at its final VA and nop-pads a shorter encoding;
growth past the reservation is a refusal, not a resize. `jmp rel32` writes no flags, so a chunk
boundary between a `cmp` and its `jcc` is safe (a-emulated). Each chunk is an ordinary `exe_patch`
entry whose `expect` is `cc`×n, so `remove` restores the padding byte for byte; a `cave_layout`
block carries the provenance.

Occupancy comes from three sources, because none alone is right: the target image's bytes, the
ledger `tools/data/cave_reservations.json`, and a **byte-range** scan of every spec in
`tools/data/patches/`. (`0x1438b4804` reads all-int3 yet is claimed by `cave-fatigue-weakfoot`;
`linked-spin` and the retired `slice-cave` overlap *inside* one run at different start VAs, so a
VA-equality check misses it.) Inspect with `exe_patch.py caves [--near VA] [--audit]`. The allocator
refuses against an image whose sha1 does not match the pool it was built from. **Re-run
`cave_scan.py scan` after every Konami patch** and regenerate every cave spec — chunk addresses move.

`exe_patch.py` changes shipped with it: `remove` now reverts in **reverse** spec order (hook first —
the old order briefly left a live jmp into int3), specs with internally overlapping entries are
rejected at load, and a part-way write failure rolls back.

**NOT PROVEN (d):** Denuvo's tolerance of written int3 padding. The `.pdata` and reference gates
argue only that stock code never executes or points at those bytes. Chaining writes into N sites
instead of one, so it multiplies whatever that exposure is. Prefer the fewest chunks that fit.

## Defensive anticipation by ability (2026-09-18) — the first chained cave

`tools/emu_anticipation.py` (design + 10 Unicorn proofs) → `tools/data/patches/anticipation-ability.json`
(authored, **NOT applied**). `tools/anticipation_spec_check.py` re-proves the written file at its
final addresses. Both are read-only against the game.

**The site is not what it looks like.** `0x143da63b0` (682 B, one caller `0x143daa3bf` inside
`0x143da92c0`) is the AI **gait / movement-urgency chooser's "ease off while the ball is in flight"
rule**, not a prediction horizon. `0x143da92c0` has 8 call sites, all `match::player::Action*::vf13`
of move-type actions plus the `ActionBasePosition` cascade — so it runs **per player per tick for
both teams**, attacking and defending (b-disassembly).

```
edi  = basePosition.marginPredictionFrameBase [r12+0x240]       (dt270, currently 0)
       - (int)(marginPredictionFrameAdjust [r12+0x23c] * -0.0f) (DEAD: always 0)
       + ebx                                                    (ball flight frames, 1/0.6 inflated)
loop:  accept gait-1 while arrival < margin + edi                (0x143da65fe..0x143da6603)
```

`edi` is a **time budget**, and `sub edi,eax` means a **positive** delta *shrinks* it — so a positive
delta makes a player refuse to downshift. **The obvious sign is backwards**: elite ⇒ positive delta ⇒
keeps sprinting; poor ⇒ negative ⇒ coasts while the pass travels. The literal at `0x147850538` is
`-0.0f` in **both** images (stock, not a build accident) and `eax` comes out 0 for every int32 input
including ±INT_MAX (a-emulated) — 12 dead bytes inside a live function.

**The patch.** Hook = 16 B at `0x143da6545` (`mulss` 8 + `cvttss2si` 4 + `sub edi,eax` 2 +
`add edi,ebx` 2), ending exactly on the stock call `0x143da6555`. Nothing rip-relative is relocated:
the dead multiply is discarded, not copied. Payload = 74 B across **10 tier-A caves**
(`0x143da6964` … `0x143dab061`, entry `0x143da6964`), 119 B written. It reads Defensive Awareness
via the same pure leaf `0x1442d6ef0` the stock code calls six bytes later, then
`delta = floor((min(attr,120) − PIVOT) × GAIN)`, `edi = base − delta + ballFrames`, banded ±4,000,000.

**Attribute = match index `0x15` = `DATA_PARAMETER_DEFENSE_DECISION`** (a-emulated: enum registrar
`0x1409f5043` + range table `0x1442bfae0`; the +7 alignment is forced by the 0..3 / 0..7 / 0..2
ranges at 0x27 / 0x2f / 0x30). **Not** `0x17`, which is DRIBBLE — see the corrected row above.

| Def. Awareness | 40 | 50 | 60 | **70** | 80 | 90 | 99 |
|---|---|---|---|---|---|---|---|
| delta (frames) | −45 | −30 | −15 | **0** | +15 | +30 | +43 |
| budget vs stock | +45 (0.75 s more slack) | +30 | +15 | **identical to stock** | −15 | −30 | −43 (0.72 s less) |

Tunables are int32 immediates inside the payload: **PIVOT `0x143da7f83`** (70) and **GAIN_Q8
`0x143da8813`** (384 = 1.5 frames/point ×256). Retune by **regenerating**
(`emu_anticipation.py --gain <g> --pivot <p> --write-spec`) — a hand-edit makes `remove` refuse.
GAIN 1.5 is the largest value that still keeps neighbouring ratings within one gait step; the loop's
own hysteresis term is `(int)(fps*0.6+0.5)` = 36 frames, measured at the compare on every run.

Proven (a-emulated, on the real bytes): deadness; the attribute identity; the callee is a
7-instruction xmm-free pure leaf with rcx dead; the cave changes only rax/rcx/rdx/rdi/flags, uses no
stack and makes zero non-stack writes; **at attr == PIVOT every live register is bit-identical to
stock**; hostile inputs stay in band so `lea ecx,[rbx+rdi]` cannot overflow (a hazard the stock code
*does* have); and the game's own decision loop `0x143da6562..0x143da6618`, stock vs patched, across
40..99 in three chase geometries.

**NOT PROVEN:** (a) nothing has been observed in a running match; (b) the gait → km/h map is
undecoded, so the felt size of one gait step is unknown — the speed ladder behind the behaviour
table is an assumption (c-inferred), only the decision arithmetic is emulated; (c) it applies to
**both teams**, so an attacker's run is paced by his own Defensive Awareness too — a defence gate
exists (`0x1442d7090(ctx)` → `[rax+0x28d]==0`) but its meaning is unproven, so it is deliberately not
used; (d) the budget is dominated by `ebx`, which is 10000 when the ball is still, so a ±45-frame
term only bites while a pass is actually travelling; (e) Konami neutered this path deliberately and
we do not know why.

**Follow-up, not done:** the applied `marking-tight.json` sets the defensive recovery-dash threshold
at `0x143da9553` to `15.0 − 0.1×attr(0x17)` — under the corrected mapping that is **Dribbling**, not
Defensive Awareness. Retargeting it means four immediates (`0x143da9433`, `0x143da9449`,
`0x143da9462`, `0x143da947c`), one of them feeding the undecoded `0x1442e2580`. Needs its own
emulation pass before anyone touches it.

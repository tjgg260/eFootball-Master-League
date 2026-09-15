# eFootball's menu flow is data (mapped 2026-09-15)

Everything the game shows between the Konami logo and kick-off is driven by a **flow graph**
stored as JSON, one file per node, in two small CPKs. Changing an edge changes where the game
goes next; no code is involved. This is how the app boots eFootball straight into a match
(`tools/flow_patch.py`).

## Where the graph lives

| Archive | Files | Holds |
|---|---|---|
| `cpk/dt250_console_all.cpk` (2.3 MB) | 1,093 | the whole menu graph |
| `cpk/dt251_console_all.cpk` (92 KB) | 42 | the exhibition flow + a few intro/match nodes (later overrides) |

Every file is named `sha256(upper("common/script/flow/<Node>.json"))` — the exe builds the path
`cpk_dat/common/script/flow/<Node>.json`, and the hashed-name CPK layer hashes the upper-cased
path. Each file is a WESYS-zlib container (`FF 2x 83 "WESYS"`, decode with
`tools/kit_codec.decode_container`, pack with the vendored Sider `pack_wesys_container`).
1,066 of the 1,134 nodes are named by following edges; the rest are referenced by nothing.

## Node format

```json
{"events": {"proceed": {"to": "Exhibition/ExhibiSideSetting", "go": "forward", "clear": "all",
                        "fadeStart": "", "fadeEnd": "do", "bgType": "none"},
            "return":  {"to": "", "go": "backward", ...}},
 "data": {"type": "process", "bgId": "", "dialog": "", "mark": "home"}}
```

- `data.type`: `menu` (a screen — waits for the player; implemented by a `menu::Window`
  subclass registered under the node name), `process` (runs and fires `proceed` itself —
  `process::Process*` classes, e.g. `Exhibition/ExhibiFlowInit` ↔
  `process::ProcessExhibitionFlowInit`), `group` (runs `inner`, fires `end` when the inner flow
  finishes with an empty `to`).
- `events`: event name → transition. `go: forward` pushes, `backward` pops to that node.
  `clear: all` clears the screen stack. Events are fired by name: the game's
  `0x144961c50(this, "proceed")` builds a std::string and hands it to the flow manager
  (global at `0x148c23f78`) — `this` is unused, so any code can fire any event.

## The boot chain (offline build)

```
ProcRoot ─0_master→ ProcPreStartup → Intro/MenuIntroTitleLicense (menu: licence, press a button)
  → Common/CmnReset → Intro/ProcessIntroDecideMainUser → ProcessIntroSystemDataLoad
  → ProcessIntroInGameTextLoad → ProcessIntroOnlineLanguage → ProcessIntroLoginInit
  → ProcessIntroInputUserInfo → Intro/MenuIntroPesLogo (menu) → Intro/MenuIntroTitle (menu:
  "press any button"; 0_proceed) → Intro/IntroEnd → TopMenu/TopMenu
```

`ProcRoot` also has `1_DebugMenu → Test/DebugTopMenu`, which does not exist in the shipped
data (the `Def_Boot_DebugMenu` define that selects it is never set: the define map at
`0x14867ed50` is enabled but empty in this build).

## The exhibition chain

```
TopMenu/TopMenu ─exhibition→ Exhibition/ExhibiFlowRoot (group; end → TopMenu/TopMenu backward)
  inner: ExhibiFlowInit (process) → ExhibiSideSetting (menu) → ExhibiPadConnection (process)
  → ExhibiTeamSelect (menu) → ProcessExhibiMatchInit (process; proceedMatchSkip → ExhibiFlowEnd)
  → ExhibiStadiumSelect (menu) → ExhibiUniformSelect (menu) → ExhibiMatchLineup (menu)
  → Match/Setup/MatchSetup (process: proceed → Match/Enter/MatchEnterDemo1, skipdemo1 →
  MatchEnterDemo2, startMatch → Match/MatchIdle)
After the match: Match/End/MatchEnd ─03_postExhibition→ Exhibition/ExhibiFlowEnd → (group end)
```

## The team-select work area (where the chosen teams live)

Read from the running game (`tools/live_patch.py` helpers, read-only) and from the
`SetTeamID` debug command at `0x1410f2ba0`:

```
singleton = *(void**)0x1486e0de8          ; the system object
work      = *(void**)(singleton + 0x48)   ; the flow work block
teamsel   = work + 0x6c310                ; team-select work (reset by ExhibiFlowInit)
teamsel + 0x620 + i*0x5f8 : int32 packed id of side i (0 home, 1 away)
      packed = (teamId << 14) | 0x3ffd (home) / 0x3ffe (away)   e.g. Aberdeen 1219 = 0x130fffd
work + 0x6c414            : int32 side the player controls (written by the side-select functor)
```

`ProcessExhibitionFlowInit::vf25` (`0x1449626e0`) resets `teamsel` and sets defaults, then
`vf26` (`0x144962770`) fires `proceed`; `MenuTeamSelectExhibitionFunctor::vf1`
(`0x1443a8fe0`) writes −1 into both ids when the team-select screen is left. So to pre-select
teams: write the packed ids after `vf25` and route the flow around `ExhibiTeamSelect`.

## What the app changes (`tools/data/flow/autoplay.json`)

1. `ProcPreStartup.proceed → Common/CmnReset` — no licence screen.
2. `Intro/ProcessIntroInputUserInfo.proceed → Intro/IntroEnd` — no logo, no "press any button".
3. `Intro/IntroEnd.proceed → Exhibition/ExhibiFlowRoot` — boot lands in the exhibition flow.
4. `Exhibition/ExhibiFlowRoot.end → TopMenu/TopMenu (forward)` — the top menu was never on
   the stack, so the group ends by entering it, not popping to it.

`python tools/flow_patch.py install` copies the built archives into the game (originals in
`build/backups/cpk/*.orig`); `restore` puts them back. Both refuse while eFootball runs.

## Dead ends, so nobody repeats them

- **Runtime defines** (`Def_Game_Set_Home_Team_Id`, `Def_System_Team_Select_On`, …): the
  lookup (`0x143b345d0`) works, but nothing in the shipped exe ever inserts a define; the
  `SetTeamID` menu command that reads the two team defines is QA rehearsal tooling.
- **Command line**: the only Unreal switch found is `NOSPLASH`; Konami's flow ignores argv.
- **`UUEMenuDebugCommandExcuter` / `menu::DebugCommandExecuter`**: every method is a stub.
- **Live update**: `IsSuccessLiveUpdate` / `StartLiveUpdate` / `BadLiveUpdate` are Blueprint
  (reflection) names with no direct code references; no on-disk cache was found outside the
  encrypted save. Whether the exhibition uses live-update squads when its team-select screen is
  skipped is an open question for the in-game test.

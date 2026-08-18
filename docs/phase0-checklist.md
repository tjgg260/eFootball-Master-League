# Phase 0 — Manual proof of concept

**This gates everything.** No Phase 1 code gets written until the pass condition below is met.
Nothing here is automated on purpose: the point is to find out what the game and the editor
actually do before we build anything that assumes it.

Work top to bottom and fill in the **Record** sections as you go. Phase 1 reads its schema out
of what you write here, so blanks are real blockers, not paperwork.

---

## 0. Install the game

> **Status on this machine: NOT INSTALLED.**
> `steamapps\common\eFootball` exists but is empty — the manifest reads `SizeOnDisk 0`,
> `buildid 0`, `StateFlags 1026` (update required). Steam has the licence, not the files.

Install eFootball from Steam and launch it once so it finishes first-run setup and unpacks its
data files. Nothing below works until this is done.

- [ ] eFootball installed and launched once
- [ ] Played one offline match against the CPU, so the game has generated its local data

---

## 1. Back up — the data files, not the whole install

> **Disk reality on this machine:** `C:` is the only drive, with ~90 GB free. There is no `D:`,
> despite `libraryfolders.vdf` still referencing a `D:\SteamLibrary` that is not attached.
> eFootball runs 40–60 GB, so the install plus a full mirror of it will not fit. Do not try.

That is fine, because a full-folder backup is the wrong insurance for a Steam game. Steam's
**Verify integrity of game files** restores any vanilla file on demand, and the whole install is
redownloadable. What is *not* trivially recoverable is a `Player.bin` you have spent an evening
editing — so that is what gets backed up, and it is small.

Backup directory (already created): `C:\Users\tjgg2\Backups\eFootball`

**After the game is installed and you have located the files in step 3**, copy them:

```bash
Copy-Item "<path>\Player.bin","<path>\PlayerAssignment.bin","<path>\PlayerAppearance.bin" -Destination "C:\Users\tjgg2\Backups\eFootball\vanilla\" -Force
```

Take that copy **before the editor's first save**, so you always hold a known-vanilla set that
does not depend on the editor's own `.bak`.

- [ ] Backup folder exists
- [ ] Vanilla `.bin` files copied into it, before any edit
- [ ] Confirmed Steam → eFootball → Properties → Installed Files → Verify integrity is available
      as the fallback for everything else

**Record — actual backup location and file sizes:** `________________________`

---

## 2. Install EvoMod 6.0 (optional, but decide now)

Do this now if you're going to do it at all, so the install ordering is established before any
of our edits exist. Adding it later means redoing the apply.

- [ ] EvoMod installed, or consciously skipped
- [ ] If installed: noted which `cpk`/`pak` folders it replaced

**Record — EvoMod installed?** `yes / no`
**Record — files or folders it overwrote:** `________________________`

---

## 3. Point the editor at the game

You already have `eFootball-Player-Editor.exe`. Before running it: scan it, and check it opens
the game's own encrypted `Player.bin` directly — v6.0.0 claims to decrypt WESYS on the fly, so
the separate `eFootball-WESYS-Unzlib-Tool.exe` should not be needed.

- [ ] Editor opens the game's `Player.bin` without a separate unpack step
- [ ] `PlayerAssignment.bin` loaded alongside it (team membership + squad numbers)

**Record — exact path to `Player.bin`:** `________________________`
**Record — exact path to `PlayerAssignment.bin`:** `________________________`
**Record — exact path to `PlayerAppearance.bin`:** `________________________`

**Record — do these live inside a `cpk`/`pak` that EvoMod overwrites?** `yes / no`
This is the difference between "reapply after an EvoMod reinstall" and "don't care".

---

## 4. The Wirtz test

The single most informative thing you can do this evening. It proves the whole writeback path
end to end — that an edit outside the game survives into a playable match — which is the one
assumption the entire project rests on.

1. Find **Florian Wirtz** in the editor. Note his PID.
2. Note his current club and squad number.
3. Move him to **Chelsea**. Give him a squad number that is free at Chelsea — check the
   existing list first, a collision is the most likely way this fails.
4. Move one Chelsea player the other way, to Wirtz's old club, so both squads stay legal.
   Pick a squad player, not a key one, and give them a free number at the destination.
5. Save. **Verify the editor wrote a `.bak`** next to `Player.bin` — it only does this on the
   first save, so if it's missing, stop and take your own copy before going further.
6. Launch eFootball. Start an offline match against the CPU. Open the Chelsea squad list.

**Pass condition:** Wirtz is in the Chelsea squad, with his own face, and is playable.

- [ ] Wirtz appears in the Chelsea squad list
- [ ] His face is correct (not a generic model)
- [ ] He is selectable and plays

**Record — Wirtz's PID:** `________________________`
**Record — his original club and shirt number:** `________________________`
**Record — the player swapped the other way (PID, name):** `________________________`
**Record — `.bak` file written? Where?** `________________________`

### If it fails

Stop. Do not start Phase 1. Note which part failed:

- Nothing changed in game → the game is reading a different copy of the file than you edited.
  Check for a `cpk`/`pak` layer taking priority.
- Wirtz appears with a generic face → `PlayerAppearance.bin` is keyed separately and needs
  moving too. Record that; it changes Phase 4's scope.
- Game crashes or rejects the squad → likely a squad number collision or a roster limit. Go to
  step 6 and find the limit first.

---

## 5. Export the CSVs

This is what unblocks Phase 1. Export **full** CSVs, not filtered subsets.

- [ ] `players.csv` exported
- [ ] `assignments.csv` exported (from `PlayerAssignment.bin`)
- [ ] `appearances.csv` exported (from `PlayerAppearance.bin`)
- [ ] All three dropped into [`/samples`](../samples/)

**Record the column headers verbatim.** Copy the first line of each file exactly — spelling,
casing, spacing, order. Phase 1 derives its schema from these and is forbidden from guessing.

**`players.csv` header:**

```
```

**`assignments.csv` header:**

```
```

**`appearances.csv` header:**

```
```

**Record — does the editor's import accept a sparse CSV** (only changed columns present),
or does it need every column back? This decides whether Phase 4 emits diffs or full rows.

`sparse / full rows` — `________________________`

---

## 6. Find the roster limits

The engine currently assumes a legal squad is 18–35 players with at least 2 goalkeepers, and
those numbers are **placeholders** sitting in
[`SquadRules.cs`](../src/ML.Core/Validation/SquadRules.cs). Phase 4 refuses to emit a CSV that
breaks them, so a wrong limit here either blocks legal transfers or lets a corrupt squad
through.

Add players to one club until the game complains, then remove until it complains the other way.

**Record — maximum squad size before the game objects:** `________`
**Record — minimum squad size before the game objects:** `________`
**Record — minimum goalkeepers required:** `________`
**Record — valid squad number range:** `________`
**Record — what "the game complains" actually looks like** (crash / silent truncation / error
message — silent truncation is the dangerous one): `________________________`

---

## 7. Phase 3 groundwork (five minutes, do it while you're here)

- [ ] Press **F12** during a match to confirm Steam screenshots are enabled and working
- [ ] Confirm the screenshots land in
      `C:\Program Files (x86)\Steam\userdata\1253972527\760\remote\1665460\screenshots`
      (this folder does not exist yet — it is created on first capture)
- [ ] Take one screenshot of a **full-time results screen** and keep it; it becomes the
      calibration sample for the OCR region editor

**Record — actual screenshot path:** `________________________`
**Record — resolution the game runs at:** `________________________`

---

## Done?

When every box above is ticked and the blanks are filled:

- Phase 0 is passed.
- Update the phase status table in [CLAUDE.md](../CLAUDE.md).
- Phase 1 is unblocked and starts by deriving the SQLite schema from the headers you recorded
  in step 5.

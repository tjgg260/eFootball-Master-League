# Master League — Playtester Guide

Thanks for testing! This is a **companion app** that turns eFootball into a persistent Football-
Manager-style career: you run the club (squad, tactics, transfers, board, staff, youth), the app
sims the rest of the league, and you play *your* fixture — in eFootball if you want, or just by
entering the score. Your save is the app's database; eFootball is only the pitch.

It's an early build. The **management sim is solid**; the **auto-capture from eFootball is
experimental**. This guide covers the easy path first, then the advanced integration.

> **ML.App is the only supported app.** Launch it with **`Play Master League.bat`** (or
> `ML.App.exe`). The older browser UI (`ML.Web`) is **deprecated and frozen** — recording
> results there uses a shallow engine and will desync your career. Don't use it.

---

## 1. What you need

**To run the app and play a career (everyone):**
- Windows 10/11
- **.NET 8 Desktop Runtime** — https://dotnet.microsoft.com/download/dotnet/8.0 (pick
  *".NET Desktop Runtime 8.x → Windows x64"*). If you'll build from source instead, install the
  **.NET 8 SDK**.
- The app itself (either a published build, or the source repo — see step 2).

**Only for the full eFootball integration (optional, advanced):**
- eFootball on Steam (PC)
- Python 3.11+ with `Pillow` (the club crests are BC7 textures and nothing else decodes them),
  `numpy` and `pycryptodome`
- A Rust toolchain, to build and install the stats host (for automatic result capture)
- These are **not needed** to play a career by entering results yourself.

---

## 2. Get it running

**Option A — published build (easiest):**
1. Unzip the release folder anywhere (e.g. `Documents\MasterLeague`).
2. Double-click **`ML.App.exe`**.
3. If Windows SmartScreen warns "unknown publisher", click *More info → Run anyway* (it's an
   unsigned playtest build).

**Option B — from source:**
1. Install the .NET 8 **SDK**.
2. In the repo folder, run:
   ```bash
   dotnet run --project src/ML.App
   ```

Either way, the first thing you get is **New Career**, which builds a world out of your own
eFootball install before it offers you a club — about a minute, once. Then the app opens on the
**Office** (dashboard) screen. Your world and your save both live in `build/game_world.db` — back
that file up to keep a save.

---

## 3. Playing a season (the core loop)

1. **Office** shows your next fixture. Set your lineup and tactics first (see below).
2. Hit **▶ Play Match**.
   - *Without eFootball:* just type the **Result** (e.g. `2 – 1`), optionally add goalscorers,
     assists, cards and ratings with the pickers, then **Record**.
   - *With eFootball:* it compiles your squad into the game and boots it — play the match, then
     come back and enter/capture the result (see §5).
3. **Record** saves your result, sims every other match in the round, updates the table, and
   loads your next fixture.
4. Repeat through the season. At season end the app handles promotion/relegation, awards,
   retirements, youth intake, the board's verdict, and rolls you into the next campaign.

**Screens to explore** (left sidebar): Squad, Game Plan (tactics), Transfer Market, Staff,
Board, Finances, Calendar, News, Stats, Table, Settings.

---

## 4. Tactics & squad (please stress-test this)

- **Squad / Game Plan**: click a player to **select** him — his position and playstyle editors
  appear. Clicking only selects; it never moves anyone.
- **To swap two players**: select one, press **⇄ Swap**, then click his partner (a starter or a
  sub). This is deliberate so you can't swap by accident while editing.
- Set formation, team instructions, set-piece takers, captain. **Suggest XI** auto-picks.

---

## 5. eFootball integration (optional, experimental — expect rough edges)

If you play the match *in eFootball* and want the result captured instead of typing it:

1. Install the stats host into the game once: close eFootball, run
   `bash tools/vendor/efootball-re/memprobe/deploy_host.sh`, and put empty `statshook.on` and
   `attrhook.on` files in the game folder and in `eFootball\Binaries\Win64`
   (`tools/vendor/efootball-re/VENDOR.md` has the details).
   **Settings → Match data** shows whether exports are arriving.
2. **Play Match** compiles the squads and boots eFootball. Play the fixture.
3. After full time, choose to leave the match and go back to the main menu. About 15 seconds later
   the host writes the match, and the Dashboard opens the result pre-filled: score, scorers,
   every player's rating. Check it, add assists and cards, and **Record**. Recording also stores
   the team stats and each player's counters.
   - **📥 Load match export** loads the newest export by hand if nothing pre-filled.

**Known issues here (help us test these):**
- The host has no goal minutes, assists or cards. Pick those by hand.
- Goals come from a counter efootball-re labels as inferred, so glance at the score before you
  record.
- An export only pre-fills when its players' ids match the fixture's two squads. A match played
  on a squad file the app did not compile is refused, and the reason is shown.

**For a smooth playtest, we recommend: play in eFootball, then just type the score + a few
ratings and hit Record.** The management depth is the thing to test.

---

## 6. What to test & how to report

Please poke at: season progression, transfers & negotiations, the board/objectives, staff
hiring & delegation, youth intake, tactics UX, and anything that feels off or crashes.

When reporting, include:
- What you did (which screen, which button)
- What you expected vs what happened
- A screenshot if you can
- Your `build/master.db` if it's a save-specific bug (zip it)

Back up your career before long sessions so a bad state doesn't cost you one — either copy
`build/master.db`, or (from source) export just the career as a small standalone save file:

```bash
python tools/career_snapshot.py save        # -> careers/<club>_<date>.db
python tools/career_snapshot.py list        # show saves
python tools/career_snapshot.py restore careers/<file>.db
```

---

## 7. Honest status

- ✅ **Solid**: the management sim — squads, tactics, league/cup sim, transfers, board, staff,
  youth, finances, news, season rollover.
- ⚠️ **Experimental**: eFootball result capture through efootball-re's stats host (score,
  scorers, ratings, stats). Needs the host installed into the game. Type results if in doubt.
- 🧪 **Dev-only for now**: the game-file writeback (compiling squads into eFootball, custom
  team names) needs Python + your own eFootball extraction and isn't part of the basic playtest.

Thanks for helping shape it!

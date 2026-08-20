# Match video capture + analysis

eFootball never stores scorers, assists or cards — it only shows them. This pipeline records
every match and mines the recording afterwards, so you confirm events instead of typing them.

## One-time setup

1. **Install OBS Studio** (free, obsproject.com). In OBS: Tools → WebSocket Server Settings →
   enable the server. Port 4455 is the default; set a password or leave auth off.
2. **Install ffmpeg**: `winget install ffmpeg` (or set the full exe path in Settings).
3. In OBS, add a Game Capture source for eFootball. 720p30 output is plenty for OCR and keeps
   files small.
4. In the app: Settings → **Match video** — tick "Record every match", set the WebSocket URL/
   password and your OBS recordings folder. Save.

## Per match

- **Play Match** compiles + boots the game, then tells OBS to start recording.
- Play. Afterwards, back in the app, hit **🎞 Analyse recording** on the Dashboard: it stops
  OBS, samples the newest recording (~1 frame per 2s), OCRs the scoreboard strip, and turns
  score changes into goals with the clock minute. Around each goal it OCRs the scorer banner
  and fuzzy-matches the text against the 22 players in the two XIs.
- The score and goal pickers arrive prefilled with suggestions. Check, correct, **Record**.

## Calibration (once, after your first recording)

The scoreboard regions default to generic 16:9 fractions and usually need a one-time nudge to
your HUD. From a recording, dump a frame and read the region positions off it:

```bash
python - <<'EOF'
# frame at 5 minutes in — open the PNG, note the scoreboard's fractional position
import subprocess
subprocess.run(["ffmpeg", "-ss", "300", "-i", "<your recording>", "-frames:v", "1", "-y", "build/calib_frame.png"])
EOF
```

Then edit `build/video_regions.json` (created on first analyse) — each region is
`[x, y, w, h]` as fractions of the frame — and set `"Calibrated": true`. The regions to place:
`HomeScore`, `AwayScore`, `Clock` (the top scoreboard strip) and `GoalBanner` (the lower-third
that names the scorer). Drop the frame PNG into a session with Claude and it can be done for you.

## Full-time team stats

Capture the STATS screen (F12 screenshot or let the recording run over it). The whole-screen
OCR parser reads "62% Possession 38%"-style rows into `match_team_stats` — possession, shots,
shots on target, passes, pass accuracy and the rest of the sheet, per fixture per side.

## Honest limits

- Per-player pass/tackle/duel numbers are **not extractable** — the game never renders them.
- Banner OCR quality depends on your resolution + HUD scale; the 22-candidate fuzzy match
  absorbs most of the noise, and anything unreadable is left for you to pick manually.
- Recordings are only mined, never uploaded anywhere; delete them after analysis if disk
  space matters.

#!/usr/bin/env bash
# One-time Linux setup: the Python venv the app's tools run in, and a first build of the app.
# eFootball itself stays an ordinary Steam game run by Proton; nothing here touches it.
#
#   ./setup-linux.sh            # then ./play-master-league.sh
#
# Needs: python3 (3.11+) with venv, and the .NET 8 SDK or newer (dotnet).
set -euo pipefail
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "python3 not found — install it from your distro"; exit 1; }
command -v dotnet  >/dev/null || { echo "dotnet not found — install the .NET 8 SDK (or newer)"; exit 1; }

if [ ! -x .venv/bin/python ]; then
  echo "== creating .venv"
  python3 -m venv .venv
fi
echo "== installing the tools' Python packages"
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt

echo "== building the app"
dotnet build src/ML.App/ML.App.csproj -v q -nologo

echo "== fonts"
# The UI draws its icons as emoji (Windows has Segoe UI Emoji built in). Without an emoji font
# every one of them is an empty box.
if command -v fc-list >/dev/null && fc-list : family | grep -qi 'emoji'; then
  echo "emoji font: $(fc-list : family | grep -i emoji | head -1)"
else
  echo "WARNING: no emoji font — the app's icons will show as boxes. Install one:"
  echo "  Arch: sudo pacman -S noto-fonts-emoji   Debian/Ubuntu: sudo apt install fonts-noto-color-emoji"
  echo "  Fedora: sudo dnf install google-noto-color-emoji-fonts"
fi

echo "== where eFootball is"
.venv/bin/python tools/steam_paths.py

cat <<'MSG'

Done. Start the app with ./play-master-league.sh
The app finds .venv/ by itself; set ML_PYTHON to use another interpreter, or ML_EFOOTBALL_DIR
if eFootball lives somewhere Steam's library list does not say.
MSG

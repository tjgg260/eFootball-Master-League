#!/usr/bin/env bash
# Linux counterpart of "Play Master League.bat": build ML.App on first run, then launch it from
# the repo root so it can find tools/play_match.py and build/ by walking up from its own folder.
set -euo pipefail
cd "$(dirname "$0")"
APP=src/ML.App/bin/Debug/net8.0/ML.App
if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up (./setup-linux.sh)…"
  ./setup-linux.sh
elif [ ! -f "$APP.dll" ]; then
  echo "Building the app for the first time…"
  dotnet build src/ML.App/ML.App.csproj -v q -nologo
fi
# The apphost is only made executable by the build on some SDKs; dotnet runs the dll either way.
if [ -x "$APP" ]; then exec "$APP" "$@"; else exec dotnet "$APP.dll" "$@"; fi

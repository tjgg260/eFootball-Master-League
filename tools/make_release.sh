#!/usr/bin/env bash
# Build the "download and play" package: the published app, the world database, and the
# runtime folders the app resolves by walking up to a root that holds tools/play_match.py.
#
#   ML_WORLD_ROOT=<checkout with build/master.db and assets packs> bash tools/make_release.sh <version> [out-dir]
#
# Layout of the package (a zip of the MasterLeague/ folder):
#   app/                published self-contained win-x64 ML.App
#   build/master.db     the world (copied from the repo's build/, WAL checkpointed first)
#   tools/ assets/ data/ docs/   tracked files, plus the club-logo and flag packs the DB references
#   README.md PLAYTESTING.md LICENSE  "Play Master League.bat" (launches app\ML.App.exe)
# Player faces (facepack/, build/game_faces/) are NOT shipped: multi-GB, and game_faces is Konami's
# art. A player with eFootball installed runs tools/game_faces.py; otherwise generated avatars.
set -euo pipefail
VER="${1:?version, e.g. v0.1.0}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${2:-$REPO/dist}"
PKG="$OUT/MasterLeague"
# The checkout that holds build/master.db and the downloaded asset packs (a worktree may not).
WORLD="${ML_WORLD_ROOT:-$REPO}"
DB="${ML_DB:-$WORLD/build/master.db}"

rm -rf "$PKG"; mkdir -p "$PKG"
echo "== publish app"
dotnet publish "$REPO/src/ML.App/ML.App.csproj" -c Release -r win-x64 --self-contained true \
  -p:DebugType=none -o "$PKG/app" -v q -nologo
echo "== tracked runtime files"
git -C "$REPO" archive HEAD tools assets data docs README.md PLAYTESTING.md LICENSE | tar -x -C "$PKG"
rm -rf "$PKG/tools/ActionsSmoke" "$PKG/tools/TacticsSmoke"
echo "== untracked asset packs the database references"
for d in assets/dvx_logos assets/dvx_flags assets/gen_badges; do
  [ -d "$WORLD/$d" ] && mkdir -p "$PKG/$d" && cp -r "$WORLD/$d/." "$PKG/$d/" || echo "  (no $d under $WORLD)"
done
echo "== database"
mkdir -p "$PKG/build"
python - "$DB" "$PKG/build/master.db" <<'PY'
import sqlite3, shutil, sys
src, dst = sys.argv[1], sys.argv[2]
c = sqlite3.connect(src); c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); c.close()
shutil.copyfile(src, dst)
PY
cat > "$PKG/Play Master League.bat" <<'BAT'
@echo off
rem Launch Master League. The app finds build\master.db and tools\ by walking up from app\.
cd /d "%~dp0"
start "" "%~dp0app\ML.App.exe"
BAT
echo "== zip"
python - "$OUT" "$VER" <<'PY'
import os, sys, zipfile
out, ver = sys.argv[1], sys.argv[2]
root = os.path.join(out, "MasterLeague"); zpath = os.path.join(out, f"MasterLeague-{ver}-win-x64.zip")
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6) as z:
    for dp, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dp, f); z.write(p, os.path.relpath(p, out))
print(zpath, f"{os.path.getsize(zpath)/2**30:.2f} GiB")
PY

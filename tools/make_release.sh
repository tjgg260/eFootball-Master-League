#!/usr/bin/env bash
# Build the "download and play" package: the published app, an embedded Python, the world
# database with the owner's career stripped out of it, and the runtime folders the app resolves
# by walking up to a root that holds tools/play_match.py.
#
#   ML_WORLD_ROOT=<checkout with build/master.db and assets packs> bash tools/make_release.sh <version> [out-dir]
#
# Layout of the package (a zip of the MasterLeague/ folder):
#   app/                    published self-contained win-x64 ML.App
#   python/                 embedded CPython 3.13 + numpy — New Career runs the seeder through
#                           this, so a downloader installs nothing (python.org/pythonhosted
#                           downloads, every one pinned by sha256, cached in $ML_CACHE)
#   build/master.db         the world — copied through sqlite3's backup API, then sanitised:
#                           no career, no owner settings, no C:\Users paths
#   build/catalog.json      the world index New Career reads to offer countries and clubs
#   src/ML.Data/schema.sql  the seeder applies this to the database it seeds
#   tools/ assets/ data/ docs/   tracked files, plus the club-logo and flag packs the DB references
#   README.md PLAYTESTING.md LICENSE  "Play Master League.bat" (launches app\ML.App.exe)
# Player faces (facepack/) are NOT shipped: multi-GB. The app falls back to generated avatars.
set -euo pipefail
VER="${1:?version, e.g. v0.1.0}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${2:-$REPO/dist}"
PKG="$OUT/MasterLeague"
# The checkout that holds build/master.db and the downloaded asset packs (a worktree may not).
WORLD="${ML_WORLD_ROOT:-$REPO}"
DB="${ML_DB:-$WORLD/build/master.db}"
CACHE="${ML_CACHE:-$OUT/.dlcache}"
PYBIN="$PKG/python/python.exe"
# The one python step that runs BEFORE the embedded interpreter exists (unpacking it) needs a
# host python. On a machine where bare `python` is the Microsoft Store stub, that step would
# silently do nothing and the failure would surface two lines later with the wrong name on it.
PYHOST="${ML_PYTHON:-python}"
# Club names are full of Đ, ş and ø. Without this every python step here prints through the
# console's cp1252 codec and dies mid-sentence on the first one.
export PYTHONIOENCODING=utf-8

# WHAT THE BUG WAS. tools/ ships from `git archive HEAD` — the last COMMIT, not the working
# tree — while app/ ships from a `dotnet publish` of the working tree. Run with edits pending,
# the package silently carried the OLD seeder (still reading the owner's private RFS.DB) and no
# sanitiser at all, and a downloader's first New Career died on an import of a file not in the
# zip. Refuse at the top, by name, instead of failing two minutes and two gigabytes in.
dirty="$(git -C "$REPO" status --porcelain -- tools assets data docs src/ML.Data/schema.sql README.md PLAYTESTING.md LICENSE)"
if [ -n "$dirty" ]; then
  echo "refusing: uncommitted changes under the packaged paths — the package is built from HEAD, so commit these first:"
  echo "$dirty"
  exit 1
fi
command -v "$PYHOST" >/dev/null 2>&1 || { echo "no usable host python to unpack the embedded interpreter — set ML_PYTHON"; exit 1; }

rm -rf "$PKG"; mkdir -p "$PKG" "$CACHE"
# The marker sanitize_release_db.py insists on: it proves the target is a package this script is
# building, never a checkout or somebody's extracted download. The zip step strips it again.
: > "$PKG/.release-package"
echo "== publish app"
dotnet publish "$REPO/src/ML.App/ML.App.csproj" -c Release -r win-x64 --self-contained true \
  -p:DebugType=none -o "$PKG/app" -v q -nologo
echo "== tracked runtime files"
# schema.sql travels with the tools: career_seed.py applies <root>/src/ML.Data/schema.sql to the
# database it seeds, and without it a fresh career died on the first CREATE TABLE it needed.
git -C "$REPO" archive HEAD tools assets data docs src/ML.Data/schema.sql \
  README.md PLAYTESTING.md LICENSE | tar -x -C "$PKG"
rm -rf "$PKG/tools/ActionsSmoke" "$PKG/tools/TacticsSmoke"
echo "== untracked asset packs the database references"
for d in assets/dvx_logos assets/dvx_flags assets/gen_badges; do
  [ -d "$WORLD/$d" ] && mkdir -p "$PKG/$d" && cp -r "$WORLD/$d/." "$PKG/$d/" || echo "  (no $d under $WORLD)"
done

echo "== OCR model (Apache-2.0) and its licence"
# Every screenshot/video OCR button in the shipped app failed "OCR model not found": the model is
# gitignored, so git archive never carried it. It is Apache-2.0 (tesseract-ocr/tessdata_best),
# which we may ship, with its licence text beside it.
TESS="$WORLD/tools/tessdata/eng.traineddata"
[ -f "$TESS" ] || { echo "missing $TESS — the OCR model must be present under ML_WORLD_ROOT"; exit 1; }
mkdir -p "$PKG/tools/tessdata"
cp "$TESS" "$PKG/tools/tessdata/"
cp "$PKG/tools/data/licenses/tessdata-NOTICE.txt" "$PKG/tools/data/licenses/tessdata-LICENSE-Apache-2.0.txt" "$PKG/tools/tessdata/"
echo "  eng.traineddata $(stat -c %s "$TESS") bytes + NOTICE + Apache-2.0 text"

echo "== VC++ runtime for the OCR engine"
# tesseract50.dll and leptonica import MSVCP140/VCRUNTIME140(_1); nothing in the self-contained
# .NET publish provides them, so a Windows that never had the redistributable failed OCR with a
# load error. Microsoft permits app-local deployment of these three from the VS Redist folder.
VCDIR="${ML_VCREDIST_DIR:-}"
if [ -z "$VCDIR" ]; then
  VCDIR="$(ls -d "/c/Program Files/Microsoft Visual Studio/"*/*/VC/Redist/MSVC/*/x64/Microsoft.VC14*.CRT 2>/dev/null | sort | tail -1 || true)"
fi
if [ -n "$VCDIR" ] && [ -f "$VCDIR/msvcp140.dll" ]; then
  cp "$VCDIR/msvcp140.dll" "$VCDIR/vcruntime140.dll" "$VCDIR/vcruntime140_1.dll" "$PKG/app/"
  echo "  msvcp140 + vcruntime140 + vcruntime140_1 from $VCDIR"
else
  echo "  NOTE: no VS Redist folder found (set ML_VCREDIST_DIR) — OCR will need the VC++ 2015-2022 x64 runtime installed"
fi

echo "== embedded python (so a downloader installs nothing)"
# Pinned by sha256 and verified before use — a release must not build on whatever the CDN served
# today. Downloads come only from python.org and files.pythonhosted.org.
PY_EMBED_URL="https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-amd64.zip"
PY_EMBED_SHA="d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf"
PY_SBOM_URL="https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-amd64.zip.spdx.json"
PY_SBOM_SHA="ba428f93acb06764f0005246f8ca48bb1c04feef64ce7db0b177fb2fd371c423"
NUMPY_URL="https://files.pythonhosted.org/packages/f3/ec/100f2b1794ede74a9b3d7ec6b9736927f56713414c1dfe19ab6c383494bf/numpy-2.5.3-cp313-cp313-win_amd64.whl"
NUMPY_SHA="71cad2b2a7451ab79d8f5e71b453485b6775963d5cf794179144a7463fe6e8ec"

fetch() {                       # fetch <url> <sha256> -> prints the cached file's path
  local url="$1" want="$2" dst got
  dst="$CACHE/$(basename "$url")"
  if [ -f "$dst" ]; then
    got="$(sha256sum "$dst" | cut -d' ' -f1)"
    if [ "$got" = "$want" ]; then echo "$dst"; return 0; fi
    echo "  cached $(basename "$dst") has the wrong hash — refetching" >&2
    rm -f "$dst"
  fi
  echo "  fetching $url" >&2
  curl -fsSL --retry 3 -o "$dst" "$url" >&2
  got="$(sha256sum "$dst" | cut -d' ' -f1)"
  if [ "$got" != "$want" ]; then
    rm -f "$dst"
    echo "  sha256 MISMATCH for $url: got $got, expected $want" >&2
    return 1
  fi
  echo "$dst"
}
PY_EMBED_ZIP="$(fetch "$PY_EMBED_URL" "$PY_EMBED_SHA")"
PY_SBOM_JSON="$(fetch "$PY_SBOM_URL" "$PY_SBOM_SHA")"
NUMPY_WHEEL="$(fetch "$NUMPY_URL" "$NUMPY_SHA")"

"$PYHOST" - "$PY_EMBED_ZIP" "$NUMPY_WHEEL" "$PY_SBOM_JSON" "$PKG/python" <<'PY'
import os, shutil, sys, zipfile
embed, wheel, sbom, dest = sys.argv[1:5]
shutil.rmtree(dest, ignore_errors=True); os.makedirs(dest)
with zipfile.ZipFile(embed) as z:
    z.extractall(dest)                       # keeps python/LICENSE.txt — we must ship it
site = os.path.join(dest, "Lib", "site-packages"); os.makedirs(site, exist_ok=True)
with zipfile.ZipFile(wheel) as z:
    z.extractall(site)
# numpy's test suites are megabytes nothing in the app ever runs. *.dist-info is off limits:
# it carries the licence files the wheel is distributed under.
stripped = 0
for root, dirs, _ in os.walk(os.path.join(site, "numpy"), topdown=True):
    if ".dist-info" in root:
        dirs[:] = []; continue
    for d in list(dirs):
        if d == "tests":
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)
            dirs.remove(d); stripped += 1
shutil.copyfile(sbom, os.path.join(dest, os.path.basename(sbom)))
print(f"  unpacked python + numpy ({stripped} test dirs stripped), SBOM alongside")
PY

# The stock embed ._pth does NOT put the script's own directory on sys.path, and every tools/
# script imports its siblings — ..\tools is what makes that work from python/. Written with a
# QUOTED heredoc: an unquoted one turned '..\tools' into a tab and the imports all failed.
cat > "$PKG/python/python313._pth" <<'PTH'
python313.zip
.
Lib\site-packages
..\tools

#import site
PTH
"$PYBIN" -c "import sqlite3, ctypes, zlib, numpy; print('embedded python ok', numpy.__version__)"

echo "== database"
mkdir -p "$PKG/build"
"$PYBIN" - "$DB" "$PKG/build/master.db" <<'PY'
import os, pathlib, sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
for stale in (dst, dst + "-wal", dst + "-shm"):
    if os.path.exists(stale):
        os.remove(stale)
# This step used to checkpoint the source over a WRITE connection and then copy the file out from
# under whatever else had it open — on the owner's live save. The backup API reads a consistent
# snapshot through a read-only connection instead, and never writes a byte of the source.
# as_uri() rather than an f-string: the world lives under "eFootball Master League" and the
# spaces have to be percent-encoded for SQLite to see the path at all.
uri = pathlib.Path(src).resolve().as_uri() + "?mode=ro"
s = d = None
try:
    s = sqlite3.connect(uri, uri=True)
    d = sqlite3.connect(dst)
    s.backup(d)
except sqlite3.Error as e:
    sys.exit(f"cannot snapshot {src} ({e}) — close ML.App and any tool holding it, "
             "or point ML_DB at a backup")
finally:
    for c in (d, s):
        if c is not None:
            c.close()
print(f"  {dst} {os.path.getsize(dst)/2**30:.2f} GiB")
PY

echo "== world index"
# New Career offers countries and clubs straight out of catalog.json. Without it the picker is
# empty and nothing can be seeded, so a missing catalog fails the release rather than shipping.
[ -f "$WORLD/build/catalog.json" ] || {
  echo "  missing $WORLD/build/catalog.json — run: python tools/build_catalog.py" >&2; exit 1; }
cp "$WORLD/build/catalog.json" "$PKG/build/catalog.json"

echo "== sanitise the shipped world"
ML_WORLD_ROOT="$WORLD" ML_DB="$DB" \
  "$PYBIN" "$PKG/tools/sanitize_release_db.py" "$PKG/build/master.db" "$PKG"
rm -f "$PKG/build/master.db-wal" "$PKG/build/master.db-shm"

echo "== gate: every club in the picker is a club the package can open"
"$PYBIN" - "$PKG" <<'PY'
import json, os, sqlite3, sys
pkg = sys.argv[1]
cat = json.load(open(os.path.join(pkg, "build", "catalog.json"), encoding="utf-8"))
con = sqlite3.connect(os.path.join(pkg, "build", "master.db"))
teams = {r[0] for r in con.execute("SELECT id FROM teams")}
leagues = {r[0] for r in con.execute("SELECT id FROM leagues")}
squads = {r[0] for r in con.execute("SELECT DISTINCT team_id FROM squad_members")}
con.close()
bad, n_t, n_l, n_logo = [], 0, 0, 0
countries_of = {}          # team id -> the countries whose leagues list it
for co in cat["countries"]:
    for lg in co["leagues"]:
        n_l += 1
        lid = lg.get("league_id", lg.get("comp_id"))
        if lid not in leagues:
            bad.append(f"{lg.get('name')}: league {lid} is not in the database")
        for t in lg["teams"]:
            n_t += 1
            tid = t.get("team_id", t.get("rfs_id"))
            countries_of.setdefault(tid, {}).setdefault(co["name"], t.get("name"))
            if tid not in teams:
                bad.append(f"{t.get('name')}: team {tid} is not in the database")
            elif tid not in squads:
                bad.append(f"{t.get('name')}: team {tid} has no players")
            logo = t.get("logo")
            if logo:
                n_logo += 1
                if not os.path.exists(os.path.join(pkg, logo.replace("/", os.sep))):
                    bad.append(f"{t.get('name')}: crest {logo} is not in the package")
if bad:
    print(f"  {len(bad)} clubs a downloader could pick and not get:")
    for b in bad[:25]:
        print("   ", b)
    sys.exit(1)
print(f"  {n_t} clubs across {n_l} leagues, {n_logo} crests — all present")
# One id, two countries: the picker offers the same squad under two flags — pick Newcastle Utd
# in Australia's A-League and you get Newcastle United of England. A catalog-build fault
# (build_catalog / fix_catalog_dupes), warned here so the release notes can say so.
cross = {tid: cs for tid, cs in countries_of.items() if len(cs) > 1}
if cross:
    print(f"  WARNING: {len(cross)} club id(s) are listed under more than one country:")
    for tid, cs in sorted(cross.items())[:12]:
        print("   ", tid, " | ".join(f"{c}: {n}" for c, n in cs.items()))
PY

echo "== gate: a first career, built by the packaged python from the packaged files"
SMOKE="$OUT/.seedsmoke"
rm -rf "$SMOKE"; mkdir -p "$SMOKE/home"
cp "$PKG/build/master.db" "$SMOKE/master.db"
# HOME and USERPROFILE point at an empty directory: the downloader has no RFS install and no
# OneDrive, and the seed has to work without them. Everything it reads must be in the package.
if ( cd "$PKG" && HOME="$SMOKE/home" USERPROFILE="$SMOKE/home" PYTHONIOENCODING=utf-8 \
       ML_CONFIRM_RESEED=1 "$PYBIN" "$PKG/tools/career_seed.py" --db "$SMOKE/master.db" \
       --comp-id 13 --rfs-id 3000005 --team "Chelsea FC" ); then
  echo "  a Chelsea career seeded cleanly with nothing installed"
else
  echo "  career_seed.py failed against the package — a downloader would land nowhere" >&2
  rm -rf "$SMOKE"; exit 1
fi
rm -rf "$SMOKE" "$PKG/careers"
find "$PKG" -type d -name __pycache__ -prune -exec rm -rf {} +

cat > "$PKG/Play Master League.bat" <<'BAT'
@echo off
rem Launch Master League. The app finds build\master.db and tools\ by walking up from app\.
cd /d "%~dp0"
start "" "%~dp0app\ML.App.exe"
BAT
echo "== zip"
rm -f "$PKG/build/master.db-wal" "$PKG/build/master.db-shm"
"$PYBIN" - "$OUT" "$VER" <<'PY'
import os, sys, zipfile
out, ver = sys.argv[1], sys.argv[2]
root = os.path.join(out, "MasterLeague"); zpath = os.path.join(out, f"MasterLeague-{ver}-win-x64.zip")
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6) as z:
    for dp, _, fs in os.walk(root):
        for f in fs:
            if f == ".release-package":     # build-time marker; an extracted download must NOT carry it
                continue
            p = os.path.join(dp, f); z.write(p, os.path.relpath(p, out))
print(zpath, f"{os.path.getsize(zpath)/2**30:.2f} GiB")
PY

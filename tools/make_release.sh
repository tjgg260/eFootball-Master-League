#!/usr/bin/env bash
# Build the "download and play" package: the published app, an embedded Python, and the runtime
# folders the app resolves by walking up to a root that holds tools/play_match.py.
#
#   ML_WORLD_ROOT=<checkout with the assets packs> bash tools/make_release.sh <version> [out-dir]
#
# NO WORLD IS SHIPPED. The app's world is build/game_world.db, which the first run builds from the
# player's own eFootball — CareerLoader.FindMasterDb() returns WorldFiles.Database and nothing
# resolves to master.db any more (ruling 2026-09-13). The package carried a 2.05 GiB master.db and
# a 138 MB club-logo pack reachable only through its rows, so ~95% of the download was a world the
# app could not open. Set ML_SHIP_WORLD=1 to put them back — the copy, the sanitiser and both
# world gates are still here, just off — for when there is a curated world worth shipping again.
#
# Layout of the package (a zip of the MasterLeague/ folder):
#   app/                    published self-contained win-x64 ML.App
#   python/                 embedded CPython 3.13 + numpy + Pillow (the crest decoder) — New
#                           Career runs the seeder through
#                           this, so a downloader installs nothing (python.org/pythonhosted
#                           downloads, every one pinned by sha256, cached in $ML_CACHE)
#   src/ML.Data/schema.sql  the seeder applies this to the database it seeds
#   tools/ assets/ data/ docs/   tracked files, plus the nationality flag pack the Squad screen
#                           reads through assets/flag_map.json
#   tools/vendor/efootball-re/bin/dxgi.dll   the built match-stats host, so a downloader needs
#                           no Rust; its source ships beside it (GPL-3.0). Gated below.
#   README.md PLAYTESTING.md LICENSE  "Play Master League.bat" (launches app\ML.App.exe)
# Player faces (facepack/, build/game_faces/) are NOT shipped: multi-GB, and game_faces is Konami's
# art. A player with eFootball installed runs tools/game_faces.py; otherwise generated avatars.
set -euo pipefail
VER="${1:?version, e.g. v0.1.0}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${2:-$REPO/dist}"
PKG="$OUT/MasterLeague"
# The checkout that holds the downloaded asset packs, and master.db when one is shipped (a
# worktree may not).
WORLD="${ML_WORLD_ROOT:-$REPO}"
DB="${ML_DB:-$WORLD/build/master.db}"
# Off by default: see NO WORLD IS SHIPPED at the top.
SHIP_WORLD="${ML_SHIP_WORLD:-0}"
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
echo "== untracked asset packs"
# dvx_flags is the one the MVP path reads: SquadViewModel resolves a player's nationality through
# assets/flag_map.json into it. dvx_logos (138 MB) and gen_badges are club art reachable ONLY
# through master.db's logo_path — a game-built world wears build/game_emblems/, decoded from the
# player's own paks — so they ship only when the world does.
packs="assets/dvx_flags"
[ "$SHIP_WORLD" = "1" ] && packs="$packs assets/dvx_logos assets/gen_badges"
for d in $packs; do
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
# Pillow decodes the club crests. WITHOUT IT THE DOWNLOAD HAS NO CRESTS AT ALL: the game keeps
# every emblem as a BC7 Texture2D, tools/game_emblems.py decodes BC7 through Pillow's "bcn" raw
# decoder and exits at its first line when Pillow is missing, so first_run.py reports "Crests
# could not be read this time" and every club falls back to its two initials. game_faces.py's
# numpy path covers DXT5 only — the variant card art needs Pillow too.
PILLOW_URL="https://files.pythonhosted.org/packages/a6/9b/7a58e61d62be561da3a356fe2384d4059a6345fc130e23ef1c36a5b81d24/pillow-12.3.0-cp313-cp313-win_amd64.whl"
PILLOW_SHA="1cca606cd25738df4ed873d5ad46bbdb3d83b5cbca291f6b4ff13a4df6b0bbe8"

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
PILLOW_WHEEL="$(fetch "$PILLOW_URL" "$PILLOW_SHA")"

"$PYHOST" - "$PY_EMBED_ZIP" "$NUMPY_WHEEL" "$PILLOW_WHEEL" "$PY_SBOM_JSON" "$PKG/python" <<'PY'
import os, shutil, sys, zipfile
embed, numpy_whl, pillow_whl, sbom, dest = sys.argv[1:6]
shutil.rmtree(dest, ignore_errors=True); os.makedirs(dest)
with zipfile.ZipFile(embed) as z:
    z.extractall(dest)                       # keeps python/LICENSE.txt — we must ship it
site = os.path.join(dest, "Lib", "site-packages"); os.makedirs(site, exist_ok=True)
for wheel in (numpy_whl, pillow_whl):
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
print(f"  unpacked python + numpy + Pillow ({stripped} test dirs stripped), SBOM alongside")
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
# The BC7 check is not decoration: Pillow without its "bcn" raw decoder ships a package that
# imports cleanly and still leaves the download with no club crests.
"$PYBIN" -c "import sqlite3, ctypes, zlib, numpy; from PIL import Image; \
Image.frombytes('RGBA', (4, 4), b'\x00' * 16, 'bcn', 7); \
print('embedded python ok - numpy', numpy.__version__, 'Pillow', Image.__version__, 'BC7 ok')"

if [ "$SHIP_WORLD" = "1" ]; then
# Everything from here to the matching fi ships a curated world. Left whole and flush-left (the
# heredoc terminators have to sit at column 0) so turning it back on is one variable.
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
else
echo "== no world shipped — the first run builds one from the player's eFootball"
echo "  (ML_SHIP_WORLD=1 restores the database, the logo packs and the two gates above)"
fi
find "$PKG" -type d -name __pycache__ -prune -exec rm -rf {} +

echo "== gate: the match-stats host is in the package"
# The one binary a downloader cannot build without installing Rust. It went missing for three
# releases because .gitignore has a bare `bin/` rule that matches
# tools/vendor/efootball-re/bin/ at any depth, so `git archive` silently dropped it and
# install_stats_host.py refused with "no dxgi.dll to install" — while its own comment said the
# release ships one. Fail the build instead, and check the SOURCE travels with it: GPL-3.0
# means the corresponding source, and a stale DLL beside fresh .rs files is its own bug.
HOSTDLL="$PKG/tools/vendor/efootball-re/bin/dxgi.dll"
if [ ! -f "$HOSTDLL" ]; then
  echo "  MISSING $HOSTDLL — the download could not capture a result." >&2
  echo "  Build it (cargo build --release in tools/vendor/efootball-re/memprobe/host), copy it" >&2
  echo "  to tools/vendor/efootball-re/bin/dxgi.dll and commit it." >&2
  exit 1
fi
for f in Cargo.toml Cargo.lock src/lib.rs src/statshook.rs src/statsexport.rs; do
  [ -f "$PKG/tools/vendor/efootball-re/memprobe/host/$f" ] || {
    echo "  the host DLL ships but its source does not: missing $f" >&2; exit 1; }
done
echo "  dxgi.dll $(stat -c%s "$HOSTDLL") bytes, sha256 $(sha256sum "$HOSTDLL" | cut -c1-16)…, source alongside"

echo "== gate: the packaged python can drive the first run"
# The bug this replaces the old seed gate with. tools/ ships from `git archive HEAD`, so a module
# that only ever existed in someone's working tree is in no commit and in no zip, and the failure
# lands on a downloader's first New Career. Import everything first_run.py reaches, through the
# PACKAGED interpreter, from the package, with HOME pointing at an empty directory — no eFootball,
# no OneDrive, nothing of the owner's on any path.
IMPORTS="$OUT/.importgate"
rm -rf "$IMPORTS"; mkdir -p "$IMPORTS"
if ( cd "$PKG" && HOME="$IMPORTS" USERPROFILE="$IMPORTS" "$PYBIN" - <<'GATE'
import importlib, sys
# The tools first_run.py drives, in the order it drives them. Only these are importable by name:
# the vendored readers live under tools/vendor/ and reach sys.path when a tool puts them there,
# so they are checked below as a CONSEQUENCE of these imports rather than imported directly.
for name in ("steam_paths", "cpk_patch", "game_world", "game_faces", "game_emblems",
             "career_seed", "play_match"):
    importlib.import_module(name)
for vendored in ("wesys", "pesdb", "iostore"):
    if vendored not in sys.modules:
        sys.exit(f"{vendored} never loaded — tools/vendor is not in the package")
import sqlite3, pathlib
schema = pathlib.Path("src/ML.Data/schema.sql")
if not schema.exists():
    sys.exit("src/ML.Data/schema.sql is not in the package — career_seed dies on its first CREATE TABLE")
con = sqlite3.connect(":memory:")
con.executescript(schema.read_text(encoding="utf-8"))
tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
for need in ("teams", "players", "squad_members", "formations", "formation_slots", "team_tactics"):
    if need not in tables:
        sys.exit(f"schema.sql applied but has no {need} table")
print(f"  every first-run module imports; schema.sql builds {len(tables)} tables")
GATE
); then :; else
  echo "  the package cannot drive its own first run — a downloader would land nowhere" >&2
  rm -rf "$IMPORTS"; exit 1
fi
rm -rf "$IMPORTS"

echo "== gate: first run + a career, end to end from the package"
# The real thing, when this machine has eFootball: build a world out of the game with the PACKAGED
# tools and the PACKAGED python, seed a career into it, and check the three things a downloader
# notices first — squads, club crests, formations. Run in a COPY so no build artefact ships.
E2E="$OUT/.e2e"
GAMEDIR="${ML_EFOOTBALL_DIR:-}"
if [ -z "$GAMEDIR" ] && [ -f "$WORLD/build/efootball_dir.txt" ]; then
  GAMEDIR="$(tr -d '\r' < "$WORLD/build/efootball_dir.txt")"
fi
if [ -n "$GAMEDIR" ] && [ -f "$GAMEDIR/cpk/dt200_console_all.cpk" ]; then
  rm -rf "$E2E"; mkdir -p "$E2E/home"
  cp -r "$PKG" "$E2E/pkg"
  if ( cd "$E2E/pkg" && HOME="$E2E/home" USERPROFILE="$E2E/home" PYTHONIOENCODING=utf-8 \
         "$E2E/pkg/python/python.exe" "$E2E/pkg/tools/first_run.py" --game-dir "$GAMEDIR" --skip-faces ); then
    "$PYBIN" - "$E2E/pkg" <<'CHECK'
import json, os, sqlite3, sys
pkg = sys.argv[1]
con = sqlite3.connect(os.path.join(pkg, "build", "game_world.db"))
n = lambda q: con.execute(q).fetchone()[0]
clubs, squads = n("SELECT COUNT(*) FROM teams"), n("SELECT COUNT(*) FROM squad_members")
shapes = n("SELECT COUNT(DISTINCT formation_id) FROM formation_slots")
tactics = n("SELECT COUNT(DISTINCT team_id) FROM team_tactics")
crests = n("SELECT COUNT(*) FROM teams WHERE logo_path IS NOT NULL AND logo_path<>''")
con.close()
cat = json.load(open(os.path.join(pkg, "build", "game_catalog.json"), encoding="utf-8"))
picker = sum(len(l["teams"]) for c in cat["countries"] for l in c["leagues"])
print(f"  {clubs:,} clubs, {squads:,} squad places, {picker:,} in the picker; "
      f"{crests:,} crests, {shapes:,} formations over {tactics:,} clubs")
for what, got in (("clubs", clubs), ("squad places", squads), ("picker clubs", picker),
                  ("crests", crests), ("formations", shapes)):
    if got == 0:
        sys.exit(f"the first run produced NO {what} — that is what a downloader would get")
CHECK
    # One line, team and ITS league together — picking the club from a flattened list and the
    # league from countries[0] would seed a club into a competition it does not play in.
    PICK="$(cd "$E2E/pkg" && "$PYBIN" - <<'PICK'
import json
cat = json.load(open("build/game_catalog.json", encoding="utf-8"))
for country in cat["countries"]:
    for league in country["leagues"]:
        if league["teams"]:
            t = league["teams"][0]
            print(f"{league['league_id']}|{t['team_id']}|{t['name']}")
            raise SystemExit
raise SystemExit("the catalog the first run wrote has no club in any league")
PICK
)"
    PICK="$(echo "$PICK" | tr -d '\r')"
    LID="${PICK%%|*}"; TID="$(echo "$PICK" | cut -d'|' -f2)"; TNAME="${PICK#*|*|}"
    if ( cd "$E2E/pkg" && HOME="$E2E/home" USERPROFILE="$E2E/home" PYTHONIOENCODING=utf-8 \
           ML_CONFIRM_RESEED=1 "$PYBIN" tools/career_seed.py --db "build/game_world.db" \
           --catalog "build/game_catalog.json" --comp-id "$LID" --rfs-id "$TID" --team "$TNAME" ); then
      echo "  a $TNAME career seeded from the world the package built"
    else
      echo "  career_seed.py failed against the world the package built" >&2
      rm -rf "$E2E"; exit 1
    fi
  else
    echo "  first_run.py failed against the package" >&2
    rm -rf "$E2E"; exit 1
  fi
  rm -rf "$E2E"
else
  echo "  SKIPPED: no eFootball on this machine (set ML_EFOOTBALL_DIR) — the package ships UNPROVEN"
fi

cat > "$PKG/Play Master League.bat" <<'BAT'
@echo off
rem Launch Master League. The app finds tools\ (and the world it builds beside them) by
rem walking up from app\.
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

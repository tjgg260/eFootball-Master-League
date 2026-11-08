#!/usr/bin/env bash
# Build the stats host (dxgi.dll, a Windows DLL) on Linux, and put it where the app ships it from:
# tools/vendor/efootball-re/bin/dxgi.dll. Settings -> Install stats host (or
# tools/install_stats_host.py) then copies it into the game.
#
# The upstream build is MSVC on Windows (deploy_host.sh). Here it is Rust's x86_64-pc-windows-gnu
# target linked by zig, so no Windows SDK and no root are needed:
#   rustup target add x86_64-pc-windows-gnu
#   cargo install --locked cargo-zigbuild        (and zig itself, from your distro)
#
#   bash tools/vendor/efootball-re/memprobe/build_host_linux.sh [--test <pristine eFootball.exe>]
#
# --test also builds the offline signature test and runs it under wine, against an untouched copy
# of eFootball.exe (exe_patch.py keeps one at ~/Backups/eFootball/eFootball.exe.PRISTINE).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOST="$HERE/host"
TARGET=x86_64-pc-windows-gnu
cd "$HOST"

if [ "${1:-}" = "--test" ]; then
  EXE="${2:?path to an untouched eFootball.exe}"
  WIN_EXE="Z:$(realpath "$EXE" | tr / '\\')"
  echo "== signature test against $EXE"
  EFOOTBALL_PRISTINE_EXE="$WIN_EXE" cargo zigbuild --release --target "$TARGET" --tests -q
  T=$(ls -t target/$TARGET/release/deps/dxgi-*.exe | head -1)
  WINEDEBUG=-all WINEPREFIX="${WINEPREFIX:-$HOST/target/wineprefix}" wine "$T" sigscan --nocapture 2>&1 \
    | grep -E '^(test |skip:|test result|thread|  left|  right)'
fi

echo "== building dxgi.dll ($TARGET)"
# The .def pins the export table to the proxy's functions (see dxgi-gnu.def for why).
RUSTFLAGS="${RUSTFLAGS:-} -C link-arg=$HOST/dxgi-gnu.def" cargo zigbuild --release --target "$TARGET" -q
cp "target/$TARGET/release/dxgi.dll" "$HERE/../bin/dxgi.dll"
echo "built -> tools/vendor/efootball-re/bin/dxgi.dll ($(stat -c %s "$HERE/../bin/dxgi.dll") bytes)"
echo "install it into the game with the game closed: Settings -> Install stats host"

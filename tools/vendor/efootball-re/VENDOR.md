# Vendored: efootball-re stats host

The in-game stats host that writes `<eFootball>\ml_stats\match_*.json`, which `ML.Ingest` reads
for result capture, plus the export's documentation and the rating model `ML.Ingest.MatchRating`
ports.

Upstream: efootball-re, a contributor's reverse-engineering workspace (not public).
The host is built on `rust_sider` from [Efootball-Sider](https://github.com/Master-Antonio/Efootball-Sider)
(GPL-3.0; its Cargo.toml author, "Toriga Modding Team", is kept).
Licence here: GPL-3.0
Vendored: 2026-09-14

## Files

| File | Why |
|---|---|
| `memprobe/host/` | The host: a `dxgi.dll` proxy loaded by the game. `statshook.rs` finds the match stats, `statsexport.rs` writes `live.json` during a match and `match_<kick-off>.json` when it is final, `attrhook.rs` supplies each player's identity and attributes, `sigscan.rs` resolves every address from `signatures.txt` at startup (compiled in), `iohook.rs` / `plugin.rs` / `logger.rs` / `lib.rs` are the Sider-derived loader. |
| `memprobe/deploy_host.sh` | Builds the host and installs it into the game, backing up the `dxgi.dll` it replaces. |
| `mlstats/README.md` | The export: where it is written, when it is final, every JSON field and how sure each counter's meaning is. It also mentions tools that are **not** vendored (report, popup, identify, rate). |
| `mlstats/rating.py` | The rating model. `samples/ml-stats/*.expected-ratings.json` is its output, and the C# port is tested against it player by player. Regenerate those files with `tools/rating_reference.py` after changing it. |

Not vendored: the hot-reload analysis plugin (`sider_tools.dll`), the exe analysis tool, the
report / popup / identity-check scripts and the stat-labelling snapshots.

## Changes from upstream

Two, both removing machine-specific paths:

- `memprobe/host/src/sigscan.rs`, test module: the pristine-exe path comes from the build-time
  environment variable `EFOOTBALL_PRISTINE_EXE` instead of a hard-coded local path. Without it
  the test that needs the exe skips, as it did when the file was missing.
- `memprobe/deploy_host.sh`: the host folder is found from the script's own location, the game
  folder is `$EFOOTBALL_DIR` (default: the Steam install path) and backups go to
  `$EFOOTBALL_DXGI_BACKUP` (default: `~/Backups/eFootball/dxgi`).

Everything else is as upstream. sha256 of the files as copied, before those two changes:

```
087ce3f26f52d6b62c374e542005bc6c7194ce99b9d4a81478aa19070aebae29  memprobe/deploy_host.sh
e143fbcffa7f9334eb44dc8508061f7428d5daa36c8bb1c623730633deab46fb  memprobe/host/Cargo.lock
6fd5e7c5919a7d86cc91cee8b09bb6bddff7865b675871a3af9fbaf7d2264bb4  memprobe/host/Cargo.toml
4774549f6c0966b3749ca7800fc73916e1a80c5db487e94dcae7cdab54b13fd8  memprobe/host/signatures.txt
786c2c203424188e94e0c324788cef9187902736fd6ebd137ac6e50da4de5043  memprobe/host/src/attrhook.rs
ba64ff1f7aa1a2db1f54e6baad7ff70f681dfd7e734f9ba2eb7392094ac47153  memprobe/host/src/iohook.rs
d975ce29872960f229fd6a1196627aa4243972020ccbf6f3872d78d8c1e301e1  memprobe/host/src/lib.rs
6822d45feda4b7deaf23c6c28574317571ad27b8612f0cd03438aa64a486dd81  memprobe/host/src/logger.rs
06b04704b9fb656c4af2689a2d6b37fc7d8348a847dae31e4de49bed5223c28d  memprobe/host/src/plugin.rs
a8fba244003f9fe35314c915f3956a4904352498c9195290c57325011b355e8b  memprobe/host/src/sigscan.rs
31ea15033bf20d1a27b62613b907059bcabd42000e0e71963ba806bfcb063934  memprobe/host/src/statsexport.rs
e4622a26a64b4a08836ddff6ead5d185386dae49e2ab5e50937c317229196fea  memprobe/host/src/statshook.rs
d4a5c2900bdbb173c50b401289fbe7e91c50d5673e64a15fe52db93ba5a63be5  mlstats/README.md
cb27d43d763b27a484a61759ebc5377ee822ee3652ba23c388e6def6ffbda826  mlstats/rating.py
```

## Install (once, then after every change to the host)

Needs a Rust toolchain (`rustup`, stable) and Git Bash.

1. Quit eFootball completely: the game imports from `dxgi.dll`, so it stays locked while running.
2. `bash tools/vendor/efootball-re/memprobe/deploy_host.sh`. It builds `dxgi.dll` and copies it
   into `<eFootball>\eFootball\Binaries\Win64\`. The folder next to the exe is the one that
   counts; a copy in the game root is never loaded.
3. Put empty files `statshook.on` and `attrhook.on` in both the game root and
   `eFootball\Binaries\Win64`. `attrhook` is only there for player identity here; do not leave an
   `attrhook.mode` file, which makes it rewrite abilities.
4. Play. `sider_rust.log` in the game root shows `[EXPORT]` lines while it works. The match is
   final about 15 seconds after returning to the main menu (or at the next kick-off, or the next
   game start), as `ml_stats\match_<kick-off>.json`.

Uninstall: quit the game and delete `eFootball\Binaries\Win64\dxgi.dll`, or copy back the backup
the script took.

This injects into the running game. Keep it to offline play, like every other modification here.

## After a game update

The host does not hard-code addresses. At startup it scans for the patterns in
`signatures.txt` and logs what it resolved (`[SIG]` lines). A pattern that no longer matches
switches off only the features that need it, so nothing is patched at a wrong address. To check a
new exe offline against the recorded values:

```bash
cd tools/vendor/efootball-re/memprobe/host
EFOOTBALL_PRISTINE_EXE="<an untouched copy of eFootball.exe>" cargo test --release sigscan
```

If values moved, only `signatures.txt` needs changing; then run `deploy_host.sh` again.

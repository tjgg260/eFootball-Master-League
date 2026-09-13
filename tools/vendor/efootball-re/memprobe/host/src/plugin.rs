//! Hot-reloadable plugin host.
//!
//! dxgi.dll cannot be unloaded -- the game imports from it -- so the code we actually
//! iterate on lives in a separate `sider_tools.dll`.
//!
//! The essential trick: we never load `sider_tools.dll` itself, we load a numbered
//! *copy*. Windows locks a loaded image against writing, so loading the original would
//! make `cargo build` fail with a sharing violation until the game exits -- exactly the
//! restart cycle this exists to remove. Loading a copy leaves the build output free to
//! be overwritten at any moment.
//!
//! Triggering is deliberately dumb: a watcher thread polls for a trigger file. Writing
//! that file from outside is enough to make the running game reload and run new code,
//! with no IPC layer to build or keep in sync.

use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::RwLock;
use std::time::Duration;

use windows_sys::Win32::Foundation::{FreeLibrary, HMODULE};
use windows_sys::Win32::System::LibraryLoader::{GetProcAddress, LoadLibraryW};

const EXPECTED_ABI: u32 = 1;
const PLUGIN_NAME: &str = "sider_tools.dll";
const TRIGGER_NAME: &str = "sider_probe.trigger";

#[repr(C)]
struct ToolsApi {
    abi_version: u32,
    log: unsafe extern "C" fn(*const u8, usize),
}

type FnAbi = unsafe extern "C" fn() -> u32;
type FnInit = unsafe extern "C" fn(*const ToolsApi);
type FnHandle = unsafe extern "C" fn(u32, u64, *const u8, usize, *mut u8, usize) -> usize;

struct Loaded {
    module: HMODULE,
    handle: FnHandle,
    copy_path: PathBuf,
}

// SAFETY: the handle stays valid while the copy is loaded, and all access is behind the
// RwLock below.
unsafe impl Send for Loaded {}
unsafe impl Sync for Loaded {}

static LOADED: RwLock<Option<Loaded>> = RwLock::new(None);
static GENERATION: AtomicU32 = AtomicU32::new(0);

unsafe extern "C" fn plugin_log(ptr: *const u8, len: usize) {
    if ptr.is_null() || len == 0 {
        return;
    }
    if let Ok(t) = std::str::from_utf8(std::slice::from_raw_parts(ptr, len)) {
        crate::log_msg(t);
    }
}

/// Plugin and trigger both live in the process working directory, which is the game
/// root -- the same place sider_rust.log is written.
fn work_dir() -> PathBuf {
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

fn wide(p: &std::path::Path) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;
    p.as_os_str().encode_wide().chain(Some(0)).collect()
}

fn unload_locked(slot: &mut Option<Loaded>) {
    if let Some(old) = slot.take() {
        unsafe { FreeLibrary(old.module) };
        let _ = std::fs::remove_file(&old.copy_path);
    }
}

/// Load, or reload, the plugin. Returns a human-readable status.
pub fn reload() -> String {
    let dir = work_dir();
    let source = dir.join(PLUGIN_NAME);
    if !source.exists() {
        return format!("plugin not found: {}", source.display());
    }

    let mut slot = match LOADED.write() {
        Ok(g) => g,
        Err(_) => return "plugin lock poisoned".into(),
    };
    unload_locked(&mut slot);

    let generation = GENERATION.fetch_add(1, Ordering::SeqCst) + 1;
    let copy_path = dir.join(format!("sider_tools_live_{}.dll", generation));
    if let Err(e) = std::fs::copy(&source, &copy_path) {
        return format!("copy failed: {}", e);
    }

    let module = unsafe { LoadLibraryW(wide(&copy_path).as_ptr()) };
    if module == 0 {
        let _ = std::fs::remove_file(&copy_path);
        return "LoadLibrary failed".into();
    }

    unsafe {
        let (abi_s, init_s, handle_s) = match (
            GetProcAddress(module, b"sider_tools_abi\0".as_ptr()),
            GetProcAddress(module, b"sider_tools_init\0".as_ptr()),
            GetProcAddress(module, b"sider_tools_handle\0".as_ptr()),
        ) {
            (Some(a), Some(i), Some(h)) => (a, i, h),
            _ => {
                FreeLibrary(module);
                let _ = std::fs::remove_file(&copy_path);
                return "plugin missing required exports".into();
            }
        };

        let abi: FnAbi = std::mem::transmute(abi_s);
        let got = abi();
        if got != EXPECTED_ABI {
            FreeLibrary(module);
            let _ = std::fs::remove_file(&copy_path);
            return format!("plugin ABI {} != host {}", got, EXPECTED_ABI);
        }

        let init: FnInit = std::mem::transmute(init_s);
        init(&ToolsApi { abi_version: EXPECTED_ABI, log: plugin_log });

        *slot = Some(Loaded {
            module,
            handle: std::mem::transmute::<_, FnHandle>(handle_s),
            copy_path,
        });
    }

    format!("plugin loaded (generation {})", generation)
}

/// Forward one command to the plugin.
pub fn handle(cmd: u32, p_u64: u64, arg: &str) -> String {
    let guard = match LOADED.read() {
        Ok(g) => g,
        Err(_) => return "plugin lock poisoned".into(),
    };
    let Some(loaded) = guard.as_ref() else {
        return "plugin not loaded".into();
    };
    let mut out = vec![0u8; 512];
    let n = unsafe {
        (loaded.handle)(cmd, p_u64, arg.as_ptr(), arg.len(), out.as_mut_ptr(), out.len())
    };
    String::from_utf8_lossy(&out[..n.min(out.len())]).into_owned()
}

/// Remove stale copies left by a previous run so the directory does not accumulate them.
fn clean_stale_copies() {
    if let Ok(entries) = std::fs::read_dir(work_dir()) {
        for e in entries.flatten() {
            let n = e.file_name();
            let n = n.to_string_lossy();
            if n.starts_with("sider_tools_live_") && n.ends_with(".dll") {
                let _ = std::fs::remove_file(e.path());
            }
        }
    }
}

/// Watch for the trigger file. Its first line is `<cmd> [u64] [text]`; writing it makes
/// the running game reload the plugin and dispatch, so new code can be tested without
/// restarting the game.
pub fn start() {
    clean_stale_copies();
    crate::log_msg(&format!("[PLUGIN] {}", reload()));

    std::thread::spawn(|| {
        let trigger = work_dir().join(TRIGGER_NAME);
        loop {
            std::thread::sleep(Duration::from_millis(500));
            let Ok(body) = std::fs::read_to_string(&trigger) else {
                continue;
            };
            // Consume it first: a failure below must not cause an endless retry loop.
            let _ = std::fs::remove_file(&trigger);

            let line = body.lines().next().unwrap_or("").trim().to_string();
            let mut parts = line.split_whitespace();
            let cmd: u32 = parts.next().and_then(|s| s.parse().ok()).unwrap_or(0);
            let p_u64: u64 = parts.next().and_then(|s| s.parse().ok()).unwrap_or(0);
            let rest: String = parts.collect::<Vec<_>>().join(" ");

            crate::log_msg(&format!("[PLUGIN] trigger: cmd={} p={} arg={:?}", cmd, p_u64, rest));
            crate::log_msg(&format!("[PLUGIN] {}", reload()));
            let reply = handle(cmd, p_u64, &rest);
            crate::log_msg(&format!("[PLUGIN] reply: {}", reply));
        }
    });
}

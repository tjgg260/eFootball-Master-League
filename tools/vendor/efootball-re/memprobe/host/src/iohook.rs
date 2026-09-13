//! File-I/O observation hook. Answers one question: does the game re-read the player
//! data CPK (dt200) when a match loads, or only once at startup?
//!
//! This lives in the HOST, never in the plugin. A trampoline detour redirects a Windows
//! function into our code; if that code lived in the hot-reloadable plugin, the next
//! FreeLibrary would leave the detour pointing at freed memory -> crash. dxgi.dll is
//! never unloaded, so the detour target stays valid for the whole process lifetime.
//!
//! Read-only: every hook calls the original and returns its result unchanged. We never
//! alter a handle, a buffer, an offset, or a return value. No breakpoints, no debugger,
//! no PAGE_GUARD -- a trampoline is an ordinary `jmp`, which is why it does not fight the
//! CPU exception machinery the way the earlier watchpoint experiments did.
//!
//! We hook at the ntdll layer (NtCreateFile / NtReadFile). Every higher-level path
//! (CreateFileW, ReadFile, overlapped I/O, CRI's own file access) funnels through it.
//! Denuvo protects the game's own code sections, not ntdll, so this is outside its
//! integrity checks. The one thing it cannot see is memory-mapped access (page faults),
//! but the hook is self-validating: startup reads of the CPK prove it sees CPK I/O at
//! all, so a later ABSENCE of reads at match load is meaningful rather than a blind spot.

use std::collections::HashSet;
use std::ffi::c_void;
use std::sync::atomic::{AtomicIsize, AtomicUsize, Ordering};
use std::sync::Mutex;

use retour::RawDetour;
use windows_sys::Win32::System::LibraryLoader::{GetModuleHandleA, GetProcAddress, LoadLibraryA};

use crate::log_msg;

// ---------------------------------------------------------------------------
// Windows structures we touch. Kept minimal and local so we depend on no extra
// windows-sys features.
// ---------------------------------------------------------------------------

#[repr(C)]
struct UnicodeString {
    length: u16,          // bytes, not chars
    maximum_length: u16,
    buffer: *mut u16,
}

#[repr(C)]
struct ObjectAttributes {
    length: u32,
    root_directory: isize,
    object_name: *mut UnicodeString,
    attributes: u32,
    security_descriptor: *mut c_void,
    security_quality_of_service: *mut c_void,
}

// NtCreateFile: only FileHandle (out, arg0) and ObjectAttributes (arg2) are inspected;
// the rest are declared so the calling convention matches the real function exactly.
type NtCreateFileFn = unsafe extern "system" fn(
    *mut isize,             // FileHandle (out)
    u32,                    // DesiredAccess
    *mut ObjectAttributes,  // ObjectAttributes
    *mut c_void,            // IoStatusBlock
    *mut i64,               // AllocationSize
    u32,                    // FileAttributes
    u32,                    // ShareAccess
    u32,                    // CreateDisposition
    u32,                    // CreateOptions
    *mut c_void,            // EaBuffer
    u32,                    // EaLength
) -> i32;

// NtReadFile: FileHandle (arg0), Length (arg6), ByteOffset (arg7) are what we log.
type NtReadFileFn = unsafe extern "system" fn(
    isize,                  // FileHandle
    isize,                  // Event
    *mut c_void,            // ApcRoutine
    *mut c_void,            // ApcContext
    *mut c_void,            // IoStatusBlock
    *mut c_void,            // Buffer
    u32,                    // Length
    *mut i64,               // ByteOffset (LARGE_INTEGER*, may be null)
    *mut u32,               // Key
) -> i32;

// NtQueryInformationFile, used only to resolve a handle's path once. Not hooked.
type NtQueryInformationFileFn = unsafe extern "system" fn(
    isize,                  // FileHandle
    *mut c_void,            // IoStatusBlock
    *mut c_void,            // FileInformation
    u32,                    // Length
    u32,                    // FileInformationClass
) -> i32;

const FILE_NAME_INFORMATION: u32 = 9;

// ---------------------------------------------------------------------------
// State. Trampolines are set once at install, before the detours are enabled.
// ---------------------------------------------------------------------------

static TRAMP_CREATE: AtomicUsize = AtomicUsize::new(0);
static TRAMP_READ: AtomicUsize = AtomicUsize::new(0);
static NTQIF: AtomicUsize = AtomicUsize::new(0);

// Handles whose path matched a keyword. Lock-free membership check on the read hot path;
// eight slots is far more than the handful of data CPKs ever open at once.
static INTERESTING: [AtomicIsize; 8] = [
    AtomicIsize::new(0), AtomicIsize::new(0), AtomicIsize::new(0), AtomicIsize::new(0),
    AtomicIsize::new(0), AtomicIsize::new(0), AtomicIsize::new(0), AtomicIsize::new(0),
];

fn interesting_contains(h: isize) -> bool {
    INTERESTING.iter().any(|s| s.load(Ordering::Relaxed) == h)
}

fn interesting_add(h: isize) {
    for s in INTERESTING.iter() {
        if s.compare_exchange(0, h, Ordering::Relaxed, Ordering::Relaxed).is_ok() {
            return;
        }
    }
}

// ---------------------------------------------------------------------------
// Read-time substitution state. Separate from INTERESTING because substitution
// must fire ONLY on the dt200 CPK (Player.bin), never dt230/pesdb which share the
// same numeric offset range. A handle enters DT200 when its resolved path contains
// "dt200" (in the open hook or the lazy classify path). No NtClose eviction yet:
// dt200 stays open the whole session, so its handle number is not recycled mid-run;
// harden with a close hook before any unattended use.
static DT200: [AtomicIsize; 4] = [
    AtomicIsize::new(0), AtomicIsize::new(0), AtomicIsize::new(0), AtomicIsize::new(0),
];

fn dt200_contains(h: isize) -> bool {
    DT200.iter().any(|s| s.load(Ordering::Relaxed) == h)
}

fn dt200_add(h: isize) {
    if h == 0 || dt200_contains(h) {
        return;
    }
    for s in DT200.iter() {
        if s.compare_exchange(0, h, Ordering::Relaxed, Ordering::Relaxed).is_ok() {
            return;
        }
    }
}

// Player.bin's byte range inside dt200_console_all.cpk (verified via cpk.py against the
// live CPK): offset 15,157,248, size 4,413,919, so end (exclusive) 19,571,167. The read
// buffers at these offsets hold WESYS-encrypted bytes (magic FF 22 83 57 45 53 59 53);
// the game decrypts (rolling-XOR 0x655f) then parses. We overwrite the encrypted bytes,
// so the game's OWN decrypt+parse runs on our data -- no foreign memory write.
const PLAYER_BIN_START: i64 = 15_157_248;

// The substitute: a full WESYS-encrypted Player.bin (same 4,413,919 bytes), loaded once
// at install into a leaked 'static slice. MOD_PTR==0 means "no substitute" -> the hook
// stays pure-observe (safe default; shipping this host without a substitute file changes
// nothing). MOD_LEN defines the window end (PLAYER_BIN_START + MOD_LEN), so the file's own
// size sets the extent -- no off-by-one on a hardcoded end.
static MOD_PTR: AtomicUsize = AtomicUsize::new(0);
static MOD_LEN: AtomicUsize = AtomicUsize::new(0);
static SUBST_PENDING_WARN: AtomicUsize = AtomicUsize::new(0);
static SUBST_FIRST_SEEN: AtomicUsize = AtomicUsize::new(0);

// Handles already resolved as not-of-interest, so we never re-query them. dt200 stays
// open for the whole session, so a handle number is not reused out from under this.
static BORING: Mutex<Option<HashSet<isize>>> = Mutex::new(None);

// Reentrancy guard: the resolve path calls back into ntdll; never recurse into ourselves.
thread_local! {
    static IN_HOOK: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

// Filenames whose data we care about. Matched case-insensitively as a substring of the
// NT path. Kept broad on purpose: seeing which CPKs are touched at match load is itself
// part of the answer.
const KEYWORDS: &[&str] = &[
    "dt200", "dt230", "dt540", "dt870", "player.bin", "playerassignment", "pesdb",
];

fn path_is_interesting(path_lower: &str) -> bool {
    KEYWORDS.iter().any(|k| path_lower.contains(k))
}

/// Resolve a handle's path (within its volume) and decide whether it is interesting.
/// Returns Some(path) when it matches, None otherwise. Never faults: a failed query
/// simply yields None.
unsafe fn resolve_handle(h: isize) -> Option<String> {
    let f = NTQIF.load(Ordering::Relaxed);
    if f == 0 {
        return None;
    }
    let ntqif: NtQueryInformationFileFn = std::mem::transmute(f);

    // FILE_NAME_INFORMATION: { ULONG FileNameLength; WCHAR FileName[...]; }
    let mut buf = [0u8; 1024];
    let mut iosb = [0u8; 16];
    let st = ntqif(
        h,
        iosb.as_mut_ptr() as *mut c_void,
        buf.as_mut_ptr() as *mut c_void,
        buf.len() as u32,
        FILE_NAME_INFORMATION,
    );
    if st < 0 {
        return None;
    }
    let name_len = u32::from_le_bytes([buf[0], buf[1], buf[2], buf[3]]) as usize; // bytes
    let name_len = name_len.min(buf.len() - 4);
    let wide: &[u16] = std::slice::from_raw_parts(buf.as_ptr().add(4) as *const u16, name_len / 2);
    let path = String::from_utf16_lossy(wide);
    if path_is_interesting(&path.to_lowercase()) {
        Some(path)
    } else {
        None
    }
}

// ---------------------------------------------------------------------------
// Detours
// ---------------------------------------------------------------------------

unsafe extern "system" fn hook_create_file(
    file_handle: *mut isize,
    desired_access: u32,
    object_attributes: *mut ObjectAttributes,
    io_status_block: *mut c_void,
    allocation_size: *mut i64,
    file_attributes: u32,
    share_access: u32,
    create_disposition: u32,
    create_options: u32,
    ea_buffer: *mut c_void,
    ea_length: u32,
) -> i32 {
    let orig: NtCreateFileFn = std::mem::transmute(TRAMP_CREATE.load(Ordering::Relaxed));
    let ret = orig(
        file_handle, desired_access, object_attributes, io_status_block, allocation_size,
        file_attributes, share_access, create_disposition, create_options, ea_buffer, ea_length,
    );

    // Observation is panic-isolated: a panic must never unwind across the FFI boundary
    // into the game (undefined behavior; a poisoned-mutex panic previously killed the
    // plugin watcher thread). catch_unwind contains any fault to a dropped observation.
    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        if IN_HOOK.with(|g| g.get()) {
            return;
        }
        IN_HOOK.with(|g| g.set(true));
        if ret == 0 && !object_attributes.is_null() {
            let oa = &*object_attributes;
            if !oa.object_name.is_null() {
                let us = &*oa.object_name;
                if !us.buffer.is_null() && us.length >= 2 {
                    let n = (us.length / 2) as usize;
                    let wide = std::slice::from_raw_parts(us.buffer, n);
                    let path = String::from_utf16_lossy(wide);
                    let path_lower = path.to_lowercase();
                    if path_is_interesting(&path_lower) {
                        let h = if file_handle.is_null() { 0 } else { *file_handle };
                        interesting_add(h);
                        if path_lower.contains("dt200") {
                            dt200_add(h);
                        }
                        log_msg(&format!("[IO][OPEN] handle=0x{:X} path={}", h, path));
                    }
                }
            }
        }
        IN_HOOK.with(|g| g.set(false));
    }));
    ret
}

unsafe extern "system" fn hook_read_file(
    file_handle: isize,
    event: isize,
    apc_routine: *mut c_void,
    apc_context: *mut c_void,
    io_status_block: *mut c_void,
    buffer: *mut c_void,
    length: u32,
    byte_offset: *mut i64,
    key: *mut u32,
) -> i32 {
    // Panic-isolated observation (see hook_create_file). The read itself always forwards.
    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        observe_read(file_handle, buffer, length, byte_offset);
    }));
    let orig: NtReadFileFn = std::mem::transmute(TRAMP_READ.load(Ordering::Relaxed));
    let ret = orig(file_handle, event, apc_routine, apc_context, io_status_block, buffer, length, byte_offset, key);

    // Post-read substitution: only touches the buffer for a dt200 Player.bin read once a
    // substitute is loaded; otherwise a no-op. Runs AFTER the original so the buffer is
    // populated, and is gated on ret==STATUS_SUCCESS (a synchronous, completed read). A
    // panic here must never cross back into the game, so it is isolated too.
    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        substitute_read(file_handle, buffer, length, byte_offset, io_status_block, ret);
    }));
    ret
}

/// Overwrite the portion of a just-completed dt200 read that falls inside the Player.bin
/// window with bytes from the loaded substitute. No-op unless a substitute is loaded, the
/// handle is dt200, the read is synchronous+successful, and the offset overlaps the window.
/// All bounds are clamped to both the read's delivered length and the substitute's size,
/// so a partial or boundary-straddling read is handled without ever reading/writing OOB.
unsafe fn substitute_read(
    file_handle: isize,
    buffer: *mut c_void,
    length: u32,
    byte_offset: *mut i64,
    io_status_block: *mut c_void,
    ret: i32,
) {
    let mod_ptr = MOD_PTR.load(Ordering::Acquire);
    if mod_ptr == 0 || buffer.is_null() {
        return; // no substitute loaded -> pure observation
    }
    if !dt200_contains(file_handle) || byte_offset.is_null() {
        return;
    }
    let off = *byte_offset;
    if off < 0 {
        return;
    }
    let mod_len = MOD_LEN.load(Ordering::Relaxed) as i64;
    let win_end = PLAYER_BIN_START + mod_len;
    // Does this read touch the Player.bin window at all?
    if off >= win_end || off + length as i64 <= PLAYER_BIN_START {
        return;
    }

    // The buffer is only guaranteed populated when the read completed synchronously.
    // STATUS_SUCCESS == 0. STATUS_PENDING (0x103) or an error means the bytes are not in
    // the buffer yet -> we must NOT overwrite (would be clobbered or corrupt). Log it a few
    // times: absence of [IO][SUBST] lines against present [IO][READ] lines == async reads.
    if ret != 0 {
        if SUBST_PENDING_WARN.fetch_add(1, Ordering::Relaxed) < 3 {
            log_msg(&format!(
                "[IO][SUBST] SKIP non-sync ret=0x{:X} handle=0x{:X} off={} — read not synchronous; needs async completion path",
                ret as u32, file_handle, off
            ));
        }
        return;
    }

    // Bytes actually delivered: IO_STATUS_BLOCK.Information (ULONG_PTR at +8 on x64).
    let delivered: i64 = if io_status_block.is_null() {
        length as i64
    } else {
        (*((io_status_block as *const usize).add(1)) as i64).min(length as i64)
    };
    if delivered <= 0 {
        return;
    }

    // One-time confirmation that the buffer holds ENCRYPTED bytes (validates the whole
    // model: we feed ciphertext, the game decrypts it). Fires on the window's first chunk.
    if off == PLAYER_BIN_START && SUBST_FIRST_SEEN.fetch_add(1, Ordering::Relaxed) == 0 {
        let b = buffer as *const u8;
        log_msg(&format!(
            "[IO][SUBST] first chunk pre-overwrite bytes = {:02X} {:02X} {:02X} {:02X} {:02X} {:02X} {:02X} {:02X} (expect WESYS FF 22 83 57 45 53 59 53)",
            *b, *b.add(1), *b.add(2), *b.add(3), *b.add(4), *b.add(5), *b.add(6), *b.add(7)
        ));
    }

    // Overlap of [off, off+delivered) with [PLAYER_BIN_START, win_end).
    let read_end = off + delivered;
    let lo = off.max(PLAYER_BIN_START);
    let hi = read_end.min(win_end);
    if hi <= lo {
        return;
    }
    let src_off = (lo - PLAYER_BIN_START) as usize; // <= mod_len
    let dst_off = (lo - off) as usize;              // <= delivered <= length
    let n = (hi - lo) as usize;

    std::ptr::copy_nonoverlapping((mod_ptr as *const u8).add(src_off), (buffer as *mut u8).add(dst_off), n);

    log_msg(&format!(
        "[IO][SUBST] handle=0x{:X} off={} delivered={} patched={} src[{}..{}]",
        file_handle, off, delivered, n, src_off, src_off + n
    ));
}

/// Load the substitute Player.bin once at install. Path: env EF_SUBST_FILE, else
/// "efsub_player.dat" relative to the process cwd (the game root, where sider_rust.log is
/// written). Absent file -> substitution stays disabled. A wrong-sized or non-WESYS file is
/// still loaded (with a warning) so the user sees exactly what went in.
fn load_subst() {
    let path = std::env::var("EF_SUBST_FILE").unwrap_or_else(|_| "efsub_player.dat".to_string());
    match std::fs::read(&path) {
        Ok(data) => {
            let n = data.len();
            if n < 1_000_000 || n > 8_000_000 {
                log_msg(&format!(
                    "[IO][SUBST] REFUSED '{}': size {} is not a plausible Player.bin (~4,413,919 bytes). Substitution disabled.",
                    path, n
                ));
                return;
            }
            let wesys = data.len() >= 8
                && &data[..8] == [0xFF, 0x22, 0x83, 0x57, 0x45, 0x53, 0x59, 0x53];
            let leaked: &'static [u8] = Box::leak(data.into_boxed_slice());
            MOD_LEN.store(leaked.len(), Ordering::Relaxed);
            MOD_PTR.store(leaked.as_ptr() as usize, Ordering::Release); // publish last
            log_msg(&format!(
                "[IO][SUBST] ARMED: {} bytes from '{}', WESYS magic={}. Window = Player.bin @ {}..{}",
                leaked.len(), path, wesys, PLAYER_BIN_START, PLAYER_BIN_START + leaked.len() as i64
            ));
            if !wesys {
                log_msg("[IO][SUBST] WARNING: substitute does not start with WESYS magic FF 22 83 57 45 53 59 53 — the game may fail to decrypt. Expected an ENCRYPTED Player.bin sliced from a CPK, not a plaintext dump.");
            }
        }
        Err(_) => {
            let cwd = std::env::current_dir()
                .map(|p| p.display().to_string())
                .unwrap_or_default();
            log_msg(&format!(
                "[IO][SUBST] no substitute file (looked for '{}' in {}) — substitution disabled; pure observation.",
                path, cwd
            ));
        }
    }
}

/// Classify the handle (once) and, for interesting handles, log the read plus the buffer
/// address the bytes land in -- that address is the in-memory anchor for the raw file.
/// Never panics: mutex poisoning is recovered rather than unwrapped.
unsafe fn observe_read(file_handle: isize, buffer: *mut c_void, length: u32, byte_offset: *mut i64) {
    let mut interesting = interesting_contains(file_handle);

    if !interesting && !IN_HOOK.with(|g| g.get()) {
        IN_HOOK.with(|g| g.set(true));
        let already_boring = {
            let mut guard = BORING.lock().unwrap_or_else(|e| e.into_inner());
            guard.get_or_insert_with(HashSet::new).contains(&file_handle)
        };
        if !already_boring {
            match resolve_handle(file_handle) {
                Some(path) => {
                    interesting_add(file_handle);
                    interesting = true;
                    if path.to_lowercase().contains("dt200") {
                        dt200_add(file_handle);
                    }
                    log_msg(&format!("[IO][ID] handle=0x{:X} is {}", file_handle, path));
                }
                None => {
                    let mut guard = BORING.lock().unwrap_or_else(|e| e.into_inner());
                    guard.get_or_insert_with(HashSet::new).insert(file_handle);
                }
            }
        }
        IN_HOOK.with(|g| g.set(false));
    }

    if interesting {
        let off = if byte_offset.is_null() { -1 } else { *byte_offset };
        log_msg(&format!(
            "[IO][READ] handle=0x{:X} offset={} len={} buf=0x{:X}",
            file_handle, off, length, buffer as usize
        ));
    }
}

// ---------------------------------------------------------------------------
// Install
// ---------------------------------------------------------------------------

unsafe fn resolve(ntdll: isize, name: &[u8]) -> Option<usize> {
    let p = GetProcAddress(ntdll, name.as_ptr());
    p.map(|f| f as usize).filter(|&a| a != 0)
}

unsafe fn install_one(target: usize, detour: usize, tramp: &AtomicUsize, label: &str) -> bool {
    match RawDetour::new(target as *const (), detour as *const ()) {
        Ok(d) => {
            tramp.store(d.trampoline() as *const () as usize, Ordering::Relaxed);
            match d.enable() {
                Ok(()) => {
                    std::mem::forget(d); // keep the detour alive for the process lifetime
                    log_msg(&format!("[IO] hooked {} @ 0x{:X}", label, target));
                    true
                }
                Err(e) => {
                    log_msg(&format!("[IO] enable {} failed: {:?}", label, e));
                    false
                }
            }
        }
        Err(e) => {
            log_msg(&format!("[IO] detour {} failed: {:?}", label, e));
            false
        }
    }
}

/// Install the file-I/O observation hooks. Called once, from the host worker thread
/// (off the loader lock). Safe to fail: a failed install just means no I/O log this run.
pub fn install() {
    unsafe {
        let ntdll = GetModuleHandleA(b"ntdll.dll\0".as_ptr());
        if ntdll == 0 {
            log_msg("[IO] ntdll handle not found; I/O hooks skipped");
            return;
        }

        if let Some(a) = resolve(ntdll, b"NtQueryInformationFile\0") {
            NTQIF.store(a, Ordering::Relaxed);
        } else {
            log_msg("[IO] NtQueryInformationFile not found; handle names will be limited to opens");
        }

        let create = resolve(ntdll, b"NtCreateFile\0");
        let read = resolve(ntdll, b"NtReadFile\0");

        match read {
            Some(a) => { install_one(a, hook_read_file as *const () as usize, &TRAMP_READ, "NtReadFile"); }
            None => log_msg("[IO] NtReadFile not found; cannot observe reads"),
        }
        match create {
            Some(a) => { install_one(a, hook_create_file as *const () as usize, &TRAMP_CREATE, "NtCreateFile"); }
            None => log_msg("[IO] NtCreateFile not found; cannot observe opens"),
        }

        log_msg("[IO] file-I/O observation armed; keywords: dt200/dt230/dt540/dt870/Player.bin/PlayerAssignment/pesdb");

        load_subst();

        install_net();
    }
}

// ---------------------------------------------------------------------------
// Network target observation (ws2_32). Read-only: logs the hostnames / addresses
// the game dials, so we know which server to redirect for a fast-fail offline login.
// The offline "cutscene" is really a connection wait; a DROP firewall rule makes the
// game hang the full TCP timeout, during which skip is disabled. Knowing the exact
// host lets us redirect it to 127.0.0.1 (instant refuse) instead of dropping.
// ---------------------------------------------------------------------------

static TRAMP_GAI: AtomicUsize = AtomicUsize::new(0);
static TRAMP_GAIW: AtomicUsize = AtomicUsize::new(0);
static TRAMP_CONNECT: AtomicUsize = AtomicUsize::new(0);
static TRAMP_GHBN: AtomicUsize = AtomicUsize::new(0);

type GetAddrInfoFn = unsafe extern "system" fn(*const u8, *const u8, *const c_void, *mut *mut c_void) -> i32;
type GetAddrInfoWFn = unsafe extern "system" fn(*const u16, *const u16, *const c_void, *mut *mut c_void) -> i32;
type ConnectFn = unsafe extern "system" fn(usize, *const u8, i32) -> i32;
type GetHostByNameFn = unsafe extern "system" fn(*const u8) -> *mut c_void;

/// Read a NUL-terminated ANSI string, bounded, without faulting on a bad pointer edge.
unsafe fn cstr(p: *const u8) -> String {
    if p.is_null() {
        return String::new();
    }
    let mut v = Vec::new();
    for i in 0..512isize {
        let b = *p.offset(i);
        if b == 0 {
            break;
        }
        v.push(b);
    }
    String::from_utf8_lossy(&v).into_owned()
}

/// Read a NUL-terminated wide string, bounded.
unsafe fn wstr(p: *const u16) -> String {
    if p.is_null() {
        return String::new();
    }
    let mut v = Vec::new();
    for i in 0..512isize {
        let c = *p.offset(i);
        if c == 0 {
            break;
        }
        v.push(c);
    }
    String::from_utf16_lossy(&v)
}

unsafe extern "system" fn hook_getaddrinfo(
    node: *const u8,
    service: *const u8,
    hints: *const c_void,
    res: *mut *mut c_void,
) -> i32 {
    if !node.is_null() {
        log_msg(&format!("[NET][DNS] getaddrinfo host={} service={}", cstr(node), cstr(service)));
    }
    let orig: GetAddrInfoFn = std::mem::transmute(TRAMP_GAI.load(Ordering::Relaxed));
    orig(node, service, hints, res)
}

unsafe extern "system" fn hook_getaddrinfow(
    node: *const u16,
    service: *const u16,
    hints: *const c_void,
    res: *mut *mut c_void,
) -> i32 {
    if !node.is_null() {
        log_msg(&format!("[NET][DNS] GetAddrInfoW host={} service={}", wstr(node), wstr(service)));
    }
    let orig: GetAddrInfoWFn = std::mem::transmute(TRAMP_GAIW.load(Ordering::Relaxed));
    orig(node, service, hints, res)
}

unsafe extern "system" fn hook_gethostbyname(name: *const u8) -> *mut c_void {
    if !name.is_null() {
        log_msg(&format!("[NET][DNS] gethostbyname host={}", cstr(name)));
    }
    let orig: GetHostByNameFn = std::mem::transmute(TRAMP_GHBN.load(Ordering::Relaxed));
    orig(name)
}

unsafe extern "system" fn hook_connect(s: usize, name: *const u8, namelen: i32) -> i32 {
    if !name.is_null() && namelen >= 8 {
        let fam = u16::from_le_bytes([*name, *name.add(1)]);
        if fam == 2 {
            // AF_INET: sin_port (be) @2, sin_addr @4
            let port = u16::from_be_bytes([*name.add(2), *name.add(3)]);
            let ip = [*name.add(4), *name.add(5), *name.add(6), *name.add(7)];
            log_msg(&format!("[NET][CONNECT] {}.{}.{}.{}:{}", ip[0], ip[1], ip[2], ip[3], port));
        } else if fam == 23 && namelen >= 28 {
            // AF_INET6: sin6_port (be) @2, sin6_addr @8..24
            let port = u16::from_be_bytes([*name.add(2), *name.add(3)]);
            let mut seg = String::new();
            for i in 0..8 {
                let hi = *name.add(8 + i * 2);
                let lo = *name.add(8 + i * 2 + 1);
                seg.push_str(&format!("{:02x}{:02x}{}", hi, lo, if i < 7 { ":" } else { "" }));
            }
            log_msg(&format!("[NET][CONNECT] [{}]:{}", seg, port));
        }
    }
    let orig: ConnectFn = std::mem::transmute(TRAMP_CONNECT.load(Ordering::Relaxed));
    orig(s, name, namelen)
}

/// Install the network-target observation hooks (ws2_32). Read-only. Loading ws2_32 if
/// absent is harmless -- it is a system DLL the game links anyway.
fn install_net() {
    unsafe {
        let ws2 = LoadLibraryA(b"ws2_32.dll\0".as_ptr());
        if ws2 == 0 {
            log_msg("[NET] ws2_32.dll not available; network observation skipped");
            return;
        }
        if let Some(a) = resolve(ws2, b"getaddrinfo\0") {
            install_one(a, hook_getaddrinfo as *const () as usize, &TRAMP_GAI, "getaddrinfo");
        }
        if let Some(a) = resolve(ws2, b"GetAddrInfoW\0") {
            install_one(a, hook_getaddrinfow as *const () as usize, &TRAMP_GAIW, "GetAddrInfoW");
        }
        if let Some(a) = resolve(ws2, b"gethostbyname\0") {
            install_one(a, hook_gethostbyname as *const () as usize, &TRAMP_GHBN, "gethostbyname");
        }
        if let Some(a) = resolve(ws2, b"connect\0") {
            install_one(a, hook_connect as *const () as usize, &TRAMP_CONNECT, "connect");
        }
        log_msg("[NET] network-target observation armed (getaddrinfo/GetAddrInfoW/gethostbyname/connect)");
    }
}

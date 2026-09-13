//! A deliberately do-nothing detour on the game's OWN attribute getter.
//!
//! Why this exists: the +0x394 attribute array is a cache the game rewrites within a
//! millisecond, and there is no raw copy anywhere in memory to edit instead (checked:
//! a player's block appears 5 times and all 5 are identical). So the only way to change
//! what the match actually uses is to intercept the read itself.
//!
//! Before doing that, one question has to be answered on its own: **does patching the
//! game's own code section set anything off?** Every hook up to now has been on ntdll or
//! ws2_32 -- Windows' own modules, which anti-tamper does not watch. eFootball.exe is
//! Denuvo-protected and nobody here has tested whether it checksums its own .text.
//!
//! Hence: this hook calls the original and returns its value **unchanged**. It cannot
//! affect gameplay. If the game runs normally with it installed, code patching is viable
//! and changing the return value is a one-line follow-up. If the game dies or misbehaves,
//! we have the answer with nothing else to disentangle.
//!
//! Two safety rails:
//!   * **Off by default.** Installs only when `attrhook.on` exists in the working
//!     directory. If it turns out to crash the game, delete that file -- no rebuild,
//!     no reinstall, and the game boots normally again.
//!   * **Byte check.** The first 7 bytes at the target must match the prologue read out
//!     of the pristine exe. A different build (or an address typo) means no patch at all,
//!     instead of a jmp written into the middle of some unrelated function.

use std::sync::atomic::{AtomicU32, AtomicU64, AtomicUsize, Ordering};

use retour::RawDetour;

use crate::log_msg;

// ATTR_get(player, id) (这个 build 是 0x143EA8CB0, 282 个调用点) 由 sigscan 按特征码定位,
// 见 signatures.txt 的 attr_get —— 前 7 字节 48 83 EC 28 44 8B C2 就是以前写死的 EXPECT。

const GATE_FILE: &str = "attrhook.on";

/// 球员对象里存槽位的字节 (`movsx edx, byte [rcx+X]`, 这个 build 0x2BD8) 和
/// 比赛上下文指针 (`mov rcx, [rcx+Y]`, 0x47C0)。都从 ATTR_get 自己的指令里捕获, 装钩前写好。
static SEL_OFF: AtomicUsize = AtomicUsize::new(0);
static CTX_OFF: AtomicUsize = AtomicUsize::new(0);

/// uint8 ATTR_get(void* player, int id) — MS x64: rcx = player, edx = id, result in eax.
type AttrGetFn = unsafe extern "system" fn(usize, u32) -> u32;

static TRAMP: AtomicUsize = AtomicUsize::new(0);
static CALLS: AtomicU64 = AtomicU64::new(0);

/// 主队 / 客队各自要被改成多少。0 = 不改, 原样透传。
///
/// 由后台线程按 `attrhook.mode` 文件设置。**钩子里绝不碰文件**: 它一秒钟要跑几万次,
/// 在里面做 I/O 就是自己制造卡顿, 而且卡顿还会被算到钩子头上。
///
/// 格式(一行, 空格分隔, 顺序随意):
/// ```
/// home=99 away=40        主队全 99, 客队全 40
/// away=40                只改客队
/// home=off away=off      全部恢复
/// away=99 id=40          只把客队的速度(id40)改成 99
/// ```
/// 有效上限看游戏自己的范围表: 走表 A 的夹到 **99**, 走表 B 的夹到 **120**,
/// 再高没有意义; 下限一律 **40**。
static HOME_VAL: AtomicU32 = AtomicU32::new(0);
static AWAY_VAL: AtomicU32 = AtomicU32::new(0);
/// 只改这一个 id; 0 或 999 = 全部 26 项。
static ONLY_ID: AtomicU32 = AtomicU32::new(0);
static OVERRIDES: AtomicU64 = AtomicU64::new(0);

/// 客队球员在那张 31 项表里的槽位区间。实测 0-10 是主队 11 人, 11-21 是客队 11 人,
/// 而控制器 1 分在主场 —— 所以要削/要抬的是 11..=21。
const HOME_LO: i32 = 0;
const HOME_HI: i32 = 10;
const AWAY_LO: i32 = 11;
const AWAY_HI: i32 = 21;


/// 只动 26 项能力。39 是逆足, 47 以上是年龄/身高/体重那些结构字段 —— 改身高体重会
/// 牵动模型和物理, 不是这次要试的东西。
fn is_ability(id: u32) -> bool {
    (20..=46).contains(&id) && id != 39
}

/// Calls the original and returns its result untouched. The only thing it adds is a few
/// log lines, and those are rate-limited hard: this runs on the game's own threads and the
/// logger writes synchronously, so logging every call would be a self-inflicted stutter
/// that then gets blamed on the hook.
unsafe extern "system" fn hk_attr_get(player: usize, id: u32) -> u32 {
    let t = TRAMP.load(Ordering::Relaxed);
    if t == 0 {
        return 0; // cannot happen once installed; never guess a value if it did
    }
    let orig: AttrGetFn = std::mem::transmute(t);
    let v = orig(player, id);

    let n = CALLS.fetch_add(1, Ordering::Relaxed);
    // 给统计导出记下 T = [player+0x47C0]: 从它能走到两队花名册 (技能链)。原函数第一件事就是
    // `mov rcx,[rcx+0x47C0]`, 所以这个地址此刻一定可读。每 1024 次记一次, 热路径上几乎零开销。
    if n & 0x3FF == 0 {
        let ctx = *((player + CTX_OFF.load(Ordering::Relaxed)) as *const usize);
        if ctx != 0 {
            crate::statsexport::LAST_CTX.store(ctx, Ordering::Relaxed);
        }
    }
    if n < 40 {
        log_msg(&format!(
            "[ATTR] #{:<3} player=0x{:X} id={} -> {}",
            n, player, id, v
        ));
    } else if n == 40 {
        log_msg("[ATTR] 前 40 条记完; 之后每 500 万次调用报一次, 证明游戏还活着");
    } else if n % 5_000_000 == 0 {
        log_msg(&format!("[ATTR] 已 {} 次调用, 游戏仍在正常运行", n));
    }

    // 改写发生在**返回的那一刻**, 所以后面那张缓存每毫秒被刷多少次都无所谓 ——
    // 这正是单纯写内存做不到、非要钩子不可的原因。
    let home = HOME_VAL.load(Ordering::Relaxed);
    let away = AWAY_VAL.load(Ordering::Relaxed);
    if (home != 0 || away != 0) && is_ability(id) {
        let only = ONLY_ID.load(Ordering::Relaxed);
        if only == 0 || only == id {
            let sel = *(player as *const i8).add(SEL_OFF.load(Ordering::Relaxed)) as i32; // movsx: 这个字节有符号
            let nv = if (HOME_LO..=HOME_HI).contains(&sel) {
                home
            } else if (AWAY_LO..=AWAY_HI).contains(&sel) {
                away
            } else {
                0 // 替补席/裁判之类的槽位一律不碰
            };
            if nv != 0 {
                // 计数器在每次设置变更时清零, 所以前三条就是「这次设置有没有真的吃到」
                // 的即时回执, 带原值和新值。以前只有「每 200 万次记一笔」, 而 ATTR_get
                // 的调用频率远没有那么高 —— 改完之后日志里长时间一片空白, 分不清是
                // 「没生效」还是「还没到 200 万」。
                let k = OVERRIDES.fetch_add(1, Ordering::Relaxed);
                if k < 3 {
                    log_msg(&format!(
                        "[ATTR] 改写#{} sel={} id={} 原值 {} -> {}",
                        k, sel, id, v, nv
                    ));
                } else if k % 500_000 == 0 {
                    log_msg(&format!("[ATTR] 本次设置已改写 {} 次", k));
                }
                return nv;
            }
        }
    }
    v
}

/// 每 250 ms 看一眼 `attrhook.mode`, 把模式塞进原子变量。
///
/// 单独开线程而不是在钩子里读文件, 是因为钩子在游戏自己的线程上、每秒几万次。
/// 好处是**改模式不用重启游戏**: 写一下那个文件, 四分之一秒内生效。
fn spawn_mode_watcher() {
    std::thread::spawn(|| loop {
        let f = std::env::current_dir()
            .unwrap_or_else(|_| std::path::PathBuf::from("."))
            .join("attrhook.mode");
        let txt = std::fs::read_to_string(&f).unwrap_or_default();
        // 旧写法 min/max 继续认, 免得手指记着老命令
        let (mut home, mut away, mut only) = match txt.trim() {
            "min" => (0u32, 40u32, 0u32),
            "max" => (0u32, 99u32, 0u32),
            _ => (0u32, 0u32, 0u32),
        };
        if !matches!(txt.trim(), "min" | "max") {
            for tok in txt.split_whitespace() {
                let (k, val) = match tok.split_once('=') {
                    Some(kv) => kv,
                    None => continue,
                };
                // 越界的值不是拒绝而是夹住: 手滑打个 999 不该让整行配置失效
                let n = match val.trim() {
                    "off" | "0" => 0,
                    other => other.parse::<u32>().unwrap_or(0).min(255),
                };
                match k.trim() {
                    "home" => home = n,
                    "away" => away = n,
                    "id" => only = if val.trim() == "all" { 0 } else { n },
                    _ => {}
                }
            }
        }
        // 三个 swap 都要执行, 所以先各自算出来再合并 —— 写成 `a || b || c` 会短路:
        // 第一个返回 true 时后两个根本不跑, 一轮只更新得了一个值, 要靠下一轮补,
        // 最坏 750 ms 才全部到位 (2026-09-13 从日志里看出来的)。
        let h_changed = HOME_VAL.swap(home, Ordering::Relaxed) != home;
        let a_changed = AWAY_VAL.swap(away, Ordering::Relaxed) != away;
        let i_changed = ONLY_ID.swap(only, Ordering::Relaxed) != only;
        let changed = h_changed || a_changed || i_changed;
        if changed {
            OVERRIDES.store(0, Ordering::Relaxed); // 让下面那三条回执对应这次设置
            log_msg(&format!(
                "[ATTR] 设置更新: 主队={} 客队={} 只改id={}",
                if home == 0 { "不改".into() } else { home.to_string() },
                if away == 0 { "不改".into() } else { away.to_string() },
                if only == 0 { "全部".into() } else { only.to_string() }
            ));
        }
        std::thread::sleep(std::time::Duration::from_millis(250));
    });
}

/// Install the no-op detour, if the gate file is present and the bytes are what we expect.
pub fn install() {
    let gate = std::env::current_dir()
        .unwrap_or_else(|_| std::path::PathBuf::from("."))
        .join(GATE_FILE);
    if !gate.exists() {
        log_msg("[ATTR] 空钩子未启用 (放一个 attrhook.on 到游戏目录即可开启)");
        return;
    }
    // 特征码没解出来 = exe 变了且特征码失效: 不下钩, 不猜
    let Some([target, sel_off, ctx_off]) =
        crate::sigscan::resolved().require("attrhook", ["attr_get", "sel_off", "ctx_off"])
    else {
        return;
    };
    SEL_OFF.store(sel_off, Ordering::Relaxed);
    CTX_OFF.store(ctx_off, Ordering::Relaxed);
    unsafe {
        log_msg(&format!(
            "[ATTR] 特征码定位到 0x{:X} (sel +0x{:X}, ctx +0x{:X}), 开始下钩",
            target, sel_off, ctx_off
        ));
        match RawDetour::new(target as *const (), hk_attr_get as *const ()) {
            Ok(d) => {
                TRAMP.store(d.trampoline() as *const () as usize, Ordering::Relaxed);
                match d.enable() {
                    Ok(()) => {
                        std::mem::forget(d); // 必须活到进程结束: 卸载=游戏跳进野指针
                        log_msg("[ATTR] 钩子已装上; 默认原样透传, 写 attrhook.mode 切 min/max");
                        spawn_mode_watcher();
                    }
                    Err(e) => log_msg(&format!("[ATTR] enable 失败: {:?}", e)),
                }
            }
            Err(e) => log_msg(&format!("[ATTR] 建 detour 失败: {:?}", e)),
        }
    }
}

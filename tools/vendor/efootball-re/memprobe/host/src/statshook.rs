//! 比赛统计数据的定位钩子。
//!
//! # 为什么要下钩子而不是扫内存
//!
//! 2026-09-13 把统计的结构从 exe 里完整解了出来(见 skill `efootball-exe-re`):
//!
//! ```text
//! 管理器   = ctx->[0x200 或 0x3710] + 0x78118   0x1442D6FE0 / 0x1442D6FF0, 然后 0x1442EB9D0
//! 球员块   = mgr + 队伍*0x38238 + 0x65C0 + 槽位*0x13E8     2 队 x 40 槽
//! 块内     = 块 + 0x10 + id*0x24, id 0..0x76 (119 项), 每项 9 个 dword:
//!            +0x10/+0x14/+0x18 上半场三段   +0x1C/+0x20/+0x24 下半场三段
//!            +0x28/+0x2C/+0x30 加时等       全场 = +0x10..+0x2C 八项相加 (0x144337943)
//! 球队合计 = 同一 id 在 40 个槽位上求和      0x14431B4C0
//! ```
//!
//! **结构是确定的, 缺的只有 `ctx` 是什么。** `0x1442D6FF0` 有 181 个调用点, 没有一个
//! 从我们手里已有的全局出发。三条路都试过并且都失败了, 别再走一遍:
//!
//! 1. 拿比赛单例的前 0x8000 逐个 qword 当 ctx —— 没有命中
//! 2. 扩到球员对象内部 0xA000(为了覆盖 `+0x47C0`) —— 还是没有
//! 3. 按结构指纹全内存扫(2.3 GB, 跑了十几分钟) —— **假阳性**:
//!    每个槽位的非零 id 正好间隔 0x2C、基址逐槽等量前移, 那是斜着穿过一片规则内存
//!    读出来的对角线; 而且主队 0 个槽有数据。
//!
//! 所以改成让游戏自己告诉我们地址: 钩住取值函数, 把它的 `rcx` 记下来。
//! 这和当初拿下属性链是同一招。
//!
//! # 这个钩子做什么
//!
//! **只读不改。** 原样转发, 只把看到的 `(块地址, id, half)` 记下来, 并用块地址反推
//! 管理器基址 —— 最小的那个块地址就是 `mgr + 0x65C0`(主队 0 号槽), 于是
//! `mgr = min_block - 0x65C0`。拿到之后写进日志, 插件 cmd 23 就可以用
//! `hot.sh 23 <mgr>` 直接读, 不用再搜。
//!
//! 开关是游戏目录里的 `statshook.on`, 和 attrhook 一样。

use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

use retour::RawDetour;
use windows_sys::Win32::System::Diagnostics::Debug::ReadProcessMemory;
use windows_sys::Win32::System::Threading::GetCurrentProcess;

use crate::log_msg;
use crate::statsexport::Layout;

// 钩子目标 (统计取值, 这个 build 是 0x1443378C0) 和统计块布局都由 sigscan 在运行时按特征码解出,
// 见 signatures.txt 的 team_total / stats_get / player_block。解不出来就不装。

const GATE_FILE: &str = "statshook.on";

static TRAMP: AtomicUsize = AtomicUsize::new(0);
static CALLS: AtomicU64 = AtomicU64::new(0);
/// 见过的最小块地址。主队 0 号槽 = mgr + 0x65C0, 所以它减 0x65C0 就是管理器。
static MIN_BLOCK: AtomicUsize = AtomicUsize::new(usize::MAX);
/// 已经报告过的管理器基址, 用来避免刷屏。
static REPORTED: AtomicUsize = AtomicUsize::new(0);

unsafe extern "system" fn hk_stats_get(block: usize, id: u32, half: u32) -> u32 {
    let t = TRAMP.load(Ordering::Relaxed);
    if t == 0 {
        return 0;
    }
    let orig: unsafe extern "system" fn(usize, u32, u32) -> u32 = std::mem::transmute(t);
    let out = orig(block, id, half);

    let n = CALLS.fetch_add(1, Ordering::Relaxed);
    if n < 8 {
        log_msg(&format!(
            "[STATSHOOK] 调用#{}: 块=0x{:X} id=0x{:02X} half={} -> {}",
            n, block, id, half, out
        ));
    }

    // 只记这个 5 秒窗口里见过的最小块地址; 定 mgr、报告都在 reporter 线程里做,
    // 热路径上不打日志 (每秒几万次调用)。
    let mut cur = MIN_BLOCK.load(Ordering::Relaxed);
    while block != 0 && block < cur {
        match MIN_BLOCK.compare_exchange_weak(cur, block, Ordering::Relaxed, Ordering::Relaxed) {
            Ok(_) => break,
            Err(v) => cur = v,
        }
    }
    out
}

/// 每 5 秒: 用这个窗口里见过的最小块重新定 mgr, 再按已标出的 id 打一行两队合计。
///
/// **为什么按窗口重算** (2026-09-13 15:35 实测到的 bug): 原版只记整个进程生命周期里的最小块。
/// 第二场比赛开始后旧 mgr 整片归零、新 mgr 换了地址 —— 那次碰巧更低才报出来,
/// 分配到更高地址就会一直报上一场的。每秒几万次调用会扫遍所有槽位, 5 秒窗口足够。
fn spawn_reporter(lay: &'static Layout) {
    // 2026-09-13 靠三次快照、两场比赛和界面对出来的 id (实测唯一)。
    const LABELS: [(&str, usize); 10] = [
        ("射门", 0x06), ("射正", 0x16), ("传球", 0x18), ("成功传球", 0x19), ("横传", 0x20),
        ("抢球", 0x35), ("犯规", 0x3C), ("越位", 0x3D), ("角球", 0x44), ("拦截", 0x50),
    ];
    std::thread::spawn(move || {
      let mut exporter = crate::statsexport::Exporter::new();
      loop {
        std::thread::sleep(std::time::Duration::from_millis(5000));
        let calls = CALLS.load(Ordering::Relaxed);
        if calls == 0 {
            continue;
        }
        let win_min = MIN_BLOCK.swap(usize::MAX, Ordering::Relaxed);
        let cur = REPORTED.load(Ordering::Relaxed);
        if win_min != usize::MAX {
            let cand = win_min.wrapping_sub(lay.players_off);
            // 窗口里只出现客队块时, 最小块是客队 0 号槽, 别把它当成换场。
            if cand != cur && !(cur != 0 && cand == cur + lay.team_stride) {
                REPORTED.store(cand, Ordering::Relaxed);
                log_msg(&format!(
                    "[STATSHOOK] ★ 管理器 = 0x{:X}  (窗口最小块 0x{:X} - 0x{:X}){}",
                    cand, win_min, lay.players_off,
                    if cur == 0 { "" } else { "  —— 换了, 多半是新一场" }
                ));
                log_msg(&format!("[STATSHOOK]   读数据: ./hot.sh 23 {} \"0,119\"", cand));
            }
        }
        let mgr = REPORTED.load(Ordering::Relaxed);
        if mgr == 0 {
            log_msg(&format!("[STATSHOOK] {} 次调用, 还没定出管理器", calls));
            continue;
        }
        // 自检兼实用: 按已标出的 id 算两队合计 (40 个槽位求和, 同 0x14431B4C0)。
        let mut parts = Vec::new();
        let mut unreadable = false;
        for (name, id) in LABELS {
            if id >= lay.ids {
                continue;
            }
            let mut t = [0u32; 2];
            for team in 0..2usize {
                for idx in 0..lay.slots {
                    let block = mgr + team * lay.team_stride + lay.players_off + idx * lay.player_stride;
                    match unsafe { read_total(block + lay.entry_off, id) } {
                        Some(v) => t[team] = t[team].wrapping_add(v),
                        None => unreadable = true,
                    }
                }
            }
            parts.push(format!("{} {}:{}", name, t[0], t[1]));
        }
        log_msg(&format!(
            "[STATSHOOK] {} 次调用, mgr=0x{:X}{} | {}",
            calls,
            mgr,
            if unreadable { " (有块读不到 —— mgr 多半推错了)" } else { "" },
            parts.join("  ")
        ));
        // 读不到也要调: tick 里要靠「单例为 null」判断回到菜单、给上一场定稿。
        exporter.tick(mgr);
      }
    });
}

/// 全场合计, 照抄 `0x144337943` 那条分支: 项起点起 **八个** dword 相加。
/// `entries` = 块 + 项起点偏移 (这个 build 是 +0x10, 由 sigscan 从跳转表解出); 每项 0x24 字节。
///
/// 2026-09-13 修过两处:
/// 1. 原来读的是 `+0x04..+0x1C` 七个 —— 早了 12 字节, 算出来的合计全是错的。
/// 2. 原来直接解引用裸指针。mgr 是从「见过的最小块地址」反推的, 推错了这里就读到未映射页,
///    **宿主线程访问违例 = 整个游戏崩掉**。改走 ReadProcessMemory, 读不到只返回 None。
unsafe fn read_total(entries: usize, id: usize) -> Option<u32> {
    let mut b = [0u8; 8 * 4];
    let mut got: usize = 0;
    let ok = ReadProcessMemory(
        GetCurrentProcess(),
        (entries + id * 0x24) as _,
        b.as_mut_ptr() as _,
        b.len(),
        &mut got,
    );
    if ok == 0 || got != b.len() {
        return None;
    }
    Some(b.chunks_exact(4).map(|c| u32::from_le_bytes([c[0], c[1], c[2], c[3]])).fold(0u32, |a, v| a.wrapping_add(v)))
}

/// 装钩子。要游戏目录里有 `statshook.on`, 且特征码解出了钩子目标和统计块布局。
pub fn install() {
    let gate = std::env::current_dir()
        .unwrap_or_else(|_| std::path::PathBuf::from("."))
        .join(GATE_FILE);
    if !gate.exists() {
        log_msg("[STATSHOOK] 未启用 (放一个 statshook.on 到游戏目录即可开启)");
        return;
    }
    // 特征码没解出来 = exe 变了且特征码失效: 宁可没数据也不要打歪
    let Some([target]) = crate::sigscan::resolved().require("statshook", ["stats_get"]) else { return };
    let Some(lay) = crate::statsexport::layout() else { return };
    unsafe {
        log_msg(&format!(
            "[STATSHOOK] 特征码定位到 0x{:X} (ids={} 槽={} 块偏移=0x{:X} 槽距=0x{:X} 队距=0x{:X} 项起点=0x{:X}), 开始下钩",
            target, lay.ids, lay.slots, lay.players_off, lay.player_stride, lay.team_stride, lay.entry_off
        ));
        match RawDetour::new(target as *const (), hk_stats_get as *const ()) {
            Ok(d) => {
                TRAMP.store(d.trampoline() as *const () as usize, Ordering::Relaxed);
                match d.enable() {
                    Ok(()) => {
                        std::mem::forget(d); // 必须活到进程结束: 卸载=游戏跳进野指针
                        log_msg("[STATSHOOK] 钩子已装上 (只读, 原样透传); 进比赛后看 ★ 那行");
                        spawn_reporter(lay);
                    }
                    Err(e) => log_msg(&format!("[STATSHOOK] enable 失败: {:?}", e)),
                }
            }
            Err(e) => log_msg(&format!("[STATSHOOK] 建 detour 失败: {:?}", e)),
        }
    }
}

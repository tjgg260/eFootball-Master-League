//! 比赛统计导出 —— 给外置大师联赛用的原始数据。
//!
//! statshook 的 reporter 线程每 5 秒调一次 [`Exporter::tick`]:
//!
//! 1. 按 mgr 读两队 x 40 槽 x 119 个 id 的 9 段计数 (布局见 statshook.rs 开头)
//! 2. 比赛进行中顺手抓上下文: 属性表 (年龄/身高/26 项能力, 赛前状态前后两份)、
//!    花名册记录 (出场表、技能位、整条 0x198 字节原文 —— 找 PID 用)
//! 3. 数值变了就重写 `<游戏根目录>\ml_stats\live.json`
//! 4. 定稿成 `match_<首次看到的时间>.json` 的三种时机 (final_reason):
//!    - `left_match`: 比赛单例连续 15 秒为 null = 回到菜单了
//!    - `counters_reset` / `manager_changed`: 计数变小 = 下一场开始了 (同一场里只增不减)
//!    - `host_restart`: 宿主启动时发现上次留下的 live.json (游戏中途退出/崩溃)
//!    不依赖「终场哨」这个时刻 —— 结算画面和集锦期间计数还在涨 (2026-09-13 15:59 实测)。
//!
//! **评分不在这里算**: 宿主改一次要重启游戏, 评分公式要反复调, 放在 `mlstats/` 的 Python 里,
//! 读这里的 JSON、把评分写回去。
//!
//! 所有读内存都走 ReadProcessMemory: 这是游戏进程里的线程, 解引用野指针 = 整个游戏崩。

use std::fmt::Write as _;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::OnceLock;

use windows_sys::Win32::System::Diagnostics::Debug::ReadProcessMemory;
use windows_sys::Win32::System::LibraryLoader::GetModuleFileNameW;
use windows_sys::Win32::System::Threading::GetCurrentProcess;

use crate::log_msg;

// ---- 数据格式本身, 不是代码里的位移: 没有可做特征码的引用, 游戏更新后要人工复核 ----
const SEGS: usize = 9; // 每个 id 9 段, 全场 = 前 8 段 (0x144337943)
const ENTRY: usize = 0x24; // = 9 * 4, 由 stats_get 的 `lea rcx,[rax+rax*8]` 和 *4 寻址定死 (特征码里固定)
const ATTR_LEN: usize = 0x3d; // 61 字节属性数组; 档案原值那份紧跟在叠状态那份后面
const ID_AGE: usize = 49;
const ID_HEIGHT: usize = 50;
const ON_PITCH: usize = 22;
/// PID 在记录视图前 8 字节: PID(槽位 j) = u64 [teamobj + rec_off - 8 + j*rec_len]。
/// 2026-09-13 从真实导出找到: 每条记录视图的 +0x190 是下一个槽位的完整 64 位 PID,
/// 两队 20 对相邻槽位全中, 和 dt200 按球衣号+年龄身高对出来的 PID 逐个相等 (已验证)。
const PID_BEFORE_REC: usize = 8;
// 相对记录视图
const SHIRT_NUMBER_OFF: usize = 0xfc; // u8, 两队 24 人和结算画面号码逐个对上 (已验证)
const SHIRT_NAME_OFF: usize = 0x113; // UTF-8, NUL 结尾: RAYA / KAKÁ / MÜLLER
const SHIRT_NAME_MAX: usize = 40;

/// 运行时从特征码解出来的布局 (sigscan.rs + signatures.txt), 游戏更新后偏移变了会跟着变。
/// 括号里是 2026-09-13 这个 build 的值。
pub struct Layout {
    pub ids: usize,           // 0x77  stats_get 的 `cmp edx,imm8` + 1
    pub slots: usize,         // 0x28
    pub entry_off: usize,     // 0x10  half 跳转表第 0 项里的位移
    pub players_off: usize,   // 0x65C0
    pub player_stride: usize, // 0x13E8
    pub team_stride: usize,   // 0x38238
    attrs: Option<AttrLayout>,
    roster: Option<RosterLayout>,
}

struct AttrLayout {
    singleton: usize, // 比赛单例格子的绝对地址 (0x1486BD888)
    table_off: usize, // 0x55A8
    stride: usize,    // 0x58
    form_off: usize,  // 0x394
}

struct RosterLayout {
    teamobj_off: usize, // 0x3BD0
    team_stride: usize, // 0x58
    lineup_off: usize,  // 4
    rec_off: usize,     // 0xE8  记录视图起点
    rec_len: usize,     // 0x198
    skill_off: usize,   // 0xC0
    skill_bits: usize,  // 0x49
}

static LAYOUT: OnceLock<Option<Layout>> = OnceLock::new();

/// 统计部分必需; 属性表或花名册解不出来时只导出统计, 对应字段为 null, 不猜。
pub fn layout() -> Option<&'static Layout> {
    LAYOUT
        .get_or_init(|| {
            let r = crate::sigscan::resolved();
            let [max_id, slots, entry_off, players_off, player_stride, team_stride] = r.require(
                "统计导出",
                ["max_id", "stat_slots", "stat_entry_off", "players_off", "player_stride", "stats_team_stride"],
            )?;
            let attrs = r
                .require("导出里的属性", ["singleton", "attr_table_off", "attr_stride", "attr_form_off"])
                .map(|[singleton, table_off, stride, form_off]| AttrLayout { singleton, table_off, stride, form_off });
            let roster = r
                .require(
                    "导出里的花名册/PID",
                    ["team_obj_off", "team_stride", "lineup_off", "rec_off", "rec_stride", "skill_off", "skill_bits"],
                )
                .map(|[teamobj_off, team_stride, lineup_off, rec_off, rec_len, skill_off, skill_bits]| RosterLayout {
                    teamobj_off, team_stride, lineup_off, rec_off, rec_len, skill_off, skill_bits,
                });
            Some(Layout { ids: max_id + 1, slots, entry_off, players_off, player_stride, team_stride, attrs, roster })
        })
        .as_ref()
}

/// Exporter 只在 layout() 解出来之后才会被创建 (statshook 保证)。
fn l() -> &'static Layout {
    layout().expect("layout resolved before Exporter")
}

/// attrhook 顺手记下的 T = [player+0x47C0]。统计 ctx 和技能链的 T 是同一种对象,
/// 从它能走到两队花名册。没装 attrhook 就一直是 0, 导出里 roster 相关字段为 null。
pub static LAST_CTX: AtomicUsize = AtomicUsize::new(0);

/// (id, 英文键, 中文, 可信度)。measured = 三次快照两场比赛唯一对上界面。
pub const LABELS: [(usize, &str, &str, &str); 21] = [
    (0x06, "shots", "射门", "measured"),
    (0x16, "shots_on_target", "射正", "measured"),
    (0x18, "passes", "传球", "measured"),
    (0x19, "passes_completed", "成功传球", "measured"),
    (0x20, "crosses", "横传", "measured"),
    (0x35, "tackles", "抢球", "measured"),
    (0x3c, "fouls", "犯规", "measured"),
    (0x3d, "offsides", "越位", "measured"),
    (0x44, "corners", "角球", "measured"),
    (0x50, "interceptions", "拦截", "measured"),
    (0x00, "goals", "进球", "inferred: always equal to 0x11 in 3 snapshots"),
    (0x6f, "saves", "扑救", "inferred: always equal to 0x71"),
    (0x6d, "gk_shots_faced", "门将面对射门", "inferred: equals opponent shots 4/4"),
    (0x6e, "gk_shots_on_target_faced", "门将面对射正", "inferred: equals opponent shots on target 4/4"),
    // 2026-09-13 受控实验 (plugin cmd 28, 每 50 ms 记变化, 用户按步骤操作):
    (0x48, "ball_receptions", "接球/获得球权", "measured: +1 on receiving a pass (same poll as the passer's pass, 9/9) or winning the ball"),
    (0x49, "ball_touches", "触球处理次数", "measured: one-touch pass +1 at reception (no possession); controlled possession +1 when it ends"),
    (0x46, "possessions", "控球次数", "measured: +1 when a controlled possession ends (not one-touch, not kickoff); counted only once it ends"),
    (0x47, "possessions_retained", "控球后保住球权", "measured: as 0x46 but only when the team kept the ball (2 losses: 0x46 only)"),
    (0x4b, "possession_time", "控球时长", "measured: 48 units per real second, same in 5- and 6-minute matches, standing still counts; added when a possession ends"),
    (0x4f, "ball_recoveries", "夺回球权", "measured: +1 on a steal and a tackle win (2/2)"),
    (0x4c, "sprints", "冲刺", "measured: continuous sprinting adds +1 every ~2.5-7.5 s (9 in 33 s); off-ball too; GK always 0"),
];

const CAVEATS: [&str; 5] = [
    "stats slot == roster slot (0..39): measured 2026-09-13, substitutes land in the slots the lineup points to",
    "segments: 9 dwords per id; total = first 8. Meaning of individual segments (e.g. 15-minute periods) is unverified",
    "player_id = u64 at teamobj+0xE0+slot*0x198, the full 64-bit dt200 PID (verified 20/20 against dt200); roster_record_hex starts 8 bytes after it",
    "attributes are captured while the player is on the pitch; form = after pre-match condition, base = file value",
    "labels marked inferred may be swapped with a twin id; see labels[].confidence",
];

fn rpm(addr: usize, buf: &mut [u8]) -> bool {
    if addr < 0x1_0000 {
        return false;
    }
    let mut got = 0usize;
    let ok = unsafe {
        ReadProcessMemory(GetCurrentProcess(), addr as _, buf.as_mut_ptr() as _, buf.len(), &mut got)
    };
    ok != 0 && got == buf.len()
}

fn read_ptr(addr: usize) -> Option<usize> {
    let mut b = [0u8; 8];
    if !rpm(addr, &mut b) {
        return None;
    }
    let v = u64::from_le_bytes(b) as usize;
    (v >= 0x1_0000 && v <= 0x7FFF_FFFF_FFFF).then_some(v)
}

fn now_rfc3339() -> String {
    chrono::Local::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, false)
}

struct Snapshot {
    mgr: usize,
    taken: String,
    /// [team*slots + slot] -> ids*SEGS 个 dword; 全 0 的槽位是空 Vec
    segs: Vec<Vec<u32>>,
    totals: Vec<Vec<u64>>, // [2][ids]
}

impl Snapshot {
    fn read(mgr: usize) -> Option<Snapshot> {
        let lay = l();
        let mut buf = vec![0u8; lay.entry_off + lay.ids * ENTRY];
        let mut segs = Vec::with_capacity(2 * lay.slots);
        let mut totals = vec![vec![0u64; lay.ids]; 2];
        let mut wild = 0usize;
        for team in 0..2 {
            for slot in 0..lay.slots {
                let block = mgr + team * lay.team_stride + lay.players_off + slot * lay.player_stride;
                if !rpm(block, &mut buf) {
                    return None;
                }
                let mut v = vec![0u32; lay.ids * SEGS];
                let mut any = false;
                for id in 0..lay.ids {
                    for k in 0..SEGS {
                        let o = lay.entry_off + id * ENTRY + k * 4;
                        let x = u32::from_le_bytes([buf[o], buf[o + 1], buf[o + 2], buf[o + 3]]);
                        v[id * SEGS + k] = x;
                        if k < 8 {
                            totals[team][id] += x as u64;
                        }
                        any |= x != 0;
                        wild += (x > 1_000_000) as usize;
                    }
                }
                segs.push(if any { v } else { Vec::new() });
            }
        }
        // mgr 推错时读到的是任意堆内存: 真统计是稀疏的小计数。
        if wild > 16 {
            log_msg(&format!("[EXPORT] mgr 0x{:X} 读出 {} 个超大值, 不像统计, 跳过", mgr, wild));
            return None;
        }
        Some(Snapshot { mgr, taken: now_rfc3339(), segs, totals })
    }

    fn is_empty(&self) -> bool {
        self.totals.iter().all(|t| t.iter().all(|&x| x == 0))
    }

    /// 上一份快照之后有计数变小 = 新的一场开始了 (或数据被清掉)。
    /// 容一两个 id 的回调 (比如判罚改判), 传球数变小或 3 个以上 id 变小才算。
    fn looks_like_new_match(&self, prev: &Snapshot) -> bool {
        let mut dropped = 0;
        for t in 0..2 {
            for id in 0..l().ids {
                if self.totals[t][id] < prev.totals[t][id] {
                    if id == 0x18 {
                        return true;
                    }
                    dropped += 1;
                }
            }
        }
        dropped >= 3
    }
}

#[derive(Clone, Default)]
struct PlayerCtx {
    pid: Option<u64>,
    attr_sel: Option<usize>,
    attr_mapping: Option<&'static str>,
    form: Option<[u8; ATTR_LEN]>,
    base: Option<[u8; ATTR_LEN]>,
    record: Option<Vec<u8>>,
}

#[derive(Clone)]
struct MatchCtx {
    players: Vec<PlayerCtx>, // 2*slots
    lineup: [Option<Vec<i32>>; 2],
    teamobj: [usize; 2],
}

impl Default for MatchCtx {
    fn default() -> Self {
        MatchCtx { players: vec![PlayerCtx::default(); 2 * l().slots], lineup: [None, None], teamobj: [0, 0] }
    }
}

impl MatchCtx {
    /// 花名册: T -> teamobj -> 出场表 + 40 条记录。出场表前 11 项必须是互不相同的 0..slots, 否则当作
    /// T 已经失效 (比赛结束后 LAST_CTX 可能指向被复用的内存)。
    fn capture_roster(&mut self) {
        let lay = l();
        let Some(ro) = &lay.roster else { return };
        let t = LAST_CTX.load(Ordering::Relaxed);
        if t == 0 || ro.rec_off < PID_BEFORE_REC {
            return;
        }
        let mut buf = vec![0u8; ro.rec_off + lay.slots * ro.rec_len];
        for team in 0..2 {
            let Some(obj) = read_ptr(t + ro.teamobj_off + team * ro.team_stride) else { continue };
            if !rpm(obj, &mut buf) {
                continue;
            }
            let lineup: Vec<i32> = (0..lay.slots)
                .map(|k| {
                    let o = ro.lineup_off + k * 4;
                    i32::from_le_bytes([buf[o], buf[o + 1], buf[o + 2], buf[o + 3]])
                })
                .collect();
            let starters = &lineup[..11];
            let valid = starters.iter().all(|&j| (0..lay.slots as i32).contains(&j))
                && (0..11).all(|a| (a + 1..11).all(|b| starters[a] != starters[b]));
            if !valid {
                continue;
            }
            self.lineup[team] = Some(lineup);
            self.teamobj[team] = obj;
            for j in 0..lay.slots {
                let r = &buf[ro.rec_off + j * ro.rec_len..ro.rec_off + (j + 1) * ro.rec_len];
                if r.iter().any(|&b| b != 0) {
                    let pc = &mut self.players[team * lay.slots + j];
                    pc.record = Some(r.to_vec());
                    let o = ro.rec_off - PID_BEFORE_REC + j * ro.rec_len;
                    let pid = u64::from_le_bytes(buf[o..o + 8].try_into().unwrap());
                    pc.pid = (pid != 0).then_some(pid);
                }
            }
        }
    }

    /// 属性表: 22 个在场槽位, 指针是瞬态的 (match-attr-chain 坑 1), 轮询最多 60 ms。
    /// sel -> 统计槽位: 有出场表就走游戏自己的映射 lineup[sel % 11] (技能链 0x1442C3050),
    /// 没有就假定槽位 == sel % 11 并在导出里注明。
    fn capture_attributes(&mut self) {
        let lay = l();
        let Some(at) = &lay.attrs else { return };
        let Some(sing) = read_ptr(at.singleton) else { return };
        let mut done = [false; ON_PITCH];
        let start = std::time::Instant::now();
        while start.elapsed().as_millis() < 60 && !done.iter().all(|&d| d) {
            for sel in 0..ON_PITCH {
                if done[sel] {
                    continue;
                }
                let Some(p) = read_ptr(sing + at.table_off + sel * at.stride) else { continue };
                let mut form = [0u8; ATTR_LEN];
                let mut basev = [0u8; ATTR_LEN];
                if !rpm(p + at.form_off, &mut form) || !rpm(p + at.form_off + ATTR_LEN, &mut basev) {
                    continue;
                }
                if !(14..=50).contains(&form[ID_AGE]) || !(140..=215).contains(&form[ID_HEIGHT]) {
                    continue; // 指针在读的途中被换掉了
                }
                let team = sel / 11;
                let idx = sel % 11;
                let (slot, how) = match &self.lineup[team] {
                    Some(lu) => (lu[idx] as usize, "lineup"),
                    None => (idx, "assumed_slot_equals_index"),
                };
                if slot >= lay.slots {
                    continue;
                }
                let pc = &mut self.players[team * lay.slots + slot];
                pc.attr_sel = Some(sel);
                pc.attr_mapping = Some(how);
                pc.form = Some(form);
                pc.base = Some(basev);
                done[sel] = true;
            }
            std::thread::sleep(std::time::Duration::from_millis(1));
        }
    }
}

pub struct Exporter {
    dir: PathBuf,
    current: Option<Snapshot>,
    ctx: MatchCtx,
    first_seen: String,
    stem: String,
    null_ticks: u32,
}

impl Exporter {
    pub fn new() -> Exporter {
        let dir = export_dir();
        if let Err(e) = std::fs::create_dir_all(&dir) {
            log_msg(&format!("[EXPORT] 建目录 {:?} 失败: {}", dir, e));
        }
        let ex = Exporter {
            dir,
            current: None,
            ctx: MatchCtx::default(),
            first_seen: String::new(),
            stem: String::new(),
            null_ticks: 0,
        };
        ex.finalize_leftover_live();
        log_msg(&format!("[EXPORT] 比赛统计导出到 {:?}", ex.dir));
        ex
    }

    /// 每 5 秒一次。mgr 由 statshook 按窗口最小块定出。
    pub fn tick(&mut self, mgr: usize) {
        // 回到菜单 = 比赛单例为 null (match-attr-chain, 实测)。连续 3 次 (15 秒) 才算,
        // 免得回放/过场里短暂为 null 就把一场切成两个文件 —— 这个 15 秒是推断, 没实测过过场。
        // 单例格子解不出来 (属性特征码失效) 就没有这条信号, 只剩「计数变小」和「宿主重启」定稿
        let in_menu = l().attrs.as_ref().map_or(false, |a| read_ptr(a.singleton).is_none());
        if in_menu {
            self.null_ticks += 1;
            if self.null_ticks >= 3 {
                if let Some(prev) = self.current.take() {
                    self.write_final(&prev, "left_match");
                    self.ctx = MatchCtx::default();
                }
            }
            return;
        }
        self.null_ticks = 0;

        let Some(snap) = Snapshot::read(mgr) else { return };

        if let Some(prev) = &self.current {
            if snap.looks_like_new_match(prev) {
                let reason = if prev.mgr != snap.mgr { "manager_changed" } else { "counters_reset" };
                let prev = self.current.take().unwrap();
                self.write_final(&prev, reason);
                self.ctx = MatchCtx::default();
            }
        }
        if snap.is_empty() {
            return;
        }
        let changed = self.current.as_ref().map_or(true, |c| c.totals != snap.totals || c.mgr != snap.mgr);
        if self.current.is_none() {
            self.first_seen = snap.taken.clone();
            self.stem = chrono::Local::now().format("match_%Y%m%d_%H%M%S").to_string();
            log_msg(&format!("[EXPORT] 新的一场, mgr=0x{:X}, 文件 {}.json", snap.mgr, self.stem));
        }
        if changed {
            // 上下文只在计数还在变 (= 比赛进行中) 时抓: 赛后 T 和属性表可能已经失效。
            self.ctx.capture_roster();
            self.ctx.capture_attributes();
            let json = self.render(&snap, None);
            write_atomic(&self.dir.join("live.json"), &json);
        }
        self.current = Some(snap);
    }

    fn write_final(&self, snap: &Snapshot, reason: &str) {
        let path = self.dir.join(format!("{}.json", self.stem));
        write_atomic(&path, &self.render(snap, Some(reason)));
        let _ = std::fs::remove_file(self.dir.join("live.json"));
        log_msg(&format!("[EXPORT] ★ 定稿 {:?} (原因 {})", path, reason));
    }

    fn finalize_leftover_live(&self) {
        let live = self.dir.join("live.json");
        let Ok(txt) = std::fs::read_to_string(&live) else { return };
        let stem = txt
            .split("\"file_stem\": \"")
            .nth(1)
            .and_then(|s| s.split('"').next())
            .unwrap_or("match_unknown")
            .to_string();
        let fixed = txt
            .replacen("\"final\": false,", "\"final\": true,", 1)
            .replacen("\"final_reason\": null,", "\"final_reason\": \"host_restart\",", 1);
        let path = self.dir.join(format!("{}.json", stem));
        write_atomic(&path, &fixed);
        let _ = std::fs::remove_file(&live);
        log_msg(&format!("[EXPORT] 上次留下的 live.json 已定稿为 {:?} (原因 host_restart)", path));
    }

    fn render(&self, snap: &Snapshot, final_reason: Option<&str>) -> String {
        let mut s = String::with_capacity(512 * 1024);
        let _ = writeln!(s, "{{");
        let _ = writeln!(s, "  \"schema\": \"efootball-re/match-stats/1\",");
        let _ = writeln!(s, "  \"final\": {},", final_reason.is_some());
        let _ = writeln!(s, "  \"final_reason\": {},", final_reason.map_or("null".to_string(), |r| format!("\"{}\"", r)));
        let _ = writeln!(s, "  \"file_stem\": \"{}\",", self.stem);
        let _ = writeln!(s, "  \"first_seen\": \"{}\",", self.first_seen);
        let _ = writeln!(s, "  \"snapshot_at\": \"{}\",", snap.taken);
        let _ = writeln!(s, "  \"manager\": \"0x{:X}\",", snap.mgr);

        let _ = writeln!(s, "  \"labels\": {{");
        for (k, (id, key, zh, conf)) in LABELS.iter().enumerate() {
            let _ = writeln!(
                s,
                "    \"0x{:02X}\": {{\"key\": \"{}\", \"zh\": \"{}\", \"confidence\": \"{}\"}}{}",
                id, key, zh, conf, if k + 1 < LABELS.len() { "," } else { "" }
            );
        }
        let _ = writeln!(s, "  }},");

        let _ = writeln!(s, "  \"caveats\": [");
        for (k, c) in CAVEATS.iter().enumerate() {
            let _ = writeln!(s, "    \"{}\"{}", c, if k + 1 < CAVEATS.len() { "," } else { "" });
        }
        let _ = writeln!(s, "  ],");

        let _ = writeln!(s, "  \"teams\": [");
        for team in 0..2 {
            let _ = writeln!(s, "    {{");
            let _ = writeln!(s, "      \"side\": \"{}\",", if team == 0 { "home" } else { "away" });
            let _ = writeln!(s, "      \"totals\": {},", labeled_obj(|id| snap.totals[team][id]));
            let _ = writeln!(s, "      \"raw_totals\": {},", raw_totals_obj(&snap.totals[team]));
            match &self.ctx.lineup[team] {
                Some(lu) => {
                    let _ = writeln!(s, "      \"teamobj\": \"0x{:X}\",", self.ctx.teamobj[team]);
                    let _ = writeln!(s, "      \"lineup\": [{}],", lu.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(", "));
                }
                None => {
                    let _ = writeln!(s, "      \"teamobj\": null,\n      \"lineup\": null,");
                }
            }
            let _ = writeln!(s, "      \"players\": [");
            let mut first = true;
            let slots = l().slots;
            for slot in 0..slots {
                let segs = &snap.segs[team * slots + slot];
                let pc = &self.ctx.players[team * slots + slot];
                if segs.is_empty() && pc.form.is_none() {
                    continue;
                }
                if !first {
                    let _ = writeln!(s, ",");
                }
                first = false;
                render_player(&mut s, slot, segs, pc, self.ctx.lineup[team].as_deref());
            }
            let _ = writeln!(s, "\n      ]");
            let _ = writeln!(s, "    }}{}", if team == 0 { "," } else { "" });
        }
        let _ = writeln!(s, "  ]");
        let _ = writeln!(s, "}}");
        s
    }
}

fn render_player(s: &mut String, slot: usize, segs: &[u32], pc: &PlayerCtx, lineup: Option<&[i32]>) {
    let lay = l();
    let total = |id: usize| -> u64 {
        if segs.is_empty() { 0 } else { segs[id * SEGS..id * SEGS + 8].iter().map(|&x| x as u64).sum() }
    };
    let lineup_index = lineup.and_then(|l| l[..11].iter().position(|&j| j as usize == slot));
    let _ = writeln!(s, "        {{");
    let _ = writeln!(s, "          \"slot\": {},", slot);
    let _ = writeln!(s, "          \"player_id\": {},", pc.pid.map_or("null".into(), |p| p.to_string()));
    let (number, name) = match &pc.record {
        Some(r) if r.len() > SHIRT_NAME_OFF => {
            let raw = &r[SHIRT_NAME_OFF..(SHIRT_NAME_OFF + SHIRT_NAME_MAX).min(r.len())];
            let end = raw.iter().position(|&b| b == 0).unwrap_or(raw.len());
            // UTF-8, 不是 ASCII: KAKÁ / MÜLLER 带重音 (2026-09-13 实测)
            let name = String::from_utf8_lossy(&raw[..end]);
            (r[SHIRT_NUMBER_OFF].to_string(), format!("\"{}\"", json_escape(&name)))
        }
        _ => ("null".into(), "null".into()),
    };
    let _ = writeln!(s, "          \"shirt_number\": {},", number);
    let _ = writeln!(s, "          \"shirt_name\": {},", name);
    let _ = writeln!(s, "          \"lineup_index\": {},", opt_num(lineup_index));
    let _ = writeln!(s, "          \"attr_sel\": {},", opt_num(pc.attr_sel));
    let _ = writeln!(s, "          \"attr_mapping\": {},", pc.attr_mapping.map_or("null".into(), |m| format!("\"{}\"", m)));
    let _ = writeln!(s, "          \"actions\": {},", labeled_obj(|id| total(id)));
    // 非零 id 的 9 段原始计数
    let mut raw = Vec::new();
    if !segs.is_empty() {
        for id in 0..lay.ids {
            let v = &segs[id * SEGS..id * SEGS + SEGS];
            if v.iter().any(|&x| x != 0) {
                raw.push(format!("\"0x{:02X}\": [{}]", id, v.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(",")));
            }
        }
    }
    let _ = writeln!(s, "          \"raw_segments\": {{{}}},", raw.join(", "));
    let _ = writeln!(s, "          \"attributes_form\": {},", opt_bytes(pc.form.as_ref().map(|a| &a[..])));
    let _ = writeln!(s, "          \"attributes_base\": {},", opt_bytes(pc.base.as_ref().map(|a| &a[..])));
    match (&pc.record, &lay.roster) {
        (Some(r), Some(ro)) => {
            let mut ids = Vec::new();
            for id in 0..ro.skill_bits {
                let o = ro.skill_off + (id >> 5) * 4;
                if o + 4 > r.len() {
                    break;
                }
                let w = u32::from_le_bytes([r[o], r[o + 1], r[o + 2], r[o + 3]]);
                if w >> (id & 31) & 1 == 1 {
                    ids.push(id.to_string());
                }
            }
            let _ = writeln!(s, "          \"skills\": [{}],", ids.join(", "));
            let hex: String = r.iter().map(|b| format!("{:02X}", b)).collect();
            let _ = write!(s, "          \"roster_record_hex\": \"{}\"\n        }}", hex);
        }
        _ => {
            let _ = write!(s, "          \"skills\": null,\n          \"roster_record_hex\": null\n        }}");
        }
    }
}

fn labeled_obj(get: impl Fn(usize) -> u64) -> String {
    let parts: Vec<String> = LABELS.iter().map(|(id, key, _, _)| format!("\"{}\": {}", key, get(*id))).collect();
    format!("{{{}}}", parts.join(", "))
}

fn raw_totals_obj(t: &[u64]) -> String {
    let parts: Vec<String> = (0..t.len()).filter(|&i| t[i] != 0).map(|i| format!("\"0x{:02X}\": {}", i, t[i])).collect();
    format!("{{{}}}", parts.join(", "))
}

fn json_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

fn opt_num(v: Option<usize>) -> String {
    v.map_or("null".into(), |x| x.to_string())
}

fn opt_bytes(v: Option<&[u8]>) -> String {
    v.map_or("null".into(), |b| format!("[{}]", b.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(",")))
}

/// 先写 .tmp 再改名: 外部程序永远读不到写了一半的文件。
fn write_atomic(path: &Path, content: &str) {
    let tmp = path.with_extension("json.tmp");
    if let Err(e) = std::fs::write(&tmp, content) {
        log_msg(&format!("[EXPORT] 写 {:?} 失败: {}", tmp, e));
        return;
    }
    if let Err(e) = std::fs::rename(&tmp, path) {
        log_msg(&format!("[EXPORT] 改名 {:?} 失败: {}", path, e));
    }
}

/// `<游戏根目录>\ml_stats`。exe 在 `<根>\eFootball\Binaries\Win64\eFootball.exe`, 往上 4 层。
/// 不用工作目录: 游戏启动后会改它 (AGENT_HANDBOOK 坑 3)。
fn export_dir() -> PathBuf {
    let mut w = [0u16; 1024];
    let n = unsafe { GetModuleFileNameW(0, w.as_mut_ptr(), w.len() as u32) } as usize;
    let exe = PathBuf::from(String::from_utf16_lossy(&w[..n]));
    exe.ancestors()
        .nth(4)
        .filter(|p| !p.as_os_str().is_empty())
        .map(Path::to_path_buf)
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default())
        .join("ml_stats")
}

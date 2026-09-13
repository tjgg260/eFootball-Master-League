//! 运行时特征码定位: 游戏更新后地址和结构偏移变了也能自己找回来。
//!
//! 特征码和解析规则在 `../signatures.txt` (编译进宿主), exetool.py 的 `sigs` 子命令读同一份,
//! 游戏更新后先离线跑 `py exetool.py sigs --live` 看哪条失效。
//!
//! 流程: 扫描所有可执行节 (按节权限选; 这个 build 的游戏代码在 .xcode, .text 是 Denuvo 的)
//! → 每条特征码必须恰好剩 1 处 (at= 顺着调用关系走过去, =键 用已解出的值做约束)
//! → 捕获出函数地址、单例地址、结构偏移。任何一条失败, 依赖它的功能就不装, 不猜。
//!
//! 游戏里所有读取走 ReadProcessMemory: 可执行节里有 Denuvo 的区域, 直接解引用碰到不可读页 = 游戏崩。
//! 解析逻辑只通过 `Rd` 读字节, 所以单测能拿原封 exe 文件喂进来离线验证 (见文件末尾)。

use std::collections::HashMap;
use std::sync::OnceLock;

use windows_sys::Win32::System::Diagnostics::Debug::ReadProcessMemory;
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::Threading::GetCurrentProcess;

use crate::log_msg;

const SIGS: &str = include_str!("../signatures.txt");
const CHUNK: usize = 1 << 20;

/// 按虚拟地址读字节, 读不到返回 false。游戏里是 ReadProcessMemory, 单测里是 exe 文件。
type Rd<'a> = &'a dyn Fn(usize, &mut [u8]) -> bool;

struct Cap {
    key: String,
    off: usize,
    kind: String,
    eq: Option<String>,
}

struct Sig {
    name: String,
    pat: Vec<Option<u8>>,
    caps: Vec<Cap>,
    at: Option<String>,
}

pub struct Resolved {
    vals: HashMap<String, usize>,
    pub problems: Vec<String>,
}

impl Resolved {
    pub fn get(&self, key: &str) -> Option<usize> {
        self.vals.get(key).copied()
    }
    /// 一次要齐一组键; 缺任何一个返回 None 并记一行日志, 调用方据此不装对应功能。
    pub fn require<const N: usize>(&self, who: &str, keys: [&str; N]) -> Option<[usize; N]> {
        let mut out = [0usize; N];
        for (i, k) in keys.iter().enumerate() {
            match self.get(k) {
                Some(v) => out[i] = v,
                None => {
                    log_msg(&format!("[SIG] {} 需要的 {} 没解出来, 不启用", who, k));
                    return None;
                }
            }
        }
        Some(out)
    }
}

static RESOLVED: OnceLock<Resolved> = OnceLock::new();

/// 第一次调用时扫描当前进程 (1~3 秒), 之后直接返回结果。
pub fn resolved() -> &'static Resolved {
    RESOLVED.get_or_init(|| {
        let start = std::time::Instant::now();
        let base = unsafe { GetModuleHandleW(std::ptr::null()) } as usize;
        let r = resolve_with(&rpm, base);
        let mut keys: Vec<_> = r.vals.iter().collect();
        keys.sort();
        log_msg(&format!(
            "[SIG] 特征码定位 {} ms, 解出 {} 项, 问题 {} 个",
            start.elapsed().as_millis(), r.vals.len(), r.problems.len()
        ));
        log_msg(&format!(
            "[SIG]   {}",
            keys.iter().map(|(k, v)| format!("{}=0x{:X}", k, v)).collect::<Vec<_>>().join(" ")
        ));
        for p in &r.problems {
            log_msg(&format!("[SIG]   问题: {}", p));
        }
        r
    })
}

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

fn rd_u32(rd: Rd, addr: usize) -> Option<u32> {
    let mut b = [0u8; 4];
    rd(addr, &mut b).then(|| u32::from_le_bytes(b))
}

fn parse() -> Vec<Sig> {
    let mut out = Vec::new();
    for ln in SIGS.lines() {
        let ln = ln.trim();
        if ln.is_empty() || ln.starts_with('#') {
            continue;
        }
        let parts: Vec<&str> = ln.split('|').map(|s| s.trim()).collect();
        if parts.len() < 3 {
            continue;
        }
        let pat = parts[1]
            .split_whitespace()
            .map(|t| if t == "??" { None } else { u8::from_str_radix(t, 16).ok() })
            .collect();
        let caps = parts[2]
            .split_whitespace()
            .filter_map(|c| {
                let (key, rest) = c.split_once('@')?;
                let (off, kind) = rest.split_once(':')?;
                let (kind, eq) = match kind.split_once('=') {
                    Some((k, e)) => (k, Some(e.to_string())),
                    None => (kind, None),
                };
                Some(Cap { key: key.into(), off: off.parse().ok()?, kind: kind.into(), eq })
            })
            .collect();
        let at = parts.get(3).and_then(|p| p.strip_prefix("at=")).map(|s| s.to_string());
        out.push(Sig { name: parts[0].into(), pat, caps, at });
    }
    out
}

/// 模块里所有可执行节的 [起, 止) 地址 (按 PE 节表, 地址 = base + VirtualAddress)。
fn exec_sections(rd: Rd, base: usize) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    let Some(lfanew) = rd_u32(rd, base + 0x3c) else { return out };
    let lfanew = lfanew as usize;
    let mut hdr = [0u8; 24];
    if !rd(base + lfanew, &mut hdr) {
        return out;
    }
    let nsec = u16::from_le_bytes([hdr[6], hdr[7]]) as usize;
    let optsz = u16::from_le_bytes([hdr[20], hdr[21]]) as usize;
    let tbl = base + lfanew + 24 + optsz;
    for i in 0..nsec {
        let mut s = [0u8; 40];
        if !rd(tbl + i * 40, &mut s) {
            break;
        }
        let vsize = u32::from_le_bytes([s[8], s[9], s[10], s[11]]) as usize;
        let vaddr = u32::from_le_bytes([s[12], s[13], s[14], s[15]]) as usize;
        let flags = u32::from_le_bytes([s[36], s[37], s[38], s[39]]);
        if flags & 0x2000_0000 != 0 {
            out.push((base + vaddr, base + vaddr + vsize));
        }
    }
    out
}

fn matches_at(pat: &[Option<u8>], hay: &[u8]) -> bool {
    hay.len() >= pat.len() && pat.iter().zip(hay).all(|(p, h)| p.map_or(true, |v| v == *h))
}

/// 一遍扫完所有「要扫描」的特征码, -> 每条的命中地址 (每条最多留 8 处)。
fn scan_all(rd: Rd, sections: &[(usize, usize)], sigs: &[&Sig]) -> Vec<Vec<usize>> {
    let maxlen = sigs.iter().map(|s| s.pat.len()).max().unwrap_or(0);
    let mut hits = vec![Vec::new(); sigs.len()];
    // 首字节 -> 以它开头的特征码
    let mut by_first: Vec<Vec<usize>> = vec![Vec::new(); 256];
    for (i, s) in sigs.iter().enumerate() {
        if let Some(Some(b)) = s.pat.first() {
            by_first[*b as usize].push(i);
        }
    }
    let mut buf = vec![0u8; CHUNK + maxlen];
    for &(lo, hi) in sections {
        let mut addr = lo;
        while addr < hi {
            // 先按 1 MB 读; 读不动 (块里夹着不可读页) 就退到 64 KB, 只跳过真正读不到的那几块
            let step = if rd(addr, &mut buf[..(hi - addr).min(CHUNK + maxlen)]) { CHUNK } else { 1 << 16 };
            let want = (hi - addr).min(step + maxlen);
            if step != CHUNK && !rd(addr, &mut buf[..want]) {
                addr += step;
                continue;
            }
            for p in 0..want.min(step) {
                for &i in &by_first[buf[p] as usize] {
                    if hits[i].len() < 8 && matches_at(&sigs[i].pat, &buf[p..want]) {
                        hits[i].push(addr + p);
                    }
                }
            }
            addr += step;
        }
    }
    hits
}

fn resolve_with(rd: Rd, base: usize) -> Resolved {
    let mut vals: HashMap<String, usize> = HashMap::new();
    let mut problems = Vec::new();
    let sigs = parse();
    let sections = exec_sections(rd, base);
    let scan: Vec<&Sig> = sigs.iter().filter(|s| s.at.is_none()).collect();
    let scanned = scan_all(rd, &sections, &scan);
    let mut scan_hits: HashMap<&str, &Vec<usize>> = HashMap::new();
    for (s, h) in scan.iter().zip(&scanned) {
        scan_hits.insert(s.name.as_str(), h);
    }

    for sig in &sigs {
        let cands: Vec<usize> = match &sig.at {
            Some(at) => match vals.get(at) {
                Some(&addr) => {
                    let mut b = vec![0u8; sig.pat.len()];
                    if rd(addr, &mut b) && matches_at(&sig.pat, &b) { vec![addr] } else { vec![] }
                }
                None => {
                    problems.push(format!("{}: at={} 没解出来", sig.name, at));
                    continue;
                }
            },
            None => scan_hits.get(sig.name.as_str()).map(|h| (*h).clone()).unwrap_or_default(),
        };
        let mut ok: Vec<(usize, Vec<(String, usize)>)> = Vec::new();
        'cand: for &m in &cands {
            let mut cap = Vec::new();
            for c in &sig.caps {
                let v = match c.kind.as_str() {
                    "u8" => {
                        let mut b = [0u8; 1];
                        if !rd(m + c.off, &mut b) {
                            continue 'cand;
                        }
                        b[0] as usize
                    }
                    "u32" => match rd_u32(rd, m + c.off) {
                        Some(v) => v as usize,
                        None => continue 'cand,
                    },
                    "rip" | "call" => match rd_u32(rd, m + c.off) {
                        Some(rel) => (m + c.off + 4).wrapping_add(rel as i32 as isize as usize),
                        None => continue 'cand,
                    },
                    _ => continue 'cand,
                };
                if let Some(eq) = &c.eq {
                    if vals.get(eq) != Some(&v) {
                        continue 'cand;
                    }
                }
                cap.push((c.key.clone(), v));
            }
            ok.push((m, cap));
        }
        if ok.len() != 1 {
            problems.push(format!("{}: {} 处字节命中, {} 处满足约束", sig.name, cands.len(), ok.len()));
            continue;
        }
        let (m, cap) = ok.pop().unwrap();
        vals.insert(sig.name.clone(), m);
        for (k, v) in cap {
            vals.insert(k, v);
        }
    }

    // 派生: 统计项起点。half 跳转表第 0 项 = 「上半场三段相加」, 三个位移里最小的就是项起点
    if let (Some(&ib), Some(&jt)) = (vals.get("image_base"), vals.get("jump_table")) {
        let want: [Option<u8>; 23] = [
            Some(0x48), Some(0x63), Some(0xC2), Some(0x48), Some(0x8D), Some(0x0C), Some(0xC0),
            Some(0x41), Some(0x8B), Some(0x44), Some(0x89), None, Some(0x41), Some(0x03), Some(0x44),
            Some(0x89), None, Some(0x41), Some(0x03), Some(0x44), Some(0x89), None, Some(0xC3),
        ];
        let mut b = [0u8; 23];
        match rd_u32(rd, ib + jt) {
            Some(rva) if rd(ib + rva as usize, &mut b) && matches_at(&want, &b) => {
                vals.insert("stat_entry_off".into(), b[11].min(b[16]).min(b[21]) as usize);
            }
            _ => problems.push("stat_entry_off: half-0 分支形状变了".into()),
        }
    }
    Resolved { vals, problems }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Untouched copy of the eFootball.exe this signature history was taken from. Point the
    // environment variable at it when building the tests; without it the test skips.
    const PRISTINE: &str = match option_env!("EFOOTBALL_PRISTINE_EXE") {
        Some(path) => path,
        None => "eFootball.exe.pristine",
    };
    const IMAGE_BASE: usize = 0x1_4000_0000;

    /// 2026-09-13 这个 build 的值 (和 exetool.py 的 SIG_HISTORY 同一份)。
    const HISTORY: [(&str, usize); 33] = [
        ("attr_get", 0x143EA8CB0), ("sel_off", 0x2BD8), ("ctx_off", 0x47C0),
        ("stats_get", 0x1443378C0), ("max_id", 0x76), ("image_base", 0x140000000),
        ("attr_table", 0x1442D6EF0), ("attr_slots", 0x1F), ("attr_stride", 0x58), ("singleton", 0x1486BD888),
        ("attr_table_off", 0x55A8), ("team_obj", 0x1442D6E40), ("team_obj_off", 0x3BD0), ("team_stride", 0x58),
        ("roster_rec", 0x1442C3050), ("roster_slots", 0x28), ("lineup_off", 4), ("rec_stride", 0x198),
        ("rec_off", 0xE8), ("skill_test", 0x1442C0000), ("skill_bits", 0x49), ("skill_off", 0xC0),
        ("player_block", 0x1442E6640), ("stat_slots", 0x28), ("player_stride", 0x13E8),
        ("stats_team_stride", 0x38238), ("players_off", 0x65C0), ("attr_form_off", 0x394),
        ("stat_entry_off", 0x10), ("attr_forward", 0x1442DD650), ("attr_array", 0x144301840),
        ("skill_by_sel", 0x1442E2640), ("team_total", 0x14431B4DA),
    ];

    /// 把 exe 文件当成「加载到 IMAGE_BASE 的模块」读: 头部按文件偏移, 节按节表映射。
    fn file_reader(d: &[u8]) -> impl Fn(usize, &mut [u8]) -> bool + '_ {
        let u32at = |o: usize| u32::from_le_bytes([d[o], d[o + 1], d[o + 2], d[o + 3]]) as usize;
        let lfanew = u32at(0x3c);
        let nsec = u16::from_le_bytes([d[lfanew + 6], d[lfanew + 7]]) as usize;
        let optsz = u16::from_le_bytes([d[lfanew + 20], d[lfanew + 21]]) as usize;
        let tbl = lfanew + 24 + optsz;
        let secs: Vec<(usize, usize, usize)> = (0..nsec)
            .map(|i| {
                let s = tbl + i * 40;
                (u32at(s + 12), u32at(s + 16), u32at(s + 20)) // VirtualAddress, SizeOfRawData, PointerToRawData
            })
            .collect();
        let headers_end = secs.iter().map(|s| s.2).min().unwrap_or(0);
        move |va: usize, buf: &mut [u8]| {
            let Some(rva) = va.checked_sub(IMAGE_BASE) else { return false };
            let off = if rva + buf.len() <= headers_end {
                rva
            } else {
                match secs.iter().find(|&&(v, raw, _)| rva >= v && rva + buf.len() <= v + raw) {
                    Some(&(v, _, ptr)) => ptr + (rva - v),
                    None => return false,
                }
            };
            if off + buf.len() > d.len() {
                return false;
            }
            buf.copy_from_slice(&d[off..off + buf.len()]);
            true
        }
    }

    #[test]
    fn signatures_file_parses() {
        let sigs = parse();
        assert_eq!(sigs.len(), 11);
        assert!(sigs.iter().all(|s| !s.pat.is_empty() && !s.caps.is_empty()));
        let tt = sigs.iter().find(|s| s.name == "team_total").unwrap();
        assert_eq!(tt.caps[0].eq.as_deref(), Some("players_off"));
        assert_eq!(sigs.iter().find(|s| s.name == "stats_get").unwrap().at.as_deref(), Some("stats_get"));
    }

    /// 离线跑一遍完整解析, 所有值必须等于这个 build 的历史值。原封备份不在就跳过。
    #[test]
    fn resolves_pristine_exe_to_known_values() {
        let Ok(d) = std::fs::read(PRISTINE) else {
            eprintln!("skip: {} not found", PRISTINE);
            return;
        };
        let rd = file_reader(&d);
        let r = resolve_with(&rd, IMAGE_BASE);
        assert!(r.problems.is_empty(), "problems: {:?}", r.problems);
        for (k, want) in HISTORY {
            assert_eq!(r.get(k), Some(want), "{}", k);
        }
    }
}

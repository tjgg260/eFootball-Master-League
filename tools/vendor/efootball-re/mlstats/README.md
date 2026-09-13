# mlstats — 比赛数据导出

每场比赛结束自动生成一份 JSON：两队合计 + 每个球员的动作、PID、属性、技能，换人也记录。
给外置大师联赛之类的程序读。

## 装

1. 完全退出游戏，跑 `memprobe/deploy_host.sh`
2. 游戏目录（根目录和 `eFootball\Binaries\Win64` 两处）放空文件 `statshook.on`、`attrhook.on`
   （attrhook 只用来拿球员身份，默认不改数值；**别留 `attrhook.mode`**，那是改能力值用的）
3. 正常踢球。日志 `<游戏目录>\sider_rust.log` 里有 `[EXPORT]` 行就是在工作

## 输出

`<游戏目录>\ml_stats\`

| 文件 | 何时 |
|---|---|
| `live.json` | 比赛进行中，每 5 秒更新 |
| `match_<开始时间>.json` | 定稿（`final: true`）：回主菜单 15 秒后 / 下一场开始 / 游戏重启 |

结算画面停着不算结束 —— 要选「结束比赛」回菜单。

## JSON

```jsonc
{
  "final": true, "final_reason": "left_match",
  "teams": [{
    "side": "home",
    "totals": { "shots": 5, "passes": 47, ... },      // 已命名的项
    "raw_totals": { "0x06": 5, ... },                 // 全部 119 个 id 里非零的
    "lineup": [0, 1, ..., 22, ...],                   // 位置 -> 槽位 (换人后会变)
    "players": [{
      "slot": 4,                                      // 首发 0-10, 替补 11+
      "player_id": 52878832201421,                    // dt200 PID
      "shirt_number": 49, "shirt_name": "LEWIS-SKELLY",
      "lineup_index": 4,                              // 被换下的为 null
      "actions": { "passes": 6, "tackles": 3, ... },
      "raw_segments": { "0x18": [9 个数] },           // 全场 = 前 8 个之和
      "attributes_base": [61 字节],                    // 下标 49 年龄, 50 身高, 20-46 能力
      "attributes_form": [61 字节],                    // 叠了赛前状态
      "skills": [技能 id], "roster_record_hex": "..."
    }]
  }]
}
```

`actions` 的键：shots · shots_on_target · passes · passes_completed · crosses · tackles ·
interceptions · fouls · offsides · corners（和游戏统计界面逐项核对过）；
ball_receptions（接球/获得球权）· possessions（持球次数）· possessions_retained（其中保住球权）·
possession_time（持球时长，5 分钟赛制下约 48/秒）· ball_recoveries（夺回球权）· sprints（冲刺）
（界面上没有，靠受控实验定的：插件 cmd 28 逐 50 ms 记变化 + 按步骤操作）；
goals · saves · gk_shots_faced · gk_shots_on_target_faced（推断）。可信度逐条见 JSON 的 `labels`。
界面上的「任意球次数」= 对手的犯规数，没有单独的 id。

## 赛后自动弹窗

```powershell
powershell -ExecutionPolicy Bypass -File mlstats\install_popup.ps1          # 开机自启 + 立刻启动
powershell -ExecutionPolicy Bypass -File mlstats\install_popup.ps1 -Remove  # 卸载 + 停止
py mlstats\popup.py --show <match_xxx.json>                                 # 手动弹一次试效果
```

后台常驻 (无窗口), 比赛定稿 (回主菜单约 15 秒) 后弹出独立报告窗口 (Edge app 模式)。
只弹启动之后的新比赛; 报告存在 `ml_stats\reports\`, 日志 `ml_stats\popup.log`。

**球员头像**: 按 PID 找图, 找到就嵌进报告, 找不到显示队色圆牌 + 球衣号。查找顺序:
`mlstats\faces\` (自己放, 文件名 = 完整 PID 或 PID 低 24 位, 如 `40352.png`; 不进 git) →
PESBuilder 的缓存 `%LOCALAPPDATA%\PESBuilder\Cache\Players\` (它也按低 24 位命名)。
游戏自带的头像在加密的 IoStore 容器里, 不取。

## 工具

```bash
py mlstats/report.py match_xxx.json     # 中英双语仪表盘报告 (自包含 HTML), 写出 .report.html
py mlstats/identify.py match_xxx.json   # 拿 dt200 核对 PID / 名字 / 年龄身高
py mlstats/rate.py match_xxx.json       # 示例评分, 写出 .rated.json; 公式在 rating.py 随便改
py -m unittest mlstats/test_rating.py mlstats/test_identity.py
```

`samples/` 是一场真实导出和同场游戏结算画面的数字。

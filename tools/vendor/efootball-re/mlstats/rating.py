"""球员比赛评分 —— 读宿主导出的比赛统计 JSON (efootball-re/match-stats/1), 给每个球员算分。

两层输出, 故意分开:

match_rating
    只看场上发生了什么。6.0 起步, 按位置给各项动作加减分, 夹在 [3.0, 10.0]。
    年龄不进这一层 —— 同样的表现不该因为球员 19 岁就更高分。
context (adjusted_rating / development_score)
    拿表现去比「按能力值该打多少分」, 再乘年龄曲线和成长势头。给大师联赛的成长/训练决策用。

每一项加减分都记在 components 里 (动作, 数量, 分值), 评分是可解释的, 调权重只改 RatingConfig。

可信度 (见 memprobe/stats_labeling 和导出 JSON 的 labels):
    射门 射正 传球 成功传球 横传 抢球 犯规 越位 角球 拦截 —— 实测
    进球 扑救 门将面对射门/射正 —— 推断 (和孪生 id 一直相等), 用到时写进 caveats
    位置 —— 从能力值推断; 没有能力值时从动作推断
    上场时间比例 —— 从 9 段计数推断 (段的含义没验证)
"""
import copy
import math
from dataclasses import dataclass, field

MODEL = "mlstats-rating/1"

# 属性数组下标 (memprobe/README 与记忆 match-attr-chain, 实测)
ATTR = {
    "att_awareness": 20, "def_awareness": 21, "gk_awareness": 22, "def_engagement": 23,
    "dribbling": 24, "ball_control": 25, "tight_possession": 26, "finishing": 27,
    "low_pass": 28, "lofted_pass": 29, "header": 30, "tackling": 31, "aggression": 32,
    "set_piece": 33, "curl": 34, "gk_catching": 35, "gk_parrying": 36, "gk_reflexes": 37,
    "gk_reach": 38, "weak_foot": 39, "speed": 40, "physical": 41, "balance": 42,
    "kicking_power": 43, "acceleration": 44, "jump": 45, "stamina": 46,
    "age": 49, "height": 50, "weight": 51,
}

# 各位置算「综合能力」时看的属性
ROLE_ABILITIES = {
    "GK": ["gk_awareness", "gk_catching", "gk_parrying", "gk_reflexes", "gk_reach"],
    "DEF": ["def_awareness", "def_engagement", "tackling", "aggression", "header", "physical", "speed"],
    "MID": ["att_awareness", "def_awareness", "ball_control", "dribbling", "low_pass", "lofted_pass", "stamina"],
    "FWD": ["att_awareness", "finishing", "ball_control", "dribbling", "tight_possession", "speed", "acceleration"],
}

INFERRED_LABELS = {"goals", "saves", "gk_shots_faced", "gk_shots_on_target_faced"}
GK_ONLY_ACTIONS = ("saves", "gk_shots_faced", "gk_shots_on_target_faced")


@dataclass
class RatingConfig:
    base: float = 6.0
    floor: float = 3.0
    ceiling: float = 10.0

    # 进攻
    goal: dict = field(default_factory=lambda: {"GK": 1.2, "DEF": 1.1, "MID": 1.0, "FWD": 0.9})
    shot_on_target: float = 0.12        # 不含进球那几脚
    cross: float = 0.04
    cross_knee: float = 5.0

    # 传球: 量 (饱和) + 成功率相对位置预期
    pass_volume: float = 0.6
    pass_volume_half: float = 30.0      # 成功传球 30 次拿到 pass_volume 的一半
    pass_accuracy_weight: float = 2.0   # 每高出预期 1 个百分点 +0.02
    pass_accuracy_cap: float = 0.4
    pass_accuracy_min_attempts: int = 5
    expected_accuracy: dict = field(default_factory=lambda: {"GK": 0.70, "DEF": 0.85, "MID": 0.83, "FWD": 0.75})

    # 防守: 线性到拐点, 之后半价
    tackle: float = 0.14
    interception: float = 0.11
    defensive_knee: float = 6.0
    defensive_role_mult: dict = field(default_factory=lambda: {"GK": 1.0, "DEF": 1.0, "MID": 1.0, "FWD": 1.2})

    # 门将 / 失球 / 零封
    save: float = 0.30
    save_knee: float = 5.0
    conceded: dict = field(default_factory=lambda: {"GK": -0.30, "DEF": -0.12, "MID": -0.05, "FWD": 0.0})
    clean_sheet: dict = field(default_factory=lambda: {"GK": 0.5, "DEF": 0.3, "MID": 0.05, "FWD": 0.0})
    clean_sheet_min_share: float = 0.6

    # 失误与纪律
    shot_off_target: float = -0.04
    offside: float = -0.08
    foul: float = -0.10

    # 比赛结果
    goal_difference: float = 0.10
    goal_difference_cap: int = 3

    # ---- 上下文层 ----
    ability_to_rating: float = 0.02     # 比队内平均能力高 10 点, 预期分 +0.2
    age_curve: tuple = ((16, 1.4), (18, 1.4), (21, 1.25), (24, 1.0), (28, 0.9), (31, 0.7), (34, 0.5), (45, 0.5))
    progression_weight: float = 0.25    # progression ∈ [-1, 1] -> 系数 0.75..1.25
    development_weight: float = 0.5
    development_cap: float = 0.6


def knee(n, k):
    """线性到 k, 之后斜率减半 —— 刷数据的边际收益递减。"""
    return n if n <= k else k + (n - k) * 0.5


def soft(x, half):
    """0 -> 0, half -> 0.5, 趋近 1。"""
    return x / (x + half) if x > 0 else 0.0


def attr(player, name, which="attributes_base"):
    arr = player.get(which) or player.get("attributes_form")
    if not arr:
        return None
    return arr[ATTR[name]]


def infer_role(player):
    """-> (GK/DEF/MID/FWD, 依据)。都是推断。

    门将先看确定性高的两条: 出场表第 0 位 (2026-09-13 实测两队都是门将), 或有门将专属动作。
    **不能只靠能力值**: 改过档的球队全员 99, 门将五项也是 99, 按能力值分不出位置 ——
    那场 0-5 的阿森纳门将就被当成中场, 失球一分没扣。
    """
    a = player.get("actions", {})
    if player.get("lineup_index") == 0:
        return "GK", "lineup"
    if any(a.get(k, 0) for k in GK_ONLY_ACTIONS):
        return "GK", "actions"

    base = player.get("attributes_base") or player.get("attributes_form")
    if base:
        mean = lambda names: sum(base[ATTR[n]] for n in names) / len(names)
        gk = mean(["gk_awareness", "gk_catching", "gk_parrying", "gk_reflexes", "gk_reach"])
        dfn = mean(["def_awareness", "def_engagement", "tackling", "aggression"])
        att = mean(["att_awareness", "finishing"])
        if gk >= 60 and gk > max(dfn, att):
            return "GK", "attributes"
        if dfn - att >= 8:
            return "DEF", "attributes"
        if att - dfn >= 8:
            return "FWD", "attributes"
        if not (gk == dfn == att):  # 全员同值 (改过档) 时能力值没有信息, 落到下面按动作判断
            return "MID", "attributes"

    defensive = a.get("tackles", 0) + a.get("interceptions", 0)
    attacking = a.get("shots", 0) + a.get("offsides", 0)
    if defensive >= 3 and defensive >= 3 * max(attacking, 1):
        return "DEF", "actions"
    if attacking >= 2 and attacking > defensive:
        return "FWD", "actions"
    return "MID", "actions"


def active_periods(player):
    """9 段计数里前 8 段哪些有动作 -> (首段, 末段) 或 None。"""
    segs = player.get("raw_segments") or {}
    active = [k for k in range(8) if any(v[k] for v in segs.values())]
    return (active[0], active[-1]) if active else None


def minutes_share(player, match_periods):
    span = active_periods(player)
    if span is None or not match_periods:
        return None
    return (span[1] - span[0] + 1) / match_periods


def rate_player(player, team_goals, opp_goals, cfg, match_periods=None):
    a = player.get("actions", {})
    role, role_source = infer_role(player)
    goals = a.get("goals", 0)
    shots = a.get("shots", 0)
    sot = a.get("shots_on_target", 0)
    passes = a.get("passes", 0)
    completed = a.get("passes_completed", 0)
    share = minutes_share(player, match_periods)

    comps = {}

    def add(comp, item, count, value):
        c = comps.setdefault(comp, {"score": 0.0, "items": []})
        if count or value:
            c["items"].append([item, count, round(value, 3)])
            c["score"] += value

    # 进攻
    add("attacking", "goals", goals, goals * cfg.goal[role])
    add("attacking", "shots_on_target_saved_or_blocked", max(0, sot - goals), max(0, sot - goals) * cfg.shot_on_target)
    add("attacking", "crosses", a.get("crosses", 0), knee(a.get("crosses", 0), cfg.cross_knee) * cfg.cross)

    # 传球
    add("passing", "completed_volume", completed, cfg.pass_volume * soft(completed, cfg.pass_volume_half))
    accuracy = completed / passes if passes else None
    if passes >= cfg.pass_accuracy_min_attempts:
        delta = (accuracy - cfg.expected_accuracy[role]) * cfg.pass_accuracy_weight
        delta = max(-cfg.pass_accuracy_cap, min(cfg.pass_accuracy_cap, delta))
        # 尝试次数少时成功率不可靠: 20 次以下按比例打折
        add("passing", "accuracy_vs_role", round(accuracy, 3), delta * min(1.0, passes / 20))

    # 防守
    mult = cfg.defensive_role_mult[role]
    add("defending", "tackles", a.get("tackles", 0), knee(a.get("tackles", 0), cfg.defensive_knee) * cfg.tackle * mult)
    add("defending", "interceptions", a.get("interceptions", 0),
        knee(a.get("interceptions", 0), cfg.defensive_knee) * cfg.interception * mult)

    # 门将与失球
    if role == "GK":
        add("goalkeeping", "saves", a.get("saves", 0), knee(a.get("saves", 0), cfg.save_knee) * cfg.save)
    add("goalkeeping", "goals_conceded", opp_goals, opp_goals * cfg.conceded[role])
    if opp_goals == 0 and (share is None or share >= cfg.clean_sheet_min_share):
        add("goalkeeping", "clean_sheet", 1, cfg.clean_sheet[role])

    # 失误与纪律
    add("errors_discipline", "shots_off_target", max(0, shots - sot), max(0, shots - sot) * cfg.shot_off_target)
    add("errors_discipline", "offsides", a.get("offsides", 0), a.get("offsides", 0) * cfg.offside)
    add("errors_discipline", "fouls", a.get("fouls", 0), a.get("fouls", 0) * cfg.foul)

    # 比赛结果
    gd = max(-cfg.goal_difference_cap, min(cfg.goal_difference_cap, team_goals - opp_goals))
    add("result", "goal_difference", team_goals - opp_goals, gd * cfg.goal_difference)

    raw = cfg.base + sum(c["score"] for c in comps.values())
    rating = max(cfg.floor, min(cfg.ceiling, raw))
    for c in comps.values():
        c["score"] = round(c["score"], 3)

    caveats = sorted(k for k in INFERRED_LABELS if a.get(k, 0))
    return {
        "model": MODEL,
        "role": role,
        "role_source": role_source,
        "match_rating": round(rating, 1),
        "match_rating_unclamped": round(raw, 3),
        "components": comps,
        "derived": {
            "pass_accuracy": round(accuracy, 3) if accuracy is not None else None,
            "failed_passes": max(0, passes - completed),
            "shots_off_target": max(0, shots - sot),
            "minutes_share": round(share, 3) if share is not None else None,
            "minutes_share_basis": "inferred: 8 stat segments" if share is not None else None,
        },
        "caveats": ["uses inferred label: %s" % k for k in caveats],
    }


def overall_ability(player, role):
    base = player.get("attributes_base")
    if not base:
        return None
    names = ROLE_ABILITIES[role]
    return sum(base[ATTR[n]] for n in names) / len(names)


def age_factor(age, cfg):
    pts = cfg.age_curve
    if age <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= age <= x1:
            return y0 + (y1 - y0) * (age - x0) / (x1 - x0)
    return pts[-1][1]


def context_block(player, rating, team_overall, cfg, external=None):
    """表现 vs 能力预期, 乘年龄曲线和成长势头。external 来自大师联赛: {"age":..., "progression":...}。"""
    external = external or {}
    role = rating["role"]
    overall = overall_ability(player, role)
    age = external.get("age")
    age_source = "external" if age is not None else None
    if age is None:
        age = attr(player, "age")
        age_source = "attributes" if age is not None else None

    expected = None
    if overall is not None and team_overall:
        expected = cfg.base + (overall - team_overall) * cfg.ability_to_rating
    over = rating["match_rating_unclamped"] - (expected if expected is not None else cfg.base)

    af = age_factor(age, cfg) if age is not None else 1.0
    prog = external.get("progression")
    pf = 1.0 + cfg.progression_weight * max(-1.0, min(1.0, prog)) if prog is not None else 1.0
    development = over * af * pf
    # 平滑饱和而不是硬截断: 硬截断时表现很好的 19 岁和 33 岁会一起顶到上限, 年龄的差别就没了
    adj = cfg.development_cap * math.tanh(cfg.development_weight * development / cfg.development_cap)
    adjusted = max(cfg.floor, min(cfg.ceiling, rating["match_rating_unclamped"] + adj))
    return {
        "overall_ability": round(overall, 1) if overall is not None else None,
        "team_overall_ability": round(team_overall, 1) if team_overall else None,
        "expected_rating": round(expected, 2) if expected is not None else None,
        "over_performance": round(over, 3),
        "age": age,
        "age_source": age_source,
        "age_factor": round(af, 3),
        "progression": prog,
        "progression_factor": round(pf, 3),
        "development_score": round(development, 3),
        "adjusted_rating": round(adjusted, 2),
    }


def player_key(side, player):
    """外部上下文的键。PID 解出来之前只能用 side:slot, 只在同一场里有意义。"""
    if player.get("player_id") is not None:
        return str(player["player_id"])
    return "%s:%d" % (side, player["slot"])


def rate_match(export, context=None, cfg=None):
    """-> 新的 dict: 每个球员加 "rating", 每队加 "rating_summary", 顶层加 "rating_model"。不改输入。"""
    cfg = cfg or RatingConfig()
    ext_players = (context or {}).get("players", {})
    out = copy.deepcopy(export)
    teams = out["teams"]
    goals = [t.get("totals", {}).get("goals", 0) for t in teams]

    all_players = [p for t in teams for p in t.get("players", [])]
    ends = [active_periods(p) for p in all_players]
    match_periods = max((e[1] + 1 for e in ends if e), default=None)

    for ti, team in enumerate(teams):
        side = team.get("side", "home" if ti == 0 else "away")
        players = team.get("players", [])
        ratings = [rate_player(p, goals[ti], goals[1 - ti], cfg, match_periods) for p in players]
        overalls = [overall_ability(p, r["role"]) for p, r in zip(players, ratings)]
        known = [o for o in overalls if o is not None]
        team_overall = sum(known) / len(known) if known else None
        for p, r in zip(players, ratings):
            r["context"] = context_block(p, r, team_overall, cfg, ext_players.get(player_key(side, p)))
            p["rating"] = r
        rated = [p for p in players if p["rating"]["derived"]["minutes_share"] != 0]
        if rated:
            best = max(rated, key=lambda p: p["rating"]["match_rating_unclamped"])
            team["rating_summary"] = {
                "average_match_rating": round(sum(p["rating"]["match_rating"] for p in rated) / len(rated), 2),
                "best_slot": best["slot"],
                "best_match_rating": best["rating"]["match_rating"],
            }
    out["rating_model"] = {"model": MODEL, "config": cfg.__dict__}
    return out

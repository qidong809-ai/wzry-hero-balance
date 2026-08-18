
"""
Skill 5：风险评级（双轴模型 + 数据兜底）

两把尺子分别衡量，避免只看一群玩家：
  - 竞技轴（巅峰千强）：管高分段/职业公平。抗"下饭/低端虚高"。
  - 大众轴（全分段）  ：管普通玩家体验。抗"高手向/绝活哥"漏判大众。

判定用【相对分布/统计法】：每轮拿全英雄数据算均值μ、标准差σ，
按 z-score（偏离几个σ）判强弱，自适应版本，不用手写死线（阈值在 config）。

绝活哥防护：巅峰胜率虚高但"出场率低 + ban率不高" → 疑似绝活哥，
高胜率不作数（因为真强的英雄大众会去 ban，ban率抗选择偏差）。

方案A 数据兜底：遍历所有有数据的英雄，不只有舆情的 → 不漏冷门。
舆情（voice）不作入口，只做"是否印证 + 优先级加成"。
"""
import statistics

from src.models.schemas import HeroVoice, HeroMetrics, HeroVerdict
from src.skills.metrics import all_metrics
from src.config import config


def _dist(values: list[float]) -> tuple[float, float]:
    """返回 (均值, 标准差)；σ=0 时给个极小值避免除零。"""
    mu = statistics.mean(values)
    sigma = statistics.pstdev(values) or 1e-9
    return mu, sigma


def _build_stats(metrics_list: list[HeroMetrics]) -> dict:
    """一次性算出各指标在全英雄里的分布（全池 z-score，保留分路平衡信号，不分组抹平）。"""
    return {
        "top_win":  _dist([m.top_win_rate for m in metrics_list]),
        "top_ban":  _dist([m.top_ban_rate for m in metrics_list]),
        "top_pick": _dist([m.top_pick_rate for m in metrics_list]),
        "all_win":  _dist([m.all_win_rate for m in metrics_list]),
        "all_pick": _dist([m.all_pick_rate for m in metrics_list]),
    }


def _z(x: float, dist: tuple[float, float]) -> float:
    mu, sigma = dist
    return (x - mu) / sigma


def assess_hero(m: HeroMetrics, voice: HeroVoice | None, stats: dict) -> HeroVerdict:
    # 各指标的 z-score（偏离全体几个σ）
    z_top_win = _z(m.top_win_rate, stats["top_win"])
    z_top_ban = _z(m.top_ban_rate, stats["top_ban"])
    z_top_pick = _z(m.top_pick_rate, stats["top_pick"])
    z_all_win = _z(m.all_win_rate, stats["all_win"])
    z_all_pick = _z(m.all_pick_rate, stats["all_pick"])

    # 两轴强弱
    comp_strong = z_top_win >= config.Z_STRONG
    comp_weak = z_top_win <= config.Z_WEAK
    pop_strong = z_all_win >= config.Z_STRONG
    pop_weak = z_all_win <= config.Z_WEAK

    # 绝活哥防护：巅峰高胜 + 冷门 + ban率不高 → 高胜不作数
    onetrick = (comp_strong
                and z_top_pick <= config.Z_PICK_LOW
                and z_top_ban < config.Z_BAN_CONFIRM)
    if onetrick:
        comp_strong = False

    # 大众轴对称防护：全段高胜但全段同样冷门(出场率低) → 小样本/绝活哥虚高，大众高胜也不作数。
    # 否则绝活哥(如雅典娜：巅峰高胜+冷门+ban0)的全段小样本高胜会被误判成"炸鱼"。
    if pop_strong and z_all_pick <= config.Z_PICK_LOW:
        pop_strong = False

    # 霸榜：出场率极高，泛用性过强（即使胜率不突出也值得关注）
    dominant = z_all_pick >= config.Z_PICK_DOMINANT

    # 两极分化：上限高(巅峰强) + 下限低(全段胜率弱) → 该削上限补下限
    # ban率高≠强：瑶/鲁班被ban是因"机制烦人"，非强度。故 ban 只在【胜率不弱(z≥0)】时
    # 才算"上限被公认强"的正向信号；纯高ban低胜(烦人型)不作超标，避免误判该削上限。
    ban_as_ceiling = z_top_ban >= config.Z_CEILING and z_top_win >= 0
    ceiling_high = z_top_win >= config.Z_CEILING or ban_as_ceiling
    polarized = ceiling_high and pop_weak
    # 上限是否真"压迫生态"：被针对ban(ban冒头) 或 大众泛用(全段出场不低)。
    # 否则多是【高操作英雄】天然的"巅峰胜高、全段胜低"技术差，非紧急，降 medium 观察，
    # 避免整类操作型英雄把高优先(削上限补下限)刷屏。
    oppressive = z_top_ban >= config.Z_BAN_CONFIRM or z_all_pick >= 0

    # —— 按双轴组合分型 ——
    if comp_strong and pop_strong:
        hero_type, suggestion, level = "真超标", "削弱", "high"
    elif polarized:
        hero_type, suggestion = "两极分化", "削上限补下限"
        level = "high" if oppressive else "medium"
    elif comp_strong and not pop_strong:
        hero_type, suggestion, level = "高手向", "削弱", "medium"
    elif pop_strong and not comp_strong:
        # 全段偏强但巅峰不强 → 「低端友好/低分段偏强」，一律维持观察，不自动削。
        # 说明：真正的「炸鱼」(高操作英雄被高手在低分段虐菜，如澜) 在【聚合胜率】里是隐形的——
        # 高手 carry 被海量玩不好的萌新拉低了平均胜率(澜全段仅47%)，单看 胜率/出场率 均值抓不到，
        # 需分位数据(高端局单独胜率/carry率/连胜率)，当前数据源没有，故不做自动炸鱼判定。
        # 这批(下饭英雄如后羿伽罗、或辅/坦低分段职业红利)巅峰并不强，削之误伤大众。
        hero_type, suggestion, level = "低端友好", "维持", "low"
    elif comp_weak and pop_weak:
        hero_type, suggestion, level = "真弱势", "加强", "high"
    elif comp_weak or pop_weak:
        hero_type, suggestion, level = "偏弱势", "加强", "medium"
    elif onetrick:
        hero_type, suggestion, level = "疑似绝活哥", "维持", "low"
    elif dominant:
        hero_type, suggestion, level = "泛用霸榜", "削弱", "medium"
    else:
        hero_type, suggestion, level = "健康", "维持", "low"

    # 数据描述
    data_desc = (f"巅峰胜{m.top_win_rate:.1%}(z{z_top_win:+.1f})/出{m.top_pick_rate:.1%}"
                 f"/ban{m.top_ban_rate:.0%}(z{z_top_ban:+.1f})；"
                 f"全段胜{m.all_win_rate:.1%}(z{z_all_win:+.1f})/出{m.all_pick_rate:.1%}")
    reason = f"[{hero_type}] {data_desc}。"

    # —— 舆情加成（不作入口，只印证/提级）——
    # 低置信舆情（单条爆帖垄断/口水战/小样本）不参与提级，只记录，避免被节奏带偏。
    net_voice = (voice.nerf_votes - voice.buff_votes) if voice else 0
    total_voice = voice.total if voice else 0
    conf = voice.confidence if voice else 0
    trusted = conf >= config.VOICE_CONF_MIN
    lowconf_note = "" if trusted else f"（舆情低置信{conf}，疑跟风/单条爆帖主导/口水战，仅记录不提级）"
    if suggestion == "削弱":
        if net_voice > 0:
            reason += f"舆情亦呼吁削弱(合计{total_voice:.0f}){lowconf_note}，印证。"
            if trusted and total_voice > 1000 and level == "medium":
                level = "high"
        elif total_voice == 0:
            reason += "舆情尚未发酵，属数据预警。"
    elif suggestion == "加强":
        if net_voice < 0:
            reason += f"舆情亦呼吁加强(合计{total_voice:.0f}){lowconf_note}，印证。"
            if trusted and total_voice > 1000 and level == "medium":
                level = "high"
        elif total_voice == 0:
            reason += "舆情尚未发酵，属数据预警。"
    elif suggestion == "削上限补下限":
        eco = "上限被针对ban/大众泛用，压迫生态" if oppressive else "上限未被针对ban，疑高操作英雄的技术差(非紧急)"
        if total_voice > 0:
            dir_ = "该削" if net_voice > 0 else "该加强"
            reason += (f"上限高(巅峰胜/ban冒头)但下限低(全段胜弱)，{eco}；舆情倾向「{dir_}」"
                       f"(合计{total_voice:.0f}){lowconf_note}——体感与数据冲突，宜结构性调整(削上限、补下限)，需人工研判。")
        else:
            reason += f"上限高但下限低，{eco}，舆情尚未发酵，属数据预警(结构性)。"
    else:  # 维持
        if hero_type == "低端友好":
            reason += "全段胜率虚高但巅峰并不强，属低分段友好(容错高/对手弱)，非强度问题；削之误伤大众，建议维持。"
            if total_voice > 0 and net_voice > 0:
                reason += f"舆情虽呼吁削弱(合计{total_voice})，仍不建议一刀切削，至多针对性微调。"
        elif hero_type == "疑似绝活哥":
            reason += "巅峰高胜但冷门且无人ban，全段亦小样本，属绝活哥虚高，高胜不作数，建议维持观察。"
            if total_voice > 0 and net_voice > 0:
                reason += f"舆情呼吁削弱(合计{total_voice})，但仅少数玩家精通，削之伤面小、误伤大，宜观察。"
        elif total_voice > 0:
            dir_ = "该削" if net_voice > 0 else "该加强"
            reason += f"舆情倾向「{dir_}」(合计{total_voice})，但数据不支持，疑似体感偏差，建议观察。"

    return HeroVerdict(hero=m.hero, suggestion=suggestion,
                       level=level, hero_type=hero_type, reason=reason)


def assess_all(voices: list[HeroVoice]) -> list[HeroVerdict]:
    """
    方案A 入口：遍历所有有数据的英雄评级，舆情按英雄名匹配加成。
    再补上"有舆情但无数据"的英雄（标数据缺失）。
    """
    metrics_list = all_metrics()
    stats = _build_stats(metrics_list)
    voice_map = {v.hero: v for v in voices}

    verdicts = [assess_hero(m, voice_map.get(m.hero), stats) for m in metrics_list]

    # 有舆情却查不到数据的英雄
    data_heroes = {m.hero for m in metrics_list}
    for v in voices:
        if v.hero not in data_heroes:
            verdicts.append(HeroVerdict(
                hero=v.hero, suggestion="维持", level="low", hero_type="数据缺失",
                reason=f"舆情有呼声(合计{v.total})，但暂无客观数据，无法印证，建议补数据。",
            ))

    # 按优先级排序：high > medium > low
    order = {"high": 0, "medium": 1, "low": 2}
    verdicts.sort(key=lambda vd: order[vd.level])
    return verdicts


# 单独测试（不需 LLM，直接用 mock 数据验证双轴分型）：python -m src.skills.risk
if __name__ == "__main__":
    for vd in assess_all(voices=[]):
        print(f"[{vd.level:6}] {vd.hero:8} {vd.suggestion}  {vd.reason}")

"""
告警：决定"要不要通知 + 通知什么"，防告警疲劳。

聚焦策略（避免把半个英雄池糊脸）：
  【A】舆情+数据双印证：玩家净呼声方向与数据建议一致 → 最高优先，全推。
  【B】数据盲区：舆情尚未发酵、但数据异常的 → 只推 high，且限 Top N。
抑制规则：
  - cron 模式只推 high；standalone 连 medium(仅印证类)一起
  - 免打扰时段(23:00-07:00)非 high 一律不推
  - 同一英雄上一轮已告警 → 标"持续告警"，仍推但降噪
本文件只 print 告警块作占位；接飞书/邮件/IM 时，把 _send() 换成真实发送即可。
"""
from datetime import datetime

from src.models.schemas import HeroVerdict, HeroVoice
from src.skills import storage
from src.config import config


def _in_quiet_hours() -> bool:
    h = datetime.now().hour
    # 跨零点时段：23,0,1,...,6
    return h >= config.QUIET_START or h < config.QUIET_END


def _confirmed_by_voice(v: HeroVerdict, voice: HeroVoice | None) -> bool:
    """玩家净呼声方向是否与数据建议一致（双印证）。"""
    if not voice:
        return False
    net = voice.nerf_votes - voice.buff_votes
    if v.suggestion == "削弱" and net > 0:
        return True
    if v.suggestion == "加强" and net < 0:
        return True
    return False


def _send(text: str):
    """占位：真实场景改成调飞书/邮件/IM webhook。"""
    print("\n" + "🔔 [告警推送]".center(60, "="))
    print(text)
    print("=" * 60 + "\n")


def _fmt(v: HeroVerdict, trends: dict, last: set) -> str:
    t = trends.get(v.hero, {})
    cont = "（持续告警）" if v.hero in last else ""
    tag = t.get("tag", "")
    return (f"• 【{v.hero}】{v.hero_type} → 建议{v.suggestion} "
            f"[{v.level}] {tag}{cont}\n    {v.reason}")


def notify(run_ts: str, verdicts: list[HeroVerdict],
           trends: dict[str, dict], mode: str, voices: list[HeroVoice]):
    """
    verdicts：本轮所有评级（已按 high>medium>low 排序）。
    voices  ：本轮舆情，用于判断"是否双印证"。
    mode    ："cron"(定时) / "standalone"(手动)。
    """
    voice_map = {v.hero: v for v in voices}
    threshold = {"high"} if mode == "cron" else {"high", "medium"}

    actionable = [v for v in verdicts
                  if v.suggestion != "维持" and v.level in threshold]

    # —— 闭环：读人工处置，抑制重复告警 ——
    storage.tick_feedback()                       # 抑制轮数递减、到期清除
    fb = storage.get_feedback()
    suppressed = set(fb)                          # 有处置在生效 → 本轮不重复 push
    paused = {h for h, i in fb.items() if i["status"] == "需跟进"}  # 冻结积压计数
    if suppressed:
        _tags = "、".join(f"{h}({fb[h]['status']}剩{fb[h]['snooze_left']}轮)"
                          for h in sorted(suppressed))
        print(f"🔕 已抑制(人工处置生效)：{_tags}")

    # 维护"陈年欠账"：需跟进的冻结(不+1不删)，其余照常
    backlog_map = storage.update_backlog(
        run_ts, [v.hero for v in actionable if v.hero not in paused], protect=paused)

    # 去重分桶：每个英雄只进一个桶，优先级 ④积压 > ①双印证 > ③结构 > ②盲区
    #   被抑制(有处置)的英雄预置进 seen → 直接跳过所有推送桶
    seen: set[str] = set(suppressed)

    def _take(pred) -> list[HeroVerdict]:
        out = []
        for v in actionable:
            if v.hero in seen:
                continue
            if pred(v):
                out.append(v)
                seen.add(v.hero)
        return out

    # 【④】陈年欠账：连续 N 轮仍需改动 → 越拖越显眼。
    #   收敛防爆：只收 high，按「积压轮数↓、舆情呼声↓」排序取 TopN；没选中的回落①②③。
    def _vtotal(h: str) -> float:
        v = voice_map.get(h)
        return v.total if v else 0.0

    backlog_cand = [v for v in actionable
                    if v.hero not in seen
                    and backlog_map.get(v.hero, 0) >= config.BACKLOG_ALERT_ROUNDS
                    and v.level == "high"]
    backlog_cand.sort(key=lambda v: (-backlog_map[v.hero], -_vtotal(v.hero)))
    backlog = backlog_cand[:config.DATA_ALERT_TOPN]
    seen.update(v.hero for v in backlog)

    # 【①】舆情+数据双印证
    confirmed = _take(lambda v: _confirmed_by_voice(v, voice_map.get(v.hero)))
    # 【③】结构性：两极分化(削上限补下限)，方向天然冲突，无视舆情方向全推
    structural = _take(lambda v: v.suggestion == "削上限补下限")
    # 【②】数据盲区：舆情未发酵，只留 high，限 Top N（verdicts 已按严重度排序）
    data_only = _take(lambda v: v.hero not in voice_map and v.level == "high")[:config.DATA_ALERT_TOPN]

    # 免打扰：非 high 一律压掉（积压欠账同样只在白天推非high）
    if _in_quiet_hours():
        confirmed = [v for v in confirmed if v.level == "high"]
        backlog = [v for v in backlog if v.level == "high"]

    if not backlog and not confirmed and not structural and not data_only:
        print("（本轮无需告警）")
        storage.save_alerts(run_ts, [])
        return

    last = storage.last_alerted_heroes()
    blocks = [f"📊 王者英雄强度舆情告警  {run_ts[:16]}"]

    if backlog:
        blocks.append(f"\n—— ④陈年欠账（连续≥{config.BACKLOG_ALERT_ROUNDS}轮判需改动仍未解决）——")
        blocks += [f"⚠️积压{backlog_map[v.hero]}轮 " + _fmt(v, trends, last) for v in backlog]
    if confirmed:
        blocks.append("\n—— ①舆情+数据双印证（优先跟进）——")
        blocks += [_fmt(v, trends, last) for v in confirmed]
    if structural:
        blocks.append("\n—— ③结构性（削上限/补下限，体感与数据冲突，需人工研判）——")
        blocks += [_fmt(v, trends, last) for v in structural]
    if data_only:
        blocks.append(f"\n—— ②数据盲区（舆情未发酵，Top{config.DATA_ALERT_TOPN}）——")
        blocks += [_fmt(v, trends, last) for v in data_only]

    _send("\n".join(blocks) + "\n\n请确认：误报 / 已关注 / 需跟进")
    storage.save_alerts(run_ts, backlog + confirmed + structural + data_only)

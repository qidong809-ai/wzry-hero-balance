"""
Skill 3：舆情聚合与排行
职责：把一堆 HeroMention 按英雄汇总成 HeroVoice。
权重：一条一票为主 + 点赞做 log 弱加成，公式 weight = 1 + log10(1 + likes)。
  - 一票保底：契合舆情本意「多少人在吵」，不被少数爆款视频一手遮天
  - log 加成：热帖略重(3万赞≈4.5、500赞≈3.7、10赞≈2)，差距压到 ~2x，不失真
  - log 自带软封顶：再离谱的点赞也就到 6~7，无需额外硬封顶
置信度：五因子合成，抗羊群/水军/跟风。见 _confidence()。
输入：list[HeroMention]
输出：list[HeroVoice]（按呼声从高到低排序）
"""
import math
from datetime import datetime

from src.models.schemas import HeroMention, HeroVoice


def _weight(likes: int) -> float:
    return 1 + math.log10(1 + max(likes, 0))


def _parse_ts(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def _confidence(v: HeroVoice, platforms: set[str], times: list[datetime],
                batch_platforms: set[str]) -> float:
    """舆情置信度 0~1，五因子合成（抗羊群/单条爆帖/口水战/信息茧房/跟风突发）：
      ① 分散度(0.3)：1 - 单条最大权重占比。防一条爆帖垄断呼声。
      ② 样本量(0.2)：min(mentions/10,1)。人越多越可信。
      ③ 方向明确度(0.15)：|net|/total。削强对喷=争议=噪音。
      ④ 跨平台(0.2)：命中平台数/全批平台数。孤证于单一圈子降权(信息茧房)。
      ⑤ 时间分散(0.15)：呼声在时间上越均匀越像真实体感；集中爆发疑跟风。
    ④⑤ 缺数据(单平台批/无时间戳)时给中性值，不误伤。
    """
    if v.total <= 0:
        return 0.0
    dispersion = 1 - (v.max_weight / v.total)
    sample = min(v.mentions / 10, 1.0)
    direction = abs(v.nerf_votes - v.buff_votes) / v.total

    # ④ 跨平台：整批只有单一平台时该因子无意义 → 中性 1.0，不惩罚
    cross = len(platforms) / len(batch_platforms) if len(batch_platforms) > 1 else 1.0

    # ⑤ 时间分散：≥2 个有效时间才算，跨度 24h 记满；否则中性 0.5
    if len(times) >= 2:
        span_h = (max(times) - min(times)).total_seconds() / 3600
        time_spread = min(span_h / 24, 1.0)
    else:
        time_spread = 0.5

    return round(0.3 * dispersion + 0.2 * sample + 0.15 * direction
                 + 0.2 * cross + 0.15 * time_spread, 2)


def aggregate_voices(mentions: list[HeroMention]) -> list[HeroVoice]:
    voices: dict[str, HeroVoice] = {}
    platforms: dict[str, set[str]] = {}
    times: dict[str, list[datetime]] = {}
    batch_platforms: set[str] = set()

    for m in mentions:
        if m.hero not in voices:
            voices[m.hero] = HeroVoice(hero=m.hero)
            platforms[m.hero] = set()
            times[m.hero] = []
        v = voices[m.hero]
        v.mentions += 1
        w = _weight(m.likes)
        v.max_weight = max(v.max_weight, w)
        if m.stance == "该削":
            v.nerf_votes += w
        else:
            v.buff_votes += w
        if m.platform:
            platforms[m.hero].add(m.platform)
            batch_platforms.add(m.platform)
        ts = _parse_ts(m.created_at)
        if ts:
            times[m.hero].append(ts)

    for hero, v in voices.items():
        v.confidence = _confidence(v, platforms[hero], times[hero], batch_platforms)

    # 按呼声总量从高到低排序 → 排在前面的就是"被吐槽最多"的英雄
    return sorted(voices.values(), key=lambda x: x.total, reverse=True)


# 单独测试（需 LLM）：python -m src.skills.aggregate
if __name__ == "__main__":
    from src.skills.collect import collect_feedback
    from src.skills.analyze import analyze_feedback

    voices = aggregate_voices(analyze_feedback(collect_feedback()))
    print("英雄呼声排行：")
    for i, v in enumerate(voices, 1):
        print(f"  {i}. {v.hero:6} 该削{v.nerf_votes:.1f} / 该加强{v.buff_votes:.1f} "
              f"(合计{v.total:.1f}，{v.mentions}条，置信{v.confidence})")

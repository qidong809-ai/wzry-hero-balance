"""
基线与突增检测：让告警只关注"新增/突增"，而非每轮重报老争议。
对每个英雄，把本轮呼声和它自己过去 N 天的历史比：
  - 无历史(第一次出现) → 新增争议
  - 呼声相对历史均值 z ≥ SURGE_Z → 突增
  - 否则 → 持续/平稳
时间维度的 z-score，和 risk.py 里"跨英雄"的 z-score 互补。
"""
import statistics

from src.models.schemas import HeroVoice
from src.skills import storage
from src.config import config


def trend_for(voice: HeroVoice) -> dict:
    """返回该英雄的趋势判断。"""
    hist = storage.hero_history(voice.hero, config.BASELINE_DAYS)

    if not hist:
        return {"tag": "新增", "z": None, "mean": 0.0,
                "desc": "历史无记录，首次出现的强度争议"}

    mean = statistics.mean(hist)

    # 样本太少：σ 不可靠，别据此判突增（否则 σ≈0 会让 z 飙到天文数字）
    if len(hist) < config.SURGE_MIN_HISTORY:
        return {"tag": "持续", "z": None, "mean": mean,
                "desc": f"呼声{voice.total}，历史仅{len(hist)}条样本不足，暂不判突增"}

    # σ 封底：历史全同值时 pstdev≈0，用均值比例兜底，避免除极小数导致 z 爆炸
    sigma = max(statistics.pstdev(hist), mean * config.SURGE_SIGMA_FLOOR, 1.0)
    z = (voice.total - mean) / sigma

    if z >= config.SURGE_Z:
        return {"tag": "突增", "z": z, "mean": mean,
                "desc": f"呼声{voice.total} 远超历史周均{mean:.0f}(z{z:+.1f})，明显升温"}
    return {"tag": "持续", "z": z, "mean": mean,
            "desc": f"呼声{voice.total} 与历史周均{mean:.0f}持平(z{z:+.1f})"}


def trends_for_all(voices: list[HeroVoice]) -> dict[str, dict]:
    return {v.hero: trend_for(v) for v in voices}


# 单独测试：python -m src.skills.baseline
if __name__ == "__main__":
    storage.init_db()
    demo = HeroVoice(hero="澜", nerf_votes=3000, buff_votes=0)
    print(trend_for(demo))

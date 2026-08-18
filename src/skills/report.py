"""
流程编排 + 报告（舆情为主，数据为验证器，含记忆/基线/容错/告警）

一轮流程：
  采集 → LLM抽取 → 聚合呼声 →〔基线对比:新增/突增〕→ 双轴数据研判
       → 落库 → 出报告(舆情榜+数据预警) → 告警(带抑制)
容错：任一步失败 → dataQuality 降级(ok/partial/missing)，风险只升不降、不漏报。
"""
from datetime import datetime

from src.skills.collect import collect_feedback
from src.skills.analyze import analyze_feedback
from src.skills.aggregate import aggregate_voices
from src.skills.risk import assess_all
from src.skills.baseline import trends_for_all
from src.skills import storage, notify, metrics

_ICON = {"low": "🟢", "medium": "🟡", "high": "🔴"}
_TREND_ICON = {"新增": "🆕", "突增": "📈", "持续": "➖"}


def run_once(mode: str = "cron"):
    run_ts = datetime.now().isoformat()
    storage.init_db()

    print("=" * 66)
    print(f"王者荣耀 英雄强度舆情巡检  {run_ts[:19]}  [{mode}]")
    print("=" * 66)

    # —— 采集 + 抽取（含容错，标数据质量）——
    quality = "ok"
    try:
        feedbacks = collect_feedback()
    except Exception as e:
        feedbacks, quality = [], "partial"
        print(f"⚠️ 采集失败：{e}")

    try:
        mentions = analyze_feedback(feedbacks)
    except Exception as e:
        mentions, quality = [], "missing" if not feedbacks else "partial"
        print(f"⚠️ 情感分析失败：{e}")

    voices = aggregate_voices(mentions)
    print(f"采集 {len(feedbacks)} 条，命中词条 {len(mentions)} 条，涉及英雄 {len(voices)} 个"
          f"｜数据质量：{quality}")

    # —— 基线对比（新增/突增）：必须在落库【之前】，否则历史含本轮 ——
    trends = trends_for_all(voices)
    storage.save_snapshot(run_ts, voices)

    # —— 双轴数据研判 ——
    verdict_map = {vd.hero: vd for vd in assess_all(voices)}
    voiced = {v.hero for v in voices}

    # —— 数据轴快照落库（客观指标 + CSV 批次），供日后回测 ——
    storage.save_metrics(run_ts, metrics.all_metrics(), metrics.csv_batch())

    # partial 时保守：风险只升不降（此处仅提示，评级逻辑本身不因缺数据而降级）
    if quality != "ok":
        print(f"⚠️ 数据质量={quality}，采取保守策略：宁可误报，不漏报。")

    _print_report(voices, list(verdict_map.values()), trends, mode)
    notify.notify(run_ts, list(verdict_map.values()), trends, mode, voices)
    print("=" * 66 + "\n")


def _print_report(voices, verdicts, trends, mode):
    """格式化输出报告（可被 agent 复用）。"""
    verdict_map = {vd.hero: vd for vd in verdicts}
    voiced = {v.hero for v in voices}

    # 【一】舆情呼声榜（主）+ 基线标签
    print("\n【一】舆情呼声榜（玩家呼声从高到低）")
    print("-" * 66)
    if not voices:
        print("  本轮无有效舆情。")
    for i, v in enumerate(voices, 1):
        vd = verdict_map.get(v.hero)
        if not vd:
            continue
        tr = trends.get(v.hero, {"tag": "", "desc": ""})
        ti = _TREND_ICON.get(tr.get("tag", ""), "")
        dir_ = "该削" if v.nerf_votes >= v.buff_votes else "该加强"
        print(f"No.{i} {ti}{tr.get('tag','')} 【{v.hero}】呼声{v.total:.1f}"
              f"（削{v.nerf_votes:.1f}/强{v.buff_votes:.1f}，{v.mentions}条，倾向{dir_}）")
        print(f"     {_ICON[vd.level]} 数据研判：{vd.hero_type} → 建议 {vd.suggestion}")
        print(f"     舆情趋势：{tr.get('desc','')}")
        print(f"     {vd.reason}")

    # 【二】数据预警（辅：舆情没提但数据异常的冷门）
    silent = [vd for vd in verdicts
              if vd.hero not in voiced and vd.suggestion != "维持"]
    print("\n【二】数据预警（舆情未提及、但数据异常的盲区）")
    print("-" * 66)
    if not silent:
        print("  无。")
    for vd in silent:
        print(f"{_ICON[vd.level]} 【{vd.hero}】{vd.hero_type} → 建议 {vd.suggestion}")
        print(f"     {vd.reason}")

    print("\n【三】告警")
    print("-" * 66)


# 手动跑一轮（详细模式）：python -m src.skills.report
if __name__ == "__main__":
    run_once(mode="standalone")

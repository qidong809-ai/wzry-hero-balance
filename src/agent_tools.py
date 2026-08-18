"""
Agent 工具注册表：每个 tool 对应一个可执行函数。
Agent 的 planner 从这里选工具，execute_tool 负责调度。
"""
import time
from src.skills import crawl, storage
from src.skills.collect import collect_feedback, latest_batch_date
from src.skills.analyze import analyze_feedback
from src.skills.aggregate import aggregate_voices
from src.skills.baseline import trends_for_all
from src.skills.risk import assess_all
from src.skills.notify import notify


TOOLS = {
    "check_freshness": {
        "desc": "检查舆情数据新鲜度（各平台最新落盘时间）",
    },
    "crawl_platform": {
        "desc": "爬取指定平台（xhs/douyin），拉起 MediaCrawler",
        "args": ["platform"],
    },
    "crawl_hero": {
        "desc": "针对某英雄补充爬取（更多关键词组合）",
        "args": ["hero"],
    },
    "analyze": {
        "desc": "对当前采集数据做语义分析，抽取英雄+词条+倾向",
    },
    "assess": {
        "desc": "跑双轴数据研判（z-score 分型+告警分桶）",
    },
    "report": {
        "desc": "输出最终报告并落库（结束 Agent 循环）",
    },
}


def _tool_check_freshness(args: dict, state: dict) -> dict:
    """检查各平台数据 age，标记过期的。"""
    stale = []
    for code, data_dir in crawl.PLATFORMS:
        age_h = (time.time() - crawl._latest_mtime(data_dir)) / 3600
        if age_h >= crawl.CRAWL_INTERVAL_HOURS:
            stale.append(data_dir)
        print(f"  {data_dir}：{age_h:.1f}h（{'⚠️过期' if data_dir in stale else '✅新鲜'}）")

    state["findings"]["stale_platforms"] = stale
    state["phase"] = "freshness_checked"
    return {"stale": stale, "msg": f"{len(stale)} 个平台过期" if stale else "全部新鲜"}


def _tool_crawl_platform(args: dict, state: dict) -> dict:
    """爬取指定平台。"""
    platform = args.get("platform", "xhs")
    code = next((c for c, d in crawl.PLATFORMS if d == platform), None)
    if not code:
        code = platform  # fallback: treat as code directly

    print(f"  拉起爬虫 → {platform}...")
    ok, msg = crawl._run(code)
    print(f"  {'✅' if ok else '❌'} {msg}")

    # 从 stale 列表移除
    stale = state["findings"].get("stale_platforms", [])
    if platform in stale:
        stale.remove(platform)
    state["findings"]["stale_platforms"] = stale
    state["phase"] = "crawled"
    return {"ok": ok, "msg": msg}


def _tool_crawl_hero(args: dict, state: dict) -> dict:
    """针对某英雄补充爬取（简化版：用英雄名作为额外关键词跑一轮）。"""
    hero = args.get("hero", "")
    print(f"  补采验证：针对「{hero}」单独爬取...")
    # TODO: 实际应调用 MediaCrawler 并传入 hero-specific keywords
    # 当前 mock：标记已补采
    print(f"  ⚠️ 补采功能待实现（需扩展 MediaCrawler 关键词参数），本轮跳过")
    state["phase"] = "hero_crawled"
    return {"ok": False, "msg": "补采功能待实现，跳过"}


def _tool_analyze(args: dict, state: dict) -> dict:
    """采集 + 语义分析。"""
    feedbacks = collect_feedback()
    mentions = analyze_feedback(feedbacks)
    voices = aggregate_voices(mentions)

    state["findings"]["feedbacks"] = len(feedbacks)
    state["findings"]["mentions"] = len(mentions)
    state["findings"]["voices"] = voices
    state["findings"]["mentions_raw"] = mentions
    state["phase"] = "analyzed"

    print(f"  采集 {len(feedbacks)} 条 → 命中 {len(mentions)} 条 → 涉及 {len(voices)} 英雄")
    return {"feedbacks": len(feedbacks), "mentions": len(mentions), "heroes": len(voices)}


def _tool_assess(args: dict, state: dict) -> dict:
    """双轴研判 + 基线对比 + 识别低置信度信号。"""
    voices = state["findings"].get("voices", [])
    if not voices:
        return {"error": "未分析，先调用 analyze"}

    trends = trends_for_all(voices)
    verdicts = assess_all(voices)
    storage.save_snapshot(state["run_ts"], voices)

    # 识别低置信度：突增且样本 < 5 条的英雄
    voice_map = {v.hero: v for v in voices}
    low_confidence = []
    for v in voices:
        t = trends.get(v.hero, {})
        if t.get("tag") == "突增" and v.mentions < 5:
            low_confidence.append(v.hero)

    state["findings"]["verdicts"] = verdicts
    state["findings"]["trends"] = trends
    state["findings"]["low_confidence_heroes"] = low_confidence
    state["phase"] = "assessed"

    high = [vd for vd in verdicts if vd.level == "high" and vd.suggestion != "维持"]
    print(f"  研判完成：{len(verdicts)} 英雄评级，{len(high)} 个 high 告警")
    if low_confidence:
        print(f"  ⚠️ 低置信度（突增但样本<5）：{low_confidence}")
    return {"verdicts": len(verdicts), "high_alerts": len(high),
            "low_confidence": low_confidence}


def _tool_report(args: dict, state: dict) -> dict:
    """输出最终报告（复用 report.py 的格式化逻辑）。"""
    from src.skills.report import _print_report

    voices = state["findings"].get("voices", [])
    verdicts = state["findings"].get("verdicts", [])
    trends = state["findings"].get("trends", {})
    mentions = state["findings"].get("mentions_raw", [])

    if not verdicts:
        print("  ⚠️ 未经研判就输出报告，结果可能不完整")

    _print_report(voices, verdicts, trends, state["mode"])
    notify(state["run_ts"], verdicts, trends, state["mode"], voices)
    return {"reported": True}


_DISPATCH = {
    "check_freshness": _tool_check_freshness,
    "crawl_platform": _tool_crawl_platform,
    "crawl_hero": _tool_crawl_hero,
    "analyze": _tool_analyze,
    "assess": _tool_assess,
    "report": _tool_report,
}


def execute_tool(name: str, args: dict, state: dict) -> dict:
    fn = _DISPATCH.get(name)
    if not fn:
        print(f"  ❌ 未知工具：{name}")
        return {"error": f"unknown tool: {name}"}
    return fn(args, state)

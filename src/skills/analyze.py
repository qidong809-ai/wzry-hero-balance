"""
Skill 2：舆情分析（关键词抽取）
职责：把每条反馈交给 LLM，判断：
  - 提到哪个英雄
  - 是否命中监控词条（超标/弱势/增强/削弱）
  - 玩家诉求倾向（该削 / 该加强）
输入：list[Feedback]
输出：list[HeroMention]（没命中词条或没提英雄的会被过滤掉）
"""
import glob
import json
import os
import re

from src.models.schemas import Feedback, HeroMention
from src.utils.llm import ask_json
from src.config import config
from src.skills.aliases import normalize

_KEYWORDS = "、".join(config.KEYWORDS.keys())

# 没配云端 LLM 时，回退读「人工/AI 预分析」结果，充当离线 LLM。
# 按批次归档：data/mentions/mentions_YYYY-MM-DD.json（读日期最新的一份）。
# 每份带 meta.source_batch，标明它分析的是哪一批采集数据。
_MENTIONS_DIR = "data/mentions"
_LEGACY_PATH = "data/analyzed_mentions.json"


def _latest_batch() -> str | None:
    files = sorted(glob.glob(os.path.join(_MENTIONS_DIR, "mentions_*.json")))
    return files[-1] if files else (
        _LEGACY_PATH if os.path.exists(_LEGACY_PATH) else None)


def _load_analyzed() -> tuple[list[HeroMention], str, str]:
    """返回 (mentions, 分析批次, 文件名)；批次未知时为 ""。"""
    path = _latest_batch()
    if not path:
        return [], "", ""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict):                 # 新格式：带 meta
        rows = raw.get("mentions", [])
        batch = raw.get("meta", {}).get("source_batch", "")
    else:                                     # 旧格式：裸 list，批次未知
        rows, batch = raw, ""

    out: list[HeroMention] = []
    for r in rows:
        hero = normalize(r["hero"])          # 别名/黑话 → 规范名；装备等非英雄 → 丢弃
        if not hero:
            continue
        out.append(HeroMention(hero=hero, keyword=r["keyword"],
                               stance=r["stance"], likes=r["likes"],
                               source=r.get("source", ""),
                               platform=r.get("platform", ""),
                               created_at=r.get("created_at", "")))
    return out, batch, os.path.basename(path)


_SYSTEM = f"""你是《{config.GAME_NAME}》英雄强度舆情分析师。
判断这条反馈是否在讨论某个英雄的强度，只输出 JSON，字段：
- hero: 提到的英雄名；若没明确提到具体英雄，填 ""
- keyword: 命中的监控词条，只能是这几个之一：{_KEYWORDS}；都没命中填 ""
- stance: 诉求倾向，只能是 "该削" 或 "该加强"；无法判断填 ""
判定规则：超标/削弱 → 该削；弱势/增强 → 该加强。
不要输出多余文字。"""


def analyze_feedback(feedbacks: list[Feedback]) -> list[HeroMention]:
    # 没配云端 LLM key → 用离线预分析结果（AI 逐条语义分析的归档）
    if not config.LLM_API_KEY:
        from src.skills.collect import latest_batch_date

        analyzed, batch, fname = _load_analyzed()
        if analyzed:
            data_batch = latest_batch_date()
            if batch and data_batch and batch != data_batch:
                print(f"🚨 语义分析结果已过期：{fname} 分析的是 {batch} 批数据，"
                      f"但当前采集数据是 {data_batch} 批。")
                print("   → 榜单反映的是旧舆情，新爬到的内容【未被分析】。"
                      f"请重做语义分析并存为 {_MENTIONS_DIR}/mentions_{data_batch}.json")
            elif not batch:
                print(f"⚠️ {fname} 无批次标记（旧格式），无法校验是否对应当前采集数据。")
            else:
                print(f"ℹ️ 未配 LLM，采用离线语义分析结果 {len(analyzed)} 条"
                      f"（{fname}，批次 {batch} 与采集数据一致）。")
            return analyzed

    mentions: list[HeroMention] = []
    for fb in feedbacks:
        data = ask_json(_SYSTEM, fb.content)
        hero = normalize(data.get("hero", ""))   # 归一到规范名（黑话/皮肤名/装备过滤）
        keyword = data.get("keyword", "").strip()
        stance = data.get("stance", "").strip()
        # 只保留：提到了具体英雄、且命中词条、且有明确倾向的
        if hero and keyword in config.KEYWORDS and stance in ("该削", "该加强"):
            mentions.append(HeroMention(
                hero=hero, keyword=keyword, stance=stance, likes=fb.likes,
                source=fb.content[:120],
                platform=fb.platform,
                created_at=fb.created_at.isoformat(),
            ))
    return mentions


# 单独测试（需 LLM 配置）：python -m src.skills.analyze
if __name__ == "__main__":
    from src.skills.collect import collect_feedback

    for m in analyze_feedback(collect_feedback()):
        print(f"{m.hero:6} {m.keyword} → {m.stance}  👍{m.likes}")

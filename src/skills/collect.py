"""
Skill 1：采集玩家反馈
真实源接 MediaCrawler 抓的【小红书 + 抖音】JSON（笔记/视频正文 + 评论）。
读不到真实数据时，自动回退到模拟数据，保证流程不断。
只改本文件内部，返回同样的 Feedback 列表即可。
"""
import glob
import json
import os
import re
import time
from datetime import datetime

from src.models.schemas import Feedback
from src.skills import crawl

# MediaCrawler 输出根目录；各平台在其下自己的子目录
MC_DATA_ROOT = os.path.join(crawl.MC_ROOT, "data")
# 平台名(存入 Feedback) -> MediaCrawler 的目录代号
PLATFORMS = {"xiaohongshu": "xhs", "douyin": "douyin"}

# 只保留近 N 天的反馈（综合/相关度排序会掺老帖，必须按时间过滤）
RECENT_DAYS = 14


def _latest(json_dir: str, pattern: str) -> str | None:
    """挑目录下最新的一份文件。"""
    files = glob.glob(os.path.join(json_dir, pattern))
    return max(files, key=os.path.getmtime) if files else None


def _load(path: str) -> list[dict]:
    """读 JSON；文件为空或正在写入(半截)时返回空列表，不中断。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _to_int(v) -> int:
    """点赞数可能是字符串、可能带 '万'，转成整数。"""
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if not s:
        return 0
    try:
        if s.endswith("万"):
            return int(float(s[:-1]) * 10000)
        return int(s)
    except ValueError:
        return 0


def _recent(ts) -> bool:
    """时间戳是否落在近 RECENT_DAYS 天内；兼容秒(抖音)/毫秒(小红书)。无则丢弃。"""
    if not ts:
        return False
    sec = ts / 1000 if ts > 1e12 else ts   # >1e12 视为毫秒
    return sec >= time.time() - RECENT_DAYS * 86400


def _to_iso(ts) -> datetime:
    """源时间戳(秒/毫秒) → datetime；无效则退回当前时刻。"""
    if ts:
        sec = ts / 1000 if ts > 1e12 else ts
        try:
            return datetime.fromtimestamp(sec)
        except (OSError, ValueError, OverflowError):
            pass
    return datetime.now()


def _read_platform(platform: str, code: str) -> list[Feedback]:
    """读单个平台目录下的 正文 + 评论。"""
    json_dir = os.path.join(MC_DATA_ROOT, code, "json")
    out: list[Feedback] = []
    # 同日重复爬取会往同一份 json 里追加，故按条目 id 去重
    seen: set[str] = set()

    def _new(item: dict, *id_keys: str) -> bool:
        key = next((str(item[k]) for k in id_keys if item.get(k)), "")
        if not key or key in seen:
            return not key
        seen.add(key)
        return True

    contents_path = _latest(json_dir, "search_contents_*.json")
    if contents_path:
        for n in _load(contents_path):
            ts = n.get("time") or n.get("create_time")
            if not _recent(ts):
                continue
            if not _new(n, "note_id", "aweme_id", "id"):
                continue
            title, desc = n.get("title", ""), n.get("desc", "")
            text = title if title == desc else f"{title} {desc}".strip()
            if text:
                out.append(Feedback(platform=platform, content=text,
                                    likes=_to_int(n.get("liked_count")),
                                    created_at=_to_iso(ts)))

    comments_path = _latest(json_dir, "search_comments_*.json")
    if comments_path:
        for c in _load(comments_path):
            ts = c.get("create_time")
            if not _recent(ts):
                continue
            if not _new(c, "comment_id"):
                continue
            text = (c.get("content") or "").strip()
            if text:
                out.append(Feedback(platform=platform, content=text,
                                    likes=_to_int(c.get("like_count")),
                                    created_at=_to_iso(ts)))
    return out


def _real_data() -> list[Feedback]:
    """合并所有平台的近 RECENT_DAYS 天反馈。"""
    out: list[Feedback] = []
    for platform, code in PLATFORMS.items():
        out.extend(_read_platform(platform, code))
    return out


def latest_batch_date() -> str:
    """本轮所读数据的批次日期（各平台最新落盘文件名里的日期，取最大）。
    供 analyze 校验「语义分析结果是否对应当前数据」，避免拿旧分析套新数据。"""
    dates = []
    for code in PLATFORMS.values():
        path = _latest(os.path.join(MC_DATA_ROOT, code, "json"),
                       "search_contents_*.json")
        if path:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path))
            if m:
                dates.append(m.group(1))
    return max(dates) if dates else ""


def _mock_data() -> list[Feedback]:
    """模拟一批含"超标/弱势/增强/削弱"等词条、并提到具体英雄的反馈。"""
    samples = [
        ("douyin", "澜这英雄强度严重超标，位移多伤害爆炸，必须削弱！", 1200),
        ("douyin", "澜太超标了吧，打野被他压得没法玩", 800),
        ("xiaohongshu", "求求了赶紧削弱澜，排位场场被秀", 650),
        ("xiaohongshu", "妲己现在好弱势啊，二技能都躲得掉，该增强了", 400),
        ("weibo", "夏洛特手感是真的好，就是有点超标", 300),
        ("weibo", "鲁班七号太弱势了，射手里垫底，建议增强", 220),
        ("tieba", "镜的强度也超标，连招无脑还高伤，该削", 500),
        ("tieba", "廉颇太弱势没人玩，官方给点增强吧", 90),
        ("douyin", "澜再不削弱我要退游了", 1500),
        ("xiaohongshu", "亚瑟这种老英雄该增强下了，太弱势", 120),
    ]
    return [Feedback(platform=p, content=c, likes=l) for p, c, l in samples]


def collect_feedback() -> list[Feedback]:
    """采集入口：先保证数据新鲜（必要时拉起爬虫），再读；读不到则回退模拟数据。"""
    print("🕷️ 数据保鲜检查：")
    for line in crawl.ensure_fresh():
        print(line)

    real = _real_data()
    if real:
        return real
    print("⚠️ 未读到 MediaCrawler 真实数据，回退模拟数据。")
    return _mock_data()


# 单独测试：python -m src.skills.collect
if __name__ == "__main__":
    fbs = collect_feedback()
    print(f"共采集 {len(fbs)} 条")
    for f in fbs[:20]:
        print(f"[{f.platform}] 👍{f.likes} {f.content[:40]}")

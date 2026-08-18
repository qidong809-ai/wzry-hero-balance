"""
Skill 4：英雄客观数据（巅峰千强 + 全分段 两套）

真实数据来源：手动从「天元之弈数据站」导出的 CSV（零爬虫）。
  - 巅峰千强：游戏模式选「巅峰千强」→ 导出表格 → 文件名形如 heroes_YYYYMMDD_5.csv
               （最能代表竞技上限；若没有，回退「顶端排位」heroes_YYYYMMDD_4.csv）
  - 全分段  ：游戏模式选「全分段」  → 导出表格 → 文件名形如 heroes_YYYYMMDD_1.csv
把两个 CSV 放进 data/ 目录即可，本模块自动读取最新的一份并按【表头名】解析
（胜率/出场率/禁用率），不依赖列顺序，稳。

读不到 CSV 时，回退到下面的少量 mock（仅供离线跑通，非真实）。
"""
import csv
import glob
import os
import re

from src.models.schemas import HeroMetrics

_DATA_DIR = "data"
# 竞技轴：优先「巅峰千强」(gameMode=5，最能代表竞技上限)，无则回退「顶端排位」(gameMode=4)
_TOP_GLOB = "heroes_*_5.csv"
_TOP_FALLBACK = "heroes_*_4.csv"
_ALL_GLOB = "heroes_*_1.csv"   # 全分段（gameMode=1）

# —— 离线兜底 mock（读不到 CSV 时用；不是真实数据）——
_MOCK_TABLE = {
    #          巅峰:胜率  出场   ban    全段:胜率  出场   ban
    "澜":       (0.545, 0.16, 0.55,   0.532, 0.18, 0.40),  # 真超标
    "夏洛特":   (0.548, 0.05, 0.35,   0.505, 0.06, 0.10),  # 高手向
    "赵云":     (0.492, 0.07, 0.06,   0.542, 0.14, 0.08),  # 低端友好
    "阿古朵":   (0.560, 0.015, 0.03,  0.508, 0.02, 0.02),  # 疑似绝活哥
    "廉颇":     (0.470, 0.02, 0.01,   0.462, 0.03, 0.01),  # 真弱势
    "亚瑟":     (0.501, 0.04, 0.02,   0.499, 0.05, 0.02),  # 健康
    "妲己":     (0.485, 0.05, 0.04,   0.478, 0.07, 0.03),  # 偏弱
    "鲁班七号": (0.478, 0.05, 0.03,   0.472, 0.09, 0.02),  # 偏弱
    "镜":       (0.520, 0.10, 0.28,   0.515, 0.12, 0.22),  # 略强
}


def _pct(s: str) -> float | None:
    """把 '53.3%' / '2' / '--.-%' 解析成小数；无效返回 None。"""
    if s is None:
        return None
    s = s.strip().replace("%", "").replace(",", "")
    if s in ("", "--", "--.-", "-"):
        return None
    try:
        return float(s) / 100
    except ValueError:
        return None


def _latest(pattern: str) -> str | None:
    files = glob.glob(os.path.join(_DATA_DIR, pattern))
    return max(files, key=os.path.getmtime) if files else None


def _read_csv(path: str) -> dict[str, dict]:
    """读一份导出的 CSV，按表头名取 胜率/出场率/禁用率，返回 {英雄名: {...}}。"""
    out: dict[str, dict] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("英雄") or "").strip()
            if not name:
                continue
            out[name] = {
                "win": _pct(row.get("胜率")),
                "pick": _pct(row.get("出场率")),
                "ban": _pct(row.get("禁用率")),
            }
    return out


def _load_from_csv() -> dict[str, HeroMetrics] | None:
    top_path = _latest(_TOP_GLOB) or _latest(_TOP_FALLBACK)
    all_path = _latest(_ALL_GLOB)
    if not top_path or not all_path:
        return None

    global _BATCH
    m = re.search(r"(\d{8})", os.path.basename(top_path))
    _BATCH = m.group(1) if m else os.path.basename(top_path)

    top, allseg = _read_csv(top_path), _read_csv(all_path)
    table: dict[str, HeroMetrics] = {}
    for name, t in top.items():
        a = allseg.get(name)
        if not a or t["win"] is None or a["win"] is None:
            continue
        table[name] = HeroMetrics(
            hero=name,
            top_win_rate=t["win"], top_pick_rate=t["pick"] or 0, top_ban_rate=t["ban"] or 0,
            all_win_rate=a["win"], all_pick_rate=a["pick"] or 0, all_ban_rate=a["ban"] or 0,
        )
    if table:
        print(f"ℹ️ 已载入真实客观数据 {len(table)} 个英雄"
              f"（竞技={os.path.basename(top_path)}，全段={os.path.basename(all_path)}）")
    return table or None


def _load_mock() -> dict[str, HeroMetrics]:
    return {
        h: HeroMetrics(hero=h,
                       top_win_rate=r[0], top_pick_rate=r[1], top_ban_rate=r[2],
                       all_win_rate=r[3], all_pick_rate=r[4], all_ban_rate=r[5])
        for h, r in _MOCK_TABLE.items()
    }


# 每次进程内只加载一次
_TABLE: dict[str, HeroMetrics] | None = None
_BATCH: str = ""   # 本次所用竞技轴 CSV 的批次日期（YYYYMMDD），mock 时为 "mock"


def _table() -> dict[str, HeroMetrics]:
    global _TABLE, _BATCH
    if _TABLE is None:
        _TABLE = _load_from_csv()
        if _TABLE is None:
            print("⚠️ 未找到导出的 CSV，回退到离线 mock 数据（非真实）。")
            _TABLE = _load_mock()
            _BATCH = "mock"
    return _TABLE


def csv_batch() -> str:
    """本轮数据轴所用 CSV 的批次日期（供回测溯源"当时看到的是哪份数据"）。"""
    _table()   # 确保已加载
    return _BATCH


def query_hero_metrics(hero: str) -> HeroMetrics | None:
    """查单个英雄数据；查不到返回 None。"""
    return _table().get(hero)


def all_metrics() -> list[HeroMetrics]:
    """返回所有有数据的英雄（方案A：全量遍历，不漏冷门）。"""
    return list(_table().values())


# 单独测试：python -m src.skills.metrics
if __name__ == "__main__":
    ms = all_metrics()
    print(f"共 {len(ms)} 个英雄")
    for m in ms[:15]:
        print(f"{m.hero:8} 巅峰 胜{m.top_win_rate:.1%}/出{m.top_pick_rate:.1%}/ban{m.top_ban_rate:.1%}"
              f"  全段 胜{m.all_win_rate:.1%}/出{m.all_pick_rate:.1%}/ban{m.all_ban_rate:.1%}")

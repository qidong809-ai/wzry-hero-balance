"""
持久化：把每轮巡检结果存进本地 SQLite，让 agent "有记忆"。
- snapshots 表：每轮每个英雄的呼声 → 供"基线/突增"计算
- alerts 表：每轮触发告警的英雄 → 供"持续告警"判断

SQLite 是 Python 自带的，无需安装。数据库文件在 config.DB_PATH，删掉即重置。
"""
import os
import sqlite3
from datetime import datetime, timedelta

from src.config import config
from src.models.schemas import HeroVoice, HeroVerdict, HeroMetrics


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    return sqlite3.connect(config.DB_PATH)


def init_db():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS snapshots(
            run_ts TEXT, hero TEXT,
            nerf_votes INTEGER, buff_votes INTEGER, total INTEGER)""")
        c.execute("""CREATE TABLE IF NOT EXISTS alerts(
            run_ts TEXT, hero TEXT, level TEXT, suggestion TEXT)""")
        # 数据轴快照：每轮落库客观指标 + 所用 CSV 批次 → 回测能还原"当时看到的数据轴"
        c.execute("""CREATE TABLE IF NOT EXISTS metrics(
            run_ts TEXT, hero TEXT, csv_batch TEXT,
            top_win REAL, top_pick REAL, top_ban REAL,
            all_win REAL, all_pick REAL, all_ban REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS backlog(
            hero TEXT PRIMARY KEY, streak INTEGER, first_ts TEXT, last_ts TEXT)""")
        # 人工处置(闭环)：误报/已关注/需跟进/已改。snooze_left=剩余抑制轮数
        c.execute("""CREATE TABLE IF NOT EXISTS feedback(
            hero TEXT PRIMARY KEY, status TEXT, note TEXT, ts TEXT, snooze_left INTEGER)""")
        # ground truth：官方(或人工确认)已改动的英雄，供日后阈值回测
        c.execute("""CREATE TABLE IF NOT EXISTS ground_truth(
            ts TEXT, hero TEXT, status TEXT, note TEXT)""")


def update_backlog(run_ts: str, actionable_heroes: list[str],
                   protect: set[str] | None = None) -> dict[str, int]:
    """维护"陈年欠账"连续轮数：
    - 本轮仍被判需改动(actionable)的英雄 → streak+1（新出现则=1）
    - 本轮不再需改动的英雄 → 从表清除（链条断裂，重新计数）
    - protect 里的英雄(如"需跟进"已冻结)：既不+1 也不删除，streak 原地冻结。
    返回 {hero: 连续轮数}（含被冻结的原值）。
    """
    protect = protect or set()
    cur = set(actionable_heroes)
    with _conn() as c:
        existing = {r[0]: r[1] for r in
                    c.execute("SELECT hero, streak FROM backlog").fetchall()}
        broken = [h for h in existing if h not in cur and h not in protect]
        if broken:
            c.executemany("DELETE FROM backlog WHERE hero=?", [(h,) for h in broken])
        result: dict[str, int] = {}
        for h in cur:
            if h in existing:
                streak = existing[h] + 1
                c.execute("UPDATE backlog SET streak=?, last_ts=? WHERE hero=?",
                          (streak, run_ts, h))
            else:
                streak = 1
                c.execute("INSERT INTO backlog VALUES(?,?,?,?)", (h, 1, run_ts, run_ts))
            result[h] = streak
        # 冻结的英雄：保留原 streak 供展示
        for h in protect:
            if h in existing:
                result[h] = existing[h]
    return result


# ========== 闭环：人工处置 ==========

def set_feedback(hero: str, status: str, rounds: int, note: str = ""):
    """记录一次人工处置。
    - 误报/已关注/需跟进：抑制 rounds 轮（期间不重复 push；"需跟进"额外冻结积压计数）
    - 已改：清零该英雄积压、写入 ground_truth，并抑制 rounds 轮（等数据刷新反映）
    """
    ts = datetime.now().isoformat()
    with _conn() as c:
        if status == "已改":
            c.execute("DELETE FROM backlog WHERE hero=?", (hero,))
            c.execute("INSERT INTO ground_truth VALUES(?,?,?,?)", (ts, hero, status, note))
        c.execute("INSERT OR REPLACE INTO feedback VALUES(?,?,?,?,?)",
                  (hero, status, note, ts, rounds))


def tick_feedback():
    """每轮开头调用：抑制轮数 -1，到期清除。"""
    with _conn() as c:
        c.execute("UPDATE feedback SET snooze_left = snooze_left - 1")
        c.execute("DELETE FROM feedback WHERE snooze_left <= 0")


def get_feedback() -> dict[str, dict]:
    """当前生效的处置：{hero: {status, snooze_left, note}}。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT hero, status, snooze_left, note FROM feedback").fetchall()
    return {r[0]: {"status": r[1], "snooze_left": r[2], "note": r[3]} for r in rows}


def save_snapshot(run_ts: str, voices: list[HeroVoice]):
    """存本轮所有英雄的呼声。"""
    with _conn() as c:
        c.executemany(
            "INSERT INTO snapshots VALUES(?,?,?,?,?)",
            [(run_ts, v.hero, v.nerf_votes, v.buff_votes, v.total) for v in voices],
        )


def save_metrics(run_ts: str, metrics_list: list[HeroMetrics], csv_batch: str):
    """存本轮数据轴快照（客观指标 + CSV 批次），供日后回测溯源。"""
    with _conn() as c:
        c.executemany(
            "INSERT INTO metrics VALUES(?,?,?,?,?,?,?,?,?)",
            [(run_ts, m.hero, csv_batch,
              m.top_win_rate, m.top_pick_rate, m.top_ban_rate,
              m.all_win_rate, m.all_pick_rate, m.all_ban_rate) for m in metrics_list],
        )


def hero_history(hero: str, days: int) -> list[int]:
    """取某英雄过去 days 天的历轮呼声总量（不含本轮，本轮还没存或用更早时间点调用）。"""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT total FROM snapshots WHERE hero=? AND run_ts>=? ORDER BY run_ts",
            (hero, since),
        ).fetchall()
    return [r[0] for r in rows]


def save_alerts(run_ts: str, verdicts: list[HeroVerdict]):
    with _conn() as c:
        c.executemany(
            "INSERT INTO alerts VALUES(?,?,?,?)",
            [(run_ts, v.hero, v.level, v.suggestion) for v in verdicts],
        )


def last_alerted_heroes() -> set[str]:
    """上一轮触发过告警的英雄集合 → 用于标注"持续告警"。"""
    with _conn() as c:
        last = c.execute("SELECT MAX(run_ts) FROM alerts").fetchone()[0]
        if not last:
            return set()
        rows = c.execute("SELECT hero FROM alerts WHERE run_ts=?", (last,)).fetchall()
    return {r[0] for r in rows}


# 单独测试：python -m src.skills.storage
if __name__ == "__main__":
    init_db()
    print("数据库已初始化：", config.DB_PATH)

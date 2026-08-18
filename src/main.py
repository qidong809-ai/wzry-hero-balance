"""
程序入口：启动英雄强度舆情监控 Agent。
- 先立即跑一轮
- 然后每小时自动跑一次
停止：Ctrl+C
"""
from apscheduler.schedulers.blocking import BlockingScheduler

from src.config import config
from src.skills.report import run_once


def main():
    config.check()                         # 检查 LLM 配置
    print("王者荣耀英雄强度舆情 Agent 已启动 ✅  (Ctrl+C 停止)\n")

    run_once(mode="standalone")            # 首轮当手动，输出详细

    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(run_once, "interval", hours=1, id="hourly_check",
                      kwargs={"mode": "cron"})   # 之后定时轮用 cron(告警抑制)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\nAgent 已停止。")


if __name__ == "__main__":
    main()

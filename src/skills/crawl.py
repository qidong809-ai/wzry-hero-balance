"""
拉起 MediaCrawler 抓取（小红书 + 抖音），默认一天一次。

collect.py 读 JSON 之前先调 ensure_fresh()：
  - 最新落盘文件在 CRAWL_INTERVAL_HOURS 内 → 跳过，直接吃缓存
  - 否则 subprocess 拉起爬虫，等它落盘
爬取失败/超时不阻塞巡检，只返回状态行交给上层打印（宁可用旧数据，也不断流程）。
"""
import glob
import os
import subprocess
import sys
import time

MC_ROOT = r"c:\Users\wangqidong01\Desktop\新建文件夹\MediaCrawler-main"

# MediaCrawler 的依赖(typer/playwright)装在它自己的 .venv 里，不能用本项目的解释器
_MC_VENV_PY = os.path.join(MC_ROOT, ".venv", "Scripts", "python.exe")
MC_PYTHON = _MC_VENV_PY if os.path.exists(_MC_VENV_PY) else sys.executable

# (CLI 平台代号, 落盘目录名)：二者不一致，目录名在 store/*/_store_impl.py 里硬编码
PLATFORMS = [("xhs", "xhs"), ("dy", "douyin")]

CRAWL_INTERVAL_HOURS = 24     # 距上次落盘不足此时长 → 不重爬
TIMEOUT_SEC = 1800            # 单平台上限 30 分钟；登录态失效/量大时兜底


def _latest_mtime(data_dir: str) -> float:
    """该平台最新一份正文文件的落盘时间；没有则 0。"""
    files = glob.glob(os.path.join(
        MC_ROOT, "data", data_dir, "json", "search_contents_*.json"))
    return max((os.path.getmtime(f) for f in files), default=0.0)


def _kill_tree(p: subprocess.Popen):
    """爬虫会拉起 Chromium 子进程，必须连子进程树一起杀。"""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                       capture_output=True)
    else:
        p.kill()


def _run(code: str) -> tuple[bool, str]:
    cmd = [MC_PYTHON, "main.py",
           "--platform", code,
           "--type", "search",
           "--save_data_option", "json",
           "--get_comment", "true",
           "--headless", "true"]
    p = subprocess.Popen(cmd, cwd=MC_ROOT,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    try:
        out, _ = p.communicate(timeout=TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        _kill_tree(p)
        p.communicate()
        return False, (f"超时 {TIMEOUT_SEC//60} 分钟已终止"
                       "（已抓到的部分仍可用；登录态可能失效，需人工扫码重登）")

    if p.returncode != 0:
        tail = " | ".join((out or "").strip().splitlines()[-3:])
        return False, f"退出码 {p.returncode}：{tail}"
    return True, "完成"


def ensure_fresh(force: bool = False) -> list[str]:
    """保证两个平台的数据在 CRAWL_INTERVAL_HOURS 内；返回每平台一行状态。"""
    lines = []
    for code, data_dir in PLATFORMS:
        age_h = (time.time() - _latest_mtime(data_dir)) / 3600
        if not force and age_h < CRAWL_INTERVAL_HOURS:
            lines.append(f"  {data_dir}：数据 {age_h:.1f}h 前落盘，跳过爬取")
            continue

        stale = "无数据" if age_h > 1e6 else f"{age_h:.1f}h 前"
        print(f"  {data_dir}：{stale}，开始爬取（最多 {TIMEOUT_SEC // 60} 分钟）...")
        ok, msg = _run(code)
        lines.append(f"  {'✅' if ok else '❌'} {data_dir}：{msg}")
    return lines


# 手动强制爬一轮：python -m src.skills.crawl
if __name__ == "__main__":
    for line in ensure_fresh(force=True):
        print(line)

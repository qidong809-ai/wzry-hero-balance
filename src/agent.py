"""
Agent 核心：LLM 驱动的 ReAct 决策循环。
替代 report.py 的固定管道，让系统能根据中间结果自主决定下一步。

运行：python -m src.agent
配好 LLM 后自动用真 LLM 决策；没配则用 mock planner（模拟决策路径）。
"""
import json
from datetime import datetime

from src.config import config
from src.skills import storage
from src.agent_tools import TOOLS, execute_tool
from src.utils.llm import ask_json

MAX_STEPS = 12

SYSTEM_PROMPT = """你是王者荣耀英雄强度监控 Agent。你的目标：尽快、准确地发现失衡英雄并告警。

当前状态：
{state}

可用工具（选一个执行）：
{tools}

决策规则：
1. 第一步检查数据新鲜度；过期就爬取。
2. 爬取后做语义分析、再做双轴研判。
3. 如果某英雄突增但样本＜5条，针对性补采验证（crawl_hero）。
4. 如果数据充分（无需验证），直接 report 输出报告。
5. 每步只选一个工具。

输出严格 JSON（不要多余文字）：
{{"tool": "工具名", "args": {{}}, "reason": "一句话理由"}}
"""


def _format_tools() -> str:
    return "\n".join(f"- {name}: {t['desc']}" for name, t in TOOLS.items())


def _mock_planner(state: dict) -> dict:
    """无 LLM 时的确定性 mock 决策路径。"""
    phase = state.get("phase", "start")
    findings = state.get("findings", {})

    if phase == "start":
        return {"tool": "check_freshness", "args": {},
                "reason": "第一步：检查数据是否过期"}

    if phase == "freshness_checked":
        stale = findings.get("stale_platforms", [])
        if stale:
            return {"tool": "crawl_platform", "args": {"platform": stale[0]},
                    "reason": f"{stale[0]} 数据过期，需爬取"}
        return {"tool": "analyze", "args": {},
                "reason": "数据新鲜，直接分析"}

    if phase == "crawled":
        remaining = findings.get("stale_platforms", [])
        if remaining:
            return {"tool": "crawl_platform", "args": {"platform": remaining[0]},
                    "reason": f"还有 {remaining[0]} 待爬"}
        return {"tool": "analyze", "args": {},
                "reason": "全部爬完，开始分析"}

    if phase == "analyzed":
        return {"tool": "assess", "args": {},
                "reason": "语义分析完成，跑双轴研判"}

    if phase == "assessed":
        low_confidence = findings.get("low_confidence_heroes", [])
        if low_confidence:
            hero = low_confidence.pop(0)
            return {"tool": "crawl_hero", "args": {"hero": hero},
                    "reason": f"「{hero}」突增但样本不足，补采验证"}
        return {"tool": "report", "args": {},
                "reason": "所有信号置信度足够，输出报告"}

    if phase == "hero_crawled":
        return {"tool": "analyze", "args": {},
                "reason": "补采完成，重新分析"}

    return {"tool": "report", "args": {}, "reason": "兜底：输出报告"}


def _llm_planner(state: dict) -> dict:
    """真 LLM 决策。"""
    prompt = SYSTEM_PROMPT.format(
        state=json.dumps(state, ensure_ascii=False, default=str),
        tools=_format_tools(),
    )
    return ask_json(prompt, "请决策下一步。")


def run_agent(mode: str = "standalone"):
    storage.init_db()
    run_ts = datetime.now().isoformat()
    use_llm = bool(config.LLM_API_KEY)
    planner = _llm_planner if use_llm else _mock_planner

    print("=" * 66)
    print(f"王者荣耀英雄强度监控 Agent  {run_ts[:19]}  [{'LLM' if use_llm else 'mock'}]")
    print("=" * 66)

    state = {"phase": "start", "findings": {}, "steps": [], "run_ts": run_ts, "mode": mode}

    for step in range(1, MAX_STEPS + 1):
        decision = planner(state)
        tool_name = decision.get("tool", "report")
        args = decision.get("args", {})
        reason = decision.get("reason", "")

        print(f"\n{'─'*50}")
        print(f"Step {step} │ 🤖 决策：{tool_name}({args})")
        print(f"        │ 💭 理由：{reason}")
        print(f"{'─'*50}")

        result = execute_tool(tool_name, args, state)
        state["steps"].append({"tool": tool_name, "args": args,
                               "reason": reason, "result_summary": str(result)[:200]})

        if tool_name == "report":
            break

    print(f"\n{'═'*66}")
    print(f"Agent 完成，共 {len(state['steps'])} 步。")
    print(f"{'═'*66}")
    return state


if __name__ == "__main__":
    run_agent()

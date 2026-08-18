"""
LLM 工具：封装商用/本地大模型调用，兼容 OpenAI 协议。
"""
import json
from openai import OpenAI

from src.config import config

_client = None


def _get_client() -> OpenAI:
    """懒加载：首次调用时才建客户端，避免没配 Key 时导入就崩。"""
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    return _client


def ask_json(system_prompt: str, user_prompt: str) -> dict:
    """问 LLM 并强制返回 JSON，方便程序解析。"""
    resp = _get_client().chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)

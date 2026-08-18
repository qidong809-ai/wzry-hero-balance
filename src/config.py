"""
配置中心：统一读取 .env，并定义要监控的词条。
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

    GAME_NAME = "王者荣耀"

    # 要监控的词条，以及它们代表的"玩家诉求倾向"
    #   → 该削  ：玩家觉得太强，呼吁削弱
    #   → 该加强：玩家觉得太弱，呼吁加强
    KEYWORDS = {
        # —— 太强，该削 ——
        "超标": "该削",
        "削弱": "该削",
        "太强": "该削",
        "版本之子": "该削",
        "T0": "该削",
        "无解": "该削",
        "必ban": "该削",
        "强度爆炸": "该削",
        "恶心": "该削",
        "上分": "该削",
        "秒人": "该削",
        "无脑": "该削",
        # —— 太弱，该加强 ——
        "弱势": "该加强",
        "增强": "该加强",
        "太弱": "该加强",
        "下水道": "该加强",
        "砍废了": "该加强",
        "强度垫底": "该加强",
        "没人玩": "该加强",
        "冷门": "该加强",
        "废了": "该加强",
        "打不动": "该加强",
    }

    # === 数据异常判定：相对分布（统计法）===
    # 每轮用全英雄数据算均值μ、标准差σ，按偏离σ的倍数(z-score)判异常，自适应版本。
    # 竞技轴(巅峰)与大众轴(全分段)各自独立算分布。
    Z_STRONG = 1.0          # 胜率 z ≥ +1σ → 偏强候选
    Z_WEAK = -1.0           # 胜率 z ≤ -1σ → 偏弱候选
    Z_BAN_CONFIRM = 0.5     # 巅峰 ban率 z ≥ 此 → 强度被公认（抗绝活哥的佐证）
    Z_PICK_LOW = -0.5       # 出场率 z ≤ 此 → 冷门（绝活哥高危，高胜率需 ban 佐证）
    Z_PICK_DOMINANT = 1.5   # 出场率 z ≥ 此 → 霸榜，泛用性过强
    Z_CEILING = 0.5         # 上限信号：巅峰胜率或ban率任一 z ≥ 此 → "上限偏高"（配合全段弱→两极分化，削上限补下限）


    # === 历史记忆 / 基线（让 agent"有记忆"，只报新增/突增）===
    DB_PATH = "data/monitor.db"   # 历史快照存这（SQLite，删掉可重建）
    BASELINE_DAYS = 7             # 基线回看天数
    SURGE_Z = 2.0                 # 呼声相对自身历史 z ≥ 此 → 突增预警
    SURGE_MIN_HISTORY = 3         # 少于此快照数不算突增（样本太少 σ 不稳，防 z 爆炸）
    SURGE_SIGMA_FLOOR = 0.15      # σ 下限 = 均值×此（历史全同值时 σ≈0，不封底 z 会飙到天文数字）

    # === 舆情置信度（抗羊群/单条爆帖/口水战）===
    # confidence < 此 → 低置信：舆情不做告警提级，只记录标注（宁可漏提级，不被节奏带偏）
    VOICE_CONF_MIN = 0.4

    # === 告警抑制 ===
    QUIET_START = 23              # 免打扰时段起（含），23:00
    QUIET_END = 7                 # 免打扰时段止（不含），07:00
    DATA_ALERT_TOPN = 5          # 数据盲区(舆情未发酵)最多推几个，防告警爆炸
    BACKLOG_ALERT_ROUNDS = 3     # 连续 N 轮被判"需改动"仍未解决 → 升级"陈年欠账"，不受 TopN 挤压

    # === 闭环：人工处置各状态的默认抑制轮数（可被命令行覆盖）===
    #   误报→压一阵重看；已关注→短压降噪；需跟进→长压且冻结积压；已改→压到数据刷新反映
    FEEDBACK_ROUNDS = {"误报": 24, "已关注": 6, "需跟进": 72, "已改": 24}


    @classmethod
    def check(cls):
        if not cls.LLM_API_KEY:
            raise ValueError("没配 LLM_API_KEY！请把 .env.example 复制成 .env 并填好。")


config = Config()

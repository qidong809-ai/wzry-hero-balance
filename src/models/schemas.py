"""
数据结构定义（王者荣耀英雄强度舆情场景）。
"""
from datetime import datetime
from pydantic import BaseModel, Field


class Feedback(BaseModel):
    """一条玩家反馈"""
    platform: str
    content: str
    likes: int = 0
    created_at: datetime = Field(default_factory=datetime.now)


class HeroMention(BaseModel):
    """从一条反馈里抽取出的信息：提到哪个英雄 + 命中哪个词条 + 诉求倾向"""
    hero: str              # 英雄名，如 "澜"
    keyword: str           # 命中的词条：超标/弱势/增强/削弱
    stance: str            # 诉求倾向：该削 / 该加强
    likes: int = 0         # 该反馈热度，用于加权呼声
    source: str = ""       # 原文（截取前120字），用于人工核验判定
    platform: str = ""     # 来源平台（xiaohongshu/douyin），算跨平台一致性
    created_at: str = ""   # 发布时间 ISO 串（可空），算时间突发/集中度


class HeroVoice(BaseModel):
    """某个英雄的舆情聚合结果（呼声）"""
    hero: str
    nerf_votes: float = 0   # 呼吁削弱的加权呼声（该削）：一条一票 + log点赞弱加成
    buff_votes: float = 0   # 呼吁加强的加权呼声（该加强）
    mentions: int = 0       # 原始命中条数（多少条在吵，纯计数）
    max_weight: float = 0   # 单条最大权重（算分散度用，抗单条爆帖垄断）
    confidence: float = 0   # 舆情置信度 0~1：样本量×分散度×方向明确度

    @property
    def total(self) -> float:
        return self.nerf_votes + self.buff_votes


class HeroMetrics(BaseModel):
    """英雄客观数据（巅峰千强 + 全分段 两套）"""
    hero: str
    # --- 巅峰千强（竞技轴：管高分段/职业公平）---
    top_win_rate: float    # 巅峰胜率 0~1
    top_pick_rate: float   # 巅峰出场率 0~1
    top_ban_rate: float    # 巅峰 ban率 0~1
    # --- 全分段（大众轴：管普通玩家体验）---
    all_win_rate: float    # 全分段胜率 0~1
    all_pick_rate: float   # 全分段出场率 0~1
    all_ban_rate: float    # 全分段 ban率 0~1


class HeroVerdict(BaseModel):
    """最终对某英雄的评级结论"""
    hero: str
    suggestion: str        # 建议：削弱 / 加强 / 维持
    level: str             # 优先级：low / medium / high
    hero_type: str         # 类型：真超标/高手向/两极分化/低端友好/偏弱势/真弱势/疑似绝活哥/泛用霸榜/健康/数据缺失
    reason: str            # 人话理由

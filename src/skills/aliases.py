"""
英雄名 / 黑话归一（别名词典）

问题：玩家嘴里是"六耳、暗信、牢震、野马、糖关、元射"，而客观数据(CSV)里是
规范名"心魔六耳、李信(暗)、司空震、马超、关羽、元歌"。不归一 → analyze 抽出来的名字
对不上 metrics 的 key → 该英雄整条舆情白采集。

本模块做两件事：
  normalize(name)  把一个别名/黑话/皮肤名/简称/错别字 → 规范名（对齐 CSV）。
                   若它其实是【装备】等非英雄词（黄盾/大帽…）→ 返回 None，防误当英雄。
  find_heroes(text) 从一段原文里扫出所有提到的英雄（规范名集合），
                   供关键词兜底 / 校验 LLM 抽取结果用。

—— 分路说明 ——
天元之弈导出的 CSV 里「分路」是合并字段（如 马超=打野/对抗路，胜率是混合值），
无法区分 马超打野 vs 边路 的强度。故 野马/边马 一律归到「马超」，暂不拆分路；
若日后按分路各导一份 CSV，再扩 (英雄,分路) 维度。

维护提示：宁缺毋滥。含糊的黑话（如"死猴子"可能是六耳也可能是孙悟空）不收，
避免张冠李戴；不确定就留空，让它走原名匹配。
"""
import re

# —— 规范名(左) ← 别名/黑话/皮肤/简称/错别字(右) ——
# key=规范名（必须与 CSV「英雄」列一致），value=该英雄的所有俗称
_CANON_TO_ALIASES: dict[str, list[str]] = {
    "心魔六耳": ["六耳", "六耳猕猴", "六耳猴"],
    "李信(暗)": ["暗信", "暗李信"],
    "李信(光)": ["光信", "光李信"],
    "司空震": ["牢震", "空震"],
    "李白": ["牢白"],
    "阿轲": ["荆轲"],
    "关羽": ["糖关", "牢关"],
    "马超": ["野马", "边马", "冰脉马超"],
    "元歌": ["元哥"],
    "元流之子(射手)": ["元射"],
    "元流之子(法师)": ["元法"],
    "元流之子(坦克)": ["元坦"],
    "元流之子(辅助)": ["元辅"],
    "元流之子(刺客)": ["元刺"],
    "百里守约": ["守约", "百里"],
    "百里玄策": ["玄策"],
    "诸葛亮": ["诸葛", "村长"],
    "鲁班七号": ["鲁班"],
    "孙尚香": ["香香"],
    "花木兰": ["木兰"],
    "钟无艳": ["无艳", "石化大王"],
    "上官婉儿": ["婉儿", "上官"],
    "娜可露露": ["娜可", "露露"],
    "不知火舞": ["火舞"],
    "东皇太一": ["东皇"],
    "赵怀真": ["怀真"],
    "亚连": ["亚连"],
    "卢雅那": ["卢雅娜", "卢雅纳"],
}

# 反向查表：别名 → 规范名
CANON: dict[str, str] = {}
for _canon, _aliases in _CANON_TO_ALIASES.items():
    for _a in _aliases:
        CANON[_a] = _canon

# —— 非英雄词（装备/机制黑话）：出现时不能当英雄，normalize 返回 None ——
# 黄盾/黑盾=不祥征兆(极影?)之类护甲装；这些在舆情里常被讨论"超标"，但不是英雄。
EQUIP = {
    "黄盾", "黑盾", "大帽", "回响", "破魔", "破魔刀", "反甲", "魔女", "魔女斗篷",
    "冰痕", "冰甲", "红莲", "暴烈", "预言", "预言之书", "肉装", "法装", "物理装",
    "名刀", "复活甲", "辉月", "疾步鞋", "抵抗鞋",
}


def normalize(name: str) -> str | None:
    """别名/黑话 → 规范名；装备等非英雄词 → None；其余原样返回。"""
    if not name:
        return None
    n = name.strip()
    if n in EQUIP:
        return None
    return CANON.get(n, n)


def find_heroes(text: str, known_names: set[str] | None = None) -> set[str]:
    """从原文扫出提到的英雄（规范名集合）。
    known_names：CSV 里的全部规范名（用于直接匹配本名）；不传则只认别名表。
    先按【长名优先】匹配，避免"马"命中"马超/司马懿"这种子串误伤。
    """
    if not text:
        return set()
    hits: set[str] = set()
    candidates: list[tuple[str, str]] = []      # (待匹配词, 规范名)
    for alias, canon in CANON.items():
        candidates.append((alias, canon))
    for name in (known_names or set()):
        candidates.append((name, name))
    # 长的先匹配
    for token, canon in sorted(candidates, key=lambda x: -len(x[0])):
        if token and token in text:
            hits.add(canon)
    return hits


# 自测：python -m src.skills.aliases
if __name__ == "__main__":
    for s in ["六耳啥时候削", "暗信被削", "野马边路不行", "黄盾要削吗", "元射二技能"]:
        print(s, "→", find_heroes(s), "| normalize首词:", normalize(s.split()[0][:2]))

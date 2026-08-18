"""
闭环处置命令行：把人对某条告警的裁决回流进系统，抑制重复告警。

用法：
    python -m src.skills.ack <英雄> <处置> [抑制轮数] [备注]

处置(status) 取值与效果：
    误报    该告警不对 → 抑制 N 轮内不再报（除非数据剧变）
    已关注  知道了、暂不处理 → 短暂降噪，仍计积压
    需跟进  已排期/正在改 → 抑制并【冻结积压计数】，等上线后数据变化再算
    已改    已调整上线 → 清零该英雄积压 + 记入 ground_truth（供阈值回测），并抑制到数据刷新

不填抑制轮数时，用 config.FEEDBACK_ROUNDS 里的默认值。

例：
    python -m src.skills.ack 海月 需跟进
    python -m src.skills.ack 盾山 已改 24 "S44中版本削了平A"
    python -m src.skills.ack 关羽 误报 12 体感超标但数据健康
"""
import sys

from src.config import config
from src.skills import storage

VALID = {"误报", "已关注", "需跟进", "已改"}


def main(argv: list[str]):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    hero, status = argv[0], argv[1]
    if status not in VALID:
        print(f"处置必须是 {VALID} 之一，收到：{status}")
        return

    rounds = config.FEEDBACK_ROUNDS.get(status, 12)
    note_parts = argv[2:]
    if note_parts and note_parts[0].isdigit():
        rounds = int(note_parts[0])
        note_parts = note_parts[1:]
    note = " ".join(note_parts)

    storage.init_db()
    storage.set_feedback(hero, status, rounds, note)

    extra = ""
    if status == "需跟进":
        extra = "（已冻结积压计数）"
    elif status == "已改":
        extra = "（已清零积压并记入 ground_truth）"
    print(f"✅ 已记录：【{hero}】{status}，抑制 {rounds} 轮{extra}"
          + (f"｜备注：{note}" if note else ""))


if __name__ == "__main__":
    main(sys.argv[1:])

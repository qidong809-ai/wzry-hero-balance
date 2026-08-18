"""临时脚本：导出本轮真实反馈，供人工/AI 逐条语义分析。"""
import json

from src.skills.collect import _real_data

rows = _real_data()
with open("data/_to_analyze.txt", "w", encoding="utf-8") as f:
    for i, fb in enumerate(rows):
        text = " ".join(fb.content.split())
        f.write(f"{i}\t{fb.platform}\t{fb.likes}\t{text}\n")

json.dump([{"platform": r.platform, "likes": r.likes, "content": r.content}
           for r in rows], open("data/_to_analyze.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"导出 {len(rows)} 条 → data/_to_analyze.txt")

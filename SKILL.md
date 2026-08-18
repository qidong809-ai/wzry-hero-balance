---
name: wzry-hero-balance
description: |-
  王者荣耀英雄强度舆情监控项目的操作手册。当需要运行、维护、更新这个项目时使用。
  触发场景：(1) 跑一轮巡检 —"跑一下强度监控"、"看看这轮告警/呼声榜"；
  (2) 更新数据 —"我下载了新的CSV"、"换成最新的巅峰千强数据"；
  (3) 出看板 —"生成数据看板"、"更新那个 HTML 看板"；
  (4) 人工处置 —"把某英雄标为已改/误报/需跟进"；
  (5) 常驻监控 —"启动 agent 每小时自动跑"；
  (6) 问原理 —"为什么这个英雄被判成 XX 型"、"双轴/z-score 怎么算的"；
  (7) 爬取舆情 —"爬一下最新评论"、"强制刷新舆情数据"。
  核心能力：环境准备、自动爬取集成、CSV 数据更新规则、语义分析(离线/LLM)、各运行命令、分型/告警规则速查、闭环处置、常见问题排查。
metadata:
  version: 2.0.0
---

# 王者荣耀英雄强度舆情监控 · 操作手册

自动采集小红书/抖音对英雄强弱的反馈（集成 MediaCrawler，一天一次自动爬取），语义分析后聚合「呼声」(对数加权投票)，再用**客观 CSV 数据**做验证器，输出风险评级 + 抑制告警。数据是**双轴**：竞技轴(巅峰千强) × 大众轴(全分段)。

## 0. 项目位置

```
c:\Users\wangqidong01\Desktop\新建文件夹\wzry-hero-balance
```

所有命令都在**项目根目录**跑。Windows cmd 先切目录（路径含中文，必须引号）：

```cmd
cd /d "c:\Users\wangqidong01\Desktop\新建文件夹\wzry-hero-balance"
```

MediaCrawler 位置（爬虫，被 crawl.py 自动调用）：

```
c:\Users\wangqidong01\Desktop\新建文件夹\MediaCrawler-main
```

## 1. 一次性准备

```cmd
pip install -r requirements.txt
```

MediaCrawler 需要自己的 venv（已有，crawl.py 自动使用 `.venv\Scripts\python.exe`）。首次需人工扫码登录一次小红书和抖音，之后 `SAVE_LOGIN_STATE=True` 复用登录态。

LLM 配置(可选)：复制 `.env.example` → `.env`，填 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`(通义/DeepSeek/Ollama 任选，兼容 OpenAI 协议)。
没配时走离线语义分析归档（`data/mentions/mentions_YYYY-MM-DD.json`），数据研判照常。

## 2. 自动爬取（舆情采集）

`src/skills/crawl.py` 在每轮巡检前自动触发：

- 检查 `MediaCrawler-main/data/{xhs,douyin}/json/search_contents_*.json` 最新文件的 mtime
- 不足 **24 小时** → 跳过（用缓存）
- 超过 24 小时 → subprocess 拉起 MediaCrawler 的 headless 爬虫
- 单平台超时 900s 自动 kill（含 Chromium 子进程树）
- 失败不阻塞巡检，只打印状态行

| 命令 | 用途 |
|---|---|
| `python -m src.skills.crawl` | 强制爬一轮（不看时间阈值） |

爬取配置在 `MediaCrawler-main/config/base_config.py`：

- `KEYWORDS`：17 组王者强度关键词
- `CRAWLER_MAX_NOTES_COUNT = 10`：每关键词抓 10 条笔记（想多抓改大，但风控风险↑）
- `CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = 10`：每笔记最多 10 条评论
- 抖音按相关度排序（会带旧帖），小红书按最新排序

**登录态失效**：爬虫超时 + 无新数据 → 需人工开 `python main.py --platform xhs` 非 headless 重扫码。

## 3. 更新数据(CSV)

数据文件放 `data\`，命名：

```
heroes_YYYYMMDD_{gameMode}.csv
```

`gameMode`：
- `5` = 巅峰千强 → **竞技轴**(优先，管高分段/职业公平)
- `4` = 顶端  → 竞技轴回退档(没有 5 时用)
- `1` = 全分段 → **大众轴**(管路人体验，低分段虚高在此现形)

程序自动读**日期最新**的一批。表头需含：`英雄` / `胜率` / `出场率` / `禁用率`(按列名解析，多余列忽略)。数据源：天元之弈数据站等。

## 4. 语义分析

`src/skills/analyze.py` 负责把原始反馈 → 结构化判定（英雄/词条/倾向/原文）。

**有 LLM**：逐条调用，结果自动落入流程。
**无 LLM**：读离线归档 `data/mentions/mentions_YYYY-MM-DD.json`（日期最新的一份）。

归档格式：
```json
{
 "meta": {"analyzed_at": "2026-08-10", "source_batch": "2026-08-10", ...},
 "mentions": [
  {"hero": "海月", "keyword": "超标", "stance": "该削", "likes": 3,
   "source": "海月也太超标了吧！这都能被他反杀？..."}
 ]
}
```

**批次校验**：`meta.source_batch` 必须与当前采集数据批次一致，不一致时系统大声告警——不再静默沿用旧分析。

新爬一批数据后需重做分析（配 LLM 则自动；无 LLM 则人工/AI 做完存为 `mentions_YYYY-MM-DD.json`）。

## 5. 运行

| 目的 | 命令 |
|---|---|
| 跑一轮(详细输出，最常用) | `python -m src.skills.report` |
| 强制爬取一轮 | `python -m src.skills.crawl` |
| 常驻 agent(先跑一轮，之后每小时) | `python -m src.main`  (Ctrl+C 停) |
| 生成数据看板 HTML | `python -m src.skills.dashboard [输出路径]` |
| 评级单测 | `python -m src.skills.risk` |
| 指标读取单测 | `python -m src.skills.metrics` |

看板默认输出到桌面 `MOBA数据看板.html`(用浏览器打开；含散点/历史趋势/前端处置按钮)。

一轮 `report` 输出三段：【一】舆情呼声榜(主) 【二】数据预警(舆情没提但数据异常的盲区) 【三】告警(带抑制)。

## 6. 人工闭环处置

把人对告警的裁决回流，抑制重复告警：

```cmd
python -m src.skills.ack <英雄> <处置> [抑制轮数] [备注]
```

处置(status)：
- `误报` — 告警不对，抑制 N 轮
- `已关注` — 知道了暂不处理，短暂降噪，仍计积压
- `需跟进` — 已排期，抑制并**冻结积压计数**
- `已改` — 已上线，清零积压 + 记入 ground_truth，抑制到数据刷新

例：`python -m src.skills.ack 盾山 已改 24 "S44中版本削了平A"`

## 7. 分型规则速查

**双轴 + 全池 z-score**(所有英雄一起算 μ/σ，故意不分路，保留分路失衡信号)。

分型：
- **真超标** — 巅峰强 + 全段也强 → 削
- **高手向** — 巅峰强、全段不强 → 削上限(针对性)
- **两极分化** — 上限高且大众弱；压制性(高 ban 或全段出场高)才 high
- **低端友好** — 全段虚高但巅峰不强(下饭英雄/低分段职业红利) → **维持**，削则误伤大众
- **偏弱势 / 真弱势** — 数据偏弱 → 加强
- **疑似绝活哥** — 巅峰高胜但冷门且无人 ban，全段也小样本 → 虚高不作数，维持观察
- **泛用霸榜** — 出场率碾压
- **健康** — 维持(不进评估重点)

关键约束：
- **绝活哥双轴防护**：竞技轴高胜+冷门+低 ban → 高胜不作数；大众轴对称——全段高胜+全段冷门(出场低)同样不作数。
- **ban 率高 ≠ 强**(6B)：ban 高可能是烦而非超标。
- **不自动判「炸鱼」**：真炸鱼(如澜，高手在低分段虐菜)在**聚合胜率里是隐形的**——高手 carry 被海量玩不好的萌新拉平(澜全段仅 47%)，单看胜率/出场率均值抓不到，需分位数据(高端局单独胜率/carry 率)当前数据源没有，故坦承边界、不做自动炸鱼判定。

阈值在 `src\config.py`：`Z_STRONG=1.0` `Z_WEAK=-1.0` `Z_BAN_CONFIRM=0.5` `Z_PICK_LOW=-0.5` `Z_CEILING=0.5` 等。

### 7.1 时间基线/突增 · 舆情置信度（抗噪）

**时间基线（`baseline.py`）**：每个英雄本轮呼声 vs 它自己过去 `BASELINE_DAYS=7` 天历史 → 新增/突增/持续。突增判据 `z ≥ SURGE_Z(2.0)`。
- 防 z 爆炸两道闸（否则历史退化时 z 飙到天文数字）：`SURGE_MIN_HISTORY=3`（快照 <3 条不判突增）；`SURGE_SIGMA_FLOOR=0.15`（σ 封底 = `max(pstdev, 均值×0.15, 1.0)`）。

**舆情置信度（`aggregate.py`，抗羊群/单条爆帖/口水战）**：5 因子加权（离散度0.3/样本0.2/方向0.15/跨平台0.2/时间分散0.15），阈值 `VOICE_CONF_MIN=0.4`。`confidence < 0.4` → 低置信：**只记录标注，不做告警提级**。依赖每条舆情带真实 `platform` + `created_at`（离线归档需一并填）。

## 8. 告警 4 桶

① 双印证(舆情+数据都指向)　② 数据盲区(数据异常的 TopN 冷门)　③ 结构性(削上限补下限，压制性才 high)　④ 陈年欠账(积压达轮数)。

## 9. 别名管理

`src/skills/aliases.py` 维护英雄别名表：黑话/错别字/简称 → CSV 规范名。

新英雄上线后，若社区常用名 ≠ CSV 名（如"卢雅娜"→"卢雅那"），需在 `_CANON_TO_ALIASES` 里加一行。`normalize()` 对未知名原样返回，对装备名返回 None 过滤。

## 10. 数据库

`data\monitor.db`(SQLite)：历史快照(舆情) / 数据轴快照(metrics 表：每轮客观指标+所用 CSV 批次，供回测) / 积压计数 / 告警抑制 / ground_truth。删掉会自动重建(丢历史趋势与抑制记录)。

**回测数据齐备**：① `snapshots`(舆情) ② `metrics`(数据轴+CSV批次) ③ `alerts`(每轮告警预测) ④ `ground_truth`(官方结果，ack 已改写入)——四表按 run_ts 对齐，可算"提前告警命中率"。CSV 无需每天导(胜率日间漂移在噪声内，真事件是版本更新)，建议每周 1 次 + 官方调整后立即补，历史 CSV 勿删。

## 11. 常见问题

- **中文乱码**：Windows GBK 控制台问题，看 HTML 报告/看板即可，或设 `chcp 65001`。
- **报没配 LLM**：填 `.env` 或准备离线 mentions JSON。无 LLM 时系统会校验分析批次是否匹配采集批次。
- **🚨 语义分析结果已过期**：爬了新数据但没重做分析 → 配 LLM 或人工做新一份 mentions JSON。
- **看板历史只有一条线**：需 `data\monitor.db` 里该英雄有 ≥2 轮快照；多跑几轮 `report` 后再出看板。
- **某英雄不在告警里**：判为「健康/维持」会被过滤，属正常；舆情榜里仍可见。
- **爬虫超时/失败**：登录态过期，需人工非 headless 跑 MediaCrawler 重新扫码。
- **数据去重**：collect.py 按 `comment_id`/`note_id`/`aweme_id` 去重，同日重复爬不会膨胀数据。
- **突增 z 离谱(如 z+2398…)**：老 bug，已修。根因是历史退化(清库/快照太少)σ≈0 被除。现由 `SURGE_MIN_HISTORY` + `SURGE_SIGMA_FLOOR` 兜底；多跑几轮 `report` 攒够历史即可。

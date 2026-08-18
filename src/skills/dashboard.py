"""
数据看板生成器：动态版（Chart.js，CDN 引入）。
交互式图表 + 前端人工处置按钮（localStorage 演示，真实闭环走 CLI ack）。
python -m src.skills.dashboard [输出路径]
"""
import json
import os
import sys
from collections import Counter
from datetime import datetime

from src.skills.collect import collect_feedback
from src.skills.analyze import analyze_feedback
from src.skills.aggregate import aggregate_voices
from src.skills.baseline import trends_for_all
from src.skills.risk import assess_all, _build_stats, _z
from src.skills.metrics import all_metrics
from src.skills import storage

_DEFAULT_OUT = os.path.join(os.path.expanduser("~"), "Desktop", "MOBA数据看板.html")

_CAT = {"削弱": "nerf", "泛用霸榜": "nerf", "削上限补下限": "polar",
        "加强": "buff", "维持": "hold"}


def _payload():
    storage.init_db()
    feedbacks = collect_feedback()
    mentions = analyze_feedback(feedbacks)
    voices = aggregate_voices(mentions)
    trends = trends_for_all(voices)
    verdicts = assess_all(voices)

    vmap = {v.hero: v for v in verdicts}
    voice_map = {v.hero: v for v in voices}
    metrics_list = all_metrics()
    stats = _build_stats(metrics_list)

    voice_rank = [{
        "hero": v.hero,
        "nerf": round(v.nerf_votes, 1),
        "buff": round(v.buff_votes, 1),
        "total": round(v.total, 1),
        "dir": "该削" if v.nerf_votes >= v.buff_votes else "该加强",
        "tag": trends.get(v.hero, {}).get("tag", ""),
    } for v in voices[:12]]

    scatter = []
    for m in metrics_list:
        vd = vmap.get(m.hero)
        cat = _CAT.get(vd.suggestion, "hold") if vd else "hold"
        scatter.append({
            "hero": m.hero,
            "x": round(_z(m.all_win_rate, stats["all_win"]), 2),
            "y": round(_z(m.top_win_rate, stats["top_win"]), 2),
            "cat": cat,
            "type": vd.hero_type if vd else "数据缺失",
        })

    type_dist = Counter(vd.hero_type for vd in verdicts)

    def _vt(h):
        v = voice_map.get(h)
        return v.total if v else 0.0
    alerts = sorted(
        [vd for vd in verdicts if vd.level == "high" and vd.suggestion != "维持"],
        key=lambda vd: -_vt(vd.hero),
    )

    series = []
    for v in voices[:6]:
        hist = storage.hero_history(v.hero, 30)
        if len(hist) >= 2:
            series.append({"hero": v.hero, "data": hist})
    maxlen = max((len(s["data"]) for s in series), default=0)
    for s in series:
        s["data"] = [None] * (maxlen - len(s["data"])) + s["data"]

    lvl = Counter(vd.level for vd in verdicts if vd.suggestion != "维持")
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "kpi": {"feedbacks": len(feedbacks), "heroesVoiced": len(voices),
                "heroesData": len(metrics_list),
                "high": lvl.get("high", 0), "medium": lvl.get("medium", 0)},
        "voiceRank": voice_rank,
        "scatter": scatter,
        "typeDist": dict(type_dist),
        "alerts": [{"hero": vd.hero, "type": vd.hero_type,
                    "suggestion": vd.suggestion} for vd in alerts],
        "history": {"labels": [f"T-{maxlen-1-i}" for i in range(maxlen)], "series": series},
    }


def build(out_path: str = _DEFAULT_OUT) -> str:
    data = _payload()
    html = _TEMPLATE.replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ 看板已生成：{out_path}")
    return out_path


_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MOBA 英雄强度数据看板（以王者荣耀为例）</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root{--gold:#c9a227;--gold-lite:#e8cf7a;--ink:#12151b;--card:#1b2029;--line:#2a3140;
        --txt:#e6e9ee;--muted:#8b93a1;--red:#ff7b7b;--green:#57c98a;--purple:#b794f4;--blue:#5aa9e6;--yellow:#e8cf7a;}
  *{box-sizing:border-box}
  body{margin:0;background:#0e1116;color:var(--txt);
       font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.6}
  header{padding:26px 30px;background:linear-gradient(135deg,#12151b,#1b2029 70%,#2a2410);
         border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:10px}
  header h1{margin:0;font-size:22px;font-weight:800;letter-spacing:.5px}
  header .right{display:flex;flex-direction:column;align-items:flex-end;gap:8px}
  header .gen{font-size:13px;color:var(--muted)}
  header h1 span{color:var(--gold-lite)}
  .wrap{max-width:1240px;margin:0 auto;padding:24px 30px 70px}
  .kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:22px}
  @media(max-width:820px){.kpis{grid-template-columns:repeat(2,1fr)}}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
  .kpi .v{font-size:28px;font-weight:800;color:var(--gold-lite)}
  .kpi .l{font-size:12.5px;color:var(--muted);margin-top:2px}
  .grid{display:grid;gap:18px}
  .g2{grid-template-columns:1.15fr .85fr}
  @media(max-width:960px){.g2{grid-template-columns:1fr}}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:18px}
  .card h3{margin:0 0 4px;font-size:16px}
  .card .cap{margin:0 0 14px;font-size:12.5px;color:var(--muted)}
  .chart-box{position:relative;height:300px}
  .chart-box.tall{height:360px}
  table{width:100%;border-collapse:collapse;font-size:13.5px}
  th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
  th{color:var(--muted);font-weight:600}
  .badge{display:inline-block;font-size:11.5px;padding:1px 8px;border-radius:20px;font-weight:700}
  .b-nerf{background:rgba(255,123,123,.16);color:var(--red)}
  .b-buff{background:rgba(87,201,138,.16);color:var(--green)}
  .b-polar{background:rgba(183,148,244,.16);color:var(--purple)}
  .legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin-top:6px}
  .dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:5px;vertical-align:middle}
  .empty{color:var(--muted);font-size:13px;padding:20px 0;text-align:center}
  .ops{display:flex;gap:4px;flex-wrap:wrap}
  .ops button{font-size:11px;padding:2px 8px;border-radius:6px;cursor:pointer;
    border:1px solid var(--line);background:#141922;color:var(--muted);transition:.15s}
  .ops button:hover{border-color:var(--gold);color:var(--gold-lite)}
  .ops button.on{color:#12151b;font-weight:700;border-color:transparent}
  .ops button.on.misreport{background:var(--gray,#6b7280)}
  .ops button.on.watch{background:var(--blue)}
  .ops button.on.followup{background:var(--yellow)}
  .ops button.on.fixed{background:var(--green)}
  tr[data-st="misreport"]{opacity:.5}
  tr[data-st] td:first-child{border-left:3px solid transparent}
  tr[data-st="watch"] td:first-child{border-left-color:var(--blue)}
  tr[data-st="followup"] td:first-child{border-left-color:var(--yellow)}
  tr[data-st="fixed"] td:first-child{border-left-color:var(--green)}
  .gray{--gray:#6b7280}
</style>
</head>
<body>
<header>
  <h1>MOBA 英雄强度数据看板 · <span>以王者荣耀为例</span></h1>
  <div class="right">
    <div class="gen" id="gen"></div>
  </div>
</header>
<div class="wrap">
  <div class="kpis" id="kpis"></div>

  <div class="grid g2">
    <div class="card">
      <h3>舆情呼声榜 Top12</h3>
      <p class="cap">加权呼声（一条一票 + log 点赞加成），红=呼吁削弱 / 绿=呼吁加强</p>
      <div class="chart-box tall"><canvas id="voiceChart"></canvas></div>
    </div>
    <div class="card">
      <h3>英雄分型分布</h3>
      <p class="cap">双轴研判后的类型占比</p>
      <div class="chart-box tall"><canvas id="typeChart"></canvas></div>
    </div>
  </div>

  <div class="card">
    <h3>双轴散点：竞技轴 × 大众轴（胜率 z-score）</h3>
    <p class="cap">横=全段胜率偏离σ，纵=巅峰胜率偏离σ。右上=双高(真超标)、右下=低端友好(低分段虚高)、左下=真弱势</p>
    <div class="chart-box tall"><canvas id="scatterChart"></canvas></div>
    <div class="legend">
      <span><i class="dot" style="background:#ff7b7b"></i>削弱</span>
      <span><i class="dot" style="background:#b794f4"></i>削上限补下限</span>
      <span><i class="dot" style="background:#57c98a"></i>加强</span>
      <span><i class="dot" style="background:#6b7280"></i>维持/健康</span>
    </div>
  </div>

  <div class="grid g2">
    <div class="card">
      <h3>高优先告警清单</h3>
      <p class="cap">level=high 且需改动，按呼声降序。点按钮标记处置（浏览器本地保存，仅演示，真实闭环写库在 CLI）</p>
      <div id="alertTable"></div>
    </div>
    <div class="card">
      <h3>呼声历史趋势</h3>
      <p class="cap" id="histCap">呼声最高英雄的历轮走势</p>
      <div class="chart-box"><canvas id="histChart"></canvas></div>
      <div class="empty" id="histEmpty" style="display:none">历史快照不足（需累计≥2轮巡检）</div>
    </div>
  </div>
</div>

<script>
const DATA = /*__DATA__*/;
const C = {red:'#ff7b7b',green:'#57c98a',purple:'#b794f4',gray:'#6b7280',gold:'#e8cf7a',blue:'#5aa9e6',grid:'#2a3140',txt:'#8b93a1'};
Chart.defaults.color = C.txt;
Chart.defaults.font.family = "'Segoe UI','Microsoft YaHei',sans-serif";

document.getElementById('gen').textContent = '生成时间 ' + DATA.generated;

// KPI
const kpis = [
  {v:DATA.kpi.feedbacks,l:'采集反馈条数'},
  {v:DATA.kpi.heroesVoiced,l:'涉及英雄(舆情)'},
  {v:DATA.kpi.heroesData,l:'有数据英雄'},
  {v:DATA.kpi.high,l:'high 待改动'},
  {v:DATA.kpi.medium,l:'medium 待改动'},
];
document.getElementById('kpis').innerHTML = kpis.map(k=>
  `<div class="kpi"><div class="v">${k.v}</div><div class="l">${k.l}</div></div>`).join('');

// 呼声榜（横向堆叠柱）
new Chart(document.getElementById('voiceChart'),{
  type:'bar',
  data:{labels:DATA.voiceRank.map(d=>d.hero),
    datasets:[
      {label:'呼吁削弱',data:DATA.voiceRank.map(d=>d.nerf),backgroundColor:C.red,borderRadius:4},
      {label:'呼吁加强',data:DATA.voiceRank.map(d=>d.buff),backgroundColor:C.green,borderRadius:4},
    ]},
  options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,
    scales:{x:{stacked:true,grid:{color:C.grid}},y:{stacked:true,grid:{display:false}}},
    plugins:{legend:{position:'bottom'}}}
});

// 分型分布（环形）
const td = DATA.typeDist;
const typeColor = {'真超标':C.red,'高手向':C.gold,'两极分化':C.purple,
  '真弱势':C.green,'偏弱势':'#8fd3ad','泛用霸榜':'#e6787f','疑似绝活哥':C.blue,
  '低端友好':'#7aa2c2','健康':C.gray,'数据缺失':'#4a5160'};
new Chart(document.getElementById('typeChart'),{
  type:'doughnut',
  data:{labels:Object.keys(td),
    datasets:[{data:Object.values(td),
      backgroundColor:Object.keys(td).map(k=>typeColor[k]||C.gray),borderColor:'#1b2029',borderWidth:2}]},
  options:{responsive:true,maintainAspectRatio:false,cutout:'58%',
    plugins:{legend:{position:'right',labels:{boxWidth:12,padding:10}}}}
});

// 双轴散点
const catColor = {nerf:C.red,polar:C.purple,buff:C.green,hold:C.gray};
const cats = {nerf:[],polar:[],buff:[],hold:[]};
DATA.scatter.forEach(p=>cats[p.cat].push(p));
new Chart(document.getElementById('scatterChart'),{
  type:'scatter',
  data:{datasets:Object.keys(cats).map(c=>({
    label:c,data:cats[c].map(p=>({x:p.x,y:p.y,hero:p.hero,type:p.type})),
    backgroundColor:catColor[c],pointRadius:5,pointHoverRadius:8}))},
  options:{responsive:true,maintainAspectRatio:false,
    scales:{x:{title:{display:true,text:'全段胜率 z（大众轴）'},grid:{color:C.grid},
              ticks:{callback:v=>v}},
            y:{title:{display:true,text:'巅峰胜率 z（竞技轴）'},grid:{color:C.grid}}},
    plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>`${c.raw.hero}（${c.raw.type}） 大众z${c.raw.x} / 竞技z${c.raw.y}`}}}}
});

// 告警清单（含前端人工处置：localStorage 持久化，仅演示不写真实库）
const at = DATA.alerts;
const bcls = s=>(s==='加强')?'b-buff':(s==='削上限补下限')?'b-polar':'b-nerf';
const ST_KEY='wzry_dispose';
const ST = JSON.parse(localStorage.getItem(ST_KEY)||'{}');
const ACTS=[['misreport','误报'],['watch','已关注'],['followup','需跟进'],['fixed','已改']];
function opsHtml(hero){
  return `<div class="ops">`+ACTS.map(([k,label])=>
    `<button data-hero="${hero}" data-act="${k}">${label}</button>`).join('')+`</div>`;
}
document.getElementById('alertTable').innerHTML = at.length ?
  `<table><thead><tr><th>英雄</th><th>分型</th><th>建议</th><th>人工处置</th></tr></thead><tbody>`+
  at.map(a=>`<tr data-hero="${a.hero}"><td><b>${a.hero}</b></td><td>${a.type}</td>
    <td><span class="badge ${bcls(a.suggestion)}">${a.suggestion}</span></td>
    <td>${opsHtml(a.hero)}</td></tr>`).join('')+
  `</tbody></table>` : `<div class="empty">本轮无 high 告警</div>`;

function paint(hero){
  const st = ST[hero];
  const row = document.querySelector(`tr[data-hero="${hero}"]`);
  if(row){ if(st) row.setAttribute('data-st',st); else row.removeAttribute('data-st'); }
  document.querySelectorAll(`button[data-hero="${hero}"]`).forEach(b=>{
    b.className = (b.dataset.act===st) ? 'on '+st : '';
  });
}
at.forEach(a=>paint(a.hero));
document.getElementById('alertTable').addEventListener('click',e=>{
  const b = e.target.closest('button[data-act]'); if(!b) return;
  const hero=b.dataset.hero, act=b.dataset.act;
  if(ST[hero]===act) delete ST[hero]; else ST[hero]=act;   // 再点一次取消
  localStorage.setItem(ST_KEY,JSON.stringify(ST));
  paint(hero);
});

// 历史趋势（多英雄多线）
const h = DATA.history;
const HLINE = [C.gold,C.red,C.purple,C.green,C.blue,'#ff9f45'];
if(h.series && h.series.length){
  document.getElementById('histCap').textContent = `呼声 Top${h.series.length} 英雄的历轮走势`;
  new Chart(document.getElementById('histChart'),{
    type:'line',
    data:{labels:h.labels,datasets:h.series.map((s,i)=>({
      label:s.hero,data:s.data,borderColor:HLINE[i%HLINE.length],
      backgroundColor:'transparent',fill:false,tension:.3,pointRadius:3,spanGaps:true}))},
    options:{responsive:true,maintainAspectRatio:false,
      scales:{x:{grid:{color:C.grid}},y:{grid:{color:C.grid},beginAtZero:true}},
      plugins:{legend:{position:'bottom',labels:{boxWidth:12,padding:8}}}}
  });
}else{
  document.getElementById('histChart').style.display='none';
  document.getElementById('histEmpty').style.display='block';
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_OUT
    build(out)

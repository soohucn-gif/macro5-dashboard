#!/usr/bin/env python3
"""渲染自包含的 index.html。数据内联，不依赖任何外部资源（GitHub Pages 直接可用）。"""
import json
import os

from common import ROOT

TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>五大类数据看板</title>
<style>
:root{
  --bg:#f6f7f9; --panel:#ffffff; --ink:#12151a; --muted:#5c6673; --line:#e3e7ec;
  --grid:#eef1f5; --accent:#2f6feb; --up:#0f9d58; --down:#d93a2b; --chip:#eef1f6;
  --c1:#2f6feb; --c2:#e8710a; --c3:#0f9d58; --c4:#9334e6; --c5:#d93a2b;
  --c6:#00838f; --c7:#b0851f;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#0c0e12; --panel:#14171d; --ink:#e8ecf1; --muted:#8b95a3; --line:#242932;
    --grid:#1c2129; --accent:#6d9dff; --up:#3ddc84; --down:#ff6b5e; --chip:#1b2029;
    --c1:#6d9dff; --c2:#ffa35c; --c3:#3ddc84; --c4:#c58cff; --c5:#ff6b5e;
    --c6:#4dd0e1; --c7:#e6c15c;
  }
}
:root[data-theme="dark"]{
  --bg:#0c0e12; --panel:#14171d; --ink:#e8ecf1; --muted:#8b95a3; --line:#242932;
  --grid:#1c2129; --accent:#6d9dff; --up:#3ddc84; --down:#ff6b5e; --chip:#1b2029;
  --c1:#6d9dff; --c2:#ffa35c; --c3:#3ddc84; --c4:#c58cff; --c5:#ff6b5e;
  --c6:#4dd0e1; --c7:#e6c15c;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
  "Hiragino Sans GB","Microsoft YaHei",sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 64px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;justify-content:space-between;
  padding-bottom:18px;border-bottom:1px solid var(--line);margin-bottom:22px}
h1{font-size:22px;margin:0;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13px}
.tnum{font-variant-numeric:tabular-nums}
.kpis{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(184px,1fr));
  margin-bottom:26px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px 14px}
.kpi .k-name{font-size:12px;color:var(--muted);margin-bottom:5px}
.kpi .k-val{font-size:22px;font-weight:600;letter-spacing:-.02em;
  font-variant-numeric:tabular-nums}
.kpi .k-unit{font-size:12px;color:var(--muted);font-weight:400;margin-left:3px}
.kpi .k-row{display:flex;gap:9px;margin-top:7px;font-size:11.5px;white-space:nowrap;
  font-variant-numeric:tabular-nums}
.kpi .k-row>span:nth-child(odd){color:var(--muted)}
.kpi .k-foot{margin-top:6px;font-size:11px;color:var(--muted);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.up{color:var(--up)} .down{color:var(--down)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:18px 18px 12px;margin-bottom:20px}
.card h2{font-size:16px;margin:0 0 4px;letter-spacing:-.01em}
.card .desc{color:var(--muted);font-size:12.5px;margin:0 0 12px;max-width:76ch}
.card-top{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-start;
  justify-content:space-between}
.ranges{display:flex;gap:4px;flex-shrink:0}
.ranges button{background:var(--chip);border:1px solid transparent;color:var(--muted);
  border-radius:6px;padding:3px 9px;font-size:12px;cursor:pointer;
  font-family:inherit;transition:.12s}
.ranges button:hover{color:var(--ink)}
.ranges button[aria-pressed="true"]{background:var(--accent);color:#fff;border-color:var(--accent)}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;margin:10px 0 2px;font-size:12px}
.legend button{display:inline-flex;align-items:center;gap:6px;background:none;border:0;
  padding:0;cursor:pointer;color:var(--ink);font:inherit;font-size:12px}
.legend button[aria-pressed="false"]{opacity:.32;text-decoration:line-through}
.swatch{width:11px;height:3px;border-radius:2px;display:inline-block}
.chartbox{position:relative;width:100%;overflow:hidden}
svg{display:block;width:100%;height:auto;touch-action:pan-y}
.tip{position:absolute;pointer-events:none;background:var(--panel);
  border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:12px;
  box-shadow:0 6px 22px rgba(0,0,0,.16);opacity:0;transition:opacity .1s;
  min-width:150px;z-index:5;font-variant-numeric:tabular-nums}
.tip .t-date{color:var(--muted);margin-bottom:5px;font-size:11px}
.tip .t-row{display:flex;justify-content:space-between;gap:14px}
.tip .t-row b{font-weight:600}
.src{font-size:11.5px;color:var(--muted);margin-top:8px;
  border-top:1px solid var(--line);padding-top:8px;
  display:flex;flex-wrap:wrap;gap:6px 16px;justify-content:space-between}
footer{color:var(--muted);font-size:12px;margin-top:34px;
  border-top:1px solid var(--line);padding-top:16px}
footer a{color:var(--accent)}
footer ul{padding-left:18px;margin:8px 0}
.note{background:var(--chip);border-radius:8px;padding:10px 12px;font-size:12px;
  color:var(--muted);margin:0 0 12px}
@media(max-width:560px){h1{font-size:19px} .wrap{padding:20px 13px 48px}
  .kpi .k-val{font-size:19px}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>五大类数据看板</h1>
    <div class="sub">实际利率 · 股权风险溢价 · 股指 · 黄金 · 比特币 · GPU 租赁价格</div>
  </div>
  <div class="sub tnum">最后更新 <span id="gen"></span></div>
</header>
<div class="kpis" id="kpis"></div>
<div id="panels"></div>
<footer>
  <div><b>数据来源</b></div>
  <ul>
    <li>10年期实际利率 — FRED 圣路易斯联储：<code>DFII10</code>（10年期通胀保值债券收益率）、
        <code>DGS10</code>（名义）、<code>T10YIE</code>（10年盈亏平衡通胀）。
        三者满足 DFII10 ≈ DGS10 − T10YIE。</li>
    <li>隐含股权风险溢价 — NYU Stern，Aswath Damodaran，<code>ERPbymonth.xlsx</code>，月频。</li>
    <li>标普500 / 纳斯达克 — FRED：<code>SP500</code>、<code>NASDAQCOM</code>、<code>NASDAQ100</code>。</li>
    <li>黄金 — LBMA 伦敦金银市场协会官方下午定盘价（美元/盎司）。</li>
    <li>比特币 — Coinbase Exchange BTC-USD 日线收盘。</li>
    <li>GPU 租赁价格指数 — Silicon Data SiliconIndex；公开层仅提供滚动 7 天窗口，
        本仓库每日抓取累积。</li>
  </ul>
  <div>完整历史 CSV 见仓库 <code>data/</code> 目录。本页由 GitHub Actions 每日自动重建，
  不构成投资建议。</div>
</footer>
</div>
<script id="payload" type="application/json">__DATA__</script>
<script>
(function(){
"use strict";
var D = JSON.parse(document.getElementById("payload").textContent);
var COLORS = ["--c1","--c2","--c3","--c4","--c5","--c6","--c7"];
var RANGES = [["1年",365],["3年",1095],["5年",1825],["10年",3660],["全部",0]];

function cssv(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim();}
function fmtNum(v,unit){
  if(v===null||v===undefined) return "—";
  if(unit==="%") return v.toFixed(2)+"%";
  if(Math.abs(v)>=1000) return v.toLocaleString("en-US",{maximumFractionDigits:0});
  if(Math.abs(v)>=100) return v.toFixed(1);
  return v.toFixed(2);
}
function niceTicks(lo,hi,n){
  if(lo===hi){lo-=1;hi+=1;}
  var span=(hi-lo)/n, mag=Math.pow(10,Math.floor(Math.log10(span))), norm=span/mag;
  var step=(norm<1.5?1:norm<3?2:norm<7?5:10)*mag;
  var t=[],s=Math.ceil(lo/step)*step;
  for(var v=s; v<=hi+step*1e-9; v+=step) t.push(Math.round(v/step)*step);
  return t;
}
function logTicks(lo,hi){
  var t=[];
  for(var e=Math.floor(Math.log10(lo)); e<=Math.ceil(Math.log10(hi)); e++){
    [1,2,5].forEach(function(m){var v=m*Math.pow(10,e); if(v>=lo&&v<=hi) t.push(v);});
  }
  return t.length>=3?t:niceTicks(lo,hi,4);
}

// ------------------------------------------------------------------ KPI 卡片
var kh="";
D.kpis.forEach(function(k){
  function d(x){
    if(x===null||x===undefined) return '<span>—</span>';
    var cls = x>0?"up":x<0?"down":"";
    var s = k.is_rate ? (x>0?"+":"")+x.toFixed(2)+"pp" : (x>0?"+":"")+x.toFixed(1)+"%";
    return '<span class="'+cls+'">'+s+'</span>';
  }
  var unit = k.unit==="%" ? "%" : (k.unit?'<span class="k-unit">'+k.unit+'</span>':"");
  var val = k.unit==="%" ? k.value.toFixed(2)
          : k.value>=1000 ? k.value.toLocaleString("en-US",{maximumFractionDigits:0})
          : k.value.toFixed(2);
  kh += '<div class="kpi"><div class="k-name">'+k.name+'</div>'
      + '<div class="k-val">'+val+unit+'</div>'
      + '<div class="k-row"><span>30日</span>'+d(k.chg_30)
      + '<span>一年</span>'+d(k.chg_365)+'</div>'
      + '<div class="k-foot">'+k.date+' · '+k.note+'</div></div>';
});
document.getElementById("kpis").innerHTML = kh;
document.getElementById("gen").textContent = D.generated_at.replace("T"," ").replace("Z"," UTC");

// ------------------------------------------------------------------- 图表
function Chart(box, panel){
  var data=panel.data, labels=Object.keys(data.series);
  var hidden={}, days=(panel.key==="erp"||panel.key==="gpu")?0:1825;
  var svgNS="http://www.w3.org/2000/svg";
  var svg=document.createElementNS(svgNS,"svg");
  var tip=document.createElement("div"); tip.className="tip";
  box.appendChild(svg); box.appendChild(tip);
  var W=980,H=300,PL=54,PR=14,PT=12,PB=26, view=null;

  function slice(){
    if(!days) return {i0:0,i1:data.dates.length};
    var cut=new Date(data.dates[data.dates.length-1]);
    cut.setDate(cut.getDate()-days);
    var c=cut.toISOString().slice(0,10), i0=0;
    for(var i=0;i<data.dates.length;i++){ if(data.dates[i]>=c){i0=i;break;} }
    return {i0:i0,i1:data.dates.length};
  }
  var bases={};
  function computeBases(s){
    bases={};
    if(!panel.rebase) return;
    labels.forEach(function(l){
      var v=data.series[l];
      for(var i=s.i0;i<s.i1;i++){
        if(v[i]!==null&&v[i]!==undefined&&v[i]>0){ bases[l]=v[i]; return; }
      }
    });
  }
  function val(l,i){
    var x=data.series[l][i];
    if(x===null||x===undefined) return null;
    if(!panel.rebase) return x;
    var b=bases[l];
    return b ? x/b*100 : null;
  }
  function draw(){
    var s=slice(), lo=Infinity, hi=-Infinity, any=false;
    computeBases(s);
    labels.forEach(function(l){
      if(hidden[l]) return;
      for(var i=s.i0;i<s.i1;i++){ var x=val(l,i);
        if(x!==null&&(!panel.log||x>0)){ any=true;
          if(x<lo)lo=x; if(x>hi)hi=x; } }
    });
    if(!any){ svg.innerHTML=""; return; }
    var pad=(hi-lo)*0.08||Math.abs(hi)*0.05||1;
    var ylo=panel.log?lo/1.15:lo-pad, yhi=panel.log?hi*1.15:hi+pad;
    if(!panel.log && ylo>0 && ylo<(yhi-ylo)*0.35) ylo=0;
    var n=s.i1-s.i0;
    function X(i){ return PL+(n<2?0:(i-s.i0)/(n-1)*(W-PL-PR)); }
    function Y(v){
      if(panel.log){ var a=Math.log10(ylo),b=Math.log10(yhi);
        return PT+(1-(Math.log10(v)-a)/(b-a))*(H-PT-PB); }
      return PT+(1-(v-ylo)/(yhi-ylo))*(H-PT-PB);
    }
    var ticks=panel.log?logTicks(ylo,yhi):niceTicks(ylo,yhi,5);
    var g='<rect x="0" y="0" width="'+W+'" height="'+H+'" fill="none"/>';
    ticks.forEach(function(t){
      if(t<ylo||t>yhi) return; var y=Y(t);
      g+='<line x1="'+PL+'" y1="'+y.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+y.toFixed(1)
        +'" stroke="'+cssv("--grid")+'" stroke-width="1"/>'
        +'<text x="'+(PL-7)+'" y="'+(y+3.5).toFixed(1)+'" text-anchor="end" font-size="11" '
        +'fill="'+cssv("--muted")+'">'+fmtNum(t,panel.unit==="%"?"%":"")+'</text>';
    });
    var seen={},step=Math.max(1,Math.floor(n/7));
    for(var i=s.i0;i<s.i1;i+=step){
      var lab=n>900?data.dates[i].slice(0,4):data.dates[i].slice(0,7);
      if(seen[lab])continue; seen[lab]=1;
      g+='<text x="'+X(i).toFixed(1)+'" y="'+(H-8)+'" text-anchor="middle" font-size="11" '
        +'fill="'+cssv("--muted")+'">'+lab+'</text>';
    }
    labels.forEach(function(l,li){
      if(hidden[l]) return;
      var d="", pen=false;
      for(var i=s.i0;i<s.i1;i++){
        var x=val(l,i);
        if(x===null||(panel.log&&x<=0)){ pen=false; continue; }
        d += (pen?"L":"M")+X(i).toFixed(1)+" "+Y(x).toFixed(1)+" "; pen=true;
      }
      g+='<path d="'+d+'" fill="none" stroke="'+cssv(COLORS[li%COLORS.length])
        +'" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round"/>';
    });
    g+='<g id="cross" style="opacity:0"><line y1="'+PT+'" y2="'+(H-PB)
      +'" stroke="'+cssv("--muted")+'" stroke-width="1" stroke-dasharray="3 3"/></g>';
    svg.setAttribute("viewBox","0 0 "+W+" "+H);
    svg.innerHTML=g;
    view={s:s,X:X,Y:Y,n:n};
  }
  function onMove(ev){
    if(!view) return;
    var r=svg.getBoundingClientRect(), cx=(ev.clientX-r.left)/r.width*W;
    var frac=(cx-PL)/(W-PL-PR);
    var i=Math.round(view.s.i0+frac*(view.n-1));
    i=Math.max(view.s.i0,Math.min(view.s.i1-1,i));
    var cross=svg.querySelector("#cross");
    if(cross){ cross.style.opacity=1;
      cross.firstChild.setAttribute("x1",view.X(i)); cross.firstChild.setAttribute("x2",view.X(i)); }
    var h='<div class="t-date">'+data.dates[i]+'</div>';
    labels.forEach(function(l,li){
      if(hidden[l]) return;
      var v=val(l,i);
      if(v===null) return;
      h+='<div class="t-row"><span><i class="swatch" style="background:'
        +cssv(COLORS[li%COLORS.length])+'"></i> '+l+'</span><b>'
        +fmtNum(v,panel.unit==="%"?"%":"")+'</b></div>';
    });
    tip.innerHTML=h; tip.style.opacity=1;
    var px=view.X(i)/W*r.width;
    tip.style.left=Math.max(4,Math.min(r.width-tip.offsetWidth-4,px+12))+"px";
    tip.style.top="8px";
  }
  svg.addEventListener("mousemove",onMove);
  svg.addEventListener("touchmove",function(e){onMove(e.touches[0]);},{passive:true});
  svg.addEventListener("mouseleave",function(){
    tip.style.opacity=0;
    var c=svg.querySelector("#cross"); if(c)c.style.opacity=0;
  });
  return {draw:draw, setDays:function(d){days=d;draw();},
          getDays:function(){return days;},
          toggle:function(l){hidden[l]=!hidden[l];draw();},
          isHidden:function(l){return !!hidden[l];}, labels:labels};
}

var host=document.getElementById("panels"), charts=[];
Object.keys(D.panels).forEach(function(key){
  var p=D.panels[key]; p.key=key;
  if(!p.data.dates.length) return;
  var card=document.createElement("div"); card.className="card";
  card.innerHTML='<div class="card-top"><div><h2>'+p.title+'</h2>'
    +'<p class="desc">'+p.sub+'</p></div><div class="ranges"></div></div>'
    +'<div class="legend"></div><div class="chartbox"></div>'
    +'<div class="src"><span>来源：'+p.source+'</span><span>'+p.freq
    +' · 单位：'+p.unit+' · '+p.data.dates[0]+' → '
    +p.data.dates[p.data.dates.length-1]+'（'+p.data.dates.length+' 点）</span></div>';
  host.appendChild(card);
  var ch=Chart(card.querySelector(".chartbox"), p);
  var rbox=card.querySelector(".ranges");
  var span=(new Date(p.data.dates[p.data.dates.length-1])-new Date(p.data.dates[0]))/864e5;
  RANGES.forEach(function(r){
    if(r[1] && r[1]>span*1.1) return;
    var b=document.createElement("button"); b.textContent=r[0];
    b.setAttribute("aria-pressed", r[1]===ch.getDays()?"true":"false");
    b.onclick=function(){
      ch.setDays(r[1]);
      rbox.querySelectorAll("button").forEach(function(x){x.setAttribute("aria-pressed","false");});
      b.setAttribute("aria-pressed","true");
    };
    rbox.appendChild(b);
  });
  if(!rbox.querySelector('[aria-pressed="true"]') && rbox.lastChild)
    rbox.lastChild.setAttribute("aria-pressed","true"), ch.setDays(0);
  var lg=card.querySelector(".legend");
  ch.labels.forEach(function(l,li){
    var b=document.createElement("button"); b.setAttribute("aria-pressed","true");
    b.innerHTML='<i class="swatch" style="background:'+cssv(COLORS[li%COLORS.length])
      +'"></i>'+l;
    b.onclick=function(){ ch.toggle(l);
      b.setAttribute("aria-pressed", ch.isHidden(l)?"false":"true"); };
    lg.appendChild(b);
  });
  ch.draw(); charts.push(ch);
});
addEventListener("resize", function(){ charts.forEach(function(c){c.draw();}); });
if(window.matchMedia) matchMedia("(prefers-color-scheme:dark)")
  .addEventListener("change", function(){ charts.forEach(function(c){c.draw();}); });
})();
</script>
</body>
</html>
"""


def render(payload, out_path=None):
    out_path = out_path or os.path.join(ROOT, "index.html")
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # 数据放在 <script type="application/json"> 里，只需要防住 </script> 提前闭合
    blob = blob.replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", blob)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out_path

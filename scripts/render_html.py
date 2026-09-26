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
.xsec{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));
  margin:16px 0 4px;padding-top:14px;border-top:1px solid var(--line)}
.xsec h3{font-size:12.5px;margin:0 0 2px;font-weight:600}
.xsec .xnote{font-size:11px;color:var(--muted);margin:0 0 8px;line-height:1.45}
.xrow{margin-bottom:7px;font-size:12px}
.xhead{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.xhead b{font-weight:500}
.xhead i{font-style:normal;color:var(--muted);font-variant-numeric:tabular-nums;
  font-size:11.5px;flex-shrink:0}
.xen{color:var(--muted);font-size:10.5px;display:block;margin-top:1px}
.xbar{height:4px;border-radius:2px;background:var(--chip);margin-top:4px;overflow:hidden}
.xbar span{display:block;height:100%;border-radius:2px;background:var(--c1)}
.xsec .xrow:first-child .xbar span{background:var(--c2)}
.xmonth{display:inline-block;background:var(--chip);border-radius:5px;padding:1px 7px;
  font-size:11px;color:var(--muted);margin-left:8px;font-variant-numeric:tabular-nums}
.src{font-size:11.5px;color:var(--muted);margin-top:8px;
  border-top:1px solid var(--line);padding-top:8px;
  display:flex;flex-wrap:wrap;gap:6px 16px;justify-content:space-between}
footer{color:var(--muted);font-size:12px;margin-top:34px;
  border-top:1px solid var(--line);padding-top:16px}
footer a{color:var(--accent)}
footer ul{padding-left:18px;margin:8px 0}
.note{background:var(--chip);border-radius:8px;padding:10px 12px;font-size:12px;
  color:var(--muted);margin:0 0 12px}
@media(max-width:560px){h1{font-size:19px} .wrap{padding:20px 12px 48px}
  .kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
  .kpi{padding:10px 11px} .kpi .k-val{font-size:18px}
  .kpi .k-row{flex-wrap:wrap;gap:1px 7px}
  .card{padding:14px 12px 10px}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>五大类数据看板</h1>
    <div class="sub">利率期限结构 · 通胀预期 · 股权风险溢价 · 股指 · 黄金 · 比特币 · GPU 租赁 · 美银 FMS</div>
  </div>
  <div class="sub tnum">最后更新 <span id="gen"></span></div>
</header>
<div class="kpis" id="kpis"></div>
<div id="panels"></div>
<footer>
  <div><b>数据来源</b></div>
  <ul>
    <li>利率期限结构 — FRED 圣路易斯联储：<code>DFII5/10/30</code>（通胀保值债券 TIPS 实际利率）、
        <code>DGS5/10/30</code>（名义）、<code>T5YIE</code>/<code>T10YIE</code>（盈亏平衡通胀）。
        同期限满足 实际 ≈ 名义 − 盈亏平衡。</li>
    <li>通胀预期 — FRED：<code>T10YIE</code>、<code>T5YIFR</code>（5年后5年远期）、
        <code>EXPINF10YR</code>（克利夫兰联储模型）、<code>MICH</code>（密歇根大学）；
        纽约联储消费者预期调查（SCE）官网公开数据。</li>
    <li>隐含股权风险溢价 — NYU Stern，Aswath Damodaran，<code>ERPbymonth.xlsx</code>，月频。</li>
    <li>标普500 / 纳斯达克 — FRED：<code>SP500</code>、<code>NASDAQCOM</code>、<code>NASDAQ100</code>。</li>
    <li>黄金 — LBMA 伦敦金银市场协会官方下午定盘价（美元/盎司）。</li>
    <li>比特币 — Coinbase Exchange BTC-USD 日线收盘。</li>
    <li>GPU 租赁价格指数 — Silicon Data SiliconIndex；公开层仅提供滚动 7 天窗口，
        本仓库每日抓取累积。</li>
    <li>美银基金经理调查 — BofA Global Fund Manager Survey，每月中旬发布。本仓库只收录
        <b>派生的数字口径</b>（现金水位、拥挤交易与尾部风险的排名占比、官方 Contrarian
        Trades 标签），<b>不转载 BofA 原始图表与报告正文</b>，其版权归 BofA Global
        Research 所有。每月由定时任务从公开报道检索、交叉验证后写入，再以私有存档的原图读数校正。</li>
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
var DAY = 864e5;

function cssv(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim();}
// 数据里的文字（FMS 条目是定时任务从网上读来的）一律转义后再进 innerHTML
function esc(s){
  return String(s===null||s===undefined?"":s).replace(/[&<>"']/g,function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];});
}
function fmtNum(v,unit){
  if(v===null||v===undefined) return "—";
  if(unit==="%") return v.toFixed(2)+"%";
  if(Math.abs(v)>=1000) return v.toLocaleString("en-US",{maximumFractionDigits:0});
  if(Math.abs(v)>=100) return v.toFixed(1);
  return v.toFixed(2);
}
// 纵轴刻度：同一根轴小数位一致（按步长定），免得出现「80.00 / 100.0」混排；
// dp 为 null 时（对数轴的 1/2/5 刻度）按各自最短写法
function fmtTick(t,dp,pct){
  var s = Math.abs(t)>=1000 ? t.toLocaleString("en-US",{maximumFractionDigits:0})
        : dp===null ? String(+t.toFixed(4)) : t.toFixed(dp);
  return pct ? s+"%" : s;
}
function stepDp(t){
  var step = t.length>1 ? t[1]-t[0] : 1;
  return step>=1 ? 0 : Math.min(4, Math.ceil(-Math.log10(step)-1e-9));
}
function textW(s){   // 11px 字号下的粗略字宽，排版用
  var w=0; for(var i=0;i<s.length;i++) w += s.charCodeAt(i)>0x2e80 ? 11 : 6.6;
  return w;
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
  return t;
}
function dayNum(s){ return Date.UTC(+s.slice(0,4), +s.slice(5,7)-1, +s.slice(8,10))/DAY; }
// 时间轴刻度落在真实的日历边界上（整周 / 月初 / 季初 / 年初），疏密随图宽走
var XUNITS=[["d",1],["d",7],["d",14],["m",1],["m",2],["m",3],["m",6],
            ["y",1],["y",2],["y",5],["y",10]];
function xTicks(dates,i0,i1,plotW){
  var span=dayNum(dates[i1-1])-dayNum(dates[i0]);
  var maxN=Math.max(2, Math.min(12, Math.floor(plotW/56)));
  for(var u=0;u<XUNITS.length;u++){
    var kind=XUNITS[u][0], k=XUNITS[u][1];
    var per = kind==="d" ? k : kind==="m" ? 30.44*k : 365.25*k;
    if(span/per>maxN && u<XUNITS.length-1) continue;
    var key=function(s){
      if(kind==="d") return Math.floor((dayNum(s)+3)/k);           // +3：整周从周一起算
      if(kind==="m") return Math.floor(((+s.slice(0,4))*12+(+s.slice(5,7))-1)/k);
      return Math.floor((+s.slice(0,4))/k);
    };
    var label=function(s){
      if(kind==="d") return s.slice(5);
      if(kind==="m" && s.slice(5,7)!=="01") return (+s.slice(5,7))+"月";
      return s.slice(0,4);
    };
    // 区间起点也可能正好是边界：跟前一个点（最左端则跟前一天）比
    var prev=key(i0>0 ? dates[i0-1]
                      : new Date((dayNum(dates[i0])-1)*DAY).toISOString().slice(0,10));
    var out=[];
    for(var i=i0;i<i1;i++){
      var kk=key(dates[i]);
      if(kk!==prev) out.push({i:i, label:label(dates[i])});
      prev=kk;
    }
    return out;
  }
  return [];
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
  var unit = k.unit==="%" ? "%" : (k.unit?'<span class="k-unit">'+esc(k.unit)+'</span>':"");
  var val = k.unit==="%" ? k.value.toFixed(2)
          : k.value>=1000 ? k.value.toLocaleString("en-US",{maximumFractionDigits:0})
          : k.value.toFixed(2);
  kh += '<div class="kpi"><div class="k-name">'+esc(k.name)+'</div>'
      + '<div class="k-val">'+val+unit+'</div>'
      + '<div class="k-row"><span>30日</span>'+d(k.chg_30)
      + '<span>一年</span>'+d(k.chg_365)+'</div>'
      + '<div class="k-foot">'+(k.stale_days ? '<b class="down">⚠ '+k.stale_days+' 天没更新</b> · ' : '')
      + esc(k.date)+' · '+esc(k.note)+'</div></div>';
});
document.getElementById("kpis").innerHTML = kh;
document.getElementById("gen").textContent = D.generated_at.replace("T"," ").replace("Z"," UTC");

// ------------------------------------------------------------------- 图表
function Chart(box, panel){
  var data=panel.data, labels=Object.keys(data.series);
  // 同一期限的实际/名义用同色，名义画虚线 —— 两条线之间的竖直间距就是该期限的盈亏平衡通胀
  var COLOR_MAP=panel.colors||{}, DASH=(panel.dash||[]);
  function colorOf(l,li){
    var i = (COLOR_MAP[l]!==undefined) ? COLOR_MAP[l] : li;
    return cssv(COLORS[i%COLORS.length]);
  }
  function dashOf(l){ return DASH.indexOf(l)>=0; }
  var hidden={};
  (panel.hidden||[]).forEach(function(l){ hidden[l]=true; });
  var FULL_RANGE={erp:1, gpu:1, fms:1, infexp:1};
  var days = FULL_RANGE[panel.key] ? 0 : 1825;
  var svgNS="http://www.w3.org/2000/svg";
  var svg=document.createElementNS(svgNS,"svg");
  var tip=document.createElement("div"); tip.className="tip";
  box.appendChild(svg); box.appendChild(tip);
  // 按容器的真实像素宽度作图（viewBox 与显示尺寸 1:1）：手机上字号不再跟着整张图缩成 4px
  var W=980,H=300,PL=54,PR=14,PT=12,PB=26, view=null, drawnFor=-1;

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
    drawnFor=box.clientWidth;
    W=Math.max(240, drawnFor||980);
    H=Math.round(Math.min(320, Math.max(220, W*0.3)));
    var s=slice(), lo=Infinity, hi=-Infinity, any=false;
    computeBases(s);
    labels.forEach(function(l){
      if(hidden[l]) return;
      for(var i=s.i0;i<s.i1;i++){ var x=val(l,i);
        if(x!==null&&(!panel.log||x>0)){ any=true;
          if(x<lo)lo=x; if(x>hi)hi=x; } }
    });
    if(!any){ svg.innerHTML=""; view=null; return; }
    var pad=(hi-lo)*0.08||Math.abs(hi)*0.05||1;
    var ylo=panel.log?lo/1.15:lo-pad, yhi=panel.log?hi*1.15:hi+pad;
    if(!panel.log && ylo>0 && ylo<(yhi-ylo)*0.35) ylo=0;
    var ticks, dp=null, pct=panel.unit==="%";
    if(panel.log) ticks=logTicks(ylo,yhi);
    if(!panel.log || ticks.length<3){ ticks=niceTicks(ylo,yhi,panel.log?4:5); dp=stepDp(ticks); }
    ticks=ticks.filter(function(t){ return t>=ylo&&t<=yhi; });
    var tl=ticks.map(function(t){ return fmtTick(t,dp,pct); });
    PL=Math.ceil(Math.max.apply(null, tl.map(textW).concat([18]))+12);
    var n=s.i1-s.i0;
    function X(i){ return PL+(n<2?0:(i-s.i0)/(n-1)*(W-PL-PR)); }
    function Y(v){
      if(panel.log){ var a=Math.log10(ylo),b=Math.log10(yhi);
        return PT+(1-(Math.log10(v)-a)/(b-a))*(H-PT-PB); }
      return PT+(1-(v-ylo)/(yhi-ylo))*(H-PT-PB);
    }
    var grid=cssv("--grid"), muted=cssv("--muted");
    var g='<rect x="0" y="0" width="'+W+'" height="'+H+'" fill="none"/>';
    ticks.forEach(function(t,k){
      var y=Y(t);
      g+='<line x1="'+PL+'" y1="'+y.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+y.toFixed(1)
        +'" stroke="'+grid+'" stroke-width="1"/>'
        +'<text x="'+(PL-7)+'" y="'+(y+3.5).toFixed(1)+'" text-anchor="end" font-size="11" '
        +'fill="'+muted+'">'+tl[k]+'</text>';
    });
    xTicks(data.dates,s.i0,s.i1,W-PL-PR).forEach(function(t){
      var x=X(t.i), hw=textW(t.label)/2;
      var anchor = x+hw>W-1 ? "end" : x-hw<1 ? "start" : "middle";   // 贴边的标签别被裁掉
      g+='<text x="'+x.toFixed(1)+'" y="'+(H-8)+'" text-anchor="'+anchor+'" font-size="11" '
        +'fill="'+muted+'">'+t.label+'</text>';
    });
    labels.forEach(function(l,li){
      if(hidden[l]) return;
      // 缺测点跳过但不断笔：周末/假日没报价的序列（跨资产图里的股指、黄金）不会被切成虚线
      var d="", pen=false;
      for(var i=s.i0;i<s.i1;i++){
        var x=val(l,i);
        if(x===null||(panel.log&&x<=0)) continue;
        d += (pen?"L":"M")+X(i).toFixed(1)+" "+Y(x).toFixed(1)+" "; pen=true;
      }
      g+='<path d="'+d+'" fill="none" stroke="'+colorOf(l,li)
        +'" stroke-width="'+(dashOf(l)?1.5:1.8)+'"'
        +(dashOf(l)?' stroke-dasharray="7 4"':'')
        +' stroke-linejoin="round" stroke-linecap="round"/>';
    });
    g+='<line class="cross" y1="'+PT+'" y2="'+(H-PB)+'" stroke="'+muted
      +'" stroke-width="1" stroke-dasharray="3 3" style="opacity:0"/>';
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
    var cross=svg.querySelector(".cross");
    if(cross){ cross.style.opacity=1;
      cross.setAttribute("x1",view.X(i)); cross.setAttribute("x2",view.X(i)); }
    var h='<div class="t-date">'+esc(data.dates[i])+'</div>';
    labels.forEach(function(l,li){
      if(hidden[l]) return;
      var v=val(l,i);
      if(v===null) return;
      h+='<div class="t-row"><span><i class="swatch" style="background:'
        +colorOf(l,li)+(dashOf(l)?';opacity:.55':'')+'"></i> '+esc(l)+'</span><b>'
        +fmtNum(v,panel.unit==="%"?"%":"")+'</b></div>';
    });
    tip.innerHTML=h; tip.style.opacity=1;
    var px=view.X(i)/W*r.width;
    tip.style.left=Math.max(4,Math.min(r.width-tip.offsetWidth-4,px+12))+"px";
    tip.style.top="8px";
  }
  function touch(e){ if(e.touches.length) onMove(e.touches[0]); }
  svg.addEventListener("mousemove",onMove);
  svg.addEventListener("touchstart",touch,{passive:true});
  svg.addEventListener("touchmove",touch,{passive:true});
  svg.addEventListener("mouseleave",function(){
    tip.style.opacity=0;
    var c=svg.querySelector(".cross"); if(c)c.style.opacity=0;
  });
  return {draw:draw, colorOf:colorOf, dashOf:dashOf,
          fit:function(){ if(box.clientWidth!==drawnFor) draw(); },
          setDays:function(d){days=d;draw();},
          getDays:function(){return days;},
          toggle:function(l){hidden[l]=!hidden[l];draw();},
          isHidden:function(l){return !!hidden[l];}, labels:labels};
}

var host=document.getElementById("panels"), charts=[];
Object.keys(D.panels).forEach(function(key){
  var p=D.panels[key]; p.key=key;
  if(!p.data.dates.length) return;
  var card=document.createElement("div"); card.className="card";
  card.innerHTML='<div class="card-top"><div><h2>'+esc(p.title)+'</h2>'
    +'<p class="desc">'+esc(p.sub)+'</p></div><div class="ranges"></div></div>'
    +'<div class="legend"></div><div class="chartbox"></div>'
    +'<div class="xsec"></div>'
    +'<div class="src"><span>来源：'+esc(p.source)+'</span><span>'+esc(p.freq)
    +' · 单位：'+esc(p.unit)+' · '+esc(p.data.dates[0])+' → '
    +esc(p.data.dates[p.data.dates.length-1])+'（'+p.data.dates.length+' 点）</span></div>';
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
    var b=document.createElement("button");
    b.setAttribute("aria-pressed", ch.isHidden(l)?"false":"true");
    b.innerHTML='<i class="swatch" style="background:'+ch.colorOf(l,li)
      +(ch.dashOf(l)?';opacity:.55':'')+'"></i>'+esc(l);
    b.onclick=function(){ ch.toggle(l);
      b.setAttribute("aria-pressed", ch.isHidden(l)?"false":"true"); };
    lg.appendChild(b);
  });
  var xs=card.querySelector(".xsec");
  if(p.tables && p.tables.length){
    card.querySelector("h2").insertAdjacentHTML("beforeend",
      '<span class="xmonth">当期截面 '+esc(p.month||"")+'</span>');
    xs.innerHTML = p.tables.map(function(t){
      var mx = Math.max.apply(null, t.items.map(function(i){
        return Math.abs(i.pct||0);}).concat([1]));
      return '<div><h3>'+esc(t.title)+'</h3><p class="xnote">'+esc(t.note)+'</p>'
        + t.items.map(function(i){
            var pctTxt = (i.pct===null||i.pct===undefined) ? "" : '<i>'+i.pct+'%</i>';
            var bar = (i.pct===null||i.pct===undefined) ? ""
              : '<div class="xbar"><span style="width:'+(Math.abs(i.pct)/mx*100).toFixed(1)
                +'%'+(i.pct<0?';background:var(--c5)':'')+'"></span></div>';
            var en = i.en ? '<span class="xen">'+esc(i.en)+'</span>' : "";
            return '<div class="xrow"><div class="xhead"><b>'+esc(i.label)+'</b>'+pctTxt+'</div>'
                 + en + bar + '</div>';
          }).join("")
        + '</div>';
    }).join("");
  } else { xs.remove(); }
  ch.draw(); charts.push(ch);
});
// 图宽一变（转屏、拖窗口、首屏画完后页面变长冒出滚动条）就按新宽度重画；rAF 合并连发事件，
// 只比宽度 —— 手机上滚动时地址栏伸缩只改高度，不触发重画
var pending=0;
function refit(){
  if(pending) return;
  pending=requestAnimationFrame(function(){ pending=0; charts.forEach(function(c){c.fit();}); });
}
refit();
if(window.ResizeObserver) new ResizeObserver(refit).observe(host);
else addEventListener("resize", refit);
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

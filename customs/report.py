"""HTML 셸 + 클라이언트 JS/CSS 생성. 외부 의존성 0, 차트는 순수 인라인 SVG.

서버는 JSON API(/api/*)를 제공하고, 이 페이지의 바닐라 JS 가 이를 받아
표와 SVG 차트를 그린다. --static 모드에서는 데이터를 미리 임베드한다.
"""
from __future__ import annotations

import json

PAGE_CSS = """
:root{
  --bg:#0f1420; --panel:#161c2b; --panel2:#1d2639; --line:#2a3550;
  --txt:#e6ecf5; --muted:#8a97b1; --up:#ff5c6c; --down:#4a90ff;
  --exp:#4a90ff; --imp:#ff5c6c; --accent:#5ad1a8; --chip:#243049;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Malgun Gothic","Apple SD Gothic Neo",sans-serif;}
a{color:inherit;text-decoration:none}
.wrap{max-width:1280px;margin:0 auto;padding:18px 20px 60px}
header.top{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;
  border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:18px}
header.top h1{font-size:20px;margin:0;letter-spacing:-.3px}
header.top .meta{color:var(--muted);font-size:12.5px}
.breadcrumb{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:4px 0 16px;font-size:13px}
.breadcrumb .crumb{background:var(--chip);padding:5px 11px;border-radius:999px;cursor:pointer;
  border:1px solid var(--line);white-space:nowrap}
.breadcrumb .crumb:hover{border-color:var(--accent)}
.breadcrumb .crumb.active{background:var(--accent);color:#06281e;border-color:var(--accent);font-weight:600;cursor:default}
.breadcrumb .sep{color:var(--muted)}
.grid{display:grid;grid-template-columns:1fr;gap:16px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}
.panel h2{font-size:14px;margin:0 0 12px;color:var(--muted);font-weight:600;letter-spacing:.2px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:600;cursor:pointer;user-select:none;position:sticky;top:0;background:var(--panel)}
th:first-child,td:first-child{text-align:left}
td.name{text-align:left;color:var(--muted);max-width:360px;overflow:hidden;text-overflow:ellipsis}
tr.row{cursor:pointer}
tr.row:hover td{background:var(--panel2)}
tr.leaf{cursor:default}
tr.leaf:hover td{background:transparent}
.code{font-variant-numeric:tabular-nums;font-weight:600}
.pos{color:var(--up)} .neg{color:var(--down)}
.tablewrap{max-height:520px;overflow:auto;border-radius:8px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:4px}
.kpi{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi .label{color:var(--muted);font-size:12px;margin-bottom:6px}
.kpi .val{font-size:19px;font-weight:700;font-variant-numeric:tabular-nums}
.kpi .sub{font-size:12px;margin-top:4px}
.charts{display:grid;grid-template-columns:1fr;gap:16px}
.charts .full{grid-column:1/-1}
.chart-row{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.legend{display:flex;gap:16px;font-size:12px;color:var(--muted);margin-bottom:6px}
.legend .dot{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:middle}
svg{display:block;width:100%;height:auto}
.svg-tip{font-size:10.5px;fill:var(--muted)}
.svg-ax{font-size:11px;fill:#aab6d0;font-weight:600}
.svg-val{font-size:10px;fill:#c3cde3;font-weight:600}
.companies .co{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--line)}
.companies .co .nm{font-weight:600}
.companies .co .nt{color:var(--muted);flex:1;font-size:12.5px}
.companies form{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
input,button{font:inherit}
input[type=text]{background:var(--panel2);border:1px solid var(--line);color:var(--txt);
  border-radius:8px;padding:8px 10px;outline:none}
input[type=text]:focus{border-color:var(--accent)}
button{background:var(--accent);color:#06281e;border:none;border-radius:8px;padding:8px 14px;
  font-weight:600;cursor:pointer}
button.ghost{background:var(--chip);color:var(--txt);border:1px solid var(--line)}
button:hover{filter:brightness(1.06)}
.del{background:transparent;color:var(--muted);border:1px solid var(--line);padding:4px 9px;border-radius:7px}
.del:hover{color:var(--up);border-color:var(--up)}
.empty{color:var(--muted);font-size:13px;padding:6px 0}
.hint{color:var(--muted);font-size:12px;margin-top:8px}
@media(max-width:860px){.kpis{grid-template-columns:repeat(2,1fr)}.chart-row{grid-template-columns:1fr}}
"""


def page_html(meta: dict, embedded: dict | None = None) -> str:
    """대시보드 메인 페이지. embedded 가 주어지면 정적 모드로 데이터를 임베드."""
    latest = meta.get("latest_month", "")
    latest_disp = f"{latest[:4]}.{latest[4:]}" if latest else "-"
    embed_json = json.dumps(embedded, ensure_ascii=False) if embedded else "null"
    static_flag = "true" if embedded else "false"
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>관세청 수출입통계 대시보드</title>
<style>{PAGE_CSS}</style>
</head><body>
<div class="wrap">
  <header class="top">
    <h1>🇰🇷 관세청 수출입통계 대시보드</h1>
    <span class="meta">기준월 <b>{latest_disp}</b> · 수집범위 {meta.get('range','-')} · 수집시각 {meta.get('collected_at','-')}</span>
  </header>
  <div class="breadcrumb" id="breadcrumb"></div>
  <div id="app" class="grid"></div>
</div>
<script>
const EMBEDDED = {embed_json};
const STATIC = {static_flag};
const LATEST = {json.dumps(latest)};
</script>
<script>{PAGE_JS}</script>
</body></html>"""


PAGE_JS = r"""
// ---------- 유틸 ----------
function fmtUSD(v){
  if(v===null||v===undefined||isNaN(v)) return '-';
  const a=Math.abs(v);
  if(a>=1e9) return '$'+(v/1e9).toFixed(2)+'B';
  if(a>=1e6) return '$'+(v/1e6).toFixed(2)+'M';
  if(a>=1e3) return '$'+(v/1e3).toFixed(1)+'K';
  return '$'+Math.round(v).toLocaleString();
}
function fmtPct(v){ return (v===null||v===undefined||isNaN(v))?'-':(v>=0?'+':'')+v.toFixed(1)+'%'; }
function cls(v){ return v>=0?'pos':'neg'; }
function el(tag,attrs,children){
  const e=document.createElement(tag);
  if(attrs) for(const k in attrs){ if(k==='class')e.className=attrs[k]; else if(k==='html')e.innerHTML=attrs[k]; else e.setAttribute(k,attrs[k]); }
  (children||[]).forEach(c=>{ if(typeof c==='string')e.appendChild(document.createTextNode(c)); else if(c)e.appendChild(c); });
  return e;
}

// ---------- API ----------
async function api(path){
  if(STATIC){ return EMBEDDED[path] || null; }
  const r=await fetch(path);
  if(!r.ok) throw new Error('API '+path+' -> '+r.status);
  return await r.json();
}
async function apiPost(path,body){
  if(STATIC) return {ok:false,static:true};
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  return await r.json();
}

// ---------- 상태 ----------
const state={ path:[] }; // ['85','8542','854232'] 최대 3

function pathKey(){ return state.path.join('/'); }

// ---------- SVG 차트 ----------
function lineChart(series, opts){
  // series: [{period, exp_dlr, imp_dlr}] 오름차순
  const W=opts.w||920, H=opts.h||320, m={t:18,r:18,b:30,l:66};
  const iw=W-m.l-m.r, ih=H-m.t-m.b;
  const keys=opts.keys; // [{field,color,name}]
  let maxv=0;
  series.forEach(d=>keys.forEach(k=>{maxv=Math.max(maxv,d[k.field]||0)}));
  maxv=(maxv||1)*1.08;
  const n=series.length;
  const X=i=> m.l + (n<=1?iw/2:(i/(n-1))*iw);
  const Y=v=> m.t + ih - (v/maxv)*ih;
  const svgns='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(svgns,'svg');
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio','xMidYMid meet');
  function add(tag,at){const e=document.createElementNS(svgns,tag);for(const k in at)e.setAttribute(k,at[k]);return e;}
  // 그라데이션 정의
  const defs=add('defs',{});
  keys.forEach((k,ki)=>{
    const gid='g'+ki+'_'+Math.random().toString(36).slice(2,7);
    k._gid=gid;
    const lg=add('linearGradient',{id:gid,x1:0,y1:0,x2:0,y2:1});
    lg.appendChild(add('stop',{offset:'0%','stop-color':k.color,'stop-opacity':0.28}));
    lg.appendChild(add('stop',{offset:'100%','stop-color':k.color,'stop-opacity':0}));
    defs.appendChild(lg);
  });
  svg.appendChild(defs);
  // y축 그리드 4칸
  for(let g=0; g<=4; g++){
    const v=maxv*g/4, y=Y(v);
    svg.appendChild(add('line',{x1:m.l,y1:y,x2:W-m.r,y2:y,stroke:'#273149','stroke-width':1}));
    const t=add('text',{x:m.l-8,y:y+3.5,'text-anchor':'end'}); t.setAttribute('class','svg-tip');
    t.textContent=fmtUSD(v); svg.appendChild(t);
  }
  // x축 연도 구분선/라벨
  let lastYear=null;
  series.forEach((d,i)=>{
    const yr=d.period.slice(0,4);
    if(yr!==lastYear){ lastYear=yr;
      const t=add('text',{x:X(i),y:H-9,'text-anchor':'middle'}); t.setAttribute('class','svg-ax');
      t.textContent=yr; svg.appendChild(t);
      svg.appendChild(add('line',{x1:X(i),y1:m.t,x2:X(i),y2:m.t+ih,stroke:'#1c2435','stroke-width':1}));
    }
  });
  // 면적 + 라인
  keys.forEach(k=>{
    let dpath='', area='';
    series.forEach((d,i)=>{ const px=X(i),py=Y(d[k.field]||0);
      dpath+=(i===0?'M':'L')+px.toFixed(1)+' '+py.toFixed(1)+' ';
      area+=(i===0?('M'+px.toFixed(1)+' '+(m.t+ih)+' L'):'L')+px.toFixed(1)+' '+py.toFixed(1)+' ';
    });
    area+='L'+X(n-1).toFixed(1)+' '+(m.t+ih)+' Z';
    svg.appendChild(add('path',{d:area,fill:'url(#'+k._gid+')',stroke:'none'}));
    svg.appendChild(add('path',{d:dpath,fill:'none',stroke:k.color,'stroke-width':2.2,'stroke-linejoin':'round','stroke-linecap':'round'}));
    // 마지막 점 강조
    const last=series[n-1];
    svg.appendChild(add('circle',{cx:X(n-1),cy:Y(last[k.field]||0),r:3.2,fill:k.color,stroke:'#0f1420','stroke-width':1.5}));
  });
  return svg;
}

function barChart(items, opts){
  // items: [{label, value}], value 는 % (음수 가능). label 예: "2026Q3"
  items=items.filter(d=>d.value!=null);
  const svgns='http://www.w3.org/2000/svg';
  if(!items.length){ const s=document.createElementNS(svgns,'svg'); s.setAttribute('viewBox','0 0 460 120');
    const t=document.createElementNS(svgns,'text');t.setAttribute('x',230);t.setAttribute('y',60);
    t.setAttribute('text-anchor','middle');t.setAttribute('class','svg-tip');t.textContent='데이터가 부족합니다';
    s.appendChild(t); return s; }
  const W=opts.w||460, H=opts.h||280, m={t:16,r:14,b:46,l:52};
  const iw=W-m.l-m.r, ih=H-m.t-m.b;
  const vals=items.map(d=>d.value);
  const {lo,hi}=niceBounds(Math.min(...vals),Math.max(...vals));
  const n=items.length, step=iw/n;
  const svg=document.createElementNS(svgns,'svg');
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio','xMidYMid meet');
  function add(tag,at){const e=document.createElementNS(svgns,tag);for(const k in at)e.setAttribute(k,at[k]);return e;}
  const Y=v=> m.t + ih - ((v-lo)/(hi-lo))*ih;
  const zeroY=Y(0);
  // 그리드
  for(let g=0;g<=4;g++){
    const v=lo+(hi-lo)*g/4, y=Y(v);
    svg.appendChild(add('line',{x1:m.l,y1:y,x2:W-m.r,y2:y,stroke:'#273149','stroke-width':1}));
    const t=add('text',{x:m.l-8,y:y+3.5,'text-anchor':'end'}); t.setAttribute('class','svg-tip');
    t.textContent=v.toFixed(0)+'%'; svg.appendChild(t);
  }
  // 0% 기준선 강조
  svg.appendChild(add('line',{x1:m.l,y1:zeroY,x2:W-m.r,y2:zeroY,stroke:'#4a5675','stroke-width':1.4}));
  const bw=Math.max(3, Math.min(26, step*0.6));
  // 라벨 밀도: 겹치지 않도록 간격 계산 (최소 34px 간격)
  const labelEvery=Math.max(1, Math.ceil(34/step));
  items.forEach((d,i)=>{
    const cx=m.l+step*i+step/2;
    const v=d.value;
    const y=Y(v), h=Math.abs(y-zeroY);
    svg.appendChild(add('rect',{x:cx-bw/2,y:Math.min(y,zeroY),width:bw,height:Math.max(1,h),
      fill: v>=0?'#4a90ff':'#ff5c6c', rx:2}));
    // 값 라벨 (막대 끝)
    if(n<=14){
      const ty = v>=0 ? Math.min(y,zeroY)-4 : Math.max(y,zeroY)+12;
      const vt=add('text',{x:cx,y:ty,'text-anchor':'middle'}); vt.setAttribute('class','svg-val');
      vt.textContent=(v>=0?'+':'')+v.toFixed(0); svg.appendChild(vt);
    }
    // x축 라벨 (회전해서 잘림 방지)
    if(i%labelEvery===0 || i===n-1){
      const t=add('text',{x:cx,y:H-m.b+16,'text-anchor':'end',transform:`rotate(-40 ${cx} ${H-m.b+16})`});
      t.setAttribute('class','svg-ax'); t.textContent=d.label; svg.appendChild(t);
    }
  });
  return svg;
}

function niceBounds(minv, maxv){
  // 0 을 항상 포함하고 보기 좋은 min/max 로 확장
  minv=Math.min(0,minv); maxv=Math.max(0,maxv);
  if(minv===maxv){ maxv=1; }
  const span=maxv-minv||1;
  const pad=span*0.12;
  return {lo:minv-(minv<0?pad:0), hi:maxv+pad};
}

function groupedBar(series, opts){
  // series:[{period, expYoy, impYoy}] YoY 두 계열. null(앞 12개월) 구간은 잘라낸다.
  series=series.filter(d=>d.expYoy!=null || d.impYoy!=null);
  const svgns='http://www.w3.org/2000/svg';
  if(!series.length){ const s=document.createElementNS(svgns,'svg'); s.setAttribute('viewBox','0 0 450 120');
    const t=document.createElementNS(svgns,'text');t.setAttribute('x',225);t.setAttribute('y',60);
    t.setAttribute('text-anchor','middle');t.setAttribute('class','svg-tip');t.textContent='전년동월 데이터가 아직 없습니다';
    s.appendChild(t); return s; }
  const W=opts.w||460, H=opts.h||280, m={t:16,r:14,b:30,l:52};
  const iw=W-m.l-m.r, ih=H-m.t-m.b;
  const all=[]; series.forEach(d=>{ if(d.expYoy!=null)all.push(d.expYoy); if(d.impYoy!=null)all.push(d.impYoy);});
  const {lo,hi}=niceBounds(Math.min(...all),Math.max(...all));
  const n=series.length, step=iw/n;
  const svg=document.createElementNS(svgns,'svg');
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`); svg.setAttribute('preserveAspectRatio','xMidYMid meet');
  function add(tag,at){const e=document.createElementNS(svgns,tag);for(const k in at)e.setAttribute(k,at[k]);return e;}
  const Y=v=> m.t + ih - ((v-lo)/(hi-lo))*ih; const zeroY=Y(0);
  // 그리드
  for(let g=0;g<=4;g++){ const v=lo+(hi-lo)*g/4,y=Y(v);
    svg.appendChild(add('line',{x1:m.l,y1:y,x2:W-m.r,y2:y,stroke:'#273149','stroke-width':1}));
    const t=add('text',{x:m.l-8,y:y+3.5,'text-anchor':'end'});t.setAttribute('class','svg-tip');t.textContent=v.toFixed(0)+'%';svg.appendChild(t);
  }
  // 0% 기준선 강조
  svg.appendChild(add('line',{x1:m.l,y1:zeroY,x2:W-m.r,y2:zeroY,stroke:'#4a5675','stroke-width':1.4}));
  const bw=Math.max(1.5, Math.min(9, step*0.34));
  let lastYear=null;
  series.forEach((d,i)=>{
    const cx=m.l+step*i+step/2;
    [['expYoy','#4a90ff',-1],['impYoy','#ff5c6c',1]].forEach(([f,c,s])=>{
      const v=d[f]; if(v==null)return;
      const y=Y(v),h=Math.abs(y-zeroY);
      svg.appendChild(add('rect',{x:cx+(s*bw/2)-(bw/2)+(s*0.6),y:Math.min(y,zeroY),width:bw,height:Math.max(1,h),fill:c,rx:1.5}));
    });
    const yr=d.period.slice(0,4);
    if(yr!==lastYear){lastYear=yr;const t=add('text',{x:cx,y:H-9,'text-anchor':'middle'});t.setAttribute('class','svg-ax');t.textContent=yr;svg.appendChild(t);}
  });
  return svg;
}

// ---------- 렌더 ----------
function renderBreadcrumb(names){
  const bc=document.getElementById('breadcrumb'); bc.innerHTML='';
  const home=el('div',{class:'crumb'+(state.path.length===0?' active':'')},['전체 (HS 2자리)']);
  home.onclick=()=>{ state.path=[]; route(); };
  bc.appendChild(home);
  state.path.forEach((code,idx)=>{
    bc.appendChild(el('span',{class:'sep'},['▸']));
    const nm=(names[idx]&&names[idx][code])?names[idx][code]:'';
    const active=idx===state.path.length-1;
    const c=el('div',{class:'crumb'+(active?' active':'')},['HS '+code+(nm?('  '+nm):'')]);
    if(!active) c.onclick=()=>{ state.path=state.path.slice(0,idx+1); route(); };
    bc.appendChild(c);
  });
}

let sortState={col:'exp_dlr',dir:-1};
function renderTable(data, names){
  const app=document.getElementById('app');
  const level=(state.path.length+1)*2; // 다음 레벨 (2/4/6)
  const canDrill=level<=6;
  const panel=el('div',{class:'panel'});
  const title = state.path.length===0 ? 'HS 2자리 — 수출 금액 순위'
    : ('하위 HS '+level+'자리  (클릭하여 드릴다운)');
  panel.appendChild(el('h2',{},[title]));
  const wrap=el('div',{class:'tablewrap'});
  const tbl=el('table');
  const thead=el('thead');
  const trh=el('tr');
  const cols=[['code','HS코드'],['name','품목명'],['exp_dlr','수출(USD)'],['imp_dlr','수입(USD)'],['bal','무역수지']];
  cols.forEach(([k,label])=>{
    const th=el('th',{},[label + (sortState.col===k?(sortState.dir<0?' ▼':' ▲'):'')]);
    th.onclick=()=>{ if(sortState.col===k)sortState.dir*=-1; else {sortState.col=k;sortState.dir=-1;} renderTable(data,names); };
    trh.appendChild(th);
  });
  thead.appendChild(trh); tbl.appendChild(thead);
  const tb=el('tbody');
  const rows=[...data].sort((a,b)=>{
    let x=a[sortState.col], y=b[sortState.col];
    if(sortState.col==='code'||sortState.col==='name'){
      x=sortState.col==='name'?(names.cur[a.code]||''):a.code;
      y=sortState.col==='name'?(names.cur[b.code]||''):b.code;
      return x<y?sortState.dir:x>y?-sortState.dir:0;
    }
    return (x-y)*sortState.dir;
  });
  rows.forEach(r=>{
    const tr=el('tr',{class:canDrill?'row':'leaf'});
    tr.appendChild(el('td',{class:'code'},[r.code]));
    tr.appendChild(el('td',{class:'name'},[names.cur[r.code]||'']));
    tr.appendChild(el('td',{},[fmtUSD(r.exp_dlr)]));
    tr.appendChild(el('td',{},[fmtUSD(r.imp_dlr)]));
    const bal=el('td',{class:cls(r.bal)},[fmtUSD(r.bal)]);
    tr.appendChild(bal);
    if(canDrill) tr.onclick=()=>{ state.path.push(r.code); route(); };
    tb.appendChild(tr);
  });
  tbl.appendChild(tb); wrap.appendChild(tbl); panel.appendChild(wrap);
  if(canDrill) panel.appendChild(el('div',{class:'hint'},['행을 클릭하면 하위 품목으로 들어갑니다.']));
  app.appendChild(panel);
}

function renderDetail(detail){
  const app=document.getElementById('app');
  const s=detail.series, prefix=detail.prefix, level=detail.level;
  const nm=detail.name||'';
  // KPI
  const panel=el('div',{class:'panel'});
  panel.appendChild(el('h2',{},['📊 HS '+prefix+(nm?('  ·  '+nm):'')+'  ('+level+'자리)']));
  const kp=el('div',{class:'kpis'});
  const last=s.length?s[s.length-1]:{exp_dlr:0,imp_dlr:0};
  const expYoy=detail.expYoy.length?detail.expYoy[detail.expYoy.length-1].yoy:null;
  const impYoy=detail.impYoy.length?detail.impYoy[detail.impYoy.length-1].yoy:null;
  const qExp=detail.qExp.length?detail.qExp[detail.qExp.length-1].qoq:null;
  function kpi(label,val,sub,subcls){
    const d=el('div',{class:'kpi'});
    d.appendChild(el('div',{class:'label'},[label]));
    d.appendChild(el('div',{class:'val'},[val]));
    if(sub!==undefined&&sub!==null) d.appendChild(el('div',{class:'sub '+(subcls||'')},[sub]));
    return d;
  }
  kp.appendChild(kpi('수출 (최근월)',fmtUSD(last.exp_dlr), expYoy!=null?fmtPct(expYoy)+' YoY':null, expYoy>=0?'pos':'neg'));
  kp.appendChild(kpi('수입 (최근월)',fmtUSD(last.imp_dlr), impYoy!=null?fmtPct(impYoy)+' YoY':null, impYoy>=0?'pos':'neg'));
  kp.appendChild(kpi('무역수지 (최근월)',fmtUSD(last.exp_dlr-last.imp_dlr), null));
  kp.appendChild(kpi('수출 QoQ (최근분기)', qExp!=null?fmtPct(qExp):'-', null, qExp>=0?'pos':'neg'));
  panel.appendChild(kp);
  // 월간 추이
  const legend=el('div',{class:'legend'},[]);
  legend.innerHTML='<span><span class="dot" style="background:#4a90ff"></span>수출(USD)</span>'+
                   '<span><span class="dot" style="background:#ff5c6c"></span>수입(USD)</span>';
  panel.appendChild(el('h2',{},['월간 수출·수입 추이 (최근 5개년)']));
  panel.appendChild(legend);
  panel.appendChild(lineChart(s,{keys:[{field:'exp_dlr',color:'#4a90ff'},{field:'imp_dlr',color:'#ff5c6c'}]}));
  app.appendChild(panel);

  // YoY / QoQ 두 패널
  const row=el('div',{class:'chart-row'});
  const p1=el('div',{class:'panel'});
  p1.appendChild(el('h2',{},['전년동월 대비 증감률 (YoY %)']));
  const lg=el('div',{class:'legend'}); lg.innerHTML='<span><span class="dot" style="background:#4a90ff"></span>수출</span><span><span class="dot" style="background:#ff5c6c"></span>수입</span>';
  p1.appendChild(lg);
  const merged=detail.expYoy.map((d,i)=>({period:d.period,expYoy:d.yoy,impYoy:detail.impYoy[i]?detail.impYoy[i].yoy:null}));
  p1.appendChild(groupedBar(merged,{}));
  row.appendChild(p1);
  const p2=el('div',{class:'panel'});
  p2.appendChild(el('h2',{},['전분기 대비 증감률 (수출 QoQ %)']));
  p2.appendChild(barChart(detail.qExp.map(d=>({label:d.label.replace(' ',''),value:d.qoq})),{}));
  row.appendChild(p2);
  app.appendChild(row);

  // 관련 기업
  renderCompanies(prefix, level, detail.companies);
}

function renderCompanies(prefix, level, companies){
  const app=document.getElementById('app');
  const panel=el('div',{class:'panel companies'});
  panel.appendChild(el('h2',{},['🏢 관련 기업']));
  if(!STATIC){
    const form=el('form');
    const co=el('input',{type:'text',placeholder:'기업명',style:'flex:1;min-width:140px'});
    const nt=el('input',{type:'text',placeholder:'메모 (선택)',style:'flex:2;min-width:160px'});
    const btn=el('button',{type:'submit'},['추가']);
    form.appendChild(co); form.appendChild(nt); form.appendChild(btn);
    form.onsubmit=async(e)=>{ e.preventDefault(); if(!co.value.trim())return;
      await apiPost('/api/company/add',{hs_code:prefix,hs_level:level,company:co.value.trim(),note:nt.value.trim()});
      route();
    };
    panel.appendChild(form);
  }
  if(!companies||!companies.length){
    panel.appendChild(el('div',{class:'empty'},['등록된 관련 기업이 없습니다.']));
  } else {
    companies.forEach(c=>{
      const row=el('div',{class:'co'});
      row.appendChild(el('span',{class:'nm'},[c.company]));
      row.appendChild(el('span',{class:'nt'},[c.note||'']));
      if(!STATIC){
        const d=el('button',{class:'del'},['삭제']);
        d.onclick=async()=>{ await apiPost('/api/company/delete',{id:c.id}); route(); };
        row.appendChild(d);
      }
      panel.appendChild(row);
    });
  }
  app.appendChild(panel);
}

// ---------- 라우팅 ----------
async function route(){
  const app=document.getElementById('app'); app.innerHTML='';
  const key=pathKey();
  // 대표명 레벨별 캐시 로드
  const names=await loadNames();
  renderBreadcrumb(names.levels);

  if(state.path.length>0){
    // 상세 (현재 선택된 가장 깊은 코드)
    const prefix=state.path[state.path.length-1];
    const detail=await api('/api/detail?code='+prefix);
    if(detail){ renderDetail(detail); }
    else if(STATIC){
      const app=document.getElementById('app');
      const p=el('div',{class:'panel'});
      p.appendChild(el('h2',{},['📊 HS '+prefix]));
      p.appendChild(el('div',{class:'empty'},['정적 리포트에서는 HS 6자리 상세 차트를 포함하지 않습니다. 서버 모드(python run.py)에서 확인하세요. 아래 하위 품목 표는 사용할 수 있습니다.']));
      app.appendChild(p);
    }
  }
  if(state.path.length<3){
    // 하위 목록 표
    const prefix=state.path.length?state.path[state.path.length-1]:'';
    const level=(state.path.length+1)*2;
    const data=await api('/api/level?code='+encodeURIComponent(prefix)+'&level='+level);
    names.cur=names.levels[state.path.length]||{};
    renderTable(data, names);
  }
  window.scrollTo({top:0,behavior:'smooth'});
}

let _namesCache=null;
async function loadNames(){
  if(_namesCache) return _namesCache;
  const levels=[await api('/api/names?level=2'),await api('/api/names?level=4'),await api('/api/names?level=6')];
  _namesCache={levels,cur:levels[0]};
  return _namesCache;
}

route();
"""


def build_static(conn, meta: dict) -> str:
    """서버 없이 모든 데이터를 임베드한 단일 HTML 문자열 생성.

    모든 시계열을 레벨당 1쿼리로 일괄 계산한다(2/4/6 → 3쿼리).
    관련기업 입력/삭제는 정적 모드에서 비활성화된다.
    """
    from . import db

    latest = meta.get("latest_month") or db.latest_month(conn)
    meta = dict(meta)
    meta["latest_month"] = latest or ""

    embedded: dict = {}
    names = {}
    for lv in (2, 4, 6):
        names[lv] = db.representative_names(conn, lv)
        embedded[f"/api/names?level={lv}"] = names[lv]

    companies = db.all_companies(conn)

    # 레벨별 전체 시계열(일괄) → 집계표 + 상세 임베드.
    # 상세(시계열)는 용량 문제로 HS2/HS4 까지만 임베드한다.
    # HS6 은 집계표(드릴다운 표)만 제공하며, 상세는 서버 모드에서 확인.
    DETAIL_MAX_LEVEL = 4
    for lv in (2, 4, 6):
        series_map = db.all_series_by_level(conn, lv)
        name_map = names[lv]
        groups: dict[str, list] = {}
        for code, series in series_map.items():
            parent = "" if lv == 2 else code[: lv - 2]
            last = series[-1] if series else {"exp_dlr": 0, "imp_dlr": 0}
            cur = next((s for s in series if s["period"] == latest), last)
            groups.setdefault(parent, []).append(
                {
                    "code": code,
                    "exp_dlr": cur["exp_dlr"],
                    "imp_dlr": cur["imp_dlr"],
                    "bal": cur["exp_dlr"] - cur["imp_dlr"],
                }
            )
            if lv <= DETAIL_MAX_LEVEL:
                embedded["/api/detail?code=" + code] = {
                    "prefix": code,
                    "level": lv,
                    "name": name_map.get(code, ""),
                    "series": series,
                    "expYoy": db.compute_yoy(series, "exp_dlr"),
                    "impYoy": db.compute_yoy(series, "imp_dlr"),
                    "qExp": db.compute_quarterly(series, "exp_dlr"),
                    "companies": companies.get(code, []),
                }
        for parent, rows in groups.items():
            rows.sort(key=lambda r: r["exp_dlr"], reverse=True)
            embedded[f"/api/level?code={parent}&level={lv}"] = rows

    return page_html(meta, embedded=embedded)

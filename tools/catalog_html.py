# -*- coding: utf-8 -*-
"""HTML template for gameplay_catalog.py. PAGE has one placeholder: /*DATA*/{} (the catalogue JSON)."""

PAGE = r"""<title>eFootball Mod Deck</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap">
<style>
:root{
  --ground:#f4f6f2; --panel:#ffffff; --panel-2:#f0f2ee; --ink:#171c1f; --muted:#5f6b71;
  --line:#e0e3dd; --line-strong:#cfd4cc;
  --accent:#c8791b; --accent-soft:#f6e6cf;
  --live:#1f9d63; --likely:#2f77c2; --inert:#c0483f; --unverified:#8a949a;
  --live-bg:#e2f3ea; --likely-bg:#e2edf9; --inert-bg:#f8e5e3; --unverified-bg:#eceef0;
  --shadow:0 1px 2px rgba(20,28,24,.06),0 8px 24px rgba(20,28,24,.05);
}
:root:not([data-theme="light"]){ @media (prefers-color-scheme:dark){
  --ground:#0d1117; --panel:#151b22; --panel-2:#1c232c; --ink:#e6edf3; --muted:#93a1b0;
  --line:#242c36; --line-strong:#313b47;
  --accent:#f2b34b; --accent-soft:#3a2f1a;
  --live:#3fb27f; --likely:#5b9bd5; --inert:#e0716b; --unverified:#7d8896;
  --live-bg:#132a20; --likely-bg:#12233a; --inert-bg:#331b19; --unverified-bg:#1c232c;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 10px 30px rgba(0,0,0,.35);
}}
:root[data-theme="dark"]{
  --ground:#0d1117; --panel:#151b22; --panel-2:#1c232c; --ink:#e6edf3; --muted:#93a1b0;
  --line:#242c36; --line-strong:#313b47;
  --accent:#f2b34b; --accent-soft:#3a2f1a;
  --live:#3fb27f; --likely:#5b9bd5; --inert:#e0716b; --unverified:#7d8896;
  --live-bg:#132a20; --likely-bg:#12233a; --inert-bg:#331b19; --unverified-bg:#1c232c;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 10px 30px rgba(0,0,0,.35);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--ground);color:var(--ink);
  font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:15px;line-height:1.5;
  -webkit-font-smoothing:antialiased;}
.mono{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums;}
a{color:var(--accent);text-decoration:none}
h1,h2,h3{text-wrap:balance;margin:0}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}

/* header */
header{border-bottom:1px solid var(--line);background:linear-gradient(180deg,var(--panel),var(--ground));position:relative;overflow:hidden}
header::before{content:"";position:absolute;inset:0;background:
  repeating-linear-gradient(90deg,transparent 0 78px,color-mix(in srgb,var(--accent) 8%,transparent) 78px 79px);
  opacity:.5;pointer-events:none;-webkit-mask:linear-gradient(180deg,#000,transparent);mask:linear-gradient(180deg,#000,transparent)}
.head-inner{padding:34px 0 26px;position:relative}
.kicker{font-family:"IBM Plex Mono",monospace;font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:var(--accent);font-weight:600}
h1{font-family:"Archivo",sans-serif;font-weight:800;font-size:clamp(30px,5vw,50px);letter-spacing:-.02em;margin:.18em 0 .1em;line-height:1}
.tagline{color:var(--muted);max-width:60ch;font-size:15.5px}
.stat-row{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:9px 14px;box-shadow:var(--shadow)}
.stat b{font-family:"Archivo",sans-serif;font-size:20px;font-weight:800;display:block;line-height:1.1}
.stat span{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.applied{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px;align-items:center}
.applied .lbl{font-size:11.5px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted)}
.chip{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border-radius:999px;font-size:12.5px;font-weight:500;border:1px solid var(--line-strong);background:var(--panel)}
.chip.on{border-color:var(--accent);background:var(--accent-soft);color:var(--ink)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 22%,transparent)}

/* controls */
.controls{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--ground) 88%,transparent);
  backdrop-filter:blur(10px);border-bottom:1px solid var(--line);padding:12px 0}
.controls-inner{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.search{flex:1;min-width:220px;display:flex;align-items:center;gap:9px;background:var(--panel);
  border:1px solid var(--line-strong);border-radius:10px;padding:9px 13px}
.search:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.search input{border:0;background:transparent;color:var(--ink);font:inherit;width:100%;outline:none}
.search svg{flex:none;color:var(--muted)}
.seg{display:inline-flex;border:1px solid var(--line-strong);border-radius:10px;overflow:hidden}
.seg button{border:0;background:var(--panel);color:var(--muted);font:inherit;font-size:13px;padding:8px 14px;cursor:pointer;font-weight:500}
.seg button+button{border-left:1px solid var(--line)}
.seg button[aria-pressed=true]{background:var(--accent-soft);color:var(--ink)}
.filters{display:flex;gap:7px;flex-wrap:wrap}
.fbtn{cursor:pointer;user-select:none;border:1px solid var(--line-strong);background:var(--panel);
  border-radius:999px;padding:5px 11px 5px 9px;font-size:12.5px;display:inline-flex;gap:7px;align-items:center;color:var(--muted)}
.fbtn[aria-pressed=true]{color:var(--ink);border-color:currentColor}
.fbtn .sw{width:8px;height:8px;border-radius:50%}
.sw.live{background:var(--live)} .sw.likely{background:var(--likely)}
.sw.inert{background:var(--inert)} .sw.unverified{background:var(--unverified)}

main{padding:28px 0 80px}
.sec-head{display:flex;align-items:baseline;gap:14px;margin:34px 0 6px;flex-wrap:wrap}
.sec-head h2{font-family:"Archivo",sans-serif;font-size:23px;font-weight:800;letter-spacing:-.01em}
.sec-head .n{font-family:"IBM Plex Mono",monospace;color:var(--muted);font-size:13px}
.sec-note{color:var(--muted);max-width:74ch;margin:0 0 18px;font-size:14px}

/* dt270 accordion */
.obj{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin-bottom:12px;box-shadow:var(--shadow);overflow:hidden}
.obj>summary{list-style:none;cursor:pointer;padding:15px 18px;display:grid;grid-template-columns:auto 1fr auto;gap:6px 16px;align-items:center}
.obj>summary::-webkit-details-marker{display:none}
.obj summary:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.obj .oname{font-family:"IBM Plex Mono",monospace;font-weight:600;font-size:16px;color:var(--ink)}
.obj .ofile{font-family:"IBM Plex Mono",monospace;font-size:11.5px;color:var(--muted);background:var(--panel-2);padding:2px 7px;border-radius:6px;margin-left:8px}
.obj .oblurb{grid-column:1/2;grid-row:2;color:var(--muted);font-size:13px;max-width:70ch}
.obj .ometa{grid-column:2/4;grid-row:2;justify-self:end;align-self:center}
.obj .ocount{grid-column:3;grid-row:1;justify-self:end;display:flex;align-items:center;gap:10px}
.bar{display:inline-flex;height:7px;border-radius:4px;overflow:hidden;width:120px;background:var(--panel-2);border:1px solid var(--line)}
.bar i{height:100%}
.chev{color:var(--muted);transition:transform .18s ease}
.obj[open] .chev{transform:rotate(90deg)}
.fieldwrap{overflow-x:auto;border-top:1px solid var(--line)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
thead th{position:sticky;top:0;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--muted);font-weight:600;padding:9px 14px;background:var(--panel-2);border-bottom:1px solid var(--line)}
tbody td{padding:8px 14px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--panel-2)}
td.path{font-family:"IBM Plex Mono",monospace;color:var(--ink);white-space:nowrap}
td.type{font-family:"IBM Plex Mono",monospace;color:var(--muted);font-size:12.5px}
td.val{font-family:"IBM Plex Mono",monospace;white-space:nowrap;color:var(--accent);font-weight:500}
td.val.bool-t{color:var(--live)} td.val.bool-f{color:var(--inert)}
td.note{color:var(--muted);font-size:12.5px;max-width:44ch}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;white-space:nowrap;text-transform:capitalize}
.badge.live{color:var(--live);background:var(--live-bg)}
.badge.likely{color:var(--likely);background:var(--likely-bg)}
.badge.inert{color:var(--inert);background:var(--inert-bg);text-decoration:line-through}
.badge.unverified{color:var(--unverified);background:var(--unverified-bg)}
mark{background:color-mix(in srgb,var(--accent) 40%,transparent);color:inherit;border-radius:3px;padding:0 1px}

/* exe systems */
.sys{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin-bottom:14px;box-shadow:var(--shadow);overflow:hidden}
.sys-head{padding:16px 18px 14px;border-bottom:1px solid var(--line)}
.sys-head h3{font-family:"Archivo",sans-serif;font-size:18px;font-weight:700}
.sys-head p{color:var(--muted);font-size:13px;margin:6px 0 0;max-width:82ch}
td.lname{font-weight:600;color:var(--ink);white-space:nowrap}
td.va{font-family:"IBM Plex Mono",monospace;color:var(--likely);white-space:nowrap;font-size:12.5px}
td.cur{font-family:"IBM Plex Mono",monospace;color:var(--accent);white-space:nowrap}
.pack{font-family:"IBM Plex Mono",monospace;font-size:11.5px;color:var(--muted);background:var(--panel-2);padding:2px 7px;border-radius:6px;white-space:nowrap}
.conf{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.conf.proven{color:var(--live)} .conf.likely{color:var(--likely)} .conf.guess{color:var(--unverified)}
.empty{color:var(--muted);text-align:center;padding:40px;font-size:14px}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:4px 0 26px;color:var(--muted);font-size:12.5px}
.legend span{display:inline-flex;gap:7px;align-items:center}
footer{border-top:1px solid var(--line);color:var(--muted);font-size:12.5px;padding:22px 0 40px}
footer code{font-family:"IBM Plex Mono",monospace;background:var(--panel-2);padding:1px 6px;border-radius:5px}
.riskbar{display:flex;gap:10px;align-items:flex-start;background:var(--inert-bg);border:1px solid color-mix(in srgb,var(--inert) 35%,transparent);
  border-radius:10px;padding:11px 14px;margin:2px 0 22px;font-size:13px;color:var(--ink)}
.riskbar b{color:var(--inert)}
@media (max-width:640px){
  .obj>summary{grid-template-columns:1fr auto}
  .obj .ocount{grid-column:2;grid-row:1} .obj .oblurb{grid-column:1/3} .obj .ometa{display:none}
  td.note{display:none}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
</style>

<header><div class="wrap head-inner">
  <div class="kicker">eFootball 2027 · gameplay internals</div>
  <h1>eFootball Mod Deck</h1>
  <p class="tagline">Every gameplay lever we can reach — the safe dt270 data constants and the exe hex/runtime patches — with its current value, what it does, and whether it's proven to actually change anything.</p>
  <div class="stat-row" id="stats"></div>
  <div class="applied" id="applied"></div>
</div></header>

<div class="controls"><div class="wrap controls-inner">
  <label class="search">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
    <input id="q" type="search" placeholder="Search 900+ levers — magnus, dfLine, shank, reaction, curl…" autocomplete="off">
  </label>
  <div class="seg" id="surface" role="group" aria-label="surface">
    <button data-s="all" aria-pressed="true">All</button>
    <button data-s="dt270" aria-pressed="false">dt270</button>
    <button data-s="exe" aria-pressed="false">Exe</button>
  </div>
  <div class="filters" id="filters"></div>
</div></div>

<main class="wrap">
  <div class="legend" id="legend"></div>
  <section id="sec-dt270">
    <div class="sec-head"><h2>dt270 data constants</h2><span class="n" id="dt270n"></span></div>
    <p class="sec-note">Named fields inside <span class="mono">dt270_console_all.cpk</span>. Editing these is safe and reversible — <span class="mono">gameplay_tune.py set &lt;object&gt; &lt;path&gt;=&lt;value&gt;</span> — and survives Konami patches once the schema is regenerated. Values shown are what's <em>installed right now</em>.</p>
    <div id="objects"></div>
  </section>
  <section id="sec-exe">
    <div class="sec-head"><h2>eFootball.exe levers</h2><span class="n" id="exen"></span></div>
    <div class="riskbar"><span>⚠</span><div><b>Different rules.</b> These are hex edits to the game binary (<span class="mono">exe_patch.py</span>) or runtime memory writes (<span class="mono">live_patch.py</span>). Denuvo may reject a modified exe — a crash or refuse-to-launch, never a ban (offline). A pristine backup restores it byte-for-byte; Steam "verify integrity" also reverts.</div></div>
    <div id="systems"></div>
  </section>
  <p class="empty" id="empty" hidden>No levers match that search.</p>
</main>

<footer><div class="wrap">
  Generated <span id="gen" class="mono"></span> from <code>tools/gameplay_catalog.py</code> · schema <code>tools/data/dt270_schema.json</code> · exe map <code>docs/exe-gameplay-map.md</code>. Re-run after a Konami patch. Addresses are at image base <span class="mono">0x140000000</span>.
</div></footer>

<script>
const DATA = /*DATA*/{};
const STATUS = ["live","likely","inert","unverified"];
const STATUS_LABEL = {live:"Live",likely:"Likely",inert:"Inert",unverified:"Unverified"};
const active = new Set();          // status filters (empty = all)
let surface = "all", query = "";
const $ = s => document.querySelector(s);
const el = (t,c,txt) => { const e=document.createElement(t); if(c)e.className=c; if(txt!=null)e.textContent=txt; return e; };
const esc = s => String(s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

function fmtVal(v){
  if(v===null||v===undefined) return "";
  if(typeof v==="boolean") return v?"true":"false";
  if(Array.isArray(v)) return "["+v.map(x=>typeof x==="number"?trimNum(x):x).join(", ")+"]";
  if(typeof v==="number") return trimNum(v);
  return '"'+v+'"';
}
function trimNum(x){ if(Number.isInteger(x))return String(x); return parseFloat(x.toPrecision(6))+""; }
function hl(text){ if(!query) return esc(text); const i=text.toLowerCase().indexOf(query);
  if(i<0) return esc(text); return esc(text.slice(0,i))+"<mark>"+esc(text.slice(i,i+query.length))+"</mark>"+esc(text.slice(i+query.length)); }

/* header */
function renderHead(){
  const t=DATA.totals;
  const stats=[[t.dt270_fields,"dt270 fields"],[t.dt270_objects,"gameplay objects"],[t.exe_levers,"exe levers"],
    [DATA.patch_packs.length,"patch packs"]];
  const sr=$("#stats");
  stats.forEach(([n,l])=>{ const s=el("div","stat"); s.innerHTML=`<b>${n}</b><span>${l}</span>`; sr.appendChild(s); });
  const ap=$("#applied"); ap.appendChild(el("span","lbl","Applied now"));
  const t2=DATA.tuning;
  if(t2){ const c=el("span","chip on"); c.innerHTML=`<span class="dot"></span>dt270 · ${t2.name} <span style="color:var(--muted)">(${t2.count-t2.inert} live edits)</span>`; ap.appendChild(c); }
  DATA.patch_packs.filter(p=>p.applied).forEach(p=>{ const c=el("span","chip on"); c.innerHTML=`<span class="dot"></span>exe · ${p.name.replace(".json","")} <span style="color:var(--muted)">(${p.count})</span>`; ap.appendChild(c); });
  if(!DATA.patch_packs.some(p=>p.applied) && !t2) ap.appendChild(el("span","chip","nothing applied — stock game"));
  $("#gen").textContent=DATA.generated;
}
/* filters + legend */
function renderFilters(){
  const f=$("#filters");
  STATUS.forEach(s=>{ const b=el("button","fbtn"); b.setAttribute("aria-pressed","false"); b.dataset.s=s;
    b.innerHTML=`<span class="sw ${s}"></span>${STATUS_LABEL[s]}`;
    b.onclick=()=>{ b.getAttribute("aria-pressed")==="true"?(active.delete(s),b.setAttribute("aria-pressed","false")):(active.add(s),b.setAttribute("aria-pressed","true")); apply(); };
    f.appendChild(b); });
  const lg=$("#legend");
  const defs={live:"a consumer reads it — it works",likely:"strong evidence, one link unconfirmed",inert:"no reader in this build — dead",unverified:"name-based, not yet traced in the exe"};
  STATUS.forEach(s=>{ const sp=el("span"); sp.innerHTML=`<span class="sw ${s}"></span><b style="color:var(--ink);font-weight:600">${STATUS_LABEL[s]}</b> — ${defs[s]}`; lg.appendChild(sp); });
}
/* dt270 */
function statusBar(counts){
  const total=STATUS.reduce((a,s)=>a+(counts[s]||0),0)+(counts.sub||0); if(!total) return "";
  const seg=s=>counts[s]?`<i class="sw ${s}" style="width:${100*counts[s]/total}%;background:var(--${s})"></i>`:"";
  return `<span class="bar" title="${STATUS.map(s=>counts[s]?counts[s]+" "+s:"").filter(Boolean).join(", ")}">${STATUS.map(seg).join("")}</span>`;
}
function renderObjects(){
  const box=$("#objects"); box.innerHTML="";
  DATA.objects.forEach(o=>{
    const d=el("details","obj"); d.dataset.name=o.name;
    const rows=o.fields.map(fr=>{
      const showStatus=fr.status||"";
      const cls=typeof fr.value==="boolean"?(fr.value?"val bool-t":"val bool-f"):"val";
      return `<tr data-status="${showStatus}" data-hay="${esc((o.name+" "+fr.path+" "+(fr.note||"")).toLowerCase())}">
        <td class="path">${hl(o.name+"."+fr.path)}</td>
        <td class="type">${esc(fr.type)}</td>
        <td class="${cls}">${esc(fmtVal(fr.value))}</td>
        <td>${showStatus?`<span class="badge ${showStatus}">${showStatus}</span>`:""}</td>
        <td class="note">${hl(fr.note||"")}</td></tr>`;
    }).join("");
    d.innerHTML=`<summary>
        <span class="oname">${o.name}<span class="ofile">${o.file.replace("constant_","").replace(".bin","")}</span></span>
        <span class="ocount">${statusBar(o.counts)}<span class="n mono" style="color:var(--muted);font-size:12px">${o.field_count}</span>
          <svg class="chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 18 6-6-6-6"/></svg></span>
        <span class="oblurb">${esc(o.blurb)}</span></summary>
      <div class="fieldwrap"><table><thead><tr><th>Field</th><th>Type</th><th>Value now</th><th>Status</th><th>What it does / where</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    box.appendChild(d);
  });
}
/* exe */
function renderSystems(){
  const box=$("#systems"); box.innerHTML="";
  DATA.exe_systems.forEach(s=>{
    const rows=s.levers.map(l=>`<tr data-hay="${esc((l.name+" "+l.effect+" "+l.knob+" "+l.va).toLowerCase())}">
      <td class="lname">${hl(l.name)}</td><td class="va">${esc(l.va)}</td><td class="cur">${esc(l.current)}</td>
      <td>${hl(l.effect)}<div style="color:var(--muted);font-size:12px;margin-top:2px">${esc(l.knob)}</div></td>
      <td><span class="conf ${l.confidence}">${l.confidence}</span></td>
      <td><span class="pack">${esc(l.pack)}</span></td></tr>`).join("");
    const c=el("div","sys");
    c.innerHTML=`<div class="sys-head"><h3>${esc(s.system)}</h3><p>${esc(s.blurb)}</p></div>
      <div class="fieldwrap"><table><thead><tr><th>Lever</th><th>Address</th><th>Now</th><th>Effect</th><th>Conf.</th><th>Pack</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    box.appendChild(c);
  });
}
/* filtering */
function apply(){
  const showDt=surface!=="exe", showExe=surface!=="dt270";
  let hits=0;
  document.querySelectorAll("#objects .obj").forEach(d=>{
    let vis=0;
    d.querySelectorAll("tbody tr").forEach(tr=>{
      const st=tr.dataset.status;
      const okStatus=active.size===0||active.has(st)||(active.has("unverified")&&st==="");
      const okQuery=!query||tr.dataset.hay.includes(query);
      const ok=showDt&&okStatus&&okQuery; tr.hidden=!ok; if(ok)vis++;
    });
    d.hidden=!showDt||vis===0;
    if(showDt&&vis>0){hits+=vis; if(query||active.size)d.open=true;}
  });
  document.querySelectorAll("#systems .sys").forEach(c=>{
    let vis=0;
    c.querySelectorAll("tbody tr").forEach(tr=>{
      const okStatus=active.size===0; // exe levers aren't status-tagged; show unless a dt270-only status filter is on
      const okQuery=!query||tr.dataset.hay.includes(query);
      const ok=showExe&&okStatus&&okQuery; tr.hidden=!ok; if(ok)vis++;
    });
    c.hidden=!showExe||vis===0; if(showExe&&vis>0)hits+=vis;
  });
  $("#sec-dt270").hidden=!showDt || (active.size>0 && !STATUS.some(s=>active.has(s)));
  $("#sec-exe").hidden=!showExe || active.size>0;   // status filters are dt270-only
  $("#empty").hidden=hits>0;
  $("#dt270n").textContent=DATA.totals.dt270_fields+" fields · "+DATA.totals.dt270_objects+" objects";
  $("#exen").textContent=DATA.totals.exe_levers+" levers · "+DATA.exe_systems.length+" systems";
}
/* wire up */
renderHead(); renderFilters(); renderObjects(); renderSystems();
$("#q").addEventListener("input",e=>{query=e.target.value.trim().toLowerCase();
  renderObjects();renderSystems();apply();});
$("#surface").addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;
  surface=b.dataset.s;[...e.currentTarget.children].forEach(x=>x.setAttribute("aria-pressed",x===b));apply();});
apply();
</script>
"""

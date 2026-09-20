# -*- coding: utf-8 -*-
"""HTML template for gameplay_catalog.py. PAGE has one placeholder: /*DATA*/{} (the catalogue JSON).

Seven views, subsystem-first:
  Questions   the football question a reader actually arrives with, answered in a sentence
  Subsystems  the eight chapters — machine paragraph, what each enables, negatives, open questions
  Levers      everything actually changeable, grouped by route, NOT-SAFELY-TUNABLE first
  Negatives   proven absent / proven placebo / corrected, so nobody rebuilds them
  dt270       the old field-level table, kept, now joined per field to build/dt270_liveness.json
  Exe map     the 2026-08-23 curated + swept exe levers, with superseded rows marked not deleted
  State       what is measured to be installed right now, and what the old catalogue got wrong
"""

PAGE = r"""<meta charset="utf-8">
<title>eFootball Gameplay Catalogue</title>
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
.mono,code{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
code{background:var(--panel-2);padding:1px 5px;border-radius:5px;font-size:.92em}
a{color:var(--accent);text-decoration:none}
h1,h2,h3{text-wrap:balance;margin:0}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px}

header{border-bottom:1px solid var(--line);background:linear-gradient(180deg,var(--panel),var(--ground));position:relative;overflow:hidden}
header::before{content:"";position:absolute;inset:0;background:
  repeating-linear-gradient(90deg,transparent 0 78px,color-mix(in srgb,var(--accent) 8%,transparent) 78px 79px);
  opacity:.5;pointer-events:none;-webkit-mask:linear-gradient(180deg,#000,transparent);mask:linear-gradient(180deg,#000,transparent)}
.head-inner{padding:30px 0 22px;position:relative}
.kicker{font-family:"IBM Plex Mono",monospace;font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:var(--accent);font-weight:600}
h1{font-family:"Archivo",sans-serif;font-weight:800;font-size:clamp(28px,5vw,46px);letter-spacing:-.02em;margin:.18em 0 .1em;line-height:1}
.tagline{color:var(--muted);max-width:66ch;font-size:15.5px}
.stat-row{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 13px;box-shadow:var(--shadow)}
.stat b{font-family:"Archivo",sans-serif;font-size:19px;font-weight:800;display:block;line-height:1.1}
.stat span{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.applied{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px;align-items:center}
.applied .lbl{font-size:11.5px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted)}
.chip{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border-radius:999px;font-size:12.5px;font-weight:500;border:1px solid var(--line-strong);background:var(--panel)}
.chip.on{border-color:var(--accent);background:var(--accent-soft);color:var(--ink)}
.chip.good{border-color:var(--live);background:var(--live-bg);color:var(--ink)}
.chip.warn{border-color:var(--inert);background:var(--inert-bg);color:var(--ink)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 22%,transparent)}

.controls{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--ground) 90%,transparent);
  backdrop-filter:blur(10px);border-bottom:1px solid var(--line);padding:10px 0}
.controls-inner{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.search{flex:1;min-width:200px;display:flex;align-items:center;gap:9px;background:var(--panel);
  border:1px solid var(--line-strong);border-radius:10px;padding:8px 12px}
.search:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.search input{border:0;background:transparent;color:var(--ink);font:inherit;width:100%;outline:none}
.search svg{flex:none;color:var(--muted)}
.seg{display:inline-flex;border:1px solid var(--line-strong);border-radius:10px;overflow:hidden;flex-wrap:wrap}
.seg button{border:0;background:var(--panel);color:var(--muted);font:inherit;font-size:13px;padding:8px 13px;cursor:pointer;font-weight:500}
.seg button+button{border-left:1px solid var(--line)}
.seg button[aria-pressed=true]{background:var(--accent-soft);color:var(--ink)}
.filters{display:flex;gap:6px;flex-wrap:wrap}
.fbtn{cursor:pointer;user-select:none;border:1px solid var(--line-strong);background:var(--panel);
  border-radius:999px;padding:4px 10px;font-size:12px;display:inline-flex;gap:6px;align-items:center;color:var(--muted)}
.fbtn[aria-pressed=true]{color:var(--ink);border-color:currentColor}
.fbtn .sw{width:8px;height:8px;border-radius:50%}
.sw.live,.sw.on{background:var(--live)} .sw.read,.sw.likely{background:var(--likely)}
.sw.unread,.sw.inert{background:var(--inert)} .sw.unlocated,.sw.unresolved,.sw.unknown{background:var(--unverified)}

main{padding:22px 0 90px}
.sec-head{display:flex;align-items:baseline;gap:12px;margin:26px 0 6px;flex-wrap:wrap}
.sec-head h2{font-family:"Archivo",sans-serif;font-size:22px;font-weight:800;letter-spacing:-.01em}
.sec-head .n{font-family:"IBM Plex Mono",monospace;color:var(--muted);font-size:13px}
.sec-note{color:var(--muted);max-width:86ch;margin:0 0 16px;font-size:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin-bottom:12px;box-shadow:var(--shadow);overflow:hidden}
.card-in{padding:15px 17px}
.q h3{font-family:"Archivo",sans-serif;font-size:17px;font-weight:700;margin-bottom:7px}
.q .ans{font-size:14.5px}
.q .meta{margin-top:10px;display:flex;gap:7px;flex-wrap:wrap;align-items:center}
.q .where{margin-top:9px;font-size:12.3px;color:var(--muted);border-left:2px solid var(--line-strong);padding-left:10px}
.q .where b{color:var(--ink);font-weight:600}
.q .lever{margin-top:8px;font-size:13.3px;background:var(--panel-2);border-radius:8px;padding:8px 11px}
.q .lever b{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);display:block}
a.tag.doclink{text-decoration:underline;text-decoration-style:dotted;text-underline-offset:2px}
.tag{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:600;white-space:nowrap;
  border:1px solid var(--line-strong);color:var(--muted);background:var(--panel-2)}
.tag.r-dt270-data,.tag.r-player-data{color:var(--live);background:var(--live-bg);border-color:transparent}
.tag.r-exe-constant,.tag.r-motion-asset,.tag.r-runtime-data{color:var(--likely);background:var(--likely-bg);border-color:transparent}
.tag.r-exe-code{color:var(--accent);background:var(--accent-soft);border-color:transparent}
.tag.r-NOT-SAFELY-TUNABLE,.tag.r-withdrawn{color:var(--inert);background:var(--inert-bg);border-color:transparent}
.tag.r-not-reachable,.tag.r-none,.tag.r-unclassified{color:var(--unverified);background:var(--unverified-bg);border-color:transparent}
.tag.e-a-emulated{color:var(--live)} .tag.e-b-disassembly{color:var(--likely)}
.tag.e-c-inferred{color:var(--inert)} .tag.e-unstated{color:var(--unverified)}
/* The 2026-08-23 sweep gets its OWN evidence words. Its "proven" was hand-typed a year before
   the chapters existed; mapping it onto the chapters' a/b/c put pre-chapter guesswork and
   chapter-verified disassembly in the same visual class. */
.tag.e-sweep-proven,.tag.e-sweep-likely,.tag.e-sweep-guess,.tag.e-sweep-unstated{
  color:var(--muted);background:var(--panel-2);border-style:dashed}
.tag.e-superseded{color:var(--inert);background:var(--inert-bg);border-color:transparent}
.tag.sup{color:var(--inert);background:var(--inert-bg);border-color:transparent}
.supnote{color:var(--inert);font-size:12.2px;margin-top:3px;max-width:60ch}

.fieldwrap{overflow-x:auto;border-top:1px solid var(--line)}
table{border-collapse:collapse;width:100%;font-size:13.4px}
thead th{position:sticky;top:0;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--muted);font-weight:600;padding:9px 13px;background:var(--panel-2);border-bottom:1px solid var(--line)}
tbody td{padding:8px 13px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--panel-2)}
td.path{font-family:"IBM Plex Mono",monospace;color:var(--ink);white-space:nowrap}
td.type{font-family:"IBM Plex Mono",monospace;color:var(--muted);font-size:12.3px}
td.val{font-family:"IBM Plex Mono",monospace;white-space:nowrap;color:var(--accent);font-weight:500}
td.val.bool-t{color:var(--live)} td.val.bool-f{color:var(--inert)}
td.note{color:var(--muted);font-size:12.4px;max-width:46ch}
td.note .clamp{display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
td.note details[open] .clamp{-webkit-line-clamp:unset;display:block}
td.site{font-size:12.4px;max-width:34ch}
td.what{max-width:38ch}
td.eff{max-width:60ch;font-size:13px}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;white-space:nowrap}
.badge.live{color:var(--live);background:var(--live-bg)}
.badge.read{color:var(--likely);background:var(--likely-bg)}
.badge.inert{color:var(--inert);background:var(--inert-bg)}
.badge.unread{color:var(--inert);background:var(--inert-bg);opacity:.85}
.badge.unlocated,.badge.unknown{color:var(--unverified);background:var(--unverified-bg)}
.badge.unresolved{color:var(--unverified);background:var(--unverified-bg);text-decoration:underline dotted}
mark{background:color-mix(in srgb,var(--accent) 40%,transparent);color:inherit;border-radius:3px;padding:0 1px}

details.obj>summary,details.sys>summary{list-style:none;cursor:pointer;padding:14px 17px;display:grid;
  grid-template-columns:auto 1fr auto;gap:5px 14px;align-items:center}
details>summary::-webkit-details-marker{display:none}
.oname{font-family:"IBM Plex Mono",monospace;font-weight:600;font-size:15.5px;color:var(--ink)}
.ofile{font-family:"IBM Plex Mono",monospace;font-size:11.5px;color:var(--muted);background:var(--panel-2);padding:2px 7px;border-radius:6px;margin-left:8px}
.oblurb{grid-column:1/3;grid-row:2;color:var(--muted);font-size:13px;max-width:78ch}
.ocount{grid-column:3;grid-row:1;justify-self:end;display:flex;align-items:center;gap:10px}
.bar{display:inline-flex;height:7px;border-radius:4px;overflow:hidden;width:120px;background:var(--panel-2);border:1px solid var(--line)}
.bar i{height:100%}
.chev{color:var(--muted);transition:transform .18s ease}
details[open] .chev{transform:rotate(90deg)}
.sys-head{padding:15px 17px 13px;border-bottom:1px solid var(--line)}
.sys-head h3{font-family:"Archivo",sans-serif;font-size:17px;font-weight:700}
.sys-head p{color:var(--muted);font-size:13px;margin:6px 0 0;max-width:92ch}
.para{font-size:14.3px;line-height:1.62;max-width:100ch}
.subhead{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.subhead h3{font-family:"Archivo",sans-serif;font-size:19px;font-weight:800}
.bullets{margin:8px 0 0;padding-left:20px}
.bullets li{margin:6px 0;font-size:13.6px}
.bullets li::marker{color:var(--muted)}
.empty{color:var(--muted);text-align:center;padding:40px;font-size:14px}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:2px 0 20px;color:var(--muted);font-size:12.4px}
.legend span{display:inline-flex;gap:7px;align-items:center}
.routebox{border-left:3px solid var(--line-strong);padding:2px 0 2px 12px;margin:0 0 12px;color:var(--muted);font-size:13px;max-width:92ch}
footer{border-top:1px solid var(--line);color:var(--muted);font-size:12.4px;padding:20px 0 40px}
.riskbar{display:flex;gap:10px;align-items:flex-start;background:var(--inert-bg);border:1px solid color-mix(in srgb,var(--inert) 35%,transparent);
  border-radius:10px;padding:11px 14px;margin:2px 0 18px;font-size:13px;color:var(--ink)}
.riskbar b{color:var(--inert)}
.okbar{display:flex;gap:10px;align-items:flex-start;background:var(--live-bg);border:1px solid color-mix(in srgb,var(--live) 35%,transparent);
  border-radius:10px;padding:11px 14px;margin:2px 0 18px;font-size:13px;color:var(--ink)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px}
@media (max-width:640px){
  details.obj>summary{grid-template-columns:1fr auto}
  .ocount{grid-column:2;grid-row:1} .oblurb{grid-column:1/3}
  td.note{display:none}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
</style>

<header><div class="wrap head-inner">
  <div class="kicker">eFootball 2027 · gameplay internals · subsystem-first</div>
  <h1>Gameplay Catalogue</h1>
  <p class="tagline">Eight decoded subsystems, re-keyed onto the football question you actually arrived with. Every row says where it was proved, how strongly, and whether there is anything you can change — including the things that look like levers and are not.</p>
  <div class="stat-row" id="stats"></div>
  <div class="applied" id="applied"></div>
</div></header>

<div class="controls"><div class="wrap controls-inner">
  <label class="search">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
    <input id="q" type="search" placeholder="Search this view — standoff, penalty, cancel frame, passget, Reflexes, dfLine… (the tabs show hits in the others)" autocomplete="off">
  </label>
  <div class="seg" id="tabs" role="group" aria-label="view">
    <button data-v="questions" aria-pressed="true">Questions</button>
    <button data-v="subsystems" aria-pressed="false">Subsystems</button>
    <button data-v="levers" aria-pressed="false">Levers</button>
    <button data-v="negatives" aria-pressed="false">Negatives</button>
    <button data-v="dt270" aria-pressed="false">dt270 fields</button>
    <button data-v="exemap" aria-pressed="false">Exe map</button>
    <button data-v="state" aria-pressed="false">State</button>
  </div>
  <div class="filters" id="filters"></div>
</div></div>

<main class="wrap">
  <section id="v-questions" hidden></section>
  <section id="v-subsystems" hidden></section>
  <section id="v-levers" hidden></section>
  <section id="v-negatives" hidden></section>
  <section id="v-dt270" hidden></section>
  <section id="v-exemap" hidden></section>
  <section id="v-state" hidden></section>
  <p class="empty" id="empty" hidden>Nothing in this view matches that search.</p>
</main>

<footer><div class="wrap">
  Generated <span id="gen" class="mono"></span> by <code>tools/gameplay_catalog.py</code> from the eight chapters in <code>docs/</code>,
  <code>build/dt270_liveness.json</code> (<span id="lvgen" class="mono"></span>), the installed dt270 CPK and a byte-compare of the installed exe.
  Addresses are at image base <span class="mono">0x140000000</span>. Re-run after a Konami patch — <code>dt270_schema_gen.py</code> and <code>exe_map.py</code> first.
  <div style="margin-top:6px">Chapter links point at raw Markdown in <code>docs/</code>: opened from <span class="mono">file://</span> a browser will offer to download or show plain text rather than render it. Each row also prints its chapter and section as text, so <code>grep</code> on the named file is the quickest check.</div>
</div></footer>

<script>
const DATA = /*DATA*/{};
let view = "questions", query = "", routeFilter = new Set(), statusFilter = new Set(), negKind = "", originFilter = "", subFilter = new Set(), qSubFilter = new Set();
const $ = s => document.querySelector(s);
const el = (t,c,txt) => { const e=document.createElement(t); if(c)e.className=c; if(txt!=null)e.textContent=txt; return e; };
const esc = s => String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const SUBT = {}; (DATA.chapters||[]).forEach(c=>SUBT[c.id]=c);
const TAB_LABEL = {questions:"Questions",subsystems:"Subsystems",levers:"Levers",negatives:"Negatives",
                   dt270:"dt270 fields",exemap:"Exe map",state:"State"};
const ROUTE_LABEL = DATA.route_label||{}, ROUTE_NOTE = DATA.route_note||{}, ROUTE_ORDER = DATA.route_order||[];

function trimNum(x){ if(Number.isInteger(x))return String(x); return parseFloat(x.toPrecision(6))+""; }
function fmtVal(v){
  if(v===null||v===undefined) return "";
  if(typeof v==="boolean") return v?"true":"false";
  if(Array.isArray(v)) return "["+v.map(x=>typeof x==="number"?trimNum(x):x).join(", ")+"]";
  if(typeof v==="number") return trimNum(v);
  return '"'+v+'"';
}
function hl(text){ const t=String(text==null?"":text); if(!query) return esc(t);
  const i=t.toLowerCase().indexOf(query); if(i<0) return esc(t);
  return esc(t.slice(0,i))+"<mark>"+esc(t.slice(i,i+query.length))+"</mark>"+esc(t.slice(i+query.length)); }
function routeTag(r){ return `<span class="tag r-${esc(r)}">${esc(ROUTE_LABEL[r]||r)}</span>`; }
function evTag(e){ return `<span class="tag e-${esc(e)}">${esc(e)}</span>`; }
/* A pack's description IS the payload of the State view — which pack to try tonight, why, and
   how to get out of it. It used to be clamped to four lines with no way to open it: the CSS rule
   that unclamps expects a <details> wrapper that nothing emitted. */
function noteCell(text){
  const t=String(text==null?"":text);
  if(t.length<220) return `<div>${hl(t)}</div>`;
  return `<details><summary style="cursor:pointer">${hl(t.slice(0,110))}… <span class="mono" style="font-size:11px;color:var(--muted)">[${t.length.toLocaleString()} chars — click]</span></summary>
    <div class="clamp">${hl(t)}</div></details>`;
}
function docLink(doc, section){
  if(!doc) return "";
  const label=esc(doc)+(section?" § "+esc(section):"");
  // This page is emitted into build/; the chapters sit beside it in docs/.
  if(String(doc).startsWith("docs/"))
    return `<a class="tag doclink" href="../${esc(doc)}" title="open the chapter">${label}</a>`;
  return `<span class="tag">${label}</span>`;
}

/* ---------------------------------------------------------------- header */
function renderHead(){
  const t=DATA.totals, s=DATA.image_state;
  [[t.questions,"questions"],[t.subsystems,"subsystems"],[t.levers,"levers"],
   [t.negatives+t.corrections,"negatives & corrections"],[t.dt270_fields,"dt270 fields"],
   [t.opens,"open questions"]]
   .forEach(([n,l])=>{ const d=el("div","stat"); d.innerHTML=`<b>${n}</b><span>${esc(l)}</span>`; $("#stats").appendChild(d); });

  const ap=$("#applied"); ap.appendChild(el("span","lbl","Measured right now"));
  const exeChip=el("span","chip "+(s.installed_is_pristine?"good":"warn"));
  exeChip.innerHTML = s.installed_is_pristine
    ? `<span class="dot" style="background:var(--live);box-shadow:none"></span>exe · PRISTINE — no patch is applied`
    : `<span class="dot"></span>exe · MODIFIED (sha1 ${esc(String(s.installed_sha1).slice(0,12))}…)`;
  ap.appendChild(exeChip);
  if(s.pristine_vs_stock){
    const c=el("span","chip");
    c.innerHTML=`PRISTINE ≠ STOCK by ${s.pristine_vs_stock.n} byte${s.pristine_vs_stock.n===1?"":"s"} (a hostname, not gameplay)`;
    ap.appendChild(c);
  }
  const on=(DATA.patch_packs||[]).filter(p=>p.verdict==="on"&&!p.noop_on_stock);
  const revert=(DATA.patch_packs||[]).filter(p=>p.verdict==="on"&&p.noop_on_stock);
  on.forEach(p=>{const c=el("span","chip on");c.innerHTML=`<span class="dot"></span>exe · ${esc(p.name.replace(".json",""))}`;ap.appendChild(c);});
  if(revert.length){const c=el("span","chip");c.innerHTML=`${revert.length} revert-shaped pack${revert.length===1?"":"s"} read “applied” on a stock exe — no-ops`;ap.appendChild(c);}
  // The dt270 pack is a SEPARATE install state from the exe, and "the exe is pristine" says
  // nothing about it. That belongs on the first screen, next to the exe chip, not three
  // scrolls down in the State view.
  const dchip=el("span","chip "+(s.dt270_is_pristine?"good":"warn"));
  dchip.innerHTML = s.dt270_is_pristine
    ? `<span class="dot" style="background:var(--live);box-shadow:none"></span>dt270 pack · pristine`
    : `<span class="dot"></span>dt270 pack · NOT pristine (sha1 ${esc(String(s.dt270_installed_sha1).slice(0,12))}…)`;
  ap.appendChild(dchip);
  const tun=(DATA.tunings||[]).filter(x=>x.verdict==="on");
  const part=(DATA.tunings||[]).filter(x=>x.verdict==="partial");
  const indet=(DATA.tunings||[]).filter(x=>x.verdict==="indeterminate");
  tun.forEach(x=>{const c=el("span","chip on");
    c.innerHTML=`<span class="dot"></span>dt270 · ${esc(x.name)} (${x.match}/${x.count} — a tuning that restores stock values reads “on” for that reason alone)`;
    ap.appendChild(c);});
  if(!tun.length){
    const best=part.slice().sort((a,b)=>b.match-a.match)[0];
    const c=el("span","chip "+(best?"on":""));
    c.innerHTML = best ? `<span class="dot"></span>dt270 · pack is EDITED — closest tuning ${esc(best.name)} (${best.match}/${best.count} fields match)`
                       : `dt270 · no tuning matches the installed pack`;
    ap.appendChild(c);
  }
  if(indet.length){
    const c=el("span","chip");
    c.innerHTML=`${indet.length} tuning${indet.length===1?"":"s"} INDETERMINATE — most of their edits could not be read back`;
    ap.appendChild(c);
  }
  const jr=(DATA.patch_journal||[]).length;
  if(jr && !on.length){
    const c=el("span","chip warn");
    c.innerHTML=`journal claims ${jr} applied — the bytes disagree, trust the bytes`;
    ap.appendChild(c);
  }
  $("#gen").textContent=DATA.generated;
  $("#lvgen").textContent=DATA.liveness_generated;
}

/* ---------------------------------------------------------------- questions */
function renderQuestions(){
  const box=$("#v-questions"); box.innerHTML="";
  const h=el("div","sec-head"); h.innerHTML=`<h2>Start with the question</h2><span class="n">${DATA.questions.length} answered · re-keyed from the eight chapters</span>`;
  box.appendChild(h);
  box.insertAdjacentHTML("beforeend",`<p class="sec-note">Each answer is one paragraph and keeps the chapter's own hedging. <b>Where a chapter says NOT PROVEN, so does the row.</b> <span class="mono">where</span> gives the section and the addresses it was proved from, so any row can be checked back in about a minute. <span class="mono">lever</span> is what you could actually change, or the literal word NONE.</p>`);
  DATA.questions.forEach(q=>{
    const c=el("article","card q"); c.dataset.hay=q.hay; c.dataset.route=q.route; c.dataset.sub=q.subsystem||"";
    const ch=(q.chapters||[]).map(id=>SUBT[id]?docLink(SUBT[id].doc,""):"").join(" ");
    c.innerHTML=`<div class="card-in">
      <h3>${hl(q.q)}</h3>
      <div class="ans">${hl(q.answer)}</div>
      <div class="lever"><b>Lever</b>${hl(q.lever)}</div>
      <div class="where"><b>Where:</b> ${hl(q.where)}${q.section?` · <i>§ ${esc(q.section)}</i>`:""}</div>
      <div class="meta">${routeTag(q.route)}${evTag(q.evidence)}<span class="tag">${esc(q.subsystem)}</span>${ch}</div>
    </div>`;
    box.appendChild(c);
  });
}

/* ---------------------------------------------------------------- subsystems */
function renderSubsystems(){
  const box=$("#v-subsystems"); box.innerHTML="";
  const h=el("div","sec-head"); h.innerHTML=`<h2>The eight subsystems</h2><span class="n">${DATA.chapters.length} chapters, all through adversarial review</span>`;
  box.appendChild(h);
  box.insertAdjacentHTML("beforeend",`<p class="sec-note">Each chapter's own “machine in one paragraph”, its “What this enables” table, and — collapsed — everything it proved <i>absent</i>, everything it <i>corrected</i>, and what it left <i>open</i>. Text is lifted verbatim; nothing here is re-worded.</p>`);
  DATA.chapters.forEach(c=>{
    const card=el("article","card"); card.dataset.hay=(c.title+" "+c.role+" "+c.paragraph).toLowerCase(); card.dataset.sub=c.id;
    const enables=c.enables.map(e=>`<tr data-hay="${esc(e.hay)}">
        <td class="what">${e.want}${e.superseded?`<div class="tag sup" style="margin-top:5px">${esc(e.superseded)}</div><div class="supnote">${esc(e.superseded_note||"")}</div>`:""}</td>
        <td class="eff"><div${e.superseded?` style="opacity:.55"`:""}>${e.where}</div></td>
        <td>${(e.routes||[e.route]).map(routeTag).join(" ")}<div style="margin-top:4px;color:var(--muted);font-size:12.2px">${e.route_text}</div></td>
        <td>${evTag(e.evidence)}<div style="margin-top:4px;color:var(--muted);font-size:12.2px">${e.state}</div></td></tr>`).join("");
    const list=(items,cls)=>items.length?`<ul class="bullets">${items.map(i=>`<li data-hay="${esc(i.hay)}">${i.text}</li>`).join("")}</ul>`:`<p class="sec-note">none recorded</p>`;
    const sweepN=(DATA.levers||[]).filter(l=>l.subsystem===c.id&&l.origin==="exe-map").length;
    // "0 levers" reads as "nothing here is changeable". It means the chapter has no Tunables
    // section at all — say that, and say where this subsystem's rows actually come from.
    const leverChip = c.counts.tunables
      ? `<span class="tag">${c.counts.tunables} levers</span>`
      : `<span class="tag">no Tunables table in this chapter${sweepN?` — ${sweepN} rows from the pre-chapter sweep`:""}</span>`;
    card.innerHTML=`<div class="card-in">
      <div class="subhead"><h3>${esc(c.title)}</h3>${docLink(c.doc,"")}<span class="tag">${esc(c.date)}</span>
        ${leverChip}<span class="tag">${c.counts.negatives} negatives</span><span class="tag">${c.counts.opens} open</span></div>
      <p class="sec-note" style="margin:8px 0 12px">${esc(c.role)}</p>
      <h4 style="margin:0 0 6px;font-size:12px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)">
        ${esc(c.paragraph_section||"The machine in one paragraph")}${c.paragraph_is_fallback?" (this chapter has no “one paragraph” section — its architecture section opens here)":""}</h4>
      <p class="para">${c.paragraph}</p>
    </div>
    <div class="fieldwrap"><table><thead><tr><th>What you want</th><th>Where it lives</th><th>Route</th><th>Evidence</th></tr></thead>
      <tbody>${enables}</tbody></table></div>
    <div class="card-in" style="border-top:1px solid var(--line)">
      <details><summary class="mono" style="cursor:pointer;color:var(--muted);font-size:12.5px">${c.counts.negatives} proven absent / refuted — ${esc(c.negatives_section||"")}</summary>${list(c.negatives)}</details>
      <details><summary class="mono" style="cursor:pointer;color:var(--muted);font-size:12.5px;margin-top:8px">${c.counts.corrections} corrections — ${esc(c.corrections_section||"")}</summary>${list(c.corrections)}</details>
      <details><summary class="mono" style="cursor:pointer;color:var(--muted);font-size:12.5px;margin-top:8px">${c.counts.opens} open questions — ${esc(c.opens_section||"")}</summary>${list(c.opens)}</details>
    </div>`;
    box.appendChild(card);
  });
}

/* ---------------------------------------------------------------- levers */
function renderLevers(){
  const box=$("#v-levers"); box.innerHTML="";
  const nSup=DATA.levers.filter(l=>l.superseded).length;
  const h=el("div","sec-head"); h.innerHTML=`<h2>Every lever the map names</h2><span class="n">${DATA.levers.length} rows · ${DATA.totals.chapter_levers} lifted verbatim from chapter Tunables tables · ${DATA.totals.exe_levers} from the 2026-08-23 sweep</span>`;
  box.appendChild(h);
  const noLever=["NOT-SAFELY-TUNABLE","withdrawn","not-reachable","none"]
    .map(r=>[r,DATA.levers.filter(l=>l.route===r).length]).filter(x=>x[1]);
  const noLeverN=noLever.reduce((a,x)=>a+x[1],0);
  box.insertAdjacentHTML("beforeend",`<p class="sec-note">Not all of these are changeable, and the list does not pretend otherwise: the first ${noLever.length} card${noLever.length===1?"":"s"} — ${noLever.map(([r,n])=>`<b>${esc(ROUTE_LABEL[r]||r)}</b> (${n})`).join(", ")}, ${noLeverN} rows in all — are the ones that <b>look</b> like levers and are not. ${nSup} row${nSup===1?" carries":"s carry"} a <span class="tag sup">superseded</span> badge, computed from the chapters' own corrections and retirement tables rather than from a hand list.</p>`);
  box.insertAdjacentHTML("beforeend",`<div class="riskbar"><span>⚠</span><div><b>Read the route before the row.</b> “Re-aim” means repoint an instruction's <span class="mono">disp32</span> at a private cell — <b>never write a shared pool cell in place</b>, whatever its sharer count. Exe writes land on three different page types with three different risk levels; a <span class="mono">.xcode</span> write is an experiment, not a setting. The dt270 and player-data routes need no memory write at all. Where a chapter offers <i>two</i> routes, the row carries both badges and is filed under the cheaper one.</div></div>`);
  const order=ROUTE_ORDER.slice();
  order.forEach(r=>{
    const rows=DATA.levers.filter(l=>l.route===r);
    if(!rows.length) return;
    const card=el("section","card"); card.dataset.route=r;
    const body=rows.map(l=>{
      const alts=(l.routes||[]).filter(x=>x!==r).map(routeTag).join(" ");
      return `<tr data-hay="${esc(l.hay)}" data-origin="${esc(l.origin)}" data-sub="${esc(l.subsystem||"")}">
      <td class="what">${l.what}
        ${l.superseded?`<div class="tag sup" style="margin-top:5px">${esc(l.superseded)}</div><div class="supnote">${esc(l.superseded_note||"")} <i>${esc(l.superseded_source||"")}</i></div>`
                      :(l.withdrawn?`<div class="tag sup" style="margin-top:5px">the chapter hedges this row — read the effect</div>`:"")}
        ${alts?`<div style="margin-top:5px">also: ${alts}</div>`:""}</td>
      <td class="site mono">${l.site}</td>
      <td class="eff">${l.superseded_note?`<div class="supnote" style="margin-bottom:6px"><b>SUPERSEDED — read this first:</b> ${esc(l.superseded_note)}</div>`:""}<div${l.superseded?` style="opacity:.55"`:""}>${l.effect}</div></td>
      <td>${evTag(l.evidence)}<div style="color:var(--muted);font-size:12.2px;margin-top:4px">${l.evidence_text||""}</div></td>
      <td class="mono" style="font-size:12.2px">${l.sharers||"—"}</td>
      <td>${l.subsystem?`<span class="tag">${esc(l.subsystem)}</span> `:""}${docLink(l.doc,l.section)}${l.origin==="exe-map"?`<div class="tag" style="margin-top:4px">pre-chapter sweep</div>`:""}</td></tr>`;}).join("");
    card.innerHTML=`<div class="sys-head"><h3>${esc(ROUTE_LABEL[r]||r)} <span class="n mono" style="color:var(--muted);font-size:12.5px">${rows.length}</span></h3>
      <p>${esc(ROUTE_NOTE[r]||"")}</p></div>
      <div class="fieldwrap"><table><thead><tr><th>What</th><th>Site</th><th>Effect</th><th>Evidence</th><th>Sharers</th><th>Subsystem / source</th></tr></thead><tbody>${body}</tbody></table></div>`;
    box.appendChild(card);
  });
}

/* ---------------------------------------------------------------- negatives */
function renderNegatives(){
  const box=$("#v-negatives"); box.innerHTML="";
  const h=el("div","sec-head"); h.innerHTML=`<h2>Proven absent, proven placebo, and corrected</h2><span class="n">${DATA.totals.negatives} negatives · ${DATA.totals.corrections} corrections</span>`;
  box.appendChild(h);
  box.insertAdjacentHTML("beforeend",`<p class="sec-note">This view is worth as much as the levers list. Everything here was built, looked reasonable and was killed by verification, or was believed by this project and is wrong. The 2026-08-23 catalogue had no equivalent, which is how the same wrong lever got tuned twice.</p>`);
  DATA.chapters.forEach(c=>{
    const items=DATA.negatives.filter(n=>n.subsystem===c.id);
    if(!items.length) return;
    const card=el("section","card"); card.dataset.sub=c.id;
    const li=items.map(n=>`<li data-hay="${esc(n.hay)}" data-kind="${esc(n.kind)}"><span class="tag">${n.kind==="negative"?"absent / refuted":"correction"}</span> ${n.text}</li>`).join("");
    card.innerHTML=`<div class="sys-head"><h3>${esc(c.title)}</h3><p>${docLink(c.doc,"")} — ${esc(c.negatives_section||"")} · ${esc(c.corrections_section||"")}</p></div>
      <div class="card-in"><ul class="bullets">${li}</ul></div>`;
    box.appendChild(card);
  });
}

/* ---------------------------------------------------------------- dt270 */
const DT_STATUS=["live","read","inert","unread","unlocated","unresolved"];
function statusBar(counts){
  const total=Object.values(counts).reduce((a,b)=>a+b,0); if(!total) return "";
  const col={live:"var(--live)",read:"var(--likely)",inert:"var(--inert)",unread:"var(--inert)",
             unlocated:"var(--unverified)",unresolved:"var(--unverified)",sub:"var(--line-strong)"};
  return `<span class="bar" title="${esc(Object.entries(counts).map(([k,v])=>v+" "+k).join(", "))}">`+
    Object.entries(counts).map(([k,v])=>`<i style="width:${100*v/total}%;background:${col[k]||"var(--line)"}"></i>`).join("")+`</span>`;
}
function renderObjects(){
  const box=$("#v-dt270"); box.innerHTML="";
  const h=el("div","sec-head"); h.innerHTML=`<h2>dt270 data constants</h2><span class="n">${DATA.totals.dt270_fields} fields · ${DATA.totals.dt270_objects} objects</span>`;
  box.appendChild(h);
  box.insertAdjacentHTML("beforeend",`<p class="sec-note">The old field-level view, kept — but every field is now joined <b>per field</b> to <code>build/dt270_liveness.json</code> instead of eighteen hand-typed prefix rules, and values are re-read from the <b>installed</b> CPK at build time. The distinction that matters: <b>read ≠ effective</b>. A field with a proven reader can still do nothing — see the <span class="badge inert">inert</span> rows. Edit by name: <span class="mono">gameplay_tune.py set &lt;object&gt; &lt;path&gt;=&lt;value&gt;</span>.</p>`);
  const defs={live:"a chapter proved the effect, not just the read",read:"a reader is proven; the EFFECT is not",
    inert:"provably does nothing — a chapter either traced the read and showed the value is discarded, or checked and found no reader at all",unread:"no reader found (trust bounded by the object's unread-confidence)",
    unlocated:"no get() site found at all — NOT evidence of anything",unresolved:"the object's fetch site is unsound; treat as not tunable"};
  const lg=el("div","legend");
  DT_STATUS.forEach(s=>{const sp=el("span");sp.innerHTML=`<span class="badge ${s}">${s}</span> ${esc(defs[s])}`;lg.appendChild(sp);});
  box.appendChild(lg);
  // The attribute id table is the Rosetta stone for a large share of the levers (attr(0x17),
  // "attribute id 0x16") and for four of the thirty corrections. It lived only in a JSON file.
  const at=DATA.attributes||{rows:[]};
  if(at.rows && at.rows.length){
    const arows=at.rows.map(a=>`<tr data-hay="${esc(a.hay)}" data-status="">
      <td class="path">${hl(a.id)}</td><td class="type">${esc(a.data_parameter||"—")}</td>
      <td class="val" style="white-space:normal">${hl(a.ui_name||"—")}${a.named?"":` <span class="tag">guess</span>`}</td>
      <td><span class="badge ${a.confidence==="proven"?"live":a.confidence==="inferred"?"unknown":"unlocated"}">${esc(a.confidence)}</span></td>
      <td class="note">range ${a.lo}–${a.hi}${a.levelup!=null&&a.levelup!==a.hi?` · level-up ceiling ${a.levelup}`:""}</td></tr>`).join("");
    const d=el("details","card obj"); d.dataset.name="attribute ids";
    d.innerHTML=`<summary>
        <span class="oname">attribute ids<span class="ofile">player data</span></span>
        <span class="ocount"><span class="mono" style="color:var(--muted);font-size:12px">${at.rows.length}</span>
          <svg class="chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 18 6-6-6-6"/></svg></span>
        <span class="oblurb">Not a dt270 object — the match-side attribute index that rows across this catalogue are written in (<span class="mono">attr(0x17)</span>, <span class="mono">cmp eax,0x55</span>). Four of the recorded corrections turn on it. <b>Re-settled 2026-09-20 from the game's own {matchAbilityIdx, compactIdx} pair table at 0x14825CAA0 (consumer 0x1454406a0): 0x17 is <b>Defensive Engagement</b> — not Dribbling (0x18) and not Defensive Awareness (0x15).</b> The old "DATA_PARAMETER + 7" rule was never derived and is refuted at 0x36. 0x16 is GK Awareness, not Speed; 0x2a is Balance, not Acceleration. <span class="mono">${esc(at.rule||"")}</span></span></summary>
      <div class="fieldwrap"><table><thead><tr><th>id</th><th>DATA_PARAMETER</th><th>UI name</th><th>Confidence</th><th>Range</th></tr></thead><tbody>${arows}</tbody></table></div>`;
    box.appendChild(d);
  }
  DATA.objects.forEach(o=>{
    const d=el("details","card obj"); d.dataset.name=o.name;
    const rows=o.fields.map(f=>{
      const cls=typeof f.value==="boolean"?(f.value?"val bool-t":"val bool-f"):"val";
      return `<tr data-status="${esc(f.status)}" data-hay="${esc((o.name+" "+f.path+" "+(f.note||"")).toLowerCase())}">
        <td class="path">${hl(o.name+"."+f.path)}</td>
        <td class="type">${esc(f.type)}</td>
        <td class="${cls}">${esc(fmtVal(f.value))}</td>
        <td>${f.status?`<span class="badge ${esc(f.status)}">${esc(f.status)}</span>`:""}</td>
        <td class="note">${hl(f.note||"")}${(f.readers&&f.readers.length)?`<div class="mono" style="margin-top:3px">${esc(f.readers.join(" "))}${f.n_readers>f.readers.length?" …":""}</div>`:""}${f.source?`<div style="margin-top:3px">${esc(f.source)}</div>`:""}</td></tr>`;
    }).join("");
    const lv=o.liveness||{};
    d.innerHTML=`<summary>
        <span class="oname">${esc(o.name)}<span class="ofile">${esc(String(o.file).replace("constant_","").replace(".bin",""))}</span></span>
        <span class="ocount">${statusBar(o.counts)}<span class="mono" style="color:var(--muted);font-size:12px">${o.field_count}</span>
          <svg class="chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 18 6-6-6-6"/></svg></span>
        <span class="oblurb">${esc(o.blurb)}${lv.idx!=null?` <span class="mono" style="color:var(--muted)">· idx ${lv.idx}${lv.get_sites!=null?" · "+lv.get_sites+" get() sites":""}${lv.unread_confidence?" · unread-confidence "+esc(lv.unread_confidence):""}</span>`:""}</span></summary>
      ${o.orphan?`<div class="card-in"><div class="riskbar"><span>?</span><div><b>No chapter owns this object.</b> ${esc(o.orphan_note)}</div></div></div>`:""}
      <div class="fieldwrap"><table><thead><tr><th>Field</th><th>Type</th><th>Value installed</th><th>Status</th><th>What is known / readers</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    box.appendChild(d);
  });
}

/* ---------------------------------------------------------------- exe map */
function renderSystems(){
  const box=$("#v-exemap"); box.innerHTML="";
  const h=el("div","sec-head"); h.innerHTML=`<h2>Exe levers — the 2026-08-23 map, re-checked</h2><span class="n">${DATA.totals.exe_levers} levers · ${DATA.exe_systems.length} systems</span>`;
  box.appendChild(h);
  const nSup=(DATA.levers||[]).filter(l=>l.origin==="exe-map"&&l.superseded).length;
  box.insertAdjacentHTML("beforeend",`<div class="riskbar"><span>⚠</span><div><b>Kept, not trusted wholesale.</b> This is the pre-chapter sweep, and its confidence words are its own: a row badged <span class="tag e-sweep-proven">sweep-proven</span> was hand-typed “proven” on 2026-08-23, which is <i>not</i> the chapters' <span class="tag e-b-disassembly">b-disassembly</span>. ${nSup} row${nSup===1?" is":"s are"} marked <span class="tag sup">superseded</span> in place rather than deleted — and that marking is now <b>computed</b>: any row naming a dt270 field the chapters proved inert or unresolved, or naming a subject or address in the “what the 2026-08-23 catalogue got wrong” table, inherits the correction automatically. Four areas were also re-checked address by address (Physical &amp; locomotion, Goalkeeper, Attribute model, Tackling/fouls); the rest were checked by lever name only.
    <div style="margin-top:6px"><b>The value column is not a live reading</b>, which is why it is headed <i>Sweep 2026-08-23</i> and not <i>Now</i>. Those values are hard-coded in <span class="mono">build/exe_full_map.json</span>; only the 44×10 difficulty table and the dt270 pack are re-measured from the image at build time.</div></div></div>`);
  DATA.exe_systems.forEach(s=>{
    const rows=s.levers.map(l=>`<tr data-hay="${esc((l.name+" "+l.effect+" "+l.knob+" "+l.va).toLowerCase())}">
      <td class="what">${hl(l.name)}${l.superseded?`<div class="tag sup" style="margin-top:5px">${esc(l.superseded)}</div>`:""}</td>
      <td class="site mono">${esc(l.va)}</td><td class="mono" style="color:var(--accent)">${esc(l.current)}</td>
      <td class="eff">${l.superseded_note?`<div class="supnote" style="margin-bottom:6px"><b>SUPERSEDED — read this first:</b> ${esc(l.superseded_note)} <i>${esc(l.superseded_source||"")}</i></div>`:""}
        <div${l.superseded?` style="opacity:.55"`:""}>${hl(l.effect)}<div style="color:var(--muted);font-size:12.2px;margin-top:2px">${esc(l.knob)}</div></div></td>
      <td>${routeTag(l.route||"unclassified")}</td>
      <td>${evTag(l.evidence||"sweep-unstated")}</td>
      <td><span class="tag mono">${esc(l.pack)}</span></td></tr>`).join("");
    const c=el("section","card sys");
    c.innerHTML=`<div class="sys-head"><h3>${esc(s.system)}${s.subsystem&&SUBT[s.subsystem]?` <span class="tag">${esc(SUBT[s.subsystem].doc)}</span>`:""}</h3><p>${esc(s.blurb)}</p>
      <p style="margin-top:6px;color:var(--muted);font-size:12.2px">source: ${esc(s.source||"")}</p></div>
      <div class="fieldwrap"><table><thead><tr><th>Lever</th><th>Address</th><th>Sweep 2026-08-23</th><th>Effect</th><th>Route</th><th>Evidence</th><th>Pack</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    box.appendChild(c);
  });
}

/* ---------------------------------------------------------------- state */
function renderState(){
  const box=$("#v-state"); box.innerHTML="";
  const s=DATA.image_state, d=DATA.difficulty_table;
  const h=el("div","sec-head"); h.innerHTML=`<h2>What is installed right now</h2><span class="n">measured ${esc(DATA.generated)}</span>`;
  box.appendChild(h);
  const bar=el("div",s.installed_is_pristine?"okbar":"riskbar");
  bar.innerHTML=`<span>${s.installed_is_pristine?"✓":"⚠"}</span><div>
    <b>${s.installed_is_pristine?"The exe is byte-identical to PRISTINE — nothing is patched.":"The exe differs from PRISTINE."}</b>
    ${s.pristine_vs_stock?` PRISTINE itself is <b>not stock</b>: ${s.pristine_vs_stock.n} byte(s) differ from <span class="mono">eFootball.exe.STOCK</span> at ${esc(s.pristine_vs_stock.first.map(x=>x.off).join(", "))} — ${esc(s.pristine_vs_stock.note)}`:""}
    <div class="mono" style="margin-top:6px;font-size:12.2px">installed ${esc(String(s.installed_sha1))}<br>PRISTINE&nbsp; ${esc(String(s.pristine_sha1))}<br>STOCK&nbsp;&nbsp;&nbsp; ${esc(String(s.stock_sha1))}</div></div>`;
  box.appendChild(bar);
  const dbar=el("div",s.dt270_is_pristine?"okbar":"riskbar");
  dbar.innerHTML=`<span>${s.dt270_is_pristine?"✓":"⚠"}</span><div>
    <b>The dt270 pack is a separate install state, and it is ${s.dt270_is_pristine?"pristine":"NOT pristine"}.</b>
    The exe being stock says nothing about the data pack — this is the asymmetry the 2026-08-23 catalogue could not express, and why it showed our own August values as the game's.
    <div class="mono" style="margin-top:6px;font-size:12.2px">installed ${esc(String(s.dt270_installed_sha1))}<br>pristine&nbsp; ${esc(String(s.dt270_pristine_sha1))}<br>last install (journal) ${esc(String(s.dt270_last_install_sha1))}</div></div>`;
  box.appendChild(dbar);

  const journal=DATA.patch_journal||[];
  const packs=DATA.patch_packs||[];
  const packRows=packs.map(p=>`<tr data-hay="${esc((p.name+" "+p.description).toLowerCase())}">
      <td class="path" style="white-space:normal;max-width:24ch">${hl(p.name)}</td>
      <td><span class="tag ${p.verdict==="on"?"r-exe-code":""}">${esc(p.verdict)}</span>${p.noop_on_stock?` <span class="tag" style="color:var(--inert)">revert-shaped ${p.noop_on_stock}/${p.count}</span>`:""}</td>
      <td class="mono" style="font-size:12px;white-space:nowrap">${esc(Object.entries(p.states.reduce((a,s)=>(a[s]=(a[s]||0)+1,a),{})).map(([k,v])=>v+"× "+k).join(" · "))}</td>
      <td>${p.journal_says_applied?`<span class="tag" style="color:var(--inert)">journal says applied</span>`:""}</td>
      <td class="note">${noteCell(p.description)}</td></tr>`).join("");
  const tuneRows=(DATA.tunings||[]).map(t=>`<tr data-hay="${esc((t.name+" "+t.description).toLowerCase())}">
      <td class="path" style="white-space:normal;max-width:24ch">${hl(t.name)}</td>
      <td><span class="tag${t.verdict==="indeterminate"?" sup":""}">${esc(t.verdict)}</span>${t.unknown?`<div class="mono" style="font-size:11.5px;color:var(--inert);margin-top:4px">${t.unknown} of ${t.count} edits UNREAD</div>`:""}</td>
      <td class="mono">${t.match}/${t.count} match · ${t.miss} differ${t.unknown?" · "+t.unknown+" unreadable":""}</td>
      <td class="note">${noteCell(t.description)}</td></tr>`).join("");
  const fixRow=f=>`<tr data-hay="${esc((f.was+" "+f.now).toLowerCase())}">
      <td class="what" style="color:var(--inert)">${hl(f.was)}</td><td class="eff">${hl(f.now)}</td>
      <td class="note">${esc(f.source)}</td></tr>`;
  const fixedRows=(DATA.fixed||[]).map(fixRow).join("");
  const selfRows=(DATA.self_fixes||[]).map(fixRow).join("");
  const gapRows=(DATA.gaps||[]).map(g=>`<li data-hay="${esc((g.title+" "+g.why).toLowerCase())}"><b>${hl(g.title)}</b> — ${hl(g.why)}
      ${(g.chapters||[]).map(id=>SUBT[id]?`<span class="tag">${esc(SUBT[id].doc)}</span>`:"").join(" ")}</li>`).join("");
  const diffRows=(d&&d.rows?d.rows:[]).map(r=>`<tr data-hay="row ${r.row} ${r.va}">
      <td class="path">0x${r.row.toString(16)}</td><td class="mono">${esc(r.va)}</td><td class="mono">${r.flag}</td>
      ${r.vals.map(v=>`<td class="mono">${v}</td>`).join("")}</tr>`).join("");

  box.insertAdjacentHTML("beforeend",`
    <section class="card"><div class="sys-head"><h3>Exe patch packs — byte-compared, not looked up</h3>
      <p>Verdicts come from comparing every spec entry against the live image. <b>on</b> = all entries match the patch bytes, <b>off</b> = all match the pristine bytes, <b>not-applicable</b> = the expect bytes match nothing in this image (built against a different base), <b>mixed</b> = both. <b>revert-shaped</b> means the spec's patch bytes ARE the stock bytes, so “applied” on a stock exe means nothing.
      The journal <span class="mono">build/exe_patch_state.json</span> lists ${journal.length} applied and is stale — the old generator read it instead of the bytes.</p></div>
      <div class="fieldwrap"><table><thead><tr><th>Pack</th><th>Verdict</th><th>Entries</th><th>Journal</th><th>Description</th></tr></thead><tbody>${packRows}</tbody></table></div></section>

    <section class="card"><div class="sys-head"><h3>dt270 tunings — evaluated against the installed pack</h3>
      <p>Each tuning's <span class="mono">edits[]</span> are read back out of the CPK that is installed. The old catalogue printed one tuning as applied because the FILE existed.
      <b>Same caveat as the exe packs:</b> a tuning whose edits restore stock values (several are annotated “back to stock”) reads <b>on</b> for that reason alone. No pristine dt270 pack is available to this tool, so it cannot tell a revert from a change — check the tuning's own notes before believing a chip.</p></div>
      <div class="fieldwrap"><table><thead><tr><th>Tuning</th><th>Verdict</th><th>Match</th><th>Description</th></tr></thead><tbody>${tuneRows}</tbody></table></div></section>

    <section class="card"><div class="sys-head"><h3>CPU difficulty table — re-dumped from PRISTINE</h3>
      <p>${esc(d?d.va:"")} , stride ${esc(d?d.stride:"")}, value at +4+col*4, ${DATA.difficulty_table?DATA.difficulty_table.rows.length:0} rows × ${d?d.cols:0} columns, measured against <b>${esc(d?d.measured_against:"")}</b>${d&&d.installed_matches_pristine?" (the installed image matches it byte for byte)":" — <b>the installed image DIFFERS from PRISTINE here</b>"}.
      Rows 0x13–0x16 gate which run types exist per level; rows 0x17/0x18/0x19 are the carrier's reaction delay in ticks. A chapter dumped row 0x14 from our patched image and says so; this dump is the corrective source.</p></div>
      <div class="fieldwrap"><table><thead><tr><th>Row</th><th>VA</th><th>flag</th>${Array.from({length:d?d.cols:0},(_,i)=>`<th>c${i}</th>`).join("")}</tr></thead><tbody>${diffRows}</tbody></table></div></section>

    <section class="card"><div class="sys-head"><h3>What the 2026-08-23 catalogue got wrong</h3>
      <p>${(DATA.fixed||[]).length} entries, each fixed in this build. Kept visible on purpose: a stale catalogue is how this project has previously wasted evenings.</p></div>
      <div class="fieldwrap"><table><thead><tr><th>It said</th><th>It now says</th><th>Source</th></tr></thead><tbody>${fixedRows}</tbody></table></div></section>

    <section class="card"><div class="sys-head"><h3>What the 2026-09-20 first cut of THIS catalogue got wrong</h3>
      <p>${(DATA.self_fixes||[]).length} defects found by two adversarial reviews of the rebuilt page, all fixed in the generator rather than in the emitted HTML. Listed for the same reason as the table above: the failure this project keeps hitting is a heading that still asserts what a correction below it withdrew.</p></div>
      <div class="fieldwrap"><table><thead><tr><th>The rebuild said</th><th>It now says</th><th>Source</th></tr></thead><tbody>${selfRows}</tbody></table></div></section>

    <section class="card"><div class="sys-head"><h3>What the map still does not know</h3>
      <p>${(DATA.gaps||[]).length} holes, each blocking real questions. Listed so no row above quietly pretends to cover them.</p></div>
      <div class="card-in"><ul class="bullets">${gapRows}</ul></div></section>`);
}

/* ---------------------------------------------------------------- filters */
function renderFilters(){
  const f=$("#filters"); f.innerHTML="";
  if(view==="levers"){
    [["","all sources"],["chapter","chapter-verified"],["exe-map","2026-08-23 map"]].forEach(([k,label])=>{
      const n=k?DATA.levers.filter(l=>l.origin===k).length:DATA.levers.length;
      const b=el("button","fbtn"); b.setAttribute("aria-pressed",originFilter===k);
      b.innerHTML=`${esc(label)} <span class="mono">${n}</span>`;
      b.onclick=()=>{ originFilter=k; renderFilters(); apply(); };
      f.appendChild(b);
    });
    ROUTE_ORDER.forEach(r=>{
      if(!DATA.levers.some(l=>l.route===r)) return;
      const b=el("button","fbtn"); b.setAttribute("aria-pressed",routeFilter.has(r)); b.dataset.r=r;
      b.innerHTML=`${esc(ROUTE_LABEL[r]||r)} <span class="mono">${DATA.levers.filter(l=>l.route===r).length}</span>`;
      b.onclick=()=>{ routeFilter.has(r)?routeFilter.delete(r):routeFilter.add(r); renderFilters(); apply(); };
      f.appendChild(b);
    });
    // "show me every goalkeeper lever" must be a filter, not a hopeful search for "keeper".
    (DATA.chapters||[]).forEach(c=>{
      const n=DATA.levers.filter(l=>l.subsystem===c.id).length; if(!n) return;
      const b=el("button","fbtn"); b.setAttribute("aria-pressed",subFilter.has(c.id));
      b.innerHTML=`<span class="sw likely"></span>${esc(c.id)} <span class="mono">${n}</span>`;
      b.onclick=()=>{ subFilter.has(c.id)?subFilter.delete(c.id):subFilter.add(c.id); renderFilters(); apply(); };
      f.appendChild(b);
    });
  } else if(view==="questions"){
    // 86 cards is ~23,000px of scroll. They are already ordered by subsystem; let the reader say
    // which one instead of guessing a search term.
    const subs=[...new Set(DATA.questions.map(q=>q.subsystem))];
    subs.forEach(sname=>{
      const n=DATA.questions.filter(q=>q.subsystem===sname).length;
      const b=el("button","fbtn"); b.setAttribute("aria-pressed",qSubFilter.has(sname));
      b.innerHTML=`${esc(sname)} <span class="mono">${n}</span>`;
      b.onclick=()=>{ qSubFilter.has(sname)?qSubFilter.delete(sname):qSubFilter.add(sname); renderFilters(); apply(); };
      f.appendChild(b);
    });
  } else if(view==="dt270"){
    DT_STATUS.forEach(s=>{
      const b=el("button","fbtn"); b.setAttribute("aria-pressed",statusFilter.has(s));
      b.innerHTML=`<span class="badge ${s}">${s}</span>`;
      b.onclick=()=>{ statusFilter.has(s)?statusFilter.delete(s):statusFilter.add(s); renderFilters(); apply(); };
      f.appendChild(b);
    });
  } else if(view==="negatives"){
    [["","all"],["negative","absent / refuted"],["correction","corrections"]].forEach(([k,label])=>{
      const b=el("button","fbtn"); b.setAttribute("aria-pressed",negKind===k);
      b.textContent=label; b.onclick=()=>{ negKind=k; renderFilters(); apply(); };
      f.appendChild(b);
    });
  }
}

/* ---------------------------------------------------------------- filtering */
function apply(){
  ["questions","subsystems","levers","negatives","dt270","exemap","state"].forEach(v=>{
    $("#v-"+v).hidden = v!==view;
  });
  let hits=0;
  const root=$("#v-"+view);
  if(view==="questions"){
    root.querySelectorAll(".card.q").forEach(c=>{
      const okSub=qSubFilter.size===0||qSubFilter.has(c.dataset.sub);
      const ok=okSub&&(!query||c.dataset.hay.includes(query)); c.hidden=!ok; if(ok)hits++;
    });
  } else if(view==="levers"){
    root.querySelectorAll(".card").forEach(card=>{
      const okRoute=routeFilter.size===0||routeFilter.has(card.dataset.route);
      let vis=0;
      card.querySelectorAll("tbody tr").forEach(tr=>{
        const okOrigin=!originFilter||tr.dataset.origin===originFilter;
        const okSub=subFilter.size===0||subFilter.has(tr.dataset.sub);
        const ok=okRoute&&okOrigin&&okSub&&(!query||tr.dataset.hay.includes(query)); tr.hidden=!ok; if(ok)vis++;
      });
      card.hidden=vis===0; hits+=vis;
    });
  } else if(view==="dt270"){
    root.querySelectorAll("details.obj").forEach(d=>{
      let vis=0;
      d.querySelectorAll("tbody tr").forEach(tr=>{
        const st=tr.dataset.status;
        const okS=statusFilter.size===0||statusFilter.has(st);
        const ok=okS&&(!query||tr.dataset.hay.includes(query)); tr.hidden=!ok; if(ok)vis++;
      });
      d.hidden=vis===0; if(vis>0){hits+=vis; if(query||statusFilter.size)d.open=true;}
    });
  } else if(view==="negatives"){
    root.querySelectorAll(".card").forEach(card=>{
      let vis=0;
      card.querySelectorAll("li").forEach(li=>{
        const okK=!negKind||li.dataset.kind===negKind;
        const ok=okK&&(!query||li.dataset.hay.includes(query)); li.hidden=!ok; if(ok)vis++;
      });
      card.hidden=vis===0; hits+=vis;
    });
  } else if(view==="subsystems"||view==="exemap"||view==="state"){
    root.querySelectorAll(".card").forEach(card=>{
      let vis=0, any=false;
      card.querySelectorAll("tbody tr, ul.bullets li").forEach(n=>{
        any=true;
        const ok=!query||(n.dataset.hay||n.textContent.toLowerCase()).includes(query);
        n.hidden=!ok; if(ok)vis++;
      });
      const headOk=!query||(card.dataset.hay||card.textContent.toLowerCase()).includes(query);
      const show=(any&&vis>0)||(!any&&headOk)||(headOk&&view==="subsystems");
      card.hidden=!show; if(show)hits+=Math.max(vis,1);
    });
  }
  updateTabCounts(hits);
}

/* The search box filters the ACTIVE view only. Saying so, and saying where the hits actually
   are, is the difference between "Nothing matches" and "3 in Questions". */
function countIn(v){
  if(!query) return null;
  const has=x=>String(x||"").toLowerCase().includes(query);
  if(v==="questions") return (DATA.questions||[]).filter(q=>has(q.hay)).length;
  if(v==="levers")    return (DATA.levers||[]).filter(l=>has(l.hay)).length;
  if(v==="negatives") return (DATA.negatives||[]).filter(n=>has(n.hay)).length;
  if(v==="exemap")    return (DATA.exe_systems||[]).reduce((a,s)=>a+s.levers.filter(l=>has(l.name+" "+l.effect+" "+l.knob+" "+l.va)).length,0);
  if(v==="dt270"){
    let n=(DATA.attributes&&DATA.attributes.rows||[]).filter(a=>has(a.hay)).length;
    (DATA.objects||[]).forEach(o=>o.fields.forEach(f=>{ if(has(o.name+" "+f.path+" "+(f.note||"")))n++; }));
    return n;
  }
  if(v==="subsystems") return (DATA.chapters||[]).reduce((a,c)=>a+(has(c.title+" "+c.role+" "+c.paragraph)?1:0)+c.enables.filter(e=>has(e.hay)).length,0);
  if(v==="state") return (DATA.patch_packs||[]).filter(p=>has(p.name+" "+p.description)).length
                       + (DATA.tunings||[]).filter(t=>has(t.name+" "+t.description)).length
                       + (DATA.fixed||[]).filter(f=>has(f.was+" "+f.now)).length;
  return null;
}
function updateTabCounts(hits){
  const spread=[];
  [...$("#tabs").children].forEach(b=>{
    const v=b.dataset.v, n=countIn(v);
    b.textContent=TAB_LABEL[v]+(n==null?"":" "+n);
    if(n>0&&v!==view) spread.push(TAB_LABEL[v]+" ("+n+")");
  });
  const e=$("#empty");
  e.hidden=hits>0;
  e.innerHTML = spread.length
    ? `Nothing in this view matches “${esc(query)}” — but there ${spread.length===1?"is a hit":"are hits"} in ${spread.map(esc).join(", ")}. The search box filters one view at a time.`
    : `Nothing in this view matches that search.`;
}

/* ---------------------------------------------------------------- wire up */
renderHead(); renderQuestions(); renderSubsystems(); renderLevers(); renderNegatives();
renderObjects(); renderSystems(); renderState(); renderFilters(); apply();
$("#q").addEventListener("input",e=>{
  query=e.target.value.trim().toLowerCase();
  renderQuestions(); renderObjects(); renderSystems(); apply();
});
$("#tabs").addEventListener("click",e=>{
  const b=e.target.closest("button"); if(!b) return;
  view=b.dataset.v;
  [...e.currentTarget.children].forEach(x=>x.setAttribute("aria-pressed",x===b));
  renderFilters(); apply(); window.scrollTo({top:0});
});
</script>
"""

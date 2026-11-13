"""The local comparison dashboard: every account, the combined lines and benchmarks side by side (issue 103).

Python precomputes every window and grouping; the page only switches between them, so it is one self-contained file.
Local only (exact balances): written to the gitignored exports/ folder, never published and never sent to a chat.
This page is performance. Holdings, drift and trades belong to the IBKR operations page (issue 82).
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from ufo.performance import metrics as M
from ufo.performance.combine import GroupRun
from ufo.performance.compare import AccountRun
from ufo.performance.holdings import CLASSES, summarize
from ufo.performance.report_html import CSS
from ufo.providers.prices import Series

WINDOWS = [("ytd", "YTD"), ("1y", "1 year"), ("3y", "3 years"), ("5y", "5 years"), ("inception", "Since inception")]


def window_start(key: str, asof: date) -> date | None:
    if key == "inception":
        return None
    if key == "ytd":
        return date(asof.year - 1, 12, 31)
    n = int(key[:-1])
    try:
        return asof.replace(year=asof.year - n)
    except ValueError:  # Feb 29
        return asof.replace(year=asof.year - n, day=28)


def _stats(flows, report, end, end_value, index: Series, start: date | None, extras: dict[str, tuple[dict, Series]]) -> dict | None:
    """Figures for one window, or None when the entity does not cover it (shown as n/a, never a shortened number)."""
    fl = sorted(flows)
    base: list[tuple[date, float]] = []  # the opening value, as the first deposit of a windowed calculation
    if start is None:
        irr = report.irr
        out = {"value": end_value, "net_in": report.contributed - report.withdrawn, "irr": irr, "bench_irr": report.index_irr,
               "excess": report.excess_irr, "bench_end": report.index_end_value, "twr": report.twr_annual,
               "sharpe": report.sharpe, "dd": report.max_drawdown, "exact": True, "open": None}
        ext_flows = fl
    else:
        if not fl or fl[0][0] > start:
            return None
        idx = [i for i, m in enumerate(report.months) if m <= start]
        if not idx:
            return None
        i = idx[-1]
        od, ov = report.months[i], report.values[i]
        ext_flows = [(d, a) for d, a in fl if d > od]
        if (end - od).days < 28:
            return None
        irr = M.xirr(M.investor_flows(ext_flows, end, end_value) + [(od, -ov)])
        base = [(od, ov)]
        cf = M.index_counterfactual(base + ext_flows, index, end)
        g = M.growth_index(report.port_returns[i + 1:])
        out = {"value": end_value, "net_in": sum(a for _, a in ext_flows), "irr": irr, "bench_irr": cf.irr,
               "excess": (irr - cf.irr) if irr is not None and cf.irr is not None else None, "bench_end": cf.terminal_value,
               "twr": M.annualize(g[-1], len(g)) if g else None, "sharpe": None, "dd": M.max_drawdown(g) if g else None,
               "exact": False, "open": str(od)}
    out["extras"] = {}
    for name, (weights, series) in extras.items():
        steps = M.basket_units(sorted(base + ext_flows), weights, series)
        v = M.basket_value(steps, series, end)
        r = M.xirr(M.investor_flows(sorted(base + ext_flows), end, v)) if v > 0 else None
        out["extras"][name] = {"excess": (irr - r) if irr is not None and r is not None else None, "end": v}
    return out


def build_data(runs: list[AccountRun], groups: list[GroupRun], benchmark: str, index: Series,
               extras: dict[str, tuple[dict, Series]], asof: date, classes: dict[str, str] | None = None) -> dict:
    ents = []
    notes_ = {g.name: g.note for g in groups}
    pairs = [(r.account.label, "account", "", r.account, r.events and [(e.when, e.external_flow) for e in r.events if e.external_flow],
              r.result.report if r.result else None, r.end, r.end_value, r.quality, r.flags, r.error) for r in runs]
    for g in groups:
        pairs.append((g.name, "group", g.kind, None, g.flows, g.report, g.end, g.end_value, g.quality, [], g.error))
    for label, kind, gk, acct, flows, rep, end, ev, quality, flags, err in pairs:
        e = {"label": label, "kind": kind, "groupKind": gk, "error": err, "flags": flags}
        if acct is not None:
            e.update(type=acct.wrapper.value, brokerage=acct.brokerage, owner=acct.owner)
            run = next((r for r in runs if r.account is acct), None)
            if run and run.holdings:
                e["holdings"] = dict(summarize(run.holdings, classes or {}), as_of=str(run.holdings_as_of))
        else:
            e.update(type="combined")
        if rep is None:
            ents.append(e)
            continue
        closed = bool(acct and acct.closed)
        note = notes_.get(label, "") if kind == "group" else ""
        e.update(start=str(rep.start), as_of=str(end), quality=quality, closed=closed,
                 windows={k: (None if (k != "inception" and (closed or end < asof)) else
                              _stats(flows, rep, end, ev, index, window_start(k, asof), extras)) for k, _ in WINDOWS},
                 months=[str(m) for m in rep.months] + ([str(end)] if end not in rep.months else []),
                 values=[round(v, 2) for v in rep.values] + ([round(ev, 2)] if end not in rep.months else []),
                 bench=[round(v, 2) for v in rep.index_values] + ([round(rep.index_end_value, 2)] if end not in rep.months else []), note=note)
        ents.append(e)
    return {"benchmark": benchmark, "asof": str(asof), "windows": WINDOWS, "extras": list(extras), "entities": ents,
            "classes": [[k, v] for k, v in CLASSES.items()]}


PAGE_CSS = """
main{max-width:1100px}
.controls{display:flex;gap:18px;flex-wrap:wrap;align-items:center}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg button{background:var(--card);color:var(--ink);border:0;border-right:1px solid var(--line);padding:6px 12px;font:inherit;cursor:pointer}
.seg button:last-child{border-right:0}.seg button[aria-pressed=true]{background:var(--port);color:var(--bg)}
.exact{color:var(--good)}.est{color:var(--warn)}.na{color:var(--muted)}.err{color:var(--bad)}
svg .bar-pos{fill:var(--good)}svg .bar-neg{fill:var(--bad)}svg text{font-family:var(--body)}
:root{--c0:#1d6f5b;--c1:#4a55c4;--c2:#b13b86;--c3:#2a7fa8;--c4:#8a7a14;--c5:#7a4a2a;--c6:#c25a1b;--c7:#5d6862}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--c0:#4fc3a3;--c1:#9ba6ff;--c2:#ef8fcb;--c3:#7cc4e8;--c4:#d8c25a;--c5:#c9a27a;--c6:#f0925a;--c7:#9aa8a0}}
:root[data-theme="dark"]{--c0:#4fc3a3;--c1:#9ba6ff;--c2:#ef8fcb;--c3:#7cc4e8;--c4:#d8c25a;--c5:#c9a27a;--c6:#f0925a;--c7:#9aa8a0}
"""

JS = r"""
const D=JSON.parse(document.getElementById('data').textContent);
let win='inception',grp='accounts',showBench=true;
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pct=x=>x==null?'n/a':(x*100).toFixed(1)+'%';
const spct=x=>x==null?'n/a':(x>=0?'+':'')+(x*100).toFixed(1)+'%';
const money=x=>x==null?'n/a':(x<0?'-':'')+'$'+Math.abs(Math.round(x)).toLocaleString('en-US');
const num=x=>x==null?'n/a':x.toFixed(2);
const COLORS=Array.from({length:8},(_,i)=>`var(--c${i})`);
const GROUPS=[['accounts','Accounts'],['all','All combined'],['brokerage','By brokerage'],['owner','By owner'],['wrapper','By wrapper']];
function seg(el,items,get,set){el.innerHTML=items.map(([k,l])=>`<button type="button" aria-pressed="${get()===k}" data-k="${k}">${esc(l)}</button>`).join('');
 el.querySelectorAll('button').forEach(b=>b.onclick=()=>{set(b.dataset.k);draw();});}
function rows(){return D.entities.filter(e=>grp==='accounts'?e.kind==='account':(e.kind==='group'&&e.groupKind===grp));}
function table(rs){
 const head=['Account','Type','Started','Value','Net in','IRR','Excess IRR vs '+D.benchmark,'Worth today in '+D.benchmark,'Time-weighted /yr (est.)','Sharpe (est.)','Worst fall','Data']
  .concat(D.extras.map(n=>'Excess vs '+n));
 let h='<tr>'+head.map(x=>`<th>${esc(x)}</th>`).join('')+'</tr>';
 for(const e of rs){
  if(e.error||!e.windows){h+=`<tr><td>${esc(e.label)}</td><td>${esc(e.type||'')}</td><td colspan="${head.length-2}" class="err">not computed: ${esc(e.error)}</td></tr>`;continue;}
  const w=e.windows[win];
  if(!w){h+=`<tr><td>${esc(e.label)}</td><td>${esc(e.type)}</td><td>${e.start}</td><td colspan="${head.length-3}" class="na">n/a: does not cover this window</td></tr>`;continue;}
  const q=w.exact&&e.quality==='exact'?'exact':'estimated';
  h+=`<tr><td>${esc(e.label)}${e.closed?' <span class="small">(closed)</span>':''}</td><td>${esc(e.type)}</td><td>${e.start}</td><td>${money(w.value)}</td><td>${money(w.net_in)}</td>`+
   `<td>${pct(w.irr)}</td><td>${spct(w.excess)}</td><td>${money(w.bench_end)}</td><td>${pct(w.twr)}</td><td>${num(w.sharpe)}</td><td>${pct(w.dd)}</td>`+
   `<td class="${q==='exact'?'exact':'est'}">${q}, as of ${e.as_of}${e.note?' (common month-end)':''}</td>`+D.extras.map(n=>`<td>${spct(w.extras[n]&&w.extras[n].excess)}</td>`).join('')+'</tr>';}
 $('#tbl').innerHTML=h;}
function bars(rs){
 const items=rs.filter(e=>e.windows&&e.windows[win]&&e.windows[win].excess!=null).map(e=>[e.label,e.windows[win].excess]).sort((a,b)=>b[1]-a[1]);
 if(!items.length){$('#bars').innerHTML='<p class="na">Nothing to chart for this window.</p>';return;}
 const W=860,rh=30,L=200,R=70,H=items.length*rh+30,m=Math.max(...items.map(i=>Math.abs(i[1])),0.01),half=(W-L-R)/2,x0=L+half;
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Excess IRR per account"><line class="zero" x1="${x0}" x2="${x0}" y1="6" y2="${H-20}"/>`;
 items.forEach(([l,v],i)=>{const y=10+i*rh,w=Math.abs(v)/m*(half-60);
  s+=`<text class="val" x="${L-8}" y="${y+14}" text-anchor="end">${esc(l)}</text><rect class="${v>=0?'bar-pos':'bar-neg'}" x="${v>=0?x0:x0-w}" y="${y}" width="${w}" height="18" rx="3"/>`+
     `<text class="val" x="${v>=0?x0+w+6:x0-w-6}" y="${y+14}" text-anchor="${v>=0?'start':'end'}">${spct(v)}</text>`;});
 $('#bars').innerHTML=s+'</svg>';}
function lines(rs){
 const es=rs.filter(e=>e.months);
 if(!es.length){$('#lines').innerHTML='';$('#key').innerHTML='';return;}
 const t=d=>Date.parse(d),all=es.flatMap(e=>e.months.map(t)),t0=Math.min(...all),t1=Math.max(...all);
 const ys=es.flatMap(e=>e.values.concat(showBench?e.bench:[])),ymax=Math.max(...ys,1)*1.05;
 const W=860,H=300,L=64,R=14,T=12,B=28,X=d=>L+(t(d)-t0)/((t1-t0)||1)*(W-L-R),Y=v=>T+(H-T-B)*(1-v/ymax);
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Account value over time">`;
 for(let i=0;i<=4;i++){const v=ymax*i/4;s+=`<line class="grid" x1="${L}" x2="${W-R}" y1="${Y(v)}" y2="${Y(v)}"/><text class="axis" x="${L-6}" y="${Y(v)+4}" text-anchor="end">$${Math.round(v/1000)}k</text>`;}
 const y0=new Date(t0).getUTCFullYear(),y1=new Date(t1).getUTCFullYear();
 for(let y=y0+1;y<=y1;y++){const d=`${y}-01-01`;s+=`<text class="axis" x="${X(d)}" y="${H-8}" text-anchor="middle">${y}</text>`;}
 es.forEach((e,i)=>{const c=COLORS[i%8],pts=a=>e.months.map((m,j)=>`${X(m).toFixed(1)},${Y(a[j]).toFixed(1)}`).join(' ');
  if(showBench)s+=`<polyline fill="none" stroke="${c}" stroke-width="1.6" stroke-dasharray="5 4" opacity=".7" points="${pts(e.bench)}"/>`;
  s+=`<polyline fill="none" stroke="${c}" stroke-width="2.4" stroke-linejoin="round" points="${pts(e.values)}"/>`;});
 $('#lines').innerHTML=s+'</svg>';
 $('#key').innerHTML=es.map((e,i)=>`<span><i style="background:${COLORS[i%8]}"></i>${esc(e.label)}</span>`).join('')+(showBench?`<span class="small">dashed: same deposits and withdrawals in ${esc(D.benchmark)}</span>`:'');}
function holdings(){
 const es=D.entities.filter(e=>e.kind==='account'&&e.holdings);
 if(!es.length){$('#hold').innerHTML='';return;}
 const keys=D.classes.filter(([k])=>es.some(e=>e.holdings.by_class[k]));
 let h='<h2>What each account holds</h2><div class="scroll"><table><tr><th>Account</th>'+keys.map(([k,l])=>`<th>${esc(l)}</th>`).join('')+'</tr>';
 for(const e of es)h+=`<tr><td>${esc(e.label)}</td>`+keys.map(([k])=>`<td>${e.holdings.by_class[k]?pct(e.holdings.by_class[k]):'-'}</td>`).join('')+'</tr>';
 h+='</table></div>';
 const names=Object.fromEntries(D.classes);
 for(const e of es){
  h+=`<details><summary>${esc(e.label)}: ${money(e.holdings.total)} as of ${esc(e.holdings.as_of)}</summary><div class="scroll"><table><tr><th>Fund</th><th>Class</th><th>Value</th><th>Weight</th></tr>`+
   e.holdings.rows.map(r=>`<tr><td>${esc(r.symbol)}${r.name?' <span class="small">'+esc(r.name)+'</span>':''}</td><td>${esc(names[r.cls])}</td><td>${money(r.value)}</td><td>${pct(r.weight)}</td></tr>`).join('')+'</table></div></details>';}
 $('#hold').innerHTML=h+'<p class="small">Classes come from your local file .data/asset_classes.json; tickers missing from it show as Unclassified. Global and balanced funds are filed under Other.</p>';}
function draw(){
 seg($('#wins'),D.windows,()=>win,k=>win=k);seg($('#grps'),GROUPS,()=>grp,k=>grp=k);
 const rs=rows();table(rs);bars(rs);lines(rs);holdings();
 $('#winnote').textContent=win==='inception'?'Since inception: IRR uses exact dated flows plus the ending value.':
  'Windowed figures are estimated: they start from a reconstructed month-end value. Accounts that do not cover the window show n/a. Sharpe is shown since inception only.';
 $('#empty').hidden=rs.length>0;}
$('#bench').onchange=e=>{showBench=e.target.checked;draw();};
document.querySelectorAll('[data-theme-set]').forEach(b=>b.onclick=()=>{const v=b.dataset.themeSet;v==='auto'?document.documentElement.removeAttribute('data-theme'):document.documentElement.setAttribute('data-theme',v);});
draw();
"""


def render(data: dict) -> str:
    blob = json.dumps(data).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>All investments side by side</title>
<style>{CSS}{PAGE_CSS}</style></head><body><main>
<header><h1>All investments side by side</h1>
<p class="muted">As of {data['asof']} · benchmark {data['benchmark']} · local only, never sent anywhere
 · <span class="seg" aria-label="Theme"><button type="button" data-theme-set="auto">Auto</button><button type="button" data-theme-set="light">Light</button><button type="button" data-theme-set="dark">Dark</button></span></p></header>
<section class="controls"><div class="seg" id="wins" aria-label="Window"></div><div class="seg" id="grps" aria-label="Grouping"></div>
<label><input type="checkbox" id="bench" checked> show the same flows in the benchmark</label></section>
<p class="small" id="winnote"></p><p id="empty" hidden class="na">No accounts to show for this grouping.</p>
<section><div class="scroll"><table id="tbl"></table></div></section>
<figure><h2>Excess IRR per account</h2><div id="bars"></div><figcaption>IRR of the real flows minus the IRR of the same deposits and withdrawals put into {data['benchmark']}. Sorted best first.</figcaption></figure>
<figure><h2>Value over time</h2><div class="key" id="key"></div><div id="lines"></div><figcaption>Month-end values are estimated; the endpoints are exact.</figcaption></figure>
<section id="hold"></section>
<section class="small">
<p>All figures are before tax. A taxable account's number is not comparable with an IRA or Roth on an after-tax basis. Transfers between your own accounts are external for each account alone and net out in combined lines. See decision 0011.</p></section>
<p class="small">Information, not investment advice. Past performance does not predict future results.</p>
</main><script id="data" type="application/json">{blob}</script><script>{JS}</script></body></html>"""


def write(path: Path, html_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html_text)
    os.chmod(path, 0o600)

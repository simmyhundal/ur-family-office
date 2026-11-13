"""The local comparison dashboard: every account, the combined lines and benchmarks side by side (issue 103).

Python precomputes every window and grouping; the page only switches between them, so it is one self-contained file.
Local only (exact balances): written to the gitignored exports/ folder, never published and never sent to a chat.
This page is performance. Holdings, drift and trades belong to the IBKR operations page (issue 82).
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

from ufo.performance import metrics as M
from ufo.performance.combine import GroupRun
from ufo.performance.compare import AccountRun
from ufo.performance.holdings import CLASSES, summarize
from ufo.performance.report_html import CSS
from ufo.performance.sharpe_lesson import build_lesson
from ufo.providers.prices import Series

MAX_PLAUSIBLE_VOL = 10.0  # annualised; above this a risk figure says more about tiny balances than about risk
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


def _stats(flows, report, end, end_value, index: Series, start: date | None, extras: dict[str, tuple[dict, Series]], market: bool = True, rf: Series | None = None,
           opening: dict[date, float] | None = None) -> dict | None:
    """Figures for one window, or None when the entity does not cover it (shown as n/a, never a shortened number)."""
    fl = sorted(flows)
    base: list[tuple[date, float]] = []  # the opening value, as the first deposit of a windowed calculation
    if start is None and not market:
        irr = report.irr
        out = {"value": end_value, "net_in": report.contributed - report.withdrawn, "irr": irr, "bench_irr": report.index_irr, "excess": report.excess_irr,
               "bench_end": report.index_end_value if report.index_irr is not None else None, "twr": None, "sharpe": None, "dd": None, "exact": True, "open": None, "risk": None}
        ext_flows = fl
    elif start is None:
        irr = report.irr
        out = {"value": end_value, "net_in": report.contributed - report.withdrawn, "irr": irr, "bench_irr": report.index_irr,
               "excess": report.excess_irr, "bench_end": report.index_end_value, "twr": report.twr_annual,
               "sharpe": report.sharpe, "dd": report.max_drawdown, "exact": True, "open": None,
               "risk": {"vol": report.volatility, "ret": report.twr_annual, "sharpe": report.sharpe}}
        ext_flows = fl
    else:
        if not fl or fl[0][0] > start:
            return None
        idx = [i for i, m in enumerate(report.months) if m <= start]
        if not idx:
            return None
        i = idx[-1]
        od, ov = report.months[i], (opening or {}).get(report.months[i], report.values[i])
        ext_flows = [(d, a) for d, a in fl if d > od]
        if (end - od).days < 28:
            return None
        irr = M.xirr(M.investor_flows(ext_flows, end, end_value) + [(od, -ov)])
        base = [(od, ov)]
        cf = M.index_counterfactual(base + ext_flows, index, end)
        chart = _window_chart(report, i, end, end_value, base + ext_flows, index, market, ov)
        if not market:  # the benchmark comparison needs only dated flows and values; the return measures need prices
            return {"value": end_value, "net_in": sum(a for _, a in ext_flows), "irr": irr, "bench_irr": cf.irr,
                    "excess": (irr - cf.irr) if irr is not None and cf.irr is not None else None, "bench_end": cf.terminal_value,
                    "twr": None, "sharpe": None, "dd": None, "exact": False, "open": str(od), "extras": {}, "chart": chart, "risk": None}
        rets = [r for r in report.port_returns[i + 1:] if r is not None]
        vol = M.volatility(rets)
        unstable = any(r <= -1 for r in rets) or (vol is not None and vol > MAX_PLAUSIBLE_VOL)  # months with almost no capital
        g = [] if unstable else M.growth_index(rets)
        out = {"value": end_value, "net_in": sum(a for _, a in ext_flows), "irr": irr, "bench_irr": cf.irr,
               "excess": (irr - cf.irr) if irr is not None and cf.irr is not None else None, "bench_end": cf.terminal_value,
               "twr": M.annualize(g[-1], len(g)) if g else None, "sharpe": None, "dd": M.max_drawdown(g) if g else None,
               "exact": False, "open": str(od), "chart": chart, "unstable": unstable,
               "risk": {"vol": None, "ret": None, "sharpe": None} if unstable else _window_risk(report, i, rf)}
    out["extras"] = {}
    if not market:
        return out
    for name, (weights, series) in extras.items():
        steps = M.basket_units(sorted(base + ext_flows), weights, series)
        v = M.basket_value(steps, series, end)
        r = M.xirr(M.investor_flows(sorted(base + ext_flows), end, v)) if v > 0 else None
        out["extras"][name] = {"excess": (irr - r) if irr is not None and r is not None else None, "end": v}
    return out


def _window_chart(report, i: int, end: date, end_value: float, flows, index: Series, market: bool, opening: float) -> dict:
    """Month-end values from the window's opening month, and (for market accounts) the same flows held in the benchmark."""
    months, values = list(report.months[i:]), [opening] + list(report.values[i + 1:])
    if end not in months:
        months.append(end)
        values.append(end_value)
    bench = [round(v, 2) for v in M.index_path(flows, index, months)] if market else []
    return {"months": [str(m) for m in months], "values": [round(v, 2) for v in values], "bench": bench}


def _group_opening(g: GroupRun, runs: list[AccountRun]) -> dict[date, float]:
    """A combined line's value at each of its month-ends: the sum of its members' own values there (a statement or
    snapshot where the account has one, otherwise the rebuilt ledger). A member not yet open, or already closed, counts 0."""
    out: dict[date, float] = {}
    for r in runs:
        if r.account.id not in g.members or r.result is None:
            continue
        rep = r.result.report
        for m, v in zip(rep.months, rep.values):
            out[m] = out.get(m, 0.0) + (r.anchors.get(m) or (v, ""))[0]
    return out


def _window_risk(report, i: int, rf: Series | None) -> dict:
    """Annualised return, volatility and Sharpe over the months after the window's opening month."""
    rets = [r for r in report.port_returns[i + 1:] if r is not None]
    ex = [r - M.monthly_rf(rf, report.months[j - 1]) for j, r in zip(range(i + 1, len(report.months)), report.port_returns[i + 1:]) if r is not None] if rf is not None else []
    g = M.growth_index(rets)
    return {"vol": M.volatility(rets), "ret": M.annualize(g[-1], len(g)) if g else None, "sharpe": M.sharpe(ex) if rf is not None else None}


def _basket_risk(weights: dict[str, float], series: Series | dict, months: list[date], rf: Series | None, first_prev: date | None = None) -> dict | None:
    """Annualised return, volatility and Sharpe of a fixed-weight mix (rebalanced monthly) over the given month-ends."""
    if len(months) < 12:
        return None
    total = sum(weights.values())
    rets, ex = [], []
    for i, m in enumerate(months):
        prev = months[i - 1] if i else (first_prev or date(m.year, m.month, 1) - timedelta(days=1))
        r = 0.0
        for sym, w in weights.items():
            sr = series[sym] if isinstance(series, dict) else series
            a, b = sr.on_or_before(prev), sr.on_or_before(m)
            r += (w / total) * ((b / a - 1) if a and b else 0.0)
        rets.append(r)
        ex.append(r - (M.monthly_rf(rf, prev) if rf is not None else 0.0))
    g = M.growth_index(rets)
    return {"vol": M.volatility(rets), "ret": M.annualize(g[-1], len(g)), "sharpe": M.sharpe(ex) if rf is not None else None}


def _bench_points(ref: M.Report, key: str, asof: date, benchmark: str, extras: dict[str, tuple[dict, Series]], rf: Series | None) -> list[dict]:
    """The benchmark and extra baskets over the same window as the entities (the whole-portfolio history for 'inception')."""
    start = window_start(key, asof)
    if start is None:
        i = -1
    else:
        idx = [j for j, m in enumerate(ref.months) if m <= start]
        if not idx:
            return []
        i = idx[-1]
    months = list(ref.months[i + 1:])
    rets = list(ref.index_returns[i + 1:])
    if not months:
        return []
    g = M.growth_index(rets)
    prevs = [ref.months[j - 1] for j in range(i + 1, len(ref.months))] if i >= 0 else None
    if prevs is None:  # whole history: the first month's opening rate is the month before it
        prevs = [date(months[0].year, months[0].month, 1) - timedelta(days=1)] + months[:-1]
    ex = [r - M.monthly_rf(rf, pv) for r, pv in zip(rets, prevs)] if rf is not None else []
    exact = start is None
    out = [{"label": benchmark, "kind": "benchmark", "gk": "", "vol": M.volatility(rets), "ret": M.annualize(g[-1], len(g)),
            "sharpe": M.sharpe(ex) if rf is not None else None, "exact": exact}]
    for name, (w, series) in extras.items():
        bk = _basket_risk(w, series, months, rf, first_prev=prevs[0])
        if bk:
            out.append({"label": name, "kind": "benchmark", "gk": "", "exact": exact, **bk})
    return [p for p in out if p["vol"] is not None and p["ret"] is not None]


def risk_data(ents: list[dict], runs: list[AccountRun], groups: list[GroupRun], benchmark: str,
              extras: dict[str, tuple[dict, Series]], rf: Series | None, asof: date) -> dict:
    """Points for the risk-vs-return scatter (issue 129), per window. Entities with no volatility are listed, not plotted.
    Each point carries its kind and grouping so the page can show only the rows the grouping picker selects."""
    ref = next((g.report for g in groups if g.kind == "all" and g.report is not None), None) or \
        max((r.result.report for r in runs if r.result and r.market), key=lambda x: len(x.months), default=None)
    out = {}
    for key, _ in WINDOWS:
        pts, left = [], []
        for e in ents:
            if e.get("error") or "windows" not in e or e["kind"] not in ("account", "group"):
                continue
            kind = "all" if e.get("groupKind") == "all" else e["kind"]
            if e.get("market") is False:
                left.append([e["label"], "non-market account: no volatility", kind, ""])
                continue
            w = e["windows"].get(key)
            if w is None:
                left.append([e["label"], "does not cover this window", kind, e.get("groupKind", "")])
                continue
            r = w.get("risk")
            if not r or r["vol"] is None or r["ret"] is None:
                left.append([e["label"], "fewer than 12 months of history" if key == "inception" else "fewer than 12 months in this window", kind, e.get("groupKind", "")])
            elif r["vol"] > MAX_PLAUSIBLE_VOL:  # early months with almost no capital make monthly returns explode
                left.append([e["label"], "figures not meaningful: very little capital in the early months", kind, e.get("groupKind", "")])
            else:
                pts.append({"label": e["label"], "kind": kind, "gk": e.get("groupKind", ""), "vol": r["vol"], "ret": r["ret"],
                            "sharpe": r["sharpe"], "exact": bool(w["exact"] and e.get("quality") == "exact")})
        if ref is not None:
            pts += _bench_points(ref, key, asof, benchmark, extras, rf)
        out[key] = {"points": pts, "left_off": left}
    return out


def build_data(runs: list[AccountRun], groups: list[GroupRun], benchmark: str, index: Series,
               extras: dict[str, tuple[dict, Series]], asof: date, classes: dict[str, str] | None = None, rf: Series | None = None) -> dict:
    ents = []
    notes_ = {g.name: g.note for g in groups}
    pairs = [(r.account.label, "account", "", r.account, r.events and [(e.when, e.external_flow) for e in r.events if e.external_flow],
              r.result.report if r.result else None, r.end, r.end_value, r.quality, r.flags, r.error, r.market, None) for r in runs]
    for g in groups:
        pairs.append((g.name, "group", g.kind, None, g.flows, g.report, g.end, g.end_value, g.quality, [], g.error, True, _group_opening(g, runs) if g.report else None))
    for label, kind, gk, acct, flows, rep, end, ev, quality, flags, err, market, opening in pairs:
        e = {"label": label, "kind": kind, "groupKind": gk, "error": err, "flags": flags}
        if acct is not None:
            e.update(market=acct.market, type=acct.wrapper.value, brokerage=acct.brokerage, owner=acct.owner)
            run = next((r for r in runs if r.account is acct), None)
            if run and run.holdings:
                e["holdings"] = dict(summarize(run.holdings, classes or {}), as_of=str(run.holdings_as_of))
        else:
            e.update(type="combined", members=[next((r.account.label for r in runs if r.account.id == m), m) for m in next(g.members for g in groups if g.name == label)])
        if rep is None:
            ents.append(e)
            continue
        closed = bool(acct and acct.closed)
        note = notes_.get(label, "") if kind == "group" else ""
        e.update(start=str(rep.start), as_of=str(end), quality=quality, closed=closed,
                 windows={k: (None if (k != "inception" and (closed or (end < asof and kind == "account"))) else
                              _stats(flows, rep, end, ev, index, window_start(k, asof), extras, market, rf, opening)) for k, _ in WINDOWS},
                 months=[str(m) for m in rep.months] + ([str(end)] if end not in rep.months else []),
                 values=[round(v, 2) for v in rep.values] + ([round(ev, 2)] if end not in rep.months else []),
                 bench=([round(v, 2) for v in rep.index_values] + ([round(rep.index_end_value, 2)] if end not in rep.months else [])) if market else [], note=note)
        ents.append(e)
    return {"benchmark": benchmark, "asof": str(asof), "windows": WINDOWS, "extras": list(extras), "entities": ents,
            "classes": [[k, v] for k, v in CLASSES.items()],
            "risk": risk_data(ents, runs, groups, benchmark, extras, rf, asof),
            "lesson": build_lesson(runs, groups, benchmark, rf)}


PAGE_CSS = """
main{max-width:1100px}
.lesson{max-width:780px}.lesson h2{margin-top:1.6em}.lesson table{margin:.6em 0}.lesson ul{margin:.4em 0 .8em 1.2em}.lesson p{line-height:1.55}
.controls{display:flex;gap:18px;flex-wrap:wrap;align-items:center}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg button{background:var(--card);color:var(--ink);border:0;border-right:1px solid var(--line);padding:6px 12px;font:inherit;cursor:pointer}
.seg button:last-child{border-right:0}.seg button[aria-pressed=true]{background:var(--port);color:var(--bg)}
.total td{font-weight:700;border-top:2px solid var(--line)}.sub td{font-weight:600}.exact{color:var(--good)}.est{color:var(--warn)}.na{color:var(--muted)}.err{color:var(--bad)}
svg .bar-pos{fill:var(--good)}svg .bar-neg{fill:var(--bad)}svg text{font-family:var(--body)}
svg .pt-account{--pc:var(--c0)}svg .pt-group{--pc:var(--c1)}svg .pt-all{--pc:var(--c2)}svg .pt-benchmark{--pc:var(--c7)}
svg .pt circle{stroke:var(--pc);stroke-width:2.2}svg .pt circle.solid{fill:var(--pc)}svg .pt circle.hollow{fill:none}svg .pt text{fill:var(--ink)}
:root{--c0:#1d6f5b;--c1:#4a55c4;--c2:#b13b86;--c3:#2a7fa8;--c4:#8a7a14;--c5:#7a4a2a;--c6:#c25a1b;--c7:#5d6862}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--c0:#4fc3a3;--c1:#9ba6ff;--c2:#ef8fcb;--c3:#7cc4e8;--c4:#d8c25a;--c5:#c9a27a;--c6:#f0925a;--c7:#9aa8a0}}
:root[data-theme="dark"]{--c0:#4fc3a3;--c1:#9ba6ff;--c2:#ef8fcb;--c3:#7cc4e8;--c4:#d8c25a;--c5:#c9a27a;--c6:#f0925a;--c7:#9aa8a0}
"""

JS = r"""
const D=JSON.parse(document.getElementById('data').textContent);
let win='inception',grp='accounts',showBench=true,tab='main';
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pct=x=>x==null?'n/a':(x*100).toFixed(1)+'%';
const spct=x=>x==null?'n/a':(x>=0?'+':'')+(x*100).toFixed(1)+'%';
const money=x=>x==null?'n/a':(x<0?'-':'')+'$'+Math.abs(Math.round(x)).toLocaleString('en-US');
const num=x=>x==null?'n/a':x.toFixed(2);
function niceTicks(lo,hi,mant,maxN){// round steps (mant x 10^k) so the range has at most maxN intervals; lo and hi are widened to whole steps
 mant=mant||[1,2,5];maxN=maxN||6;const span=Math.max(hi-lo,1e-9);let step=null;
 for(let e=-6;e<=12&&step===null;e++)for(const m of mant){const st=m*Math.pow(10,e);if(span/st<=maxN){step=st;break;}}
 const a=Math.floor(lo/step+1e-9)*step,b=Math.ceil(hi/step-1e-9)*step,t=[];
 for(let v=a;v<=b+step/2;v+=step)t.push(Math.round(v/step)*step);
 return {step,lo:a,hi:b,ticks:t};}
const trim=x=>String(+x.toFixed(2));
const moneyAxis=v=>{const a=Math.abs(v),s=v<0?'-':'';return a>=1e6?s+'$'+trim(a/1e6)+'M':a>=1000?s+'$'+trim(a/1000)+'K':s+'$'+Math.round(a);};
const MONEY_STEPS=[1,2.5,5,10],PCT_STEPS=[1,2,5];
const COLORS=Array.from({length:8},(_,i)=>`var(--c${i})`);
const GROUPS=[['accounts','Accounts'],['all','All combined'],['brokerage','By brokerage'],['owner','By owner'],['wrapper','By wrapper']];
function seg(el,items,get,set){el.innerHTML=items.map(([k,l])=>`<button type="button" aria-pressed="${get()===k}" data-k="${k}">${esc(l)}</button>`).join('');
 el.querySelectorAll('button').forEach(b=>b.onclick=()=>{set(b.dataset.k);draw();});}
function rows(){return D.entities.filter(e=>grp==='accounts'?e.kind==='account':(e.kind==='group'&&e.groupKind===grp));}
function trow(e,label,cls){
  if(e.error||!e.windows)return `<tr class="${cls}"><td>${label}</td><td>${esc(e.type||'')}</td><td colspan="${NCOLS-2}" class="err">not computed: ${esc(e.error)}</td></tr>`;
  const w=e.windows[win];
  if(!w)return `<tr class="${cls}"><td>${label}</td><td>${esc(e.type)}</td><td>${e.start}</td><td colspan="${NCOLS-3}" class="na" title="${esc(e.kind==='group'?'the combined line starts after this window begins, or has under a month of history in it':'this account starts after the window begins, or is closed')}">n/a: does not cover this window</td></tr>`;
  const q=w.exact&&e.quality==='exact'?'exact':'estimated';
  const nm=e.market===false?'non-market account: no prices, so no return-based measures':null, wn=win!=='inception';
  const why={irr:'no IRR: the dated flows and end value do not have both a deposit and a withdrawal or value',
   excess:'needs both an IRR and a benchmark IRR (none if withdrawals exceed what the benchmark could have funded)',
   bench:'none if withdrawals exceed what the benchmark could have funded',
   twr:nm||(w.unstable?'monthly returns in this window are not meaningful: some months had very little capital':wn?'needs at least 12 months of monthly returns inside this window':'needs at least 12 months of monthly returns'),
   sharpe:nm||(wn?'Sharpe is shown since inception only':'needs at least 12 months of monthly returns'),
   dd:nm||(w.unstable?'monthly returns in this window are not meaningful: some months had very little capital':'no monthly returns to measure a fall from')};
  const c=(f,v,k)=>v==null?`<td class="na" title="${esc(why[k])}">n/a</td>`:`<td>${f(v)}</td>`;
  return `<tr class="${cls}"><td>${label}${e.closed?' <span class="small">(closed)</span>':''}</td><td>${esc(e.type)}</td><td>${e.start}</td><td>${money(w.value)}</td><td>${money(w.net_in)}</td>`+
   c(pct,w.irr,'irr')+c(spct,w.excess,'excess')+c(money,w.bench_end,'bench')+c(pct,w.twr,'twr')+c(num,w.sharpe,'sharpe')+c(pct,w.dd,'dd')+
   `<td class="${q==='exact'?'exact':'est'}">${q}, as of ${e.as_of}${e.note?' (common month-end)':''}</td>`+D.extras.map(n=>c(spct,w.extras[n]&&w.extras[n].excess,'excess')).join('')+'</tr>';}
let NCOLS=12;
function table(rs){
 const head=['Account','Type','Started','Value','Net in','IRR','Excess IRR vs '+D.benchmark,'Worth today in '+D.benchmark,'Time-weighted /yr (est.)','Sharpe (est.)','Worst fall','Data']
  .concat(D.extras.map(n=>'Excess vs '+n));
 NCOLS=head.length;
 let h='<tr>'+head.map(x=>`<th>${esc(x)}</th>`).join('')+'</tr>';
 for(const e of rs)h+=trow(e,esc(e.label),grp==='accounts'||e.kind==='account'?'':'sub');
 const tot=D.entities.find(e=>e.kind==='group'&&e.groupKind==='all');
 const showTot=tot&&grp!=='all';
 if(showTot)h+=trow(tot,'Total, all accounts','total');
 $('#tbl').innerHTML=h;
 const t2=grp==='all'?rs[0]:tot;
 $('#totnote').textContent=t2&&t2.as_of?`The total is valued on ${t2.as_of}${t2.note?', the latest month-end every account covers':''}; account rows use each account's own latest date, so the sums can differ. `+
  'Non-market accounts (a fixed annuity) count in value and net in. Transfers between your own accounts net out of combined lines, so their Net in can differ from the sum of the rows.'+
  (grp!=='accounts'&&grp!=='all'?' Each group row is a subtotal for its members, valued on that group\'s own common month-end.':''):'';}
function bars(rs){
 const items=rs.filter(e=>e.windows&&e.windows[win]&&e.windows[win].excess!=null).map(e=>[e.label,e.windows[win].excess]).sort((a,b)=>b[1]-a[1]);
 if(!items.length){$('#bars').innerHTML='<p class="na">Nothing to chart for this window.</p>';return;}
 const W=860,rh=30,L=200,R=70,H=items.length*rh+44,mx=Math.max(...items.map(i=>Math.abs(i[1])),0.01),bt=niceTicks(0,mx,PCT_STEPS.map(q=>q/100),3),m=bt.hi,half=(W-L-R)/2,x0=L+half,sc=(half-60)/m;
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Excess IRR per account">`;
 for(const u of bt.ticks.flatMap(t=>t===0?[0]:[t,-t]))s+=`<line class="${u===0?'zero':'grid'}" x1="${x0+u*sc}" x2="${x0+u*sc}" y1="6" y2="${H-26}"/><text class="axis" x="${x0+u*sc}" y="${H-10}" text-anchor="middle">${u===0?'0%':spct(u)}</text>`;
 items.forEach(([l,v],i)=>{const y=10+i*rh,w=Math.abs(v)*sc;
  s+=`<text class="val" x="${L-8}" y="${y+14}" text-anchor="end">${esc(l)}</text><rect class="${v>=0?'bar-pos':'bar-neg'}" x="${v>=0?x0:x0-w}" y="${y}" width="${w}" height="18" rx="3"/>`+
     `<text class="val" x="${v>=0?x0+w+6:x0-w-6}" y="${y+14}" text-anchor="${v>=0?'start':'end'}">${spct(v)}</text>`;});
 $('#bars').innerHTML=s+'</svg>';}
function view(e){// the series to chart for the picked window, or null when the entity does not cover it
 if(win==='inception')return e.months?e:null;
 const w=e.windows&&e.windows[win];return w&&w.chart?{label:e.label,months:w.chart.months,values:w.chart.values,bench:w.chart.bench}:null;}
function lines(rs){
 const es=rs.map(view).filter(Boolean);
 if(!es.length){$('#lines').innerHTML='<p class="na">Nothing to chart for this window.</p>';$('#key').innerHTML='';return;}
 const t=d=>Date.parse(d),all=es.flatMap(e=>e.months.map(t)),t0=Math.min(...all),t1=Math.max(...all);
 const ys=es.flatMap(e=>e.values.concat(showBench?e.bench:[])),yt=niceTicks(0,Math.max(...ys,1),MONEY_STEPS,5),ymax=yt.hi;
 const W=860,H=300,L=64,R=14,T=12,B=28,X=d=>L+(t(d)-t0)/((t1-t0)||1)*(W-L-R),Y=v=>T+(H-T-B)*(1-v/ymax);
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Account value over time">`;
 for(const v of yt.ticks){s+=`<line class="${v===0?'zero':'grid'}" x1="${L}" x2="${W-R}" y1="${Y(v)}" y2="${Y(v)}"/><text class="axis" x="${L-6}" y="${Y(v)+4}" text-anchor="end">${moneyAxis(v)}</text>`;}
 const y0=new Date(t0).getUTCFullYear(),y1=new Date(t1).getUTCFullYear();
 for(let y=y0+1;y<=y1;y++){const d=`${y}-01-01`;s+=`<text class="axis" x="${X(d)}" y="${H-8}" text-anchor="middle">${y}</text>`;}
 es.forEach((e,i)=>{const c=COLORS[i%8],pts=a=>e.months.map((m,j)=>`${X(m).toFixed(1)},${Y(a[j]).toFixed(1)}`).join(' ');
  if(showBench&&e.bench.length)s+=`<polyline fill="none" stroke="${c}" stroke-width="1.6" stroke-dasharray="5 4" opacity=".7" points="${pts(e.bench)}"/>`;
  s+=`<polyline fill="none" stroke="${c}" stroke-width="2.4" stroke-linejoin="round" points="${pts(e.values)}"/>`;});
 $('#lines').innerHTML=s+'</svg>';
 $('#key').innerHTML=es.map((e,i)=>`<span><i style="background:${COLORS[i%8]}"></i>${esc(e.label)}</span>`).join('')+(showBench?`<span class="small">dashed: same deposits and withdrawals in ${esc(D.benchmark)}</span>`:'');}
function scatter(){
 const R=D.risk[win],keep=p=>p.kind==='benchmark'||p.kind==='all'||(grp==='accounts'?p.kind==='account':(grp!=='all'&&p.gk===grp)),P=R.points.filter(keep),LO=R.left_off.filter(keep);
 if(P.length<2){$('#risk').innerHTML='<p class="na">Not enough history (12 months) for a risk and return chart.</p>';}
 else{
  const W=860,H=380,L=64,Rr=40,T=14,B=44,PS=PCT_STEPS.map(m=>m/100),xt=niceTicks(0,Math.max(...P.map(p=>p.vol),0.01),PS,6),xm=xt.hi,
   yt=niceTicks(Math.min(0,...P.map(p=>p.ret)),Math.max(0.01,...P.map(p=>p.ret)),PS,6),y0=yt.lo,y1=yt.hi;
  const X=v=>L+v/xm*(W-L-Rr),Y=v=>T+(H-T-B)*(1-(v-y0)/((y1-y0)||1));
  let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Risk versus return">`;
  for(const v of yt.ticks)s+=`<line class="${v===0?'zero':'grid'}" x1="${L}" x2="${W-Rr}" y1="${Y(v)}" y2="${Y(v)}"/><text class="axis" x="${L-6}" y="${Y(v)+4}" text-anchor="end">${pct(v)}</text>`;
  for(const u of xt.ticks)s+=`<line class="grid" x1="${X(u)}" x2="${X(u)}" y1="${T}" y2="${H-B}"/><line class="zero" x1="${X(u)}" x2="${X(u)}" y1="${Y(0)}" y2="${Y(0)+4}"/><text class="axis" x="${X(u)}" y="${H-24}" text-anchor="middle">${pct(u)}</text>`;
  s+=`<text class="axis" x="${(L+W-Rr)/2}" y="${H-6}" text-anchor="middle">Volatility (annual, lower is calmer)</text><text class="axis" x="14" y="${(T+H-B)/2}" text-anchor="middle" transform="rotate(-90 14 ${(T+H-B)/2})">Return per year</text>`;
  const ly={};let last=-99;[...P].sort((a,b)=>Y(a.ret)-Y(b.ret)).forEach(p=>{last=Math.max(Y(p.ret),last+12);ly[p.label+p.kind]=last;});
  for(const p of P){const tip=`${p.label}: return ${pct(p.ret)}, volatility ${pct(p.vol)}, Sharpe ${num(p.sharpe)}${p.exact?'':' (estimated)'}`;
   s+=`<g class="pt pt-${p.kind}"><title>${esc(tip)}</title><circle class="${p.exact?'solid':'hollow'}" cx="${X(p.vol)}" cy="${Y(p.ret)}" r="${p.kind==='all'?9:6}"/>`+
      `<text class="axis" x="${X(p.vol)>W*0.7?X(p.vol)-11:X(p.vol)+11}" text-anchor="${X(p.vol)>W*0.7?'end':'start'}" y="${ly[p.label+p.kind]+4}">${esc(p.label)} · S ${num(p.sharpe)}</text></g>`;}
  $('#risk').innerHTML=s+'</svg>';}
 $('#riskleft').textContent=LO.length?'Not on the chart: '+LO.map(([l,w])=>l+' ('+w+')').join('; ')+'.':'';}
function holdings(){
 const shown=new Set(rows().flatMap(e=>e.members||[e.label])),es=D.entities.filter(e=>e.kind==='account'&&e.holdings&&(grp==='all'||shown.has(e.label)));
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
function sharpeTab(){
 const L=D.lesson;$('#lesson').innerHTML=L.html;
 const P=L.points,c=$('#sharpechart');if(!c)return;
 if(!P){c.innerHTML='<p class="na">n/a: the chart needs the T-bill rate and at least two months of returns.</p>';return;}
 const pts=[{k:'portfolio',label:'Your portfolio',...P.portfolio},{k:'benchmark',label:D.benchmark,...P.benchmark}].filter(p=>p.ret!=null&&p.vol!=null);
 const W=860,H=340,Lm=64,Rm=40,T=14,B=44,PS=PCT_STEPS.map(m=>m/100),
  xt=niceTicks(0,Math.max(...pts.map(p=>p.vol),0.01),PS,6),xm=xt.hi,
  yt=niceTicks(Math.min(0,P.rf,...pts.map(p=>p.ret)),Math.max(0.01,P.rf,...pts.map(p=>p.ret)),PS,6),y0=yt.lo,y1=yt.hi;
 const X=v=>Lm+v/xm*(W-Lm-Rm),Y=v=>T+(H-T-B)*(1-(v-y0)/((y1-y0)||1));
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Sharpe ratio as the slope of a line from the risk-free point">`;
 for(const v of yt.ticks)s+=`<line class="${v===0?'zero':'grid'}" x1="${Lm}" x2="${W-Rm}" y1="${Y(v)}" y2="${Y(v)}"/><text class="axis" x="${Lm-6}" y="${Y(v)+4}" text-anchor="end">${pct(v)}</text>`;
 for(const u of xt.ticks)s+=`<line class="grid" x1="${X(u)}" x2="${X(u)}" y1="${T}" y2="${H-B}"/><text class="axis" x="${X(u)}" y="${H-24}" text-anchor="middle">${pct(u)}</text>`;
 s+=`<text class="axis" x="${(Lm+W-Rm)/2}" y="${H-6}" text-anchor="middle">Volatility (annual)</text>`;
 pts.forEach((p,i)=>{const col=p.k==='portfolio'?'var(--c2)':'var(--c7)';
  s+=`<g class="pt"><title>${esc(p.label)}: return ${pct(p.ret)}, volatility ${pct(p.vol)}, Sharpe ${num(p.sharpe)}</title><line x1="${X(0)}" y1="${Y(P.rf)}" x2="${X(p.vol)}" y2="${Y(p.ret)}" stroke="${col}" stroke-width="2" stroke-dasharray="${p.k==='portfolio'?'0':'6 4'}"/>`+
   `<circle cx="${X(p.vol)}" cy="${Y(p.ret)}" r="6" fill="${col}"/><text class="axis" x="${X(p.vol)>W*0.7?X(p.vol)-10:X(p.vol)+10}" text-anchor="${X(p.vol)>W*0.7?'end':'start'}" y="${Y(p.ret)+(i?16:-8)}">${esc(p.label)} · slope ${num(p.sharpe)}</text></g>`;});
 s+=`<circle cx="${X(0)}" cy="${Y(P.rf)}" r="5" fill="none" stroke="var(--ink)" stroke-width="2"/><text class="axis" x="${X(0)+10}" y="${Y(P.rf)-8}">Risk-free (T-bill) ${pct(P.rf)}</text>`;
 c.innerHTML=s+'</svg>';
 $('#sharpecap').textContent='Each line starts at the risk-free point (zero risk, the T-bill return) and ends at a portfolio. The steeper the line, the higher the Sharpe ratio: its slope is the Sharpe ratio. Returns here are the average month times 12, so they differ slightly from the compounded figures in the Risk versus return chart.';}
function showTab(){$('#tab-main').hidden=tab!=='main';$('#tab-sharpe').hidden=tab!=='sharpe';if(tab==='sharpe')sharpeTab();}
function draw(){
 seg($('#tabs'),[['main','Dashboard'],['sharpe','How Sharpe works']],()=>tab,k=>{tab=k;});showTab();
 seg($('#wins'),D.windows,()=>win,k=>win=k);seg($('#grps'),GROUPS,()=>grp,k=>grp=k);
 const rs=rows();table(rs);bars(rs);lines(rs);holdings();scatter();
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
<nav class="controls"><div class="seg" id="tabs" aria-label="View"></div></nav>
<div id="tab-main">
<section class="controls"><div class="seg" id="wins" aria-label="Window"></div><div class="seg" id="grps" aria-label="Grouping"></div>
<label><input type="checkbox" id="bench" checked> show the same flows in the benchmark</label></section>
<p class="small" id="winnote"></p><p class="small" id="totnote"></p><p id="empty" hidden class="na">No accounts to show for this grouping.</p>
<section><div class="scroll"><table id="tbl"></table></div></section>
<figure><h2>Excess IRR per account</h2><div id="bars"></div><figcaption>IRR of the real flows minus the IRR of the same deposits and withdrawals put into {data['benchmark']}. Sorted best first.</figcaption></figure>
<figure><h2>Value over time</h2><div class="key" id="key"></div><div id="lines"></div><figcaption>Month-end values are estimated; the endpoints are exact.</figcaption></figure>
<figure><h2>Risk versus return</h2><div id="risk"></div><figcaption>Each point is one account, group, your whole portfolio (large) or a benchmark (grey): time-weighted return per year against how much it swings, with its Sharpe ratio (S, return above the T-bill rate per unit of risk) in the label. Since each one's start; benchmarks cover the whole-portfolio period. Hollow points are estimated from reconstructed month-end values (decision 0011). Hover for the figures.</figcaption><p class="small" id="riskleft"></p></figure>
<section id="hold"></section>
</div>
<div id="tab-sharpe" hidden><article id="lesson" class="lesson"></article></div>
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

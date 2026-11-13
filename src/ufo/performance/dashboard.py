"""The local comparison dashboard: every account, the combined lines and benchmarks side by side (issue 103).

Python precomputes every window and grouping; the page only switches between them, so it is one self-contained file.
Local only (exact balances): written to the gitignored exports/ folder, never published and never sent to a chat.
This page is performance. Holdings, drift and trades belong to the IBKR operations page (issue 82).
"""
from __future__ import annotations

import html
import json
import os
from datetime import date, timedelta
from pathlib import Path

from ufo.performance import metrics as M
from ufo.performance.combine import GroupRun
from ufo.performance.compare import AccountRun
from ufo.performance.holdings import CLASSES, summarize
from ufo.performance.sharpe_lesson import build_lesson
from ufo.providers.prices import Series

MAX_PLAUSIBLE_VOL = 10.0  # annualised; above this a risk figure says more about tiny balances than about risk
BENCHMARKS = [("VT", "Market (VT)"), ("VTI", "US total market (VTI)"), ("SPY", "S&P 500 (SPY)"), ("QQQ", "Nasdaq-100 (QQQ)"),
              ("AOR", "60/40 global stocks and bonds (AOR)"), ("BND", "US bonds (BND)")]
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
           opening: dict[date, float] | None = None, alt: bool = False) -> dict | None:
    """Figures for one window, or None when the entity does not cover it (shown as n/a, never a shortened number)."""
    fl = sorted(flows)
    base: list[tuple[date, float]] = []  # the opening value, as the first deposit of a windowed calculation
    if start is None and not market:
        irr = report.irr
        out = {"value": end_value, "net_in": report.contributed - report.withdrawn, "dep": report.contributed, "wd": report.withdrawn,
               "irr": irr, "bench_irr": report.index_irr, "excess": report.excess_irr,
               "bench_end": report.index_end_value if report.index_irr is not None else None, "twr": None, "sharpe": None, "dd": None, "exact": True, "open": None, "risk": None}
        ext_flows = fl
    elif start is None:
        irr = report.irr
        out = {"value": end_value, "net_in": report.contributed - report.withdrawn, "dep": report.contributed, "wd": report.withdrawn,
               "irr": irr, "bench_irr": report.index_irr, "excess": report.excess_irr, "bench_end": report.index_end_value, "twr": report.twr_annual,
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
        ext_flows = [(d, a) for d, a in fl if od < d <= end]
        dep, wd = sum(a for _, a in ext_flows if a > 0), -sum(a for _, a in ext_flows if a < 0)  # where the money came from
        if (end - od).days < 28:
            return None
        span = (end - od).days
        cum = span < 365  # decision 0011: a window under a year is never annualized; show the cumulative return

        def conv(r):
            return (1 + r) ** (span / 365) - 1 if cum and r is not None and r > -1 else r
        irr = conv(M.xirr(M.investor_flows(ext_flows, end, end_value) + [(od, -ov)]))
        base = [(od, ov)]
        cf = M.index_counterfactual(base + ext_flows, index, end)
        cf = cf.model_copy(update={"irr": conv(cf.irr)})
        chart = _window_chart(report, i, end, end_value, base + ext_flows, index, market, ov)
        if not market:  # the benchmark comparison needs only dated flows and values; the return measures need prices
            return {"value": end_value, "net_in": sum(a for _, a in ext_flows), "dep": dep, "wd": wd, "irr": irr, "bench_irr": cf.irr,
                    "excess": (irr - cf.irr) if irr is not None and cf.irr is not None else None, "bench_end": cf.terminal_value,
                    "twr": None, "sharpe": None, "dd": None, "exact": False, "open": str(od), "extras": {}, "chart": chart, "risk": None,
                    "cum": cum, "thru": str(end), "twr_thru": None}
        rets = [r for r in report.port_returns[i + 1:] if r is not None]
        vol = M.volatility(rets)
        unstable = any(r <= -1 for r in rets) or (vol is not None and vol > MAX_PLAUSIBLE_VOL)  # months with almost no capital
        g = [] if unstable else M.growth_index(rets)
        out = {"value": end_value, "net_in": sum(a for _, a in ext_flows), "dep": dep, "wd": wd, "irr": irr, "bench_irr": cf.irr,
               "excess": (irr - cf.irr) if irr is not None and cf.irr is not None else None, "bench_end": cf.terminal_value,
               "twr": ((g[-1] - 1) if cum else M.annualize(g[-1], len(g))) if g else None, "sharpe": None, "dd": M.max_drawdown(g) if g else None,
               "exact": False, "open": str(od), "chart": chart, "unstable": unstable, "cum": cum, "thru": str(end), "twr_thru": str(report.months[-1]),
               "risk": {"vol": None, "ret": None, "sharpe": None} if unstable else _window_risk(report, i, rf)}
    if alt and start is None:  # the same account against another benchmark: only the benchmark-side figures change
        cf = M.index_counterfactual(fl, index, end)
        out.update(bench_irr=cf.irr, excess=(irr - cf.irr) if irr is not None and cf.irr is not None else None,
                   bench_end=cf.terminal_value if (market or cf.irr is not None) else None)
        out["bench_path"] = [round(v, 2) for v in M.index_path(fl, index, list(report.months) + ([end] if end not in report.months else []))] if market else []
    out["extras"] = {}
    if not market:
        return out
    for name, (weights, series) in extras.items():
        steps = M.basket_units(sorted(base + ext_flows), weights, series)
        v = M.basket_value(steps, series, end)
        r = M.xirr(M.investor_flows(sorted(base + ext_flows), end, v)) if v > 0 else None
        r = (1 + r) ** (((end - base[0][0]).days) / 365) - 1 if out.get("cum") and r is not None and r > -1 and base else r
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
        if r.account.id not in g.members or r.result is None or r.unreconciled:
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


def _bench_points(ref: M.Report, key: str, asof: date, benchmark: str, extras: dict[str, tuple[dict, Series]], rf: Series | None,
                  index: Series | None = None) -> list[dict]:
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
    if not months:
        return []
    prevs = [ref.months[j - 1] for j in range(i + 1, len(ref.months))] if i >= 0 else None
    if prevs is None:  # whole history: the first month's opening rate is the month before it
        prevs = [date(months[0].year, months[0].month, 1) - timedelta(days=1)] + months[:-1]
    if index is not None:
        rets = [((index.on_or_before(m) / index.on_or_before(pv) - 1) if index.on_or_before(m) and index.on_or_before(pv) else 0.0) for m, pv in zip(months, prevs)]
    else:
        rets = list(ref.index_returns[i + 1:])
    g = M.growth_index(rets)
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
              extras: dict[str, tuple[dict, Series]], rf: Series | None, asof: date, benchmarks: dict[str, Series] | None = None) -> dict:
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
            if e.get("unreconciled"):
                left.append([e["label"], "estimated, does not reconcile: month-end values do not match its statements", kind, ""])
                continue
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
        bm = {}
        if ref is not None:
            for sym, series in (benchmarks or {}).items():
                bp = _bench_points(ref, key, asof, sym, {}, rf, series)
                if bp:
                    bm[sym] = bp[0]
        out[key] = {"points": pts, "left_off": left, "bm": bm}
    return out


def label_of(sym: str) -> str:
    return dict(BENCHMARKS).get(sym, sym)


def build_data(runs: list[AccountRun], groups: list[GroupRun], benchmark: str, index: Series,
               extras: dict[str, tuple[dict, Series]], asof: date, classes: dict[str, str] | None = None, rf: Series | None = None,
               benchmarks: dict[str, Series] | None = None) -> dict:
    """`benchmarks` are the series the page's benchmark picker can switch between (the default `index` is one of them)."""
    alts = {sym: s for sym, s in (benchmarks or {}).items() if sym != benchmark}
    order = ([benchmark] if benchmark not in dict(BENCHMARKS) else []) + [sym for sym, _ in BENCHMARKS if sym == benchmark or sym in alts]
    ents = []
    good = [r for r in runs if not r.unreconciled]
    notes_ = {g.name: g.note for g in groups}
    pairs = [(r.account.label, "account", "", r.account, r.events and [(e.when, e.external_flow) for e in r.events if e.external_flow],
              r.result.report if r.result else None, r.end, r.end_value, r.quality, r.flags, r.error, r.market, {d: v for d, (v, _) in r.anchors.items()}) for r in runs]
    for g in groups:
        pairs.append((g.name, "group", g.kind, None, g.flows, g.report, g.end, g.end_value, g.quality, [], g.error, True, _group_opening(g, runs) if g.report else None))
    for label, kind, gk, acct, flows, rep, end, ev, quality, flags, err, market, opening in pairs:
        e = {"label": label, "kind": kind, "groupKind": gk, "error": err, "flags": flags}
        bad_run = next((r for r in runs if r.account is acct and r.unreconciled), None) if acct is not None else None
        if bad_run:
            e["unreconciled"] = bad_run.unreconciled
        if acct is not None:
            e.update(market=acct.market, type=acct.wrapper.value, brokerage=acct.institution_name, owner=acct.owner)
            run = next((r for r in runs if r.account is acct), None)
            if run and run.holdings:
                e["holdings"] = dict(summarize(run.holdings, classes or {}), as_of=str(run.holdings_as_of))
            elif run and run.holdings_note:
                e["holdings_note"] = run.holdings_note
        else:
            e["excluded"] = list(next(g.excluded for g in groups if g.name == label))
            e.update(type="combined", members=[next((r.account.label for r in runs if r.account.id == m), m) for m in next(g.members for g in groups if g.name == label)])
        if rep is None:
            ents.append(e)
            continue
        closed = bool(acct and acct.closed)
        note = notes_.get(label, "") if kind == "group" else ""
        e.update(start=str(rep.start), as_of=str(end), quality=quality, closed=closed,
                 windows={k: (None if (k != "inception" and (closed or bad_run)) else
                              _stats(flows, rep, end, ev, index, window_start(k, asof), extras, market, rf, opening)) for k, _ in WINDOWS},
                 months=[str(m) for m in rep.months] + ([str(end)] if end not in rep.months else []),
                 values=[round(v, 2) for v in rep.values] + ([round(ev, 2)] if end not in rep.months else []),
                 bench=([round(v, 2) for v in rep.index_values] + ([round(rep.index_end_value, 2)] if end not in rep.months else [])) if market else [], note=note)
        if bad_run:  # since-inception IRR and excess rest on dated flows plus the exact ending value; everything on month-ends is dropped
            w = e["windows"]["inception"]
            if w:
                w.update(twr=None, sharpe=None, dd=None, risk=None, extras={})
            e.update(months=None, values=None, bench=[])
        e["bm"] = {}
        for sym, series in alts.items():
            ws = {}
            for k, _ in WINDOWS:
                if e["windows"][k] is None:
                    ws[k] = None
                    continue
                a = _stats(flows, rep, end, ev, series, window_start(k, asof), {}, market, rf, opening, alt=True)
                ws[k] = None if a is None else {"bench_irr": a["bench_irr"], "excess": a["excess"], "bench_end": a["bench_end"],
                                                 "bench": a["bench_path"] if k == "inception" else a["chart"]["bench"]}
            e["bm"][sym] = ws
        ents.append(e)
    return {"benchmark": benchmark, "asof": str(asof), "windows": WINDOWS, "extras": list(extras), "entities": ents,
            "classes": [[k, v] for k, v in CLASSES.items()],
            "risk": risk_data(ents, good, groups, benchmark, extras, rf, asof, {benchmark: index, **alts}),
            "lesson": build_lesson(good, groups, label_of(benchmark), rf),
            "lessons": {sym: build_lesson(good, groups, label_of(sym), rf, index=s) for sym, s in alts.items()},
            "benchmarks": [[sym, label_of(sym)] for sym in order], "benchmarkLabel": label_of(benchmark)}


PAGE_CSS = """
:root{color-scheme:light;--bg:#f5f5fa;--surface:#fff;--surface-2:#f0f0f7;--ink:#13132b;--ink-2:#54577a;--ink-3:#6b6e8f;--line:#e5e5f0;--line-2:#d6d6e6;
--accent:#5b3fe0;--accent-2:#7a62ff;--accent-soft:#eeeaff;--accent-ink:#fff;--bench:#c2410c;--up:#0d7a52;--up-soft:#e2f4ea;--down:#b42318;--down-soft:#fdecea;--warn:#8a5a00;--warn-soft:#fff2d1;
--shadow:0 1px 2px rgba(19,19,43,.04),0 6px 22px -10px rgba(19,19,43,.16);--shadow-up:0 -10px 40px -12px rgba(19,19,43,.28);
--r:22px;--r-sm:14px;--ease:cubic-bezier(.2,.7,.2,1);--font:ui-rounded,"SF Pro Rounded",system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--c0:#5b3fe0;--c1:#0e7490;--c2:#be185d;--c3:#2563eb;--c4:#a16207;--c5:#7c4a2a;--c6:#c2410c;--c7:#6b6e8f;
--k0:#5b3fe0;--k1:#0ea5b7;--k2:#2563eb;--k3:#d97706;--k4:#0d9488;--k5:#94a3b8;--k6:#db2777;--k7:#a16207;--k8:#c4c4d4;
--port:var(--accent);--card:var(--surface);--muted:var(--ink-3);--good:var(--up);--bad:var(--down)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#0b0c1d;--surface:#15172f;--surface-2:#1c1e3a;--ink:#f2f2fb;--ink-2:#b4b6d4;--ink-3:#9396b8;--line:#25284a;--line-2:#33375c;
--accent:#a594ff;--accent-2:#c3b8ff;--accent-soft:#25224f;--accent-ink:#0b0c1d;--bench:#fb9a5b;--up:#4ade9b;--up-soft:#123528;--down:#ff9a90;--down-soft:#3a1a22;--warn:#f3c969;--warn-soft:#3a2f12;
--shadow:0 1px 2px rgba(0,0,0,.4),0 10px 28px -12px rgba(0,0,0,.6);--shadow-up:0 -10px 40px -10px rgba(0,0,0,.7);
--c0:#a594ff;--c1:#5fd3e6;--c2:#f58bc6;--c3:#7fb0ff;--c4:#e7c25a;--c5:#d1a27c;--c6:#fb9a5b;--c7:#9396b8;
--k0:#a594ff;--k1:#5fd3e6;--k2:#7fb0ff;--k3:#f5b94a;--k4:#4fd1bd;--k5:#8a93ad;--k6:#f58bc6;--k7:#d6b45a;--k8:#4a4d70}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#0b0c1d;--surface:#15172f;--surface-2:#1c1e3a;--ink:#f2f2fb;--ink-2:#b4b6d4;--ink-3:#9396b8;--line:#25284a;--line-2:#33375c;
--accent:#a594ff;--accent-2:#c3b8ff;--accent-soft:#25224f;--accent-ink:#0b0c1d;--bench:#fb9a5b;--up:#4ade9b;--up-soft:#123528;--down:#ff9a90;--down-soft:#3a1a22;--warn:#f3c969;--warn-soft:#3a2f12;
--shadow:0 1px 2px rgba(0,0,0,.4),0 10px 28px -12px rgba(0,0,0,.6);--shadow-up:0 -10px 40px -10px rgba(0,0,0,.7);
--c0:#a594ff;--c1:#5fd3e6;--c2:#f58bc6;--c3:#7fb0ff;--c4:#e7c25a;--c5:#d1a27c;--c6:#fb9a5b;--c7:#9396b8;
--k0:#a594ff;--k1:#5fd3e6;--k2:#7fb0ff;--k3:#f5b94a;--k4:#4fd1bd;--k5:#8a93ad;--k6:#f58bc6;--k7:#d6b45a;--k8:#4a4d70}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%;scroll-padding-top:80px}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 var(--font);font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased;-webkit-tap-highlight-color:transparent}
button{font:inherit;color:inherit;cursor:pointer}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px;border-radius:10px}
main{max-width:1120px;margin:0 auto;padding:0 18px calc(110px + env(safe-area-inset-bottom))}
h1,h2,h3{margin:0;letter-spacing:-.01em}h2{font-size:19px;font-weight:700}h3{font-size:16px;font-weight:700}
p{margin:0}.small,small{font-size:13.5px;color:var(--ink-3);line-height:1.45}.muted{color:var(--ink-3)}
.top{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:calc(10px + env(safe-area-inset-top)) 18px 10px;margin:0 -18px;
 background:color-mix(in srgb,var(--bg) 82%,transparent);-webkit-backdrop-filter:saturate(1.6) blur(16px);backdrop-filter:saturate(1.6) blur(16px)}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:16px;letter-spacing:-.01em;min-width:0}.brand svg{width:30px;height:30px;flex:none;border-radius:9px}
.brand small{display:block;font-weight:500;font-size:12px;line-height:1.2}
.top-r{display:flex;align-items:center;gap:8px}
.icon{width:44px;height:44px;border-radius:50%;border:0;background:var(--surface);box-shadow:var(--shadow);display:grid;place-items:center;color:var(--ink)}
.icon svg{width:20px;height:20px}
.demo{margin:4px 0 6px;border-radius:14px;background:var(--warn-soft);color:var(--ink);font-size:13.5px}
.demo summary{list-style:none;display:flex;align-items:center;gap:8px;min-height:44px;padding:6px 14px;cursor:pointer}.demo summary::-webkit-details-marker{display:none}
.demo summary b{font-size:11px;letter-spacing:.08em;text-transform:uppercase;background:var(--warn);color:var(--bg);border-radius:6px;padding:2px 6px}
.demo summary span{flex:1}.demo summary i{font-style:normal;color:var(--ink-3)}.demo p{padding:0 14px 10px;line-height:1.45}
.tabs{position:fixed;z-index:30;left:50%;transform:translateX(-50%);bottom:calc(12px + env(safe-area-inset-bottom));display:flex;gap:4px;padding:6px;border-radius:999px;
 background:color-mix(in srgb,var(--surface) 88%,transparent);-webkit-backdrop-filter:saturate(1.6) blur(18px);backdrop-filter:saturate(1.6) blur(18px);box-shadow:var(--shadow-up),0 0 0 1px var(--line)}
.tabs button{border:0;background:none;min-height:48px;min-width:92px;padding:6px 16px;border-radius:999px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;font-size:12px;font-weight:600;color:var(--ink-3);transition:background .2s var(--ease),color .2s}
.tabs button svg{width:22px;height:22px}.tabs button[aria-current=page]{background:var(--accent-soft);color:var(--accent)}
.view{animation:rise .35s var(--ease)}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.ov{display:grid;gap:18px;padding-top:6px}.col{display:grid;gap:18px;align-content:start;min-width:0}
.card{background:var(--surface);border-radius:var(--r);box-shadow:var(--shadow);padding:20px}
.sec-h{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:2px 4px 12px}
.eyebrow{font-size:14px;font-weight:600;color:var(--ink-2);display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.bal{font-size:clamp(42px,12vw,56px);font-weight:750;letter-spacing:-.035em;line-height:1.05;margin:6px 0 2px}
.balsub{font-size:13.5px;color:var(--ink-3);min-height:20px}
.say{font-size:17px;line-height:1.4;margin-top:14px;font-weight:500;color:var(--ink-2)}.say b{font-weight:750}
.rate{font-size:14px;color:var(--ink-3);margin-top:6px;line-height:1.45}
.up{color:var(--up)}.down{color:var(--down)}
.chip{display:inline-flex;align-items:center;gap:6px;border:0;border-radius:999px;padding:4px 10px;font-size:12.5px;font-weight:650;background:var(--surface-2);color:var(--ink-2);min-height:26px;line-height:1.2}
button.chip{min-height:32px;position:relative}button.chip::after{content:"";position:absolute;inset:-7px -2px}.chip.est{background:var(--warn-soft);color:var(--warn)}.chip.ok{background:var(--up-soft);color:var(--up)}.chip.bad{background:var(--down-soft);color:var(--down)}
.chip.lg{min-height:44px;padding:8px 16px;font-size:14px;background:var(--surface);box-shadow:var(--shadow);color:var(--ink)}
.chartbox{position:relative;margin:18px -20px 0;touch-action:pan-y;outline-offset:-3px;cursor:crosshair;user-select:none;-webkit-user-select:none}
.chartbox svg{display:block;width:100%;height:auto;overflow:visible}
.pills{display:flex;gap:4px;padding:4px;border-radius:999px;background:var(--surface-2);overflow-x:auto;scrollbar-width:none;max-width:100%}.pills::-webkit-scrollbar{display:none}
.pills button{flex:1 0 auto;border:0;background:none;border-radius:999px;min-height:44px;padding:6px 14px;font-weight:650;font-size:14px;color:var(--ink-2);white-space:nowrap;transition:background .2s var(--ease),color .2s,box-shadow .2s}
.pills button[aria-pressed=true]{background:var(--surface);color:var(--ink);box-shadow:0 1px 3px rgba(19,19,43,.12)}
.pills button.dim{opacity:.5}
.heroCard .pills{margin-top:12px}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--ink-3);margin-top:12px}
.legend i{display:inline-block;width:18px;height:0;border-top:3px solid var(--accent);border-radius:2px;vertical-align:middle;margin-right:6px}.legend i.b{border-top:2px dashed var(--bench)}
svg .ar-line{fill:none;stroke:var(--accent);stroke-width:2.6;stroke-linejoin:round;stroke-linecap:round}
svg .ar-bench{fill:none;stroke:var(--bench);stroke-width:1.8;stroke-dasharray:5 5;opacity:.9}
svg .ar-grid{stroke:var(--line);stroke-width:1}svg .ar-ax{fill:var(--ink-3);font-size:11px;font-family:var(--font)}
svg .ar-end{fill:var(--accent)}svg .ar-halo{fill:var(--accent);opacity:.18}
svg .sc line{stroke:var(--ink-3);stroke-width:1;stroke-dasharray:3 3}svg .sc .d{fill:var(--surface);stroke:var(--accent);stroke-width:2.5}svg .sc .db{fill:var(--surface);stroke:var(--bench);stroke-width:2}
.src-row{display:grid;grid-template-columns:1fr auto;gap:4px 12px;align-items:baseline;padding:11px 0;border-bottom:1px solid var(--line)}
.src-row:last-of-type{border-bottom:0}.src-row b{font-weight:700;font-size:16px}.src-row span{font-size:15px;color:var(--ink-2);display:flex;align-items:center;gap:8px}
.src-row span i{width:10px;height:10px;border-radius:3px;display:inline-block}
.src-bar{grid-column:1/-1;height:6px;border-radius:6px;background:var(--surface-2);overflow:hidden}.src-bar u{display:block;height:100%;border-radius:6px;transform-origin:left;animation:grow .7s var(--ease)}
@keyframes grow{from{transform:scaleX(0)}to{transform:none}}
.src-tot{display:flex;justify-content:space-between;align-items:baseline;padding-top:12px;margin-top:4px;border-top:2px solid var(--line-2);font-weight:750;font-size:17px}
.cap{font-size:13px;color:var(--ink-3);line-height:1.45;margin-top:12px}
.cards{display:grid;gap:12px}
.acct{display:grid;grid-template-columns:1fr auto;grid-template-areas:"n v" "s sp" "h h";gap:2px 12px;text-align:left;width:100%;border:0;background:var(--surface);border-radius:var(--r);box-shadow:var(--shadow);padding:16px 18px;min-height:44px;
 transition:transform .18s var(--ease),box-shadow .18s var(--ease)}
.acct:hover{transform:translateY(-2px)}.acct:active{transform:scale(.985)}
.acct .n{grid-area:n;font-weight:700;font-size:16px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.acct .v{grid-area:v;font-weight:750;font-size:17px;text-align:right}
.acct .s{grid-area:s;font-size:13px;color:var(--ink-3);align-self:center}
.acct .sp{grid-area:sp;justify-self:end;width:96px;height:30px}.acct .sp svg{width:96px;height:30px;display:block}
.acct .h{grid-area:h;display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:10px;padding-top:10px;border-top:1px solid var(--line);font-size:14px;font-weight:650}
.acct .h .chev{margin-left:auto;color:var(--ink-3);font-size:20px;line-height:1}
.donut{display:grid;grid-template-columns:150px 1fr;gap:18px;align-items:center}
.donut svg{width:150px;height:150px}.donut svg circle{transition:stroke-dasharray .6s var(--ease)}
.donut ul{list-style:none;margin:0;padding:0;display:grid;gap:8px}.donut li{display:grid;grid-template-columns:12px 1fr auto;gap:8px;align-items:center;font-size:14px}
.donut li i{width:12px;height:12px;border-radius:4px}.donut li b{font-weight:700}.donut li small{grid-column:2/-1;margin-top:-6px}
.dc1{font-size:22px;font-weight:750;fill:var(--ink);font-family:var(--font)}.dc2{font-size:11px;fill:var(--ink-3);font-family:var(--font)}
.foot{margin:28px 4px 0;display:grid;gap:8px;font-size:13px;color:var(--ink-3);line-height:1.5}
.foot .disc{font-weight:650;color:var(--ink-2)}
.foot .lock{display:inline-flex;align-items:center;gap:6px}.foot .lock svg{width:14px;height:14px}
dialog.sheet{border:0;padding:0;margin:auto auto 0;width:100%;max-width:640px;max-height:92vh;max-height:92dvh;border-radius:28px 28px 0 0;background:var(--bg);color:var(--ink);box-shadow:var(--shadow-up);overflow:auto;overscroll-behavior:contain}
dialog.sheet[open]{animation:sheetup .38s var(--ease)}
@keyframes sheetup{from{transform:translateY(40px);opacity:.4}to{transform:none;opacity:1}}
dialog.sheet::backdrop{background:rgba(8,8,24,.42);-webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px)}
.sh{padding:8px 18px calc(28px + env(safe-area-inset-bottom))}.grab{width:40px;height:5px;border-radius:5px;background:var(--line-2);margin:4px auto 6px}
.sh-head{position:sticky;top:0;z-index:2;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 0 10px;background:var(--bg)}
.sh-head h2{font-size:20px}.sh-head .s{font-size:13px;color:var(--ink-3);font-weight:500}
.sh section{margin-top:14px}.sh .chartbox{margin:16px -18px 0}
.figs{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.fig{background:var(--surface);border-radius:var(--r-sm);padding:12px 14px;box-shadow:var(--shadow)}
.fig span{display:block;font-size:12.5px;color:var(--ink-3);font-weight:600;line-height:1.3}.fig b{display:block;font-size:19px;font-weight:750;margin-top:4px;letter-spacing:-.01em}
.fig em{display:block;font-style:normal;font-size:12px;color:var(--ink-3);margin-top:4px;line-height:1.35}
.fig.wide{grid-column:1/-1}
.notes{margin:0;padding-left:18px;font-size:13.5px;color:var(--ink-2);display:grid;gap:4px}
.opt .pills{flex-wrap:wrap;border-radius:20px}.opt h3{font-size:14px;color:var(--ink-3);font-weight:650;margin:18px 0 8px;text-transform:uppercase;letter-spacing:.06em}
.list{display:grid;gap:6px}.list button{display:flex;justify-content:space-between;align-items:center;text-align:left;border:0;background:var(--surface);border-radius:var(--r-sm);min-height:52px;padding:10px 16px;font-size:15px;font-weight:600;box-shadow:var(--shadow)}
.list button[aria-pressed=true]{box-shadow:0 0 0 2px var(--accent)}.list button[aria-pressed=true]::after{content:"";width:10px;height:10px;border-radius:50%;background:var(--accent)}
.tog{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:52px;background:var(--surface);border-radius:var(--r-sm);padding:10px 16px;box-shadow:var(--shadow);font-weight:600}
.tog input{width:22px;height:22px;accent-color:var(--accent)}
.dt{display:grid;grid-template-columns:minmax(0,1fr);gap:18px;padding-top:6px}.dt>*{min-width:0}.ov{grid-template-columns:minmax(0,1fr)}.ctl{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.dt h2{margin-bottom:10px}.dt figure{margin:0}
figcaption{font-size:13px;color:var(--ink-3);margin-top:10px;line-height:1.45}
svg{max-width:100%}svg text{font-family:var(--font)}svg .grid{stroke:var(--line);stroke-width:1}svg .zero{stroke:var(--ink-3);stroke-width:1.2}
svg .axis{fill:var(--ink-3);font-size:11px}svg .val{fill:var(--ink);font-size:11px}
svg .bar-pos{fill:var(--up)}svg .bar-neg{fill:var(--down)}
svg .pt-account{--pc:var(--c0)}svg .pt-group{--pc:var(--c1)}svg .pt-all{--pc:var(--c2)}svg .pt-benchmark{--pc:var(--c7)}
svg .pt circle{stroke:var(--pc);stroke-width:2.2}svg .pt circle.solid{fill:var(--pc)}svg .pt circle.hollow{fill:none}svg .pt text{fill:var(--ink)}
.key{display:flex;gap:14px;font-size:13px;flex-wrap:wrap;margin-bottom:8px}.key i{display:inline-block;width:12px;height:12px;border-radius:4px;margin-right:6px;vertical-align:-1px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:14.5px;font-variant-numeric:tabular-nums}th,td{text-align:right;padding:9px 8px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}th{font-size:12.5px;color:var(--ink-3);font-weight:650}
.total td{font-weight:750;border-top:2px solid var(--line-2)}.sub td{font-weight:600}.exact{color:var(--up)}.est{color:var(--warn)}.na{color:var(--ink-3)}.err{color:var(--down)}
.riskkey{margin:10px 0 0;padding-left:22px;display:grid;gap:3px}
details>summary{cursor:pointer;min-height:44px;display:flex;align-items:center;justify-content:space-between;gap:10px;font-weight:600;list-style:none}details>summary::-webkit-details-marker{display:none}
details:not(.demo)>summary::after{content:"";width:8px;height:8px;border-right:2px solid var(--ink-3);border-bottom:2px solid var(--ink-3);transform:rotate(45deg);transition:transform .2s;flex:none;margin-right:4px}details[open]:not(.demo)>summary::after{transform:rotate(-135deg)}
#hold details{border-top:1px solid var(--line)}
.lesson{max-width:780px;margin:0 auto;line-height:1.6}.lesson h2{font-size:22px;margin:0 0 10px}.lesson h3{margin:1.6em 0 .5em}.lesson p{margin:.6em 0}.lesson ul{margin:.4em 0 .8em 1.2em;padding:0}
.lesson table{margin:.6em 0}.lesson figure{margin:1em 0;background:var(--surface-2);border-radius:var(--r-sm);padding:12px}
.tip{border-bottom:1px dotted var(--ink-3);cursor:help;position:relative}
.tip:hover::after,.tip:focus::after{content:attr(data-tip);position:absolute;left:0;top:130%;z-index:5;width:min(300px,80vw);background:var(--ink);color:var(--bg);padding:8px 10px;border-radius:10px;font:400 13px/1.4 var(--font);text-align:left;white-space:normal;box-shadow:var(--shadow)}
[hidden]{display:none!important}
@media (min-width:900px){
 main{padding-bottom:48px}
 .top{padding-top:16px;padding-bottom:16px}
 .tabs{top:14px;bottom:auto;box-shadow:none;background:var(--surface-2);-webkit-backdrop-filter:none;backdrop-filter:none;padding:4px}
 .top{min-height:72px}
 .tabs button{flex-direction:row;min-height:44px;min-width:0;font-size:14px;gap:8px;padding:6px 16px}.tabs button svg{width:18px;height:18px}
 .tabs button[aria-current=page]{background:var(--surface);color:var(--ink);box-shadow:0 1px 3px rgba(19,19,43,.12)}
 .ov{grid-template-columns:minmax(0,1.45fr) minmax(0,1fr);gap:22px;align-items:start}.col{gap:22px}
 .card{padding:26px}.chartbox{margin:20px -26px 0}
 .bal{font-size:60px}
 dialog.sheet{margin:0 0 0 auto;height:100vh;max-height:100vh;max-width:520px;border-radius:28px 0 0 28px}
 dialog.sheet[open]{animation:sheetin .38s var(--ease)}.grab{display:none}
 @keyframes sheetin{from{transform:translateX(40px);opacity:.4}to{transform:none;opacity:1}}
}
@media (max-width:640px){
 main{padding-left:14px;padding-right:14px}.top{margin:0 -14px;padding-left:14px;padding-right:14px}
 .card{padding:18px}.chartbox{margin:16px -18px 0}
 .donut{grid-template-columns:1fr;justify-items:center}.donut ul{width:100%}
 .figs{grid-template-columns:1fr 1fr}
 .ctl .pills{width:100%}
 #tbl,#tbl tbody{display:block}#tbl tr:first-child{display:none}
 #tbl tr{display:block;border-radius:16px;padding:10px 14px;margin:0 0 10px;background:var(--surface-2)}
 #tbl tr.total{box-shadow:0 0 0 2px var(--accent)}#tbl tr.total td{border-top:0}
 #tbl td{display:flex;justify-content:space-between;align-items:baseline;gap:14px;border:0;padding:3px 0;text-align:right}
 #tbl td::before{content:attr(data-l);color:var(--ink-3);font-size:13px;font-weight:500;text-align:left}
 #tbl td:first-child{font-weight:750;font-size:1.05em;padding-bottom:5px}#tbl td:first-child::before{content:none}
 #tbl td[colspan]{display:block;text-align:left}#tbl td[colspan]::before{content:none}
}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
"""

JS = r"""
const D=JSON.parse(document.getElementById('data').textContent);
let win='inception',grp='accounts',showBench=true,tab='main',bm=D.benchmark,sheetFor=null;
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pct=x=>x==null?'n/a':(x*100).toFixed(1)+'%';
const spct=x=>x==null?'n/a':(x>=0?'+':'')+(x*100).toFixed(1)+'%';
const money=x=>x==null?'n/a':(x<0?'-':'')+'$'+Math.abs(Math.round(x)).toLocaleString('en-US');
const smoney=x=>x==null?'n/a':(x<0?'−':'+')+'$'+Math.abs(Math.round(x)).toLocaleString('en-US');
const num=x=>x==null?'n/a':x.toFixed(2);
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const fmtDate=s=>{if(!s)return '';const p=String(s).split('-');return MON[+p[1]-1]+' '+(+p[2])+', '+p[0];};
const fmtMon=s=>{if(!s)return '';const p=String(s).split('-');return MON[+p[1]-1]+' '+p[0];};
function niceTicks(lo,hi,mant,maxN){// round steps (mant x 10^k) so the range has at most maxN intervals; lo and hi are widened to whole steps
 mant=mant||[1,2,5];maxN=maxN||6;const span=Math.max(hi-lo,1e-9);let step=null;
 for(let e=-6;e<=12&&step===null;e++)for(const m of mant){const st=m*Math.pow(10,e);if(span/st<=maxN){step=st;break;}}
 const a=Math.floor(lo/step+1e-9)*step,b=Math.ceil(hi/step-1e-9)*step,tk=[];
 for(let v=a;v<=b+step/2;v+=step)tk.push(Math.round(v/step)*step);
 return {step,lo:a,hi:b,ticks:tk};}
const trim=x=>String(+x.toFixed(2));
const moneyAxis=v=>{const a=Math.abs(v),s=v<0?'-':'';return a>=1e6?s+'$'+trim(a/1e6)+'M':a>=1000?s+'$'+trim(a/1000)+'K':s+'$'+Math.round(a);};
const MONEY_STEPS=[1,2.5,5,10],PCT_STEPS=[1,2,5];
const CW=el=>Math.max(300,Math.min(860,(el&&el.clientWidth)||$('main').clientWidth||860));// charts are drawn at the screen's width so their text stays readable on a phone
const fit=(l,px)=>l.length*6.4<=px?l:l.slice(0,Math.max(3,Math.floor(px/6.4)-1))+'…';
const COLORS=Array.from({length:8},(_,i)=>`var(--c${i})`);
const GROUPS=[['accounts','Accounts'],['all','All combined'],['brokerage','By brokerage'],['owner','By owner'],['wrapper','By wrapper']];
const WSHORT={ytd:'YTD','1y':'1Y','3y':'3Y','5y':'5Y',inception:'All'};
const WRAP={taxable:'Taxable',roth_ira:'Roth IRA',traditional_ira:'Traditional IRA','401k':'401(k)',hsa:'HSA',other:'Other',combined:'Combined'};
const capS=s=>{s=String(s);return s.charAt(0).toUpperCase()+s.slice(1);};
const kmoney=x=>{const a=Math.abs(x),g=v=>String(+v.toPrecision(3));return (x<0?'-':'')+(a>=1e6?'$'+g(a/1e6)+'M':a>=1e3?'$'+g(a/1e3)+'K':'$'+Math.round(a));};
const cap1=s=>String(s).replace(/(^|[\s_-])([a-z])/g,(m,a,b)=>a.replace('_',' ')+b.toUpperCase());
const ICON={home:'<path d="M3.5 10.5 12 4l8.5 6.5V20a1 1 0 0 1-1 1H15v-6H9v6H4.5a1 1 0 0 1-1-1z"/>',details:'<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',learn:'<path d="M3 6.5C6 5 9 5 12 7c3-2 6-2 9-.5V19c-3-1.5-6-1.5-9 .5-3-2-6-2-9-.5z"/><path d="M12 7v12.5"/>'};
const svgI=p=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
function pills(items,cur,act,dim){return items.map(([k,l])=>`<button type="button" data-act="${act}" data-k="${esc(k)}" aria-pressed="${cur===k}"${dim&&dim(k)?' class="dim"':''}>${esc(l)}</button>`).join('');}
const BL=()=>(D.benchmarks.find(b=>b[0]===bm)||[0,bm])[1];
function WS(e,k){// window figures with the benchmark-side numbers of the picked benchmark
 k=k||win;const w=e.windows&&e.windows[k];if(!w||bm===D.benchmark)return w;
 const a=e.bm&&e.bm[bm]&&e.bm[bm][k];if(!a)return w;
 const o={...w,bench_irr:a.bench_irr,excess:a.excess,bench_end:a.bench_end};if(w.chart)o.chart={...w.chart,bench:a.bench};return o;}
function rows(){return D.entities.filter(e=>grp==='accounts'?e.kind==='account':(e.kind==='group'&&e.groupKind===grp));}
const totalEnt=()=>{const ac=D.entities.filter(e=>e.kind==='account');return D.entities.find(e=>e.kind==='group'&&e.groupKind==='all')||(ac.length===1?ac[0]:null);};
const isEst=(e,w)=>!(w&&w.exact&&e.quality==='exact');
function nice(e){if(e.kind!=='group')return e.label;if(e.groupKind==='all')return 'All accounts';
 const i=e.label.indexOf(': '),v=i<0?e.label:e.label.slice(i+2);return e.groupKind==='wrapper'?(WRAP[v]||cap1(v)):cap1(v);}
function subOf(e){if(e.kind==='group')return (e.members||[]).length+((e.members||[]).length===1?' account':' accounts');
 return [WRAP[e.type]||cap1(e.type||''),e.owner&&e.owner!=='household'?cap1(e.owner):(e.owner?'Household':'')].filter(Boolean).join(' · ');}
function whyOf(e,w){// plain reasons for every n/a, shown on screen (a title tooltip is invisible on a phone)
 const nm=e.market===false?'non-market account: no prices, so no return-based measures':null,wn=win!=='inception';
 return {irr:'no IRR: the dated flows and end value do not have both a deposit and a withdrawal or value',
  excess:'needs both an IRR and a benchmark IRR (none if withdrawals exceed what the benchmark could have funded)',
  bench:'none if withdrawals exceed what the benchmark could have funded',
  twr:nm||(w.unstable?'monthly returns in this window are not meaningful: some months had very little capital':wn?'needs at least 12 months of monthly returns inside this window':'needs at least 12 months of monthly returns'),
  sharpe:nm||(wn?'Sharpe is shown since inception only':'needs at least 12 months of monthly returns'),
  dd:nm||(w.unstable?'monthly returns in this window are not meaningful: some months had very little capital':'no monthly returns to measure a fall from')};}
function period(w){if(win==='inception')return null;return win==='ytd'?'this year':win==='1y'?'over the last year':'over the last '+win[0]+' years';}
function perYr(w){return w&&!w.cum;}
function verdict(w,short){// "$23,804 behind the same money in Market (VT)"
 if(!w||w.bench_end==null||w.value==null)return null;const d=w.value-w.bench_end,lbl=short?bm:BL();
 if(Math.abs(d)<1)return `even with the same money in ${esc(lbl)}`;
 return `<b class="${d>=0?'up':'down'}">${money(Math.abs(d))} ${d>=0?'ahead of':'behind'}</b> the same money in ${esc(lbl)}`;}
function excessWords(w){if(!w||w.excess==null)return null;if(Math.abs(w.excess)<0.0005)return `<span>About even with ${esc(bm)}${perYr(w)?'':' for the period'}</span>`;const x=Math.abs(w.excess*100).toFixed(1)+'%',ah=w.excess>=0;
 return `<span class="${ah?'up':'down'}">${ah?'▲':'▼'} ${x}${perYr(w)?' a year':''} ${ah?'ahead of':'behind'} ${esc(bm)}</span>`;}
function trow(e,label,cls){
  if(e.error||!e.windows)return `<tr class="${cls}"><td>${label}</td><td>${esc(e.type||'')}</td><td colspan="${NCOLS-2}" class="err">not computed: ${esc(e.error)}</td></tr>`;
  const w=WS(e);
  if(!w)return `<tr class="${cls}"><td>${label}</td><td>${esc(e.type)}</td><td>${e.start}</td><td colspan="${NCOLS-3}" class="na" title="${esc(e.unreconciled?'estimated, does not reconcile: '+e.unreconciled+'. Windowed figures are left out rather than shown wrong; the since-inception IRR is unaffected.':e.kind==='group'?'the combined line starts after this window begins, or has under a month of history in it':'this account starts after the window begins, or is closed')}">n/a: ${e.unreconciled?'estimated, does not reconcile':'does not cover this window'}</td></tr>`;
  const q=e.unreconciled?'estimated, does not reconcile':w.exact&&e.quality==='exact'?'exact':'estimated';
  const why=whyOf(e,w);
  const c=(f,v,k)=>v==null?`<td class="na" title="${esc(why[k])}">n/a</td>`:`<td>${f(v)}</td>`;
  return `<tr class="${cls}"><td>${label}${e.closed?' <span class="small">(closed)</span>':''}</td><td>${esc(e.type)}</td><td>${e.start}</td><td>${money(w.value)}</td><td>${money(w.net_in)}</td>`+
   c(pct,w.irr,'irr')+(w.twr_thru&&w.twr!=null&&w.twr_thru!==w.thru?`<td title="through ${w.twr_thru}">${pct(w.twr)}</td>`:c(pct,w.twr,'twr'))+c(spct,w.excess,'excess')+c(money,w.bench_end,'bench')+c(num,w.sharpe,'sharpe')+c(pct,w.dd,'dd')+
   `<td class="${q==='exact'?'exact':'est'}" title="${esc((e.flags||[]).join('; ')+(e.excluded&&e.excluded.length?'; left out, does not reconcile: '+e.excluded.join(', '):''))}">${q}, as of ${w.thru||e.as_of}${e.note?' (common month-end)':''}${e.excluded&&e.excluded.length?'; left out, does not reconcile: '+esc(e.excluded.join(', ')):''}${(e.flags||[]).some(f=>f.startsWith('history ends'))?' *':''}</td>`+D.extras.map(n=>c(spct,w.extras[n]&&w.extras[n].excess,'excess')).join('')+'</tr>';}
let NCOLS=12;
function table(rs){
 const head=['Account','Type','Started','Value','Net in','IRR','Time-weighted return (est.)','Excess IRR vs '+BL(),'Worth today in '+BL(),'Sharpe (est.)','Worst fall','Data']
  .concat(D.extras.map(n=>'Excess vs '+n));
 NCOLS=head.length;
 let s='<tr>'+head.map(x=>`<th>${esc(x)}</th>`).join('')+'</tr>';
 for(const e of rs)s+=trow(e,esc(e.label),grp==='accounts'||e.kind==='account'?'':'sub');
 const tot=D.entities.find(e=>e.kind==='group'&&e.groupKind==='all');
 const showTot=tot&&grp!=='all';
 if(showTot)s+=trow(tot,'Total, all accounts','total');
 $('#tbl').innerHTML=s;
 $('#tbl').querySelectorAll('tr').forEach((tr,i)=>{if(!i)return;let c=0;for(const td of tr.children){td.dataset.l=head[c]||'';c+=td.colSpan||1;}});// card labels on phones
 const t2=grp==='all'?rs[0]:tot;
 $('#totnote').textContent=t2&&t2.as_of?`The total is valued on ${t2.as_of}${t2.note?', the latest month-end every account covers':''}; account rows use each account's own latest date, so the sums can differ. `+
  'Non-market accounts (a fixed annuity) count in value and net in. Transfers between your own accounts net out of combined lines, so their Net in can differ from the sum of the rows.'+
  (grp!=='accounts'&&grp!=='all'?' Each group row is a subtotal for its members, valued on that group\'s own common month-end.':''):'';}
function bars(rs){
 const items=rs.filter(e=>WS(e)&&WS(e).excess!=null).map(e=>[e.label,WS(e).excess]).sort((a,b)=>b[1]-a[1]);
 if(!items.length){$('#bars').innerHTML='<p class="na">Nothing to chart for this window.</p>';return;}
 const W=CW($('#bars')),rh=30,L=Math.min(200,Math.round(W*0.34)),R=W<520?52:70,H=items.length*rh+44,mx=Math.max(...items.map(i=>Math.abs(i[1])),0.01),nar=W<520,bt=niceTicks(0,mx,PCT_STEPS.map(q=>q/100),nar?1:3),m=bt.hi,half=(W-L-R)/2,x0=L+half,sc=(half-(nar?40:60))/m;
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Excess IRR per account">`;
 for(const u of bt.ticks.flatMap(q=>q===0?[0]:[q,-q]))s+=`<line class="${u===0?'zero':'grid'}" x1="${x0+u*sc}" x2="${x0+u*sc}" y1="6" y2="${H-26}"/><text class="axis" x="${x0+u*sc}" y="${H-10}" text-anchor="middle">${u===0?'0%':spct(u)}</text>`;
 items.forEach(([l,v],i)=>{const y=10+i*rh,w=Math.abs(v)*sc;
  s+=`<text class="val" x="${L-8}" y="${y+14}" text-anchor="end"><title>${esc(l)}</title>${esc(fit(l,L-12))}</text><rect class="${v>=0?'bar-pos':'bar-neg'}" x="${v>=0?x0:x0-w}" y="${y}" width="${w}" height="18" rx="5"/>`+
     `<text class="val" x="${v>=0?x0+w+6:x0-w-6}" y="${y+14}" text-anchor="${v>=0?'start':'end'}">${spct(v)}</text>`;});
 $('#bars').innerHTML=s+'</svg>';}
function view(e){// the series to chart for the picked window, or null when the entity does not cover it
 if(!e||e.error)return null;
 if(win==='inception'){if(!e.months)return null;const a=bm!==D.benchmark&&e.bm&&e.bm[bm]&&e.bm[bm].inception;return a?{label:e.label,months:e.months,values:e.values,bench:a.bench}:e;}
 const w=WS(e);return w&&w.chart?{label:e.label,months:w.chart.months,values:w.chart.values,bench:w.chart.bench}:null;}
function lines(rs){
 const es=rs.map(view).filter(Boolean);
 if(!es.length){$('#lines').innerHTML='<p class="na">Nothing to chart for this window.</p>';$('#key').innerHTML='';return;}
 const tm=d=>Date.parse(d),all=es.flatMap(e=>e.months.map(tm)),t0=Math.min(...all),t1=Math.max(...all);
 const ys=es.flatMap(e=>e.values.concat(showBench?e.bench:[])),yt=niceTicks(0,Math.max(...ys,1),MONEY_STEPS,5),ymax=yt.hi;
 const W=CW($('#lines')),H=W<520?240:300,L=W<520?52:64,R=14,T=12,B=28,X=d=>L+(tm(d)-t0)/((t1-t0)||1)*(W-L-R),Y=v=>T+(H-T-B)*(1-v/ymax);
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Account value over time">`;
 for(const v of yt.ticks){s+=`<line class="${v===0?'zero':'grid'}" x1="${L}" x2="${W-R}" y1="${Y(v)}" y2="${Y(v)}"/><text class="axis" x="${L-6}" y="${Y(v)+4}" text-anchor="end">${moneyAxis(v)}</text>`;}
 const y0=new Date(t0).getUTCFullYear(),y1=new Date(t1).getUTCFullYear();
 for(let y=y0+1;y<=y1;y++){const d=`${y}-01-01`;s+=`<text class="axis" x="${X(d)}" y="${H-8}" text-anchor="middle">${y}</text>`;}
 es.forEach((e,i)=>{const c=COLORS[i%8],pts=a=>e.months.map((m,j)=>`${X(m).toFixed(1)},${Y(a[j]).toFixed(1)}`).join(' ');
  if(showBench&&e.bench.length)s+=`<polyline fill="none" stroke="${c}" stroke-width="1.6" stroke-dasharray="5 4" opacity=".7" points="${pts(e.bench)}"/>`;
  s+=`<polyline fill="none" stroke="${c}" stroke-width="2.4" stroke-linejoin="round" points="${pts(e.values)}"/>`;});
 $('#lines').innerHTML=s+'</svg>';
 $('#key').innerHTML=es.map((e,i)=>`<span><i style="background:${COLORS[i%8]}"></i>${esc(e.label)}</span>`).join('')+(showBench?`<span class="small">dashed: same deposits and withdrawals in ${esc(BL())}</span>`:'');}
function scatter(){
 const R=D.risk[win],keep=p=>(p.kind==='benchmark'&&p.label!==D.benchmark)||p.kind==='all'||(grp==='accounts'?p.kind==='account':(grp!=='all'&&p.gk===grp)),P=R.points.filter(keep).concat(R.bm[bm]?[{...R.bm[bm],label:BL(),kind:'benchmark',exact:win==='inception'}]:[]),LO=R.left_off.filter(a=>keep({kind:a[2],gk:a[3],label:a[0]}));
 if(P.length<2){$('#risk').innerHTML='<p class="na">Not enough history (12 months) for a risk and return chart.</p>';}
 else{
  const W=CW($('#risk')),H=W<520?320:380,L=64,Rr=40,T=14,B=44,PS=PCT_STEPS.map(m=>m/100),xt=niceTicks(0,Math.max(...P.map(p=>p.vol),0.01),PS,6),xm=xt.hi,
   yt=niceTicks(Math.min(0,...P.map(p=>p.ret)),Math.max(0.01,...P.map(p=>p.ret)),PS,6),y0=yt.lo,y1=yt.hi;
  const X=v=>L+v/xm*(W-L-Rr),Y=v=>T+(H-T-B)*(1-(v-y0)/((y1-y0)||1));
  let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Risk versus return">`;
  for(const v of yt.ticks)s+=`<line class="${v===0?'zero':'grid'}" x1="${L}" x2="${W-Rr}" y1="${Y(v)}" y2="${Y(v)}"/><text class="axis" x="${L-6}" y="${Y(v)+4}" text-anchor="end">${pct(v)}</text>`;
  for(const u of xt.ticks)s+=`<line class="grid" x1="${X(u)}" x2="${X(u)}" y1="${T}" y2="${H-B}"/><line class="zero" x1="${X(u)}" x2="${X(u)}" y1="${Y(0)}" y2="${Y(0)+4}"/><text class="axis" x="${X(u)}" y="${H-24}" text-anchor="middle">${pct(u)}</text>`;
  s+=`<text class="axis" x="${(L+W-Rr)/2}" y="${H-6}" text-anchor="middle">Volatility (annual, lower is calmer)</text><text class="axis" x="14" y="${(T+H-B)/2}" text-anchor="middle" transform="rotate(-90 14 ${(T+H-B)/2})">Return per year</text>`;
  const placed=[];let leg='<ol class="small riskkey">';
  P.forEach((p,i)=>{const n=i+1,cx=X(p.vol),cy=Y(p.ret),left=cx>W*0.7,tx=left?cx-11:cx+11;let ty=cy+4;
   while(placed.some(q=>Math.abs(q[0]-tx)<22&&Math.abs(q[1]-ty)<12))ty+=12;placed.push([tx,ty]);
   const tip=`${p.label}: return ${pct(p.ret)}, volatility ${pct(p.vol)}, Sharpe ${num(p.sharpe)}${p.exact?'':' (estimated)'}`;
   s+=`<g class="pt pt-${p.kind}"><title>${esc(tip)}</title><circle class="${p.exact?'solid':'hollow'}" cx="${cx}" cy="${cy}" r="${p.kind==='all'?9:6}"/>`+
      `<text class="axis" x="${tx}" text-anchor="${left?'end':'start'}" y="${ty}">${n}</text></g>`;
   leg+=`<li value="${n}">${esc(p.label)} · return ${pct(p.ret)}, volatility ${pct(p.vol)}, Sharpe ${num(p.sharpe)}${p.exact?'':' (estimated)'}</li>`;});
  $('#risk').innerHTML=s+'</svg>'+leg+'</ol>';}
 $('#riskleft').textContent=LO.length?'Not on the chart: '+LO.map(([l,w])=>l+' ('+w+')').join('; ')+'.':'';}
function holdings(){
 const shown=new Set(rows().flatMap(e=>e.members||[e.label])),vis=D.entities.filter(e=>e.kind==='account'&&(grp==='all'||shown.has(e.label))),es=vis.filter(e=>e.holdings),
  na=vis.filter(e=>!e.holdings&&e.holdings_note).map(e=>`<li>${esc(e.label)}: ${esc(e.holdings_note)}</li>`).join('');
 if(!es.length){$('#hold').innerHTML=na?'<h2>What each account holds</h2><ul class="small">'+na+'</ul>':'';return;}
 const keys=D.classes.filter(([k])=>es.some(e=>e.holdings.by_class[k]));
 let s='<h2>What each account holds</h2><div class="scroll"><table><tr><th>Account</th>'+keys.map(([k,l])=>`<th>${esc(l)}</th>`).join('')+'</tr>';
 for(const e of es)s+=`<tr><td>${esc(e.label)}</td>`+keys.map(([k])=>`<td>${e.holdings.by_class[k]?pct(e.holdings.by_class[k]):'-'}</td>`).join('')+'</tr>';
 s+='</table></div>';
 for(const e of es)s+=`<details><summary>${esc(e.label)}: ${money(e.holdings.total)} as of ${esc(e.holdings.as_of)}</summary>${fundTable(e)}</details>`;
 $('#hold').innerHTML=s+'<p class="small">Classes come from your local file .data/asset_classes.json; tickers missing from it show as Unclassified. Funds with world or global in the name count as Global stock, and balanced or target-date funds as Balanced, unless the file says otherwise.</p>'+(na?'<ul class="small">'+na+'</ul>':'');}
function fundTable(e){const names=Object.fromEntries(D.classes);
 return '<div class="scroll"><table><tr><th>Fund</th><th>Class</th><th>Value</th><th>Weight</th></tr>'+
  e.holdings.rows.map(r=>`<tr><td>${esc(r.symbol)}${r.name?' <span class="small">'+esc(r.name)+'</span>':''}</td><td>${esc(names[r.cls])}</td><td>${money(r.value)}</td><td>${pct(r.weight)}</td></tr>`).join('')+'</table></div>';}
function sharpeTab(){
 const L=bm===D.benchmark?D.lesson:(D.lessons[bm]||D.lesson);$('#lesson').innerHTML=L.html;
 const P=L.points,c=$('#sharpechart');if(!c)return;
 if(!P){c.innerHTML='<p class="na">n/a: the chart needs the T-bill rate and at least two months of returns.</p>';return;}
 const pts=[{k:'portfolio',label:'Your portfolio',...P.portfolio},{k:'benchmark',label:BL(),...P.benchmark}].filter(p=>p.ret!=null&&p.vol!=null);
 const W=CW(c),H=W<520?300:340,Lm=64,Rm=40,T=14,B=44,PS=PCT_STEPS.map(m=>m/100),
  xt=niceTicks(0,Math.max(...pts.map(p=>p.vol),0.01),PS,6),xm=xt.hi,
  yt=niceTicks(Math.min(0,P.rf,...pts.map(p=>p.ret)),Math.max(0.01,P.rf,...pts.map(p=>p.ret)),PS,6),y0=yt.lo,y1=yt.hi;
 const X=v=>Lm+v/xm*(W-Lm-Rm),Y=v=>T+(H-T-B)*(1-(v-y0)/((y1-y0)||1));
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Sharpe ratio as the slope of a line from the risk-free point">`;
 for(const v of yt.ticks)s+=`<line class="${v===0?'zero':'grid'}" x1="${Lm}" x2="${W-Rm}" y1="${Y(v)}" y2="${Y(v)}"/><text class="axis" x="${Lm-6}" y="${Y(v)+4}" text-anchor="end">${pct(v)}</text>`;
 for(const u of xt.ticks)s+=`<line class="grid" x1="${X(u)}" x2="${X(u)}" y1="${T}" y2="${H-B}"/><text class="axis" x="${X(u)}" y="${H-24}" text-anchor="middle">${pct(u)}</text>`;
 s+=`<text class="axis" x="${(Lm+W-Rm)/2}" y="${H-6}" text-anchor="middle">Volatility (annual)</text>`;
 pts.forEach((p,i)=>{const col=p.k==='portfolio'?'var(--c0)':'var(--c6)';
  s+=`<g class="pt"><title>${esc(p.label)}: return ${pct(p.ret)}, volatility ${pct(p.vol)}, Sharpe ${num(p.sharpe)}</title><line x1="${X(0)}" y1="${Y(P.rf)}" x2="${X(p.vol)}" y2="${Y(p.ret)}" stroke="${col}" stroke-width="2" stroke-dasharray="${p.k==='portfolio'?'0':'6 4'}"/>`+
   `<circle cx="${X(p.vol)}" cy="${Y(p.ret)}" r="6" fill="${col}"/><text class="axis" x="${X(p.vol)>W*(W<520?0.5:0.7)?X(p.vol)-10:X(p.vol)+10}" text-anchor="${X(p.vol)>W*(W<520?0.5:0.7)?'end':'start'}" y="${Y(p.ret)+(i?16:-8)}">${esc(p.label)} · slope ${num(p.sharpe)}</text></g>`;});
 s+=`<circle cx="${X(0)}" cy="${Y(P.rf)}" r="5" fill="none" stroke="var(--ink)" stroke-width="2"/><text class="axis" x="${X(0)+10}" y="${Y(P.rf)-8}">Risk-free (T-bill) ${pct(P.rf)}</text>`;
 c.innerHTML=s+'</svg>';
 $('#sharpecap').textContent='Each line starts at the risk-free point (zero risk, the T-bill return) and ends at a portfolio. The steeper the line, the higher the Sharpe ratio: its slope is the Sharpe ratio. Returns here are the average month times 12, so they differ slightly from the compounded figures in the Risk versus return chart.';}

/* ---------- Overview: balance, one chart, where the money came from, account cards, mix ---------- */
const CH={};// chart geometry by key, for scrubbing
function smooth(P){// monotone cubic through the points: no overshoot, so the curve never shows a value that was not there
 const n=P.length,F=p=>p[0].toFixed(1)+','+p[1].toFixed(1);if(n<3)return P.map((p,i)=>(i?'L':'M')+F(p)).join('');
 const dx=[],s=[],m=[];for(let i=0;i<n-1;i++){dx[i]=(P[i+1][0]-P[i][0])||1e-6;s[i]=(P[i+1][1]-P[i][1])/dx[i];}
 m[0]=s[0];m[n-1]=s[n-2];for(let i=1;i<n-1;i++)m[i]=s[i-1]*s[i]<=0?0:(s[i-1]+s[i])/2;
 for(let i=0;i<n-1;i++){if(s[i]===0){m[i]=0;m[i+1]=0;continue;}const a=m[i]/s[i],b=m[i+1]/s[i],q=a*a+b*b;if(q>9){const k=3/Math.sqrt(q);m[i]=k*a*s[i];m[i+1]=k*b*s[i];}}
 let d='M'+F(P[0]);for(let i=0;i<n-1;i++){const h=dx[i]/3;d+=`C${(P[i][0]+h).toFixed(1)},${(P[i][1]+m[i]*h).toFixed(1)} ${(P[i+1][0]-h).toFixed(1)},${(P[i+1][1]-m[i+1]*h).toFixed(1)} ${F(P[i+1])}`;}
 return d;}
function area(key,v,W,H){// a smooth value area with the benchmark path dashed; returns svg markup and keeps the geometry for scrubbing
 const tm=v.months.map(d=>Date.parse(d)),t0=tm[0],t1=tm[tm.length-1],bs=showBench&&v.bench&&v.bench.length===v.values.length?v.bench:[];
 const all=v.values.concat(bs).filter(x=>x!=null),mn=Math.min(...all),mx=Math.max(...all,1);
 const lo0=mn<0||mn<0.35*mx?Math.min(0,mn):mn-(mx-mn)*0.25,yt=niceTicks(lo0,mx,MONEY_STEPS,4),ylo=yt.lo,yhi=mx+(mx-ylo)*0.06,T=18,B=26,P=10;
 const X=x=>P+(x-t0)/((t1-t0)||1)*(W-2*P),Y=y=>T+(H-T-B)*(1-(y-ylo)/((yhi-ylo)||1));
 const pv=v.values.map((y,i)=>[X(tm[i]),Y(y)]),pb=bs.map((y,i)=>[X(tm[i]),Y(y)]),ln=smooth(pv),id='g'+key;
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Value over time, with the same deposits and withdrawals in ${esc(BL())}"><defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--accent)" stop-opacity=".28"/><stop offset="1" stop-color="var(--accent)" stop-opacity="0"/></linearGradient></defs>`;
 for(const g of yt.ticks.slice(1).filter(q=>q<=yhi))s+=`<line class="ar-grid" x1="0" x2="${W}" y1="${Y(g).toFixed(1)}" y2="${Y(g).toFixed(1)}"/><text class="ar-ax" x="${P+10}" y="${(Y(g)-5).toFixed(1)}">${moneyAxis(g)}</text>`;
 s+=`<path d="${ln}L${pv[pv.length-1][0].toFixed(1)},${Y(ylo).toFixed(1)}L${pv[0][0].toFixed(1)},${Y(ylo).toFixed(1)}Z" fill="url(#${id})"/>`;
 if(pb.length)s+=`<path class="ar-bench" d="${smooth(pb)}"/>`;
 s+=`<path class="ar-line" d="${ln}"/>`;
 const e=pv[pv.length-1];s+=`<circle class="ar-halo" cx="${e[0]}" cy="${e[1]}" r="9"/><circle class="ar-end" cx="${e[0]}" cy="${e[1]}" r="4.5"/>`;
 s+=`<text class="ar-ax" x="${P+2}" y="${H-6}">${fmtMon(v.months[0])}</text><text class="ar-ax" x="${W-P-2}" y="${H-6}" text-anchor="end">${fmtDate(v.months[v.months.length-1])}</text>`;
 s+=`<g class="sc" id="sc-${key}" opacity="0"><line x1="0" x2="0" y1="${T-8}" y2="${H-B}"/>${pb.length?'<circle class="db" r="4.5"/>':''}<circle class="d" r="6"/></g></svg>`;
 CH[key]={W,pv,pb,v:{months:v.months,values:v.values,bench:bs},i:null};
 return s;}
function scrub(key,i){const g=CH[key];if(!g||typeof document.getElementById!=='function')return;const n=g.pv.length;i=Math.max(0,Math.min(n-1,i));g.i=i;
 const el=document.getElementById('sc-'+key);if(!el||!el.setAttribute)return;el.setAttribute('opacity','1');
 const p=g.pv[i];el.querySelector('line').setAttribute('x1',p[0]);el.querySelector('line').setAttribute('x2',p[0]);
 const d=el.querySelector('.d');d.setAttribute('cx',p[0]);d.setAttribute('cy',p[1]);
 const db=el.querySelector('.db');if(db&&g.pb[i]){db.setAttribute('cx',g.pb[i][0]);db.setAttribute('cy',g.pb[i][1]);}
 const last=i===n-1,b=g.v.bench[i],when=`${fmtDate(g.v.months[i])} · ${last?'latest value':'estimated month-end'}`,bt=b!=null?` · ${esc(bm)} path ${money(b)}`:'';
 const val=document.getElementById('val-'+key),sub=document.getElementById('sub-'+key);
 if(val)val.textContent=money(g.v.values[i]);if(sub)sub.innerHTML=when+bt;}
function unscrub(key){const g=CH[key];if(!g)return;g.i=null;const el=document.getElementById('sc-'+key);if(el&&el.setAttribute)el.setAttribute('opacity','0');
 const val=document.getElementById('val-'+key),sub=document.getElementById('sub-'+key);if(val&&val.dataset)val.textContent=val.dataset.d;if(sub&&sub.dataset)sub.innerHTML=sub.dataset.d;}
function hero(){// the first thing on a phone: what it is worth, and the same money in the benchmark, in dollars
 const accts=D.entities.filter(e=>e.kind==='account'),t=totalEnt(),wi=t&&!t.error&&WS(t,'inception');
 if(!wi||wi.value==null){$('#hero').innerHTML='';$('#chart').innerHTML='';$('#src').innerHTML='<p class="small">Nothing to show yet.</p>';return;}
 const ex=t.excluded||[],w=WS(t),n=accts.length-ex.length,est=isEst(t,w),asof=w&&w.thru||t.as_of,sub=`${ex.length?n+' of '+accts.length+' accounts':n===1?'One account':n+' accounts'} · as of ${fmtDate(asof)}`;
 let s=`<h1 class="eyebrow">All investments ${est?'<button type="button" class="chip est" data-act="info" data-k="est">Estimated</button>':'<span class="chip ok">Exact</span>'}</h1>`+
  `<p class="bal" id="val-hero" data-d="${money(wi.value)}">${money(wi.value)}</p><p class="balsub" id="sub-hero" data-d="${esc(sub)}">${esc(sub)}</p>`;
 if(ex.length)s+=`<p class="small"><span class="chip bad">Partial</span> Left out of this total because their history does not match their statements yet: ${esc(ex.join(', '))}.</p>`;
 if(t.note)s+=`<p class="small">The total is ${esc(t.note)}${/non-market/.test(t.note)?' (a fixed annuity counts in value and deposits; it has no market prices)':''}.</p>`;
 if(!w)s+=`<p class="say">Your accounts do not go back ${({ytd:'to the start of the year','1y':'a full year','3y':'3 years','5y':'5 years'})[win]||'that far'} yet. Pick a shorter period.</p>`;
 else{const v=verdict(w),pd=period(w);
  s+=`<p class="say">${v?(pd?capS(pd)+', ':'')+v+(pd?'.':' since '+esc(fmtMon(t.start))+'.'):'No benchmark comparison for this period.'}</p>`;
  if(w.irr!=null)s+=`<p class="rate">Your money earned <b>${pct(w.irr)}</b>${perYr(w)?' a year':''}${w.bench_irr!=null?`; the same deposits and withdrawals in ${esc(bm)} earned ${pct(w.bench_irr)}`:''}. Money-weighted (IRR)${perYr(w)?'':', for the period, not annualized'}.</p>`;}
 $('#hero').innerHTML=s;
 const v=view(t),box=$('#chart');
 box.innerHTML=v&&v.months.length>1?area('hero',v,CW(box),CW(box)<520?210:260):'';
 $('#lgd').innerHTML=v?`<span><i></i>Your accounts</span>${showBench&&v.bench&&v.bench.length?`<span><i class="b"></i>Same money in ${esc(bm)}</span>`:''}`:'';
 $('#wins').innerHTML=pills(D.windows.map(([k])=>[k,WSHORT[k]||k]),win,'win',k=>!WS(t,k));
 $('#chartcap').textContent='Touch and drag the chart to see a month. Month-end values are estimated from your history; today\'s value is '+(t.quality==='exact'?'exact':'from your statements and snapshots')+'.';
 sources(t,w);}
function sources(t,w){// where the money came from: opening value, deposits, withdrawals and what the investments earned
 if(!w){$('#src').innerHTML='<p class="small">Not available for this period.</p>';return;}
 const open=win==='inception'?0:(w.chart?w.chart.values[0]:null),gain=open==null?null:w.value-open-w.net_in,dep=w.dep,wd=w.wd;
 const items=[];if(win!=='inception')items.push(['Value on '+fmtDate(w.open),open,'var(--k5)','start']);
 if(dep!=null){items.push(['Deposits',dep,'var(--accent)','dep']);items.push(['Withdrawals',-wd,'var(--k3)','wd']);}else items.push(['Net deposits',w.net_in,'var(--accent)','dep']);
 if(gain!=null)items.push([gain>=0?'Investment gain':'Investment loss',gain,gain>=0?'var(--up)':'var(--down)','gain']);
 const mx=Math.max(...items.map(r=>Math.abs(r[1]||0)),1);
 $('#src').innerHTML=items.map(([l,a,c,k])=>`<div class="src-row" data-k="${k}"><span><i style="background:${c}"></i>${esc(l)}</span><b class="${k==='gain'?(a>=0?'up':'down'):''}">${k==='start'?money(a):smoney(a)}</b><div class="src-bar"><u style="width:${(Math.abs(a||0)/mx*100).toFixed(1)}%;background:${c}"></u></div></div>`).join('')+
  `<div class="src-tot"><span>${win==='inception'?'Worth today':'Worth on '+fmtDate(w.thru||t.as_of)}</span><span>${money(w.value)}</span></div>`+
  `<p class="cap">Deposits and withdrawals are money moving in and out; moves between your own accounts net out of the total. Investment ${gain!=null&&gain<0?'loss':'gain'} is everything else: price changes, dividends and interest, after fees, before tax.${win!=='inception'?' The opening value is a month-end estimate.':''}</p>`;}
function spark(v){if(!v||!v.values||v.values.length<2)return '';const W=96,H=30,vs=v.values,mn=Math.min(...vs),mx=Math.max(...vs),r=(mx-mn)||1;
 const P=vs.map((y,i)=>[2+i/(vs.length-1)*(W-4),3+(H-6)*(1-(y-mn)/r)]),up=vs[vs.length-1]>=vs[0];
 return `<svg viewBox="0 0 ${W} ${H}" aria-hidden="true"><path d="${smooth(P)}" fill="none" stroke="var(--${up?'accent':'down'})" stroke-width="2" stroke-linecap="round"/></svg>`;}
function card(e){// one rounded card per row: name, balance, sparkline and one plain headline number
 const k=esc(e.label),open=`type="button" class="acct" data-act="open" data-k="${k}"`;
 if(e.error||!e.windows)return `<button ${open}><span class="n">${esc(nice(e))}</span><span class="v">n/a</span><span class="s">${esc(subOf(e))}</span><span class="h"><span class="chip bad">Not computed</span><span class="small">${esc(e.error||'')}</span><span class="chev">›</span></span></button>`;
 const w=WS(e),wi=WS(e,'inception'),val=(w||wi||{}).value,tags=[];
 if(e.unreconciled)tags.push('<span class="chip bad">Does not reconcile</span>');else if(w&&isEst(e,w))tags.push('<span class="chip est">Estimated</span>');
 if(e.closed)tags.push('<span class="chip">Closed</span>');
 if(e.market===false)tags.push('<span class="chip">No market prices</span>');
 const head=!w?'<span class="na">Not open for this whole period</span>':(excessWords(w)||'<span class="na">No benchmark comparison</span>');
 return `<button ${open}><span class="n">${esc(nice(e))}</span><span class="v">${money(val)}</span><span class="s">${esc(subOf(e))}</span><span class="sp">${spark(view(e))}</span>`+
  `<span class="h">${head}${tags.join('')}<span class="chev">›</span></span></button>`;}
function cards(){const rs2=rows();$('#cards').innerHTML=rs2.length?rs2.map(card).join(''):'<p class="small">No accounts to show for this grouping.</p>';
 $('#grpbtn').innerHTML=`${esc((GROUPS.find(g=>g[0]===grp)||GROUPS[0])[1])} <span aria-hidden="true">▾</span>`;}
function classMix(es){const by={};for(const e of es){const h=e.holdings;for(const [k,wt] of Object.entries(h.by_class))by[k]=(by[k]||0)+wt*h.total;}
 const sum=Object.values(by).reduce((a,b)=>a+b,0);return {by,sum};}
function donut(by,sum,center){const R=54,C=2*Math.PI*R;let off=0,s='';const keys=D.classes.map(c=>c[0]).filter(k=>by[k]>0);
 keys.forEach(k=>{const f=by[k]/sum,len=Math.max(0,f*C-(keys.length>1?2:0));const ci=D.classes.findIndex(c=>c[0]===k);
  s+=`<circle cx="75" cy="75" r="${R}" fill="none" stroke="var(--k${ci%9})" stroke-width="20" stroke-dasharray="${len.toFixed(2)} ${(C-len).toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}" transform="rotate(-90 75 75)"/>`;off+=f*C;});
 const names=Object.fromEntries(D.classes);
 return `<svg viewBox="0 0 150 150" role="img" aria-label="Mix by asset class"><circle cx="75" cy="75" r="${R}" fill="none" stroke="var(--surface-2)" stroke-width="20"/>${s}<text class="dc1" x="75" y="78" text-anchor="middle">${center[0]}</text><text class="dc2" x="75" y="96" text-anchor="middle">${center[1]}</text></svg>`+
  '<ul>'+keys.map(k=>{const ci=D.classes.findIndex(c=>c[0]===k);return `<li><i style="background:var(--k${ci%9})"></i><span>${esc(names[k])}</span><b>${pct(by[k]/sum)}</b><small>${money(by[k])}</small></li>`;}).join('')+'</ul>';}
function mix(){// the whole household's mix by asset class, from each account's latest holdings
 const acc=D.entities.filter(e=>e.kind==='account'&&!e.closed),es=acc.filter(e=>e.holdings&&e.holdings.total>0),box=$('#mix');
 if(!es.length){box.innerHTML='<p class="small">No holdings in these files, so no mix to show.</p>';return;}
 const {by,sum}=classMix(es),dates=[...new Set(es.map(e=>e.holdings.as_of))].sort(),left=acc.filter(e=>!es.includes(e));
 box.innerHTML=`<div class="donut">${donut(by,sum,[kmoney(sum),'in '+es.length+' account'+(es.length===1?'':'s')])}</div>`+
  `<p class="cap">From holdings as of ${dates.map(fmtDate).join(', ')}.${left.length?' Not included: '+left.map(e=>esc(e.label)+(e.holdings_note?' ('+esc(e.holdings_note)+')':e.market===false?' (non-market)':'')).join('; ')+'.':''}</p>`;}

/* ---------- Detail sheet ---------- */
function fig(label,val,note,wide){return `<div class="fig${wide?' wide':''}"><span>${esc(label)}</span><b>${val}</b>${note?`<em>${esc(note)}</em>`:''}</div>`;}
function sheetHtml(e){
 const head=`<div class="sh-head"><div><h2 id="sheet-h">${esc(nice(e))}</h2><div class="s">${esc(subOf(e))}${e.start?' · since '+esc(fmtMon(e.start)):''}</div></div><button type="button" class="icon" data-act="close" aria-label="Close">${svgI('<path d="M6 6l12 12M18 6 6 18"/>')}</button></div>`;
 if(e.error||!e.windows)return head+`<section><p class="err">Not computed: ${esc(e.error||'')}</p></section>`;
 const w=WS(e),wi=WS(e,'inception'),val=(w||wi).value,est=isEst(e,w);
 let s=head+`<section><p class="eyebrow">${e.unreconciled?'<span class="chip bad">Does not reconcile</span>':est?'<button type="button" class="chip est" data-act="info" data-k="est">Estimated</button>':'<span class="chip ok">Exact</span>'}${e.closed?'<span class="chip">Closed</span>':''}${e.market===false?'<span class="chip">No market prices</span>':''}</p>`+
  `<p class="bal" id="val-sheet" data-d="${money(val)}">${money(val)}</p><p class="balsub" id="sub-sheet" data-d="as of ${esc(fmtDate(w&&w.thru||e.as_of))}">as of ${esc(fmtDate(w&&w.thru||e.as_of))}</p>`;
 if(w){const v=verdict(w),pd=period(w);if(v)s+=`<p class="say">${pd?capS(pd)+', ':''}${v}${pd?'.':' since '+esc(fmtMon(e.start))+'.'}</p>`;}
 s+=`<div class="pills" style="margin-top:14px">${pills(D.windows.map(([k])=>[k,WSHORT[k]||k]),win,'win',k=>!WS(e,k))}</div>`;
 const v=view(e);s+=v&&v.months.length>1?`<div class="chartbox" data-chart="sheet" tabindex="0" aria-label="Chart: use the arrow keys to step through months">${area('sheet',v,Math.max(300,Math.min(typeof innerWidth==='number'?innerWidth:520,520)),200)}</div>`:'';
 s+='</section>';
 if(!w)return s+`<section><p class="na">n/a: ${esc(e.kind==='group'?'the combined line starts after this window begins, or has under a month of history in it':'this account starts after the window begins, or is closed')}.</p></section>`+sheetHold(e);
 const why=whyOf(e,w),f=(fn,x,k)=>x==null?['n/a',why[k]]:[fn(x),''],cumN=w.cum?'for the period, not annualized':'';
 const open=win==='inception'?0:(w.chart?w.chart.values[0]:null),gain=open==null?null:w.value-open-w.net_in;
 const twrN=w.twr_thru&&w.twr!=null&&w.twr_thru!==w.thru?'through '+fmtDate(w.twr_thru):'';
 const F=[['IRR (money-weighted)',...f(pct,w.irr,'irr')],['Same money in '+bm,...f(pct,w.bench_irr,'bench')],['Excess IRR vs '+bm,...f(spct,w.excess,'excess')],['Worth today in '+bm,...f(money,w.bench_end,'bench')],
  ['Deposits',w.dep!=null?money(w.dep):'n/a',''],['Withdrawals',w.wd!=null?money(w.wd):'n/a',''],['Net in',money(w.net_in),''],['Investment '+(gain!=null&&gain<0?'loss':'gain'),gain!=null?smoney(gain):'n/a',''],
  ['Time-weighted return (est.)',...(()=>{const r=f(pct,w.twr,'twr');return [r[0],r[1]||twrN];})()],['Sharpe (est.)',...f(num,w.sharpe,'sharpe')],['Worst fall',...f(pct,w.dd,'dd')]]
  .concat(D.extras.map(n=>['Excess vs '+n,...f(spct,w.extras[n]&&w.extras[n].excess,'excess')]));
 s+=`<section><h3 style="margin-bottom:10px">The figures</h3><div class="figs">${F.map(([l,x,n],i)=>fig(l,x,n||(i<3&&cumN?cumN:''))).join('')}</div></section>`;
 const notes=(e.unreconciled?['Estimated, does not reconcile: '+e.unreconciled+'. It is left out of combined totals and of periods other than since the start, rather than shown wrong.']:[]).concat([`${est?'Estimated':'Exact'}, as of ${w.thru||e.as_of}${e.note?' ('+e.note+')':''}.`]).concat((e.flags||[]).map(capS)).concat(w.unstable?['Some months had very little capital, so monthly returns in this window are not meaningful.']:[]);
 if(e.members)notes.push('Includes: '+e.members.join(', ')+'. Transfers between these accounts net out.');
 s+=`<section><h3 style="margin-bottom:8px">About these numbers</h3><ul class="notes">${notes.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></section>`;
 return s+sheetHold(e);}
function sheetHold(e){
 const es=e.kind==='account'?[e].filter(x=>x.holdings):D.entities.filter(x=>x.kind==='account'&&(e.members||[]).includes(x.label)&&x.holdings);
 if(!es.length)return e.holdings_note?`<section><h3>Holdings</h3><p class="small">${esc(e.holdings_note)}</p></section>`:'';
 const {by,sum}=classMix(es);
 return `<section class="card" style="padding:18px"><h3 style="margin-bottom:12px">Mix</h3><div class="donut">${donut(by,sum,[kmoney(sum),'holdings'])}</div>${e.kind==='account'?`<details><summary>Every fund, as of ${esc(fmtDate(e.holdings.as_of))}</summary>${fundTable(e)}</details>`:''}</section>`;}
function infoHtml(){const head=`<div class="sh-head"><h2 id="sheet-h">About estimated figures</h2><button type="button" class="icon" data-act="close" aria-label="Close">${svgI('<path d="M6 6l12 12M18 6 6 18"/>')}</button></div>`;
 return head+'<section class="lesson" style="margin:0"><p>Today\'s values and the dated deposits and withdrawals are exact: they come straight from your statements and history files. Since-inception IRR rests on those alone.</p>'+
  '<p>Anything that needs a value in between is estimated: month-end values are rebuilt from your history (or taken from a statement where there is one). That covers the chart, the opening value of a shorter period, the time-weighted return, the worst fall and Sharpe.</p>'+
  '<p>A period under a year is cumulative, not annualized. Longer periods are per year. An account that does not cover a period shows n/a rather than a shortened number.</p>'+
  '<p class="small">How accounts are compared is set out in decision 0011: aligned periods, before tax, and transfers between your own accounts net out of combined lines.</p></section>';}
function dlg(id){return typeof document.getElementById==='function'?document.getElementById(id):null;}
function openDlg(d){if(!d)return;if(d.open){return;}if(d.showModal)d.showModal();else d.setAttribute('open','');}
function renderSheet(){const b=$('#sheet-body');if(!b)return;if(sheetFor==='__est')b.innerHTML=infoHtml();else{const e=D.entities.find(x=>x.label===sheetFor);b.innerHTML=e?sheetHtml(e):'';}}
function optsHtml(){return `<div class="sh-head"><h2 id="opts-h">View options</h2><button type="button" class="icon" data-act="close" aria-label="Close">${svgI('<path d="M6 6l12 12M18 6 6 18"/>')}</button></div>`+
 `<div class="opt"><h3>Compare with</h3><div class="list" id="bms" role="group" aria-label="Benchmark">${D.benchmarks.map(([k,l])=>`<button type="button" data-act="bm" data-k="${esc(k)}" aria-pressed="${bm===k}">${esc(l)}</button>`).join('')}</div>`+
 `<h3>Show accounts</h3><div class="pills" role="group" aria-label="Grouping">${pills(GROUPS,grp,'grp')}</div>`+
 `<h3>Chart</h3><label class="tog">Show the same money in the benchmark<input type="checkbox" id="bench" ${showBench?'checked':''}></label>`+
 `<h3>Appearance</h3><div class="pills" role="group" aria-label="Theme">${pills([['auto','Auto'],['light','Light'],['dark','Dark']],theme(),'theme')}</div>`+
 `<p class="small" style="margin-top:18px">The benchmark is the same deposits and withdrawals, on the same dates, put into that fund instead. Information, not investment advice.</p></div>`;}
function theme(){try{return document.documentElement.getAttribute&&document.documentElement.getAttribute('data-theme')||'auto';}catch(x){return 'auto';}}
function setTheme(v){const r=document.documentElement;if(!r.setAttribute)return;v==='auto'?r.removeAttribute('data-theme'):r.setAttribute('data-theme',v);try{localStorage.setItem('ufo-theme',v);}catch(x){}}
function showTab(){$('#tab-main').hidden=tab!=='main';$('#tab-details').hidden=tab!=='details';$('#tab-sharpe').hidden=tab!=='sharpe';if(tab==='sharpe')sharpeTab();
 $('#tabs').innerHTML=[['main','Overview','home'],['details','Details','details'],['sharpe','Learn','learn']].map(([k,l,ic])=>`<button type="button" data-act="tab" data-k="${k}"${tab===k?' aria-current="page"':''}>${svgI(ICON[ic])}<span>${l}</span></button>`).join('');}
function draw(){
 document.querySelectorAll('.bml').forEach(x=>x.textContent=BL());
 showTab();
 hero();cards();mix();
 $('#wins2').innerHTML=pills(D.windows,win,'win');$('#grps').innerHTML=pills(GROUPS,grp,'grp');
 const rs2=rows();table(rs2);bars(rs2);lines(rs2);holdings();scatter();
 $('#opts-body').innerHTML=optsHtml();
 const sd=dlg('sheet');if(sd&&sd.open)renderSheet();
 $('#winnote').textContent=win==='inception'?'Since inception: IRR uses exact dated flows plus the ending value; returns are per year.':
  'Windowed figures are estimated: they start from a month-end value (a statement where there is one, otherwise rebuilt from the history) and end at the last month-end the history covers. A window under a year is cumulative, not annualized (IRR, time-weighted return and excess alike); longer windows are per year. Each row runs to the latest value date of its own account (see Data). Accounts that do not cover the window show n/a. Sharpe is shown since inception only. A * means the history ends before the ending value (hover for details): the IRR then reaches that later date while the time-weighted return stops at the last month-end.';
 $('#empty').hidden=rs2.length>0;}
function act(a,k,el){
 if(a==='win')win=k;else if(a==='grp')grp=k;else if(a==='bm')bm=k;else if(a==='theme'){setTheme(k);}
 else if(a==='tab'){tab=k;if(typeof scrollTo==='function')scrollTo({top:0});}
 else if(a==='open'||a==='info'){sheetFor=a==='info'?'__est':k;const d=dlg('sheet');renderSheet();openDlg(d);const b=$('#sheet-body');if(b&&b.parentNode)b.parentNode.scrollTop=0;return;}
 else if(a==='opts'){$('#opts-body').innerHTML=optsHtml();openDlg(dlg('opts'));return;}
 else if(a==='close'){const d=el.closest('dialog');if(d)d.close();return;}
 draw();
 if(a==='tab'){const v=$('#tab-'+k);if(v&&v.classList){v.classList.remove('view');void v.offsetWidth;v.classList.add('view');}}}
try{const th=localStorage.getItem('ufo-theme');if(th&&th!=='auto')document.documentElement.setAttribute('data-theme',th);}catch(x){}
if(typeof document.addEventListener==='function'){
 document.addEventListener('click',ev=>{const b=ev.target.closest('[data-act]');if(b){ev.preventDefault();act(b.dataset.act,b.dataset.k,b);return;}
  if(ev.target.tagName==='DIALOG')ev.target.close();});// a tap on the backdrop closes a sheet
 document.addEventListener('change',ev=>{if(ev.target.id==='bench'){showBench=ev.target.checked;draw();}});
 const keyOf=t=>{const b=t.closest&&t.closest('.chartbox');return b?[b,b.dataset.chart]:null;};
 const at=(ev,b,key)=>{const g=CH[key],sv=b.querySelector('svg');if(!g||!sv)return;const r=sv.getBoundingClientRect(),x=(ev.clientX-r.left)/r.width*g.W;
  let bi=0,bd=1e9;g.pv.forEach((p,i)=>{const d=Math.abs(p[0]-x);if(d<bd){bd=d;bi=i;}});scrub(key,bi);};
 document.addEventListener('pointerdown',ev=>{const k=keyOf(ev.target);if(k)at(ev,k[0],k[1]);});
 document.addEventListener('pointermove',ev=>{const k=keyOf(ev.target);if(k&&(ev.pointerType==='mouse'||ev.buttons||ev.pressure))at(ev,k[0],k[1]);});
 for(const t of ['pointerup','pointercancel','pointerout'])document.addEventListener(t,ev=>{const k=keyOf(ev.target);if(k&&(t!=='pointerout'||!k[0].contains(ev.relatedTarget)))unscrub(k[1]);});
 document.addEventListener('keydown',ev=>{const k=keyOf(ev.target);if(!k)return;const g=CH[k[1]];if(!g)return;
  if(ev.key==='ArrowLeft'||ev.key==='ArrowRight'){ev.preventDefault();scrub(k[1],(g.i==null?g.pv.length-1:g.i)+(ev.key==='ArrowLeft'?-1:1));}else if(ev.key==='Escape'&&g.i!=null){unscrub(k[1]);}});
 document.addEventListener('focusout',ev=>{const k=keyOf(ev.target);if(k)unscrub(k[1]);});
 const sd=dlg('sheet');if(sd&&sd.addEventListener)sd.addEventListener('close',()=>{sheetFor=null;});
}
if(typeof addEventListener==='function'){let rz,lastW=innerWidth;addEventListener('resize',()=>{if(innerWidth===lastW)return;lastW=innerWidth;clearTimeout(rz);rz=setTimeout(draw,150);});}// redraw on rotation, not on a phone's scroll-driven height changes
draw();
"""

LOGO = ('<svg viewBox="0 0 16 16" aria-hidden="true"><rect width="16" height="16" rx="3.5" fill="#4b30d6"/><path d="M6 3.9a2 2 0 0 1 4 0z" fill="#cfc4ff"/>'
        '<ellipse cx="8" cy="4.6" rx="5" ry="1.5" fill="#fff"/><rect x="3.5" y="10" width="2.2" height="3.5" rx=".5" fill="#fff"/>'
        '<rect x="6.9" y="8.2" width="2.2" height="5.3" rx=".5" fill="#fff"/><rect x="10.3" y="6.6" width="2.2" height="6.9" rx=".5" fill="#fff"/></svg>')
LOCK = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<rect x="5" y="11" width="14" height="10" rx="3"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>')
SLIDERS = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">'
           '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></svg>')


def render(data: dict) -> str:
    blob = json.dumps(data).replace("</", "<\\/")
    demo = data.get("demo")
    where = "invented demo data" if demo else "local only, never sent anywhere"
    banner = (f'<details class="demo"><summary><b>Demo</b><span>An invented household on real fund prices</span><i>More</i></summary>'
              f'<p>{html.escape(demo)}</p></details>') if demo else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark"><title>All investments side by side</title>
<style>{PAGE_CSS}</style></head><body><main>
<header class="top"><div class="brand">{LOGO}<div>Ur Family Office<small class="muted">All investments side by side</small></div></div>
<div class="top-r"><button type="button" class="icon" data-act="opts" aria-label="View options: benchmark, grouping and theme">{SLIDERS}</button></div></header>
{banner}
<div id="tab-main" class="view"><div class="ov">
<div class="col">
<section class="card heroCard" aria-label="Total value"><div id="hero" aria-live="polite"></div>
<div class="chartbox" id="chart" data-chart="hero" tabindex="0" aria-label="Value chart: use the arrow keys to step through months"></div>
<div class="legend" id="lgd"></div><div class="pills" id="wins" role="group" aria-label="Period"></div><p class="cap" id="chartcap"></p></section>
<section class="card" aria-labelledby="src-h"><h2 id="src-h" style="margin-bottom:6px">Where your money came from</h2><div id="src"></div></section>
</div>
<div class="col">
<section aria-labelledby="acc-h"><div class="sec-h"><h2 id="acc-h">Your accounts</h2><button type="button" class="chip lg" id="grpbtn" data-act="opts" aria-label="Change grouping and benchmark"></button></div>
<div id="cards" class="cards"></div></section>
<section class="card" aria-labelledby="mix-h"><h2 id="mix-h" style="margin-bottom:14px">Your mix</h2><div id="mix"></div></section>
</div></div></div>
<div id="tab-details" hidden><div class="dt">
<section class="card"><h2>Every figure</h2><div class="ctl"><div class="pills" id="wins2" role="group" aria-label="Window"></div><div class="pills" id="grps" role="group" aria-label="Grouping"></div></div>
<p class="small" id="winnote"></p><p class="small" id="totnote" style="margin-top:6px"></p><p id="empty" hidden class="na">No accounts to show for this grouping.</p>
<div class="scroll" style="margin-top:12px"><table id="tbl"></table></div></section>
<figure class="card"><h2>Excess IRR per account</h2><div id="bars"></div><figcaption>IRR of the real flows minus the IRR of the same deposits and withdrawals put into <span class="bml"></span>. Sorted best first.</figcaption></figure>
<figure class="card"><h2>Value over time</h2><div class="key" id="key"></div><div id="lines"></div><figcaption>Month-end values are estimated; the endpoints are exact.</figcaption></figure>
<figure class="card"><h2>Risk versus return</h2><div id="risk"></div><figcaption>Each point is one account, group, your whole portfolio (large) or a benchmark (grey): time-weighted return per year against how much it swings, numbered, with the names and Sharpe ratio (return above the T-bill rate per unit of risk) in the list below the chart. Since each one's start; benchmarks cover the whole-portfolio period. Hollow points are estimated from reconstructed month-end values (decision 0011). Hover for the figures.</figcaption><p class="small" id="riskleft"></p></figure>
<section class="card" id="hold"></section>
</div></div>
<div id="tab-sharpe" hidden><article id="lesson" class="lesson card"></article></div>
<footer class="foot">
<p>All figures are before tax. A taxable account's number is not comparable with an IRA or Roth on an after-tax basis. Transfers between your own accounts are external for each account alone and net out in combined lines. See decision 0011.</p>
<p class="disc">Information, not investment advice. Past performance does not predict future results.</p>
<p class="lock">{LOCK}<span>As of {html.escape(str(data.get('asof', '')))} · benchmark <span class="bml"></span> · {where}</span></p>
</footer>
</main>
<nav class="tabs" id="tabs" aria-label="Sections"></nav>
<dialog class="sheet" id="sheet" aria-labelledby="sheet-h"><div class="sh"><div class="grab" aria-hidden="true"></div><div id="sheet-body"></div></div></dialog>
<dialog class="sheet" id="opts" aria-labelledby="opts-h"><div class="sh"><div class="grab" aria-hidden="true"></div><div id="opts-body"></div></div></dialog>
<script id="data" type="application/json">{blob}</script><script>{JS}</script></body></html>"""


def write(path: Path, html_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html_text)
    os.chmod(path, 0o600)

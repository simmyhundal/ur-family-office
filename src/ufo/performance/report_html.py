"""A self-contained local HTML report: headline numbers and the standard portfolio-vs-index charts as inline SVG.

Local only (exact balances): written to the gitignored exports/ folder, never sent to a chat or published.
"""
from __future__ import annotations

import html
from datetime import date

from ufo.performance.run import Result

PORT, IDX = "var(--port)", "var(--idx)"
SCEN = ["var(--mix)", "var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"]  # one color per extra comparison
NUMBER = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}  # you + the index + each comparison
W, H, PAD_L, PAD_R, PAD_T, PAD_B = 720, 270, 52, 14, 14, 30


def pct(x: float | None, d: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


TIPS = {
    "irr": "IRR (money-weighted): the yearly rate your money earned, counting when you added and took out cash. Bigger balances count more, so it reflects your timing as well as your picks.",
    "twr": "Return per year (time-weighted): how fast the investments themselves grew, as if $1 had stayed invested the whole time. Ignores when money went in or out, so it reflects the picks, not the timing.",
    "excess": "Excess IRR: your IRR minus the IRR of the same deposits and withdrawals put into the index. Negative means the index would have done better.",
    "pme": "PME (Kaplan-Schoar): what your cash flows would have grown to in the index, compared with what you got. Above 1.0 means you beat the index.",
    "sharpe": "Sharpe ratio: return above the T-bill rate for each unit of ups and downs. Higher is better. Estimated here.",
    "vol": "Volatility: how much monthly returns swing, as a yearly figure. Higher means a bumpier ride.",
    "beta": "Beta: how much you move when the index moves (1.0 moves with it). Alpha: the yearly return left over after that.",
    "worth": "Worth today: what the same dated deposits and withdrawals would be worth now in each choice, before taxes.",
    "fall": "Worst fall: the largest drop from a previous peak in the month-end balance.",
}


def tip(label: str, key: str) -> str:
    return f'<span class="tip" tabindex="0" data-tip="{html.escape(TIPS[key], quote=True)}">{label}</span>'


def spct(x: float | None, d: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:+.{d}f}%"


def money(x: float) -> str:
    return f"${x:,.0f}"


def num(x: float | None, d: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{d}f}"


# ---------- chart helpers ----------

def nice_range(lo: float, hi: float, n: int = 5) -> tuple[float, float]:
    """Widen [lo, hi] to round tick marks (steps of 1, 2 or 5 times a power of ten)."""
    import math
    span = (hi - lo) or 1.0
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return math.floor(lo / step) * step, math.ceil(hi / step) * step


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    lo, hi = nice_range(lo, hi, n)
    step = (hi - lo) / n
    return [lo + i * step for i in range(n + 1)]


def _frame(ymin: float, ymax: float, fmt, dates: list[date], extra: str = "") -> tuple[str, "callable", "callable"]:
    pw, ph = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    ymin, ymax = nice_range(ymin, ymax)
    y = lambda v: PAD_T + ph * (1 - (v - ymin) / ((ymax - ymin) or 1))
    n = max(len(dates) - 1, 1)
    x = lambda i: PAD_L + pw * i / n
    g = []
    for t in _ticks(ymin, ymax):
        g.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                 f'<text class="axis" x="{PAD_L - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{fmt(t)}</text>')
    seen = set()
    for i, d in enumerate(dates):
        if d.month == 1 and d.year not in seen:
            seen.add(d.year)
            g.append(f'<text class="axis" x="{x(i):.1f}" y="{H - 8}" text-anchor="middle">{d.year}</text>')
    return "".join(g) + extra, x, y


def _wrap(inner: str, label: str) -> str:
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(label)}">{inner}</svg>'


def line_chart(dates, series, fmt, label, ymin=None, ymax=None, zero=False) -> str:
    vals = [v for _, _, vs in series for v in vs]
    lo, hi = (min(vals) if ymin is None else ymin), (max(vals) if ymax is None else ymax)
    pad = (hi - lo) * 0.06 or 0.1
    lo, hi = (lo if ymin is not None else lo - pad), (hi if ymax is not None else hi + pad)
    frame, x, y = _frame(lo, hi, fmt, dates)
    out = [frame]
    if zero and lo < 0 < hi:
        out.append(f'<line class="zero" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    for name, color, vs in series:
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vs))
        out.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round" points="{pts}"/>')
        out.append(f'<circle cx="{x(len(vs) - 1):.1f}" cy="{y(vs[-1]):.1f}" r="3.6" fill="{color}"/>')
    return _wrap("".join(out), label)


def area_chart(dates, series, fmt, label) -> str:
    lo = min(v for _, _, vs in series for v in vs) * 1.08 or -0.05
    frame, x, y = _frame(lo, 0.0, fmt, dates)
    out = [frame]
    for name, color, vs in series:
        pts = f"{x(0):.1f},{y(0):.1f} " + " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vs)) + f" {x(len(vs) - 1):.1f},{y(0):.1f}"
        out.append(f'<polygon points="{pts}" fill="{color}" fill-opacity="0.18"/>'
                   f'<polyline fill="none" stroke="{color}" stroke-width="1.8" points="{" ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vs))}"/>')
    return _wrap("".join(out), label)


def paired_bars(labels, a, b, fmt, label) -> str:
    vals = a + b
    lo, hi = min(0.0, min(vals)) * 1.15, max(0.0, max(vals)) * 1.15
    frame, _, y = _frame(lo, hi, fmt, [])
    pw = W - PAD_L - PAD_R
    slot = pw / len(labels)
    bw = slot * 0.32
    out = [frame, f'<line class="zero" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>']
    for i, (lab, va, vb) in enumerate(zip(labels, a, b)):
        cx = PAD_L + slot * (i + 0.5)
        for dx, v, col in ((-bw / 2 - 1, va, PORT), (bw / 2 + 1, vb, IDX)):
            top, h = (y(v), y(0) - y(v)) if v >= 0 else (y(0), y(v) - y(0))
            out.append(f'<rect x="{cx + dx - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(h, 0.5):.1f}" fill="{col}"/>')
            out.append(f'<text class="val" x="{cx + dx:.1f}" y="{(y(v) - 4) if v >= 0 else (y(v) + 12):.1f}" text-anchor="middle">{fmt(v)}</text>')
        out.append(f'<text class="axis" x="{cx:.1f}" y="{H - 8}" text-anchor="middle">{lab}</text>')
    return _wrap("".join(out), label)


def single_bars(dates, vals, fmt, label, pos="var(--port)", neg="var(--idx)") -> str:
    lo, hi = min(0.0, min(vals)) * 1.1, max(0.0, max(vals)) * 1.1
    frame, x, y = _frame(lo, hi, fmt, dates)
    bw = max((W - PAD_L - PAD_R) / len(vals) * 0.7, 1.5)
    out = [frame, f'<line class="zero" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>']
    for i, v in enumerate(vals):
        top, h = (y(v), y(0) - y(v)) if v >= 0 else (y(0), y(v) - y(0))
        out.append(f'<rect x="{x(i) - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(h, 0.4):.1f}" fill="{pos if v >= 0 else neg}"/>')
    return _wrap("".join(out), label)


def scatter(points, label) -> str:
    xs, ys = [p[1] for p in points], [p[2] for p in points]
    xlo, xhi = nice_range(0.0, max(xs) * 1.25)
    ylo, yhi = nice_range(min(0.0, min(ys)), max(ys) * 1.3)
    pw, ph = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    X = lambda v: PAD_L + pw * (v - xlo) / ((xhi - xlo) or 1)
    Y = lambda v: PAD_T + ph * (1 - (v - ylo) / ((yhi - ylo) or 1))
    out = []
    for t in _ticks(ylo, yhi):
        out.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"/><text class="axis" x="{PAD_L - 6}" y="{Y(t) + 4:.1f}" text-anchor="end">{t * 100:.0f}%</text>')
    for t in _ticks(xlo, xhi):
        out.append(f'<text class="axis" x="{X(t):.1f}" y="{H - 8}" text-anchor="middle">{t * 100:.0f}%</text>')
    for name, vol, ret, col in points:
        out.append(f'<circle cx="{X(vol):.1f}" cy="{Y(ret):.1f}" r="8" fill="{col}"/><text class="val" x="{X(vol) + 13:.1f}" y="{Y(ret) + 4:.1f}">{html.escape(name)}</text>')
    out.append(f'<text class="axis" x="{(W + PAD_L) / 2:.0f}" y="{H - 0}" text-anchor="middle"></text>')
    return _wrap("".join(out), label)


# ---------- page ----------

def calendar_years(months: list[date], port: list[float | None], idx: list[float]):
    by: dict[int, list[tuple[float, float]]] = {}
    for d, p, i in zip(months, port, idx):
        by.setdefault(d.year, []).append((p or 0.0, i))
    out = []
    for y, rows in by.items():
        gp, gi = 1.0, 1.0
        for p, i in rows:
            gp *= 1 + p
            gi *= 1 + i
        out.append((y, gp - 1, gi - 1, len(rows)))
    return out


def rolling12(port: list[float | None], idx: list[float]) -> list[float]:
    out = []
    for i in range(11, len(port)):
        gp = gi = 1.0
        for p, b in zip(port[i - 11:i + 1], idx[i - 11:i + 1]):
            gp *= 1 + (p or 0.0)
            gi *= 1 + b
        out.append(gp - gi)
    return out


CSS = """
:root{--bg:#f5f6f3;--ink:#1c2420;--muted:#5d6862;--line:#d9ded9;--card:#fff;--port:#1d6f5b;--idx:#c25a1b;--mix:#4a55c4;--s1:#8a7a14;--s2:#b13b86;--s3:#2a7fa8;--s4:#7a4a2a;--good:#1d6f5b;--bad:#a8431a;--warn:#8a6a00;
--display:"Fraunces",Georgia,serif;--body:"Source Sans 3",system-ui,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121815;--ink:#e6ece7;--muted:#9aa8a0;--line:#2c3732;--card:#19211d;--port:#4fc3a3;--idx:#f0925a;--mix:#9ba6ff;--s1:#d8c25a;--s2:#ef8fcb;--s3:#7cc4e8;--s4:#c9a27a;--good:#4fc3a3;--bad:#f0925a;--warn:#e3c35a;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#121815;--ink:#e6ece7;--muted:#9aa8a0;--line:#2c3732;--card:#19211d;--port:#4fc3a3;--idx:#f0925a;--mix:#9ba6ff;--s1:#d8c25a;--s2:#ef8fcb;--s3:#7cc4e8;--s4:#c9a27a;--good:#4fc3a3;--bad:#f0925a;--warn:#e3c35a;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 var(--body)}
main{max-width:860px;margin:0 auto;padding:28px 16px 56px;display:flex;flex-direction:column;gap:26px}
h1{font:600 28px/1.15 var(--display);margin:0 0 6px}h2{font:600 19px/1.2 var(--display);margin:0 0 8px}
p{margin:0;max-width:68ch}.muted{color:var(--muted)}small,.small{font-size:14px;color:var(--muted)}
.hero{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;display:flex;flex-direction:column;gap:14px}
.big{font:600 52px/1 var(--display);font-variant-numeric:tabular-nums}.big.bad{color:var(--bad)}.big.good{color:var(--good)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.tile{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--card)}
.tile b{display:block;font:600 22px/1.2 var(--display);font-variant-numeric:tabular-nums}.tile span{font-size:13px;color:var(--muted)}
.pair{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;font-variant-numeric:tabular-nums}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
figcaption{font-size:14px;color:var(--muted);margin-top:6px}
svg{width:100%;height:auto;display:block}svg .grid{stroke:var(--line);stroke-width:1}svg .zero{stroke:var(--muted);stroke-width:1.2}
svg .axis{fill:var(--muted);font-size:11px}svg .val{fill:var(--ink);font-size:10.5px}
.key{display:flex;gap:16px;font-size:14px;flex-wrap:wrap}.key i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}
table{width:100%;border-collapse:collapse;font-size:15px;font-variant-numeric:tabular-nums}th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}th{font-size:13px;color:var(--muted);font-weight:600}.scroll{overflow-x:auto}
.tip{border-bottom:1px dotted var(--muted);cursor:help;position:relative}
.tip:hover::after,.tip:focus::after{content:attr(data-tip);position:absolute;left:0;top:130%;z-index:5;width:min(300px,80vw);background:var(--ink);color:var(--bg);padding:8px 10px;border-radius:8px;font:400 13px/1.4 var(--body);text-align:left;white-space:normal;box-shadow:0 4px 14px rgba(0,0,0,.25)}
th:nth-last-child(-n+3) .tip:hover::after,th:nth-last-child(-n+3) .tip:focus::after{left:auto;right:0}
.ok{color:var(--good)}.chk{color:var(--warn)}.badge{font-size:12px;border:1px solid var(--warn);color:var(--warn);border-radius:99px;padding:1px 8px;margin-left:6px;vertical-align:2px}
ul{margin:4px 0 0;padding-left:20px}
"""


def render(res: Result, title: str = "Fidelity performance report") -> str:
    r = res.report
    years = (r.end - r.start).days / 365.25
    ex = r.excess_irr
    verdict = ("n/a" if ex is None else f"{abs(ex) * 100:.1f} percentage points {'above' if ex >= 0 else 'below'}")
    sentence = (f"Over {years:.1f} years, your deposits and withdrawals earned {pct(r.irr)} a year. The same cash flows in "
                f"{html.escape(res.benchmark)} would have earned {pct(r.index_irr)}. That is {verdict} the index." if ex is not None
                else f"Your cash flows earned {pct(r.irr)} a year. {html.escape(r.index_note)}")
    cy = calendar_years(r.months, r.port_returns, r.index_returns)
    cy_labels = [f"{y}{'*' if n < 12 else ''}" for y, _, _, n in cy]
    dd = lambda g: [v / max(g[: i + 1]) - 1 for i, v in enumerate(g)]
    roll = rolling12(r.port_returns, r.index_returns)
    sc = r.scenarios
    key = (f'<div class="key"><span><i style="background:{PORT}"></i>Your account</span><span><i style="background:{IDX}"></i>{html.escape(res.benchmark)} (total-market index)</span></div>')
    bal_key = key.replace("</div>", "".join(f'<span><i style="background:{SCEN[i]}"></i>{html.escape(x.name)}</span>' for i, x in enumerate(sc)) + "</div>")
    gap = r.end_value - r.index_end_value
    charts = [
        ("Your balance vs the same money in " + res.benchmark,
         line_chart(r.months + [r.end], [("You", PORT, r.values + [r.end_value]), (res.benchmark, IDX, r.index_values + [r.index_end_value])]
                    + [(x.name, SCEN[i], x.values + [x.end_value]) for i, x in enumerate(sc)],
                    lambda v: f"${v / 1000:.0f}k", "Account balance versus the same deposits and withdrawals held in the index"),
         f"Same dates, same deposits and withdrawals. Today: you {money(r.end_value)}, in {html.escape(res.benchmark)} {money(r.index_end_value)}, "
         f"a difference of {'+' if gap >= 0 else '-'}{money(abs(gap))}. Before taxes. The month-end path is estimated; the endpoints are exact."),
        ("Growth of $1 (time-weighted)", line_chart(r.months, [("You", PORT, r.port_growth), (res.benchmark, IDX, r.index_growth)], lambda v: f"${v:.2f}", "Growth of one dollar, account versus index"),
         "Month-end values with deposits and withdrawals removed, so this shows investing skill, not how much you put in. Estimated: see data checks."),
        ("Drawdown from the previous peak", area_chart(r.months, [("You", PORT, dd(r.port_growth)), (res.benchmark, IDX, dd(r.index_growth))], lambda v: f"{v * 100:.0f}%", "Drawdown, account versus index"),
         f"Worst fall: {pct(r.max_drawdown)} for you, {pct(r.index_max_drawdown)} for the index."),
        ("Calendar-year returns", paired_bars(cy_labels, [c[1] for c in cy], [c[2] for c in cy], lambda v: f"{v * 100:.0f}%", "Calendar-year returns, account versus index"),
         "* A part year: fewer than 12 months of capital."),
        ("Rolling 12-month return minus the index", single_bars(r.months[11:], roll, lambda v: f"{v * 100:.0f}%", "Rolling twelve-month excess return") if roll else "",
         "Above zero: you beat the index over the 12 months ending that month."),
        ("Risk versus return (annualized)", scatter([("You", r.volatility or 0, r.twr_annual or 0, PORT), (res.benchmark, r.index_volatility or 0, r.index_twr_annual or 0, IDX)], "Risk versus return") if r.volatility and r.twr_annual else "",
         "Up is better return, left is lower risk. Sharpe puts the two together."),
        ("Money in and out by month", single_bars(r.months, r.flows_by_month, lambda v: f"${v / 1000:.0f}k", "Contributions and withdrawals by month", pos="var(--port)", neg="var(--idx)"),
         f"Contributed {money(r.contributed)}, withdrew {money(r.withdrawn)}."),
    ]
    figs = "".join(f"<figure><h2>{t}</h2>{bal_key if t.startswith('Your balance') else key}{svg}<figcaption>{cap}</figcaption></figure>" for t, svg, cap in charts if svg)
    tiles = "".join(f'<div class="tile"><span>{a}</span><b>{b}</b><span>{c}</span></div>' for a, b, c in [
        (tip("Your IRR (money-weighted)", "irr"), pct(r.irr), f"index {pct(r.index_irr)}"),
        (tip("PME (Kaplan-Schoar)", "pme"), num(r.pme, 3), "above 1.0 beats the index"),
        (tip("Time-weighted / yr", "twr"), pct(r.twr_annual), f"index {pct(r.index_twr_annual)}"),
        (tip("Sharpe ratio", "sharpe"), num(r.sharpe), f"index {num(r.index_sharpe)}"),
        (tip("Volatility / yr", "vol"), pct(r.volatility), f"index {pct(r.index_volatility)}"),
        (tip("Beta and alpha", "beta"), f"{num(r.beta)} / {spct(r.alpha)}", "vs the index, yearly alpha"),
    ])
    scen = ""
    if sc:
        def row(n, v, irr, twr, sh, dd): return f"<tr><td>{n}</td><td>{money(v)}</td><td>{pct(irr)}</td><td>{pct(twr)}</td><td>{num(sh)}</td><td>{pct(dd)}</td></tr>"
        lines = []
        for x in sc:
            vs_you, vs_idx = x.end_value - r.end_value, x.end_value - r.index_end_value
            if x.kind == "plan":
                mixtxt = ", ".join(f"{html.escape(k)} {v / sum(x.weights.values()) * 100:.0f}%" for k, v in x.weights.items())
                lines.append(f'<p>{html.escape(x.name)} ({mixtxt}) would be worth {money(x.end_value)} today: <b>{"+" if vs_you >= 0 else "-"}{money(abs(vs_you))}</b> versus your account (how it was carried out: cash waiting, CDs, timing, fund choices) and <b>{"+" if vs_idx >= 0 else "-"}{money(abs(vs_idx))}</b> versus {html.escape(res.benchmark)} (the strategy itself).</p>')
            else:
                lines.append(f'<p><b>{html.escape(x.name)}</b> would be worth {money(x.end_value)} today: <b>{"+" if vs_you >= 0 else "-"}{money(abs(vs_you))}</b> versus your account and <b>{"+" if vs_idx >= 0 else "-"}{money(abs(vs_idx))}</b> versus {html.escape(res.benchmark)}.'
                             + (f' <span class="small">{html.escape(x.description)}</span>' if x.description else "") + "</p>")
        scen = (f'<section><h2>Same deposits and withdrawals, {NUMBER.get(len(sc) + 2, str(len(sc) + 2))} ways</h2><div><table><tr><th>Scenario</th><th>{tip("Worth today", "worth")}</th><th>{tip("IRR", "irr")}</th><th>{tip("Return/yr", "twr")}</th><th>{tip("Sharpe", "sharpe")}</th><th>{tip("Worst fall", "fall")}</th></tr>'
                + row("Your account", r.end_value, r.irr, r.twr_annual, r.sharpe, r.max_drawdown)
                + row(html.escape(res.benchmark), r.index_end_value, r.index_irr, r.index_twr_annual, r.index_sharpe, r.index_max_drawdown)
                + "".join(row(html.escape(x.name), x.end_value, x.irr, x.twr_annual, x.sharpe, x.max_drawdown) for x in sc) + "</table></div>"
                + "".join(lines)
                + '<p class="small">Each deposit goes into the comparison on its day and each withdrawal comes out of it, with no rebalancing in between. Funds are priced with dividends reinvested. Before taxes and trading costs.</p></section>')
    rows = "".join(f"<tr><td>{c['when']}</td><td>{html.escape(c['source'])}</td><td>{c['reference']:,.0f}</td><td>{c['rebuilt']:,.0f}</td><td>{c['diff']:+,.0f}</td><td class=\"{'ok' if c['ok'] else 'chk'}\">{'matches' if c['ok'] else 'check'} ({c['pct'] * 100:+.1f}%)</td></tr>" for c in res.reconciliation)
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in res.notes + res.warnings)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@600&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><main>
<header><h1>{html.escape(title)}</h1><p class="muted">{r.start} to {r.end} · one taxable account · vs {html.escape(res.benchmark)} · local only, never sent anywhere</p></header>
<section class="hero"><div><span class="small">{tip("Excess IRR", "excess")} (your IRR minus the index IRR for the same cash flows)</span>
<div class="big {'good' if (ex or 0) >= 0 else 'bad'}">{spct(ex)}</div></div><p>{sentence}</p>
<div class="tiles">{tiles}</div>
<p><b>If the same deposits and withdrawals had gone into {html.escape(res.benchmark)}, you would have {money(r.index_end_value)} today instead of {money(r.end_value)}</b> ({'+' if r.end_value - r.index_end_value >= 0 else '-'}{money(abs(r.end_value - r.index_end_value))}), before taxes.</p>
<p class="small">Ending value {money(r.end_value)} (from the statement). IRR uses the exact dated deposits and withdrawals plus that ending value, so it does not depend on the estimated month-end values below.</p></section>
{scen}{figs}
<section><h2>Data checks<span class="badge">TWR and Sharpe are estimates</span></h2>
<p class="small">The history export leaves out some activity, so share counts were corrected at six positions snapshots and are estimated in between. Where Fidelity's own totals exist, the rebuilt value is compared with them:</p>
<div class="scroll"><table><tr><th>Date</th><th>Source</th><th>Fidelity</th><th>Rebuilt</th><th>Diff</th><th>Result</th></tr>{rows}</table></div>
<ul>{notes}</ul></section>
<p class="small">Information, not investment advice. Past performance does not predict future results. Excess IRR compares your actual cash flows with the same flows invested in one index fund; taxes and fees on the index side are ignored.</p>
</main></body></html>"""

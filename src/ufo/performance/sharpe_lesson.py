"""The "How Sharpe works" tab: the lesson in docs/lessons/sharpe-ratio.md filled from the owner's own numbers.

Every {placeholder} in the template is filled at render time from the whole portfolio's monthly returns (the same
report the dashboard's Sharpe comes from) and nothing real is stored in the repo. The arithmetic is metrics.sharpe():
mean(monthly excess) / stdev(monthly excess) x sqrt(12). A placeholder that cannot be computed renders as "n/a" with
the reason (visible in the text and on hover), never as an error.
"""
from __future__ import annotations

import html
import math
import re
from datetime import date, timedelta
from itertools import combinations
from pathlib import Path
from statistics import correlation, mean, stdev, StatisticsError

from ufo.performance import metrics as M
from ufo.performance.compare import AccountRun
from ufo.performance.combine import GroupRun
from ufo.providers.prices import Series

TEMPLATE = Path(__file__).resolve().parents[3] / "docs" / "lessons" / "sharpe-ratio.md"
MIN_MONTHS = 12
MAX_PLAUSIBLE_VOL = 10.0  # annualised; above this, tiny early balances dominate (same cut-off as the risk chart)
ESTIMATE_NOTE = ("Month-end values for some accounts are rebuilt from transactions and prices, so these returns are estimates. "
                 "A deposit or withdrawal counts in proportion to the days it was in the account that month (modified Dietz). "
                 "The money-weighted IRR elsewhere on the dashboard is exact.")


def na(reason: str) -> str:
    return f"n/a⟦{reason}⟧"


def pct(x: float, signed: bool = False) -> str:
    return f"{x * 100:{'+' if signed else ''}.2f}%"


def money(x: float, signed: bool = False) -> str:
    s = "-" if x < 0 else ("+" if signed else "")
    return f"{s}${abs(round(x)):,}"


def _prev_ends(months: list[date]) -> list[date]:
    """The date each month's cash rate is read at: the previous month-end (as metrics.analyze does)."""
    return [months[i - 1] if i else date(m.year, m.month, 1) - timedelta(days=1) for i, m in enumerate(months)]


def index_returns_on(series: Series, months: list[date]) -> list[float]:
    """Monthly returns of a price series over the given month-ends (the previous month-end is the base, as in metrics.analyze)."""
    out = []
    for m, prev in zip(months, _prev_ends(months)):
        a, b = series.on_or_before(prev), series.on_or_before(m)
        out.append((b / a - 1) if a and b else 0.0)
    return out


def portfolio_figures(rep: M.Report, rf: Series | None, index: Series | None = None) -> dict:
    """All whole-portfolio numbers behind the lesson. Raw floats under 'raw', formatted text and reasons under 'fill'."""
    months = list(rep.months)
    n = len(months)
    fill: dict[str, str] = {}
    raw: dict = {}
    fill.update(n_months=str(n), start_month=months[0].strftime("%b %Y") if months else na("no history"),
                end_month=months[-1].strftime("%b %Y") if months else na("no history"))
    rets = [r for r in rep.port_returns]
    brets = index_returns_on(index, months) if index is not None else list(rep.index_returns)
    if rf is None:
        why = "the T-bill rate could not be loaded"
        for k in ("sharpe", "rf_annual", "rf_annual_compounded", "rf_month", "mean_excess_month", "mean_excess_annual", "sd_month", "sd_annual",
                  "sortino", "benchmark_sharpe", "monthly_table", "n_within", "compounded_annual"):
            fill[k] = na(why)
        fill["monthly_table_older"] = ""
        raw["points"] = None
        return {"fill": fill, "raw": raw}
    rfs = [M.monthly_rf(rf, p) for p in _prev_ends(months)]
    ex = [r - f for r, f in zip(rets, rfs)]
    bex = [b - f for b, f in zip(brets, rfs)]
    short = f"needs at least {MIN_MONTHS} months of returns, this has {n}"
    sh, so, bsh = M.sharpe(ex), M.sortino(ex), M.sharpe(bex)
    fill["sharpe"] = f"{sh:.2f}" if sh is not None else na(short if n < MIN_MONTHS else "the excess returns do not vary")
    fill["sortino"] = f"{so:.2f}" if so is not None else na(short if n < MIN_MONTHS else "no month fell below the cash rate")
    fill["benchmark_sharpe"] = f"{bsh:.2f}" if bsh is not None else na(short if n < MIN_MONTHS else "the benchmark's excess returns do not vary")
    raw.update(sharpe=sh, sortino=so, benchmark_sharpe=bsh)
    if n >= 2:
        rf_m = mean(rfs)
        sd = stdev(ex)
        mx = mean(ex)
        fill.update(rf_month=pct(rf_m), rf_annual=pct(rf_m * 12), rf_annual_compounded=pct((1 + rf_m) ** 12 - 1),
                    mean_excess_month=pct(mx), mean_excess_annual=pct(mx * 12), sd_month=pct(sd), sd_annual=pct(sd * math.sqrt(12)))
        within = sum(1 for x in ex if abs(x - mx) <= sd)
        fill["n_within"] = str(within)
        raw["within"] = within
        g = M.growth_index(rets)
        comp = M.annualize(g[-1], n) if g else None
        fill["compounded_annual"] = pct(comp) if comp is not None else na(f"needs at least {MIN_MONTHS} months of returns")
        raw.update(rf_month=rf_m, mean_excess=mx, sd=sd)
        # points for the slope chart: arithmetic yearly return (average month x 12) against yearly volatility of the
        # excess returns, so the line from the risk-free point to a portfolio has slope exactly Sharpe
        raw["points"] = {"rf": rf_m * 12,
                         "portfolio": {"ret": mean(rets) * 12, "vol": sd * math.sqrt(12), "sharpe": sh},
                         "benchmark": {"ret": mean(brets) * 12, "vol": stdev(bex) * math.sqrt(12), "sharpe": bsh}}
    else:
        for k in ("rf_month", "rf_annual", "rf_annual_compounded", "mean_excess_month", "mean_excess_annual", "sd_month", "sd_annual",
                  "n_within", "compounded_annual"):
            fill[k] = na("fewer than 2 months of returns")
        raw["points"] = None
    # the most recent month
    if n >= 2:
        i = n - 1
        start_v, flow, end_v = rep.values[i - 1], rep.flows_by_month[i], rep.values[i]
        gain = end_v - start_v - flow
        fill.update(example_month=months[i].strftime("%B %Y"), ex_start_value=money(start_v), ex_net_flow=money(flow, True),
                    ex_end_value=money(end_v), ex_gain=money(gain, True), ex_return=pct(rets[i], True))
        raw["example"] = {"start": start_v, "flow": flow, "end": end_v, "gain": gain, "ret": rets[i]}
    else:
        for k in ("example_month", "ex_start_value", "ex_net_flow", "ex_end_value", "ex_gain", "ex_return"):
            fill[k] = na("needs at least two month-ends")
    def table(idx):
        rows = ["| Month | Return | Cash (T-bill) for the month | Return above cash |", "|---|---|---|---|"]
        return "\n".join(rows + [f"| {months[i].strftime('%b %Y')} | {pct(rets[i], True)} | {pct(rfs[i])} | {pct(ex[i], True)} |" for i in idx])
    cut = max(0, n - 12)
    fill["monthly_table"] = table(range(cut, n)) if n else na("no monthly returns")
    # every month stays available: the older ones sit behind a toggle (the Sharpe ratio uses all of them)
    fill["monthly_table_older"] = f"::: details Show all {n} months\n{table(range(0, cut))}\n:::" if cut else ""
    return {"fill": fill, "raw": raw}


def account_pair(runs: list[AccountRun]) -> dict:
    """The two market accounts with the longest overlapping history (usable volatility, at least a year), with their
    correlation and the volatility of a 50/50 mix (monthly returns averaged, i.e. rebalanced each month)."""
    cand = []
    for r in runs:
        if r.market and r.result is not None and not r.error:
            rep = r.result.report
            cand.append((r.account.label, {m: x for m, x in zip(rep.months, rep.port_returns) if x is not None}))
    best = None
    for (la, a), (lb, b) in combinations(cand, 2):
        common = sorted(set(a) & set(b))
        if len(common) < MIN_MONTHS:
            continue
        ra, rb = [a[m] for m in common], [b[m] for m in common]
        va, vb = M.volatility(ra), M.volatility(rb)
        if va is None or vb is None or max(va, vb) > MAX_PLAUSIBLE_VOL:
            continue
        if best is None or len(common) > best[0]:
            best = (len(common), la, lb, ra, rb, va, vb)
    keys = ("acct_a", "acct_b", "vol_a", "vol_b", "corr_ab", "vol_mix", "vol_avg")
    if best is None:
        why = ("no two market accounts have at least a year of months in common with plausible volatility"
               if len(cand) >= 2 else "fewer than two accounts have market prices")
        return {k: na(why) for k in keys}
    _, la, lb, ra, rb, va, vb = best
    try:
        corr = correlation(ra, rb)
    except StatisticsError:
        corr = None
    mix = M.volatility([(x + y) / 2 for x, y in zip(ra, rb)])
    return {"acct_a": la, "acct_b": lb, "vol_a": pct(va), "vol_b": pct(vb), "vol_avg": pct((va + vb) / 2),
            "corr_ab": f"{corr:.2f}" if corr is not None else na("one of the accounts' returns do not vary"),
            "vol_mix": pct(mix) if mix is not None else na("not enough months")}


def _inline(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", s)
    return re.sub(r"n/a⟦(.*?)⟧", lambda m: f'<span class="na" title="{m.group(1)}">n/a</span> <span class="small">({m.group(1)})</span>', s)


def markdown_to_html(md: str) -> str:
    """The small subset the lesson uses: headings, paragraphs, bold, italic, bullets (one nested level) and tables."""
    out: list[str] = []
    lines = html.escape(md, quote=True).split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
        elif ln.startswith(":::"):
            if ln.startswith("::: details "):
                out.append(f"<details><summary>{_inline(ln[len('::: details '):].strip())}</summary>")
            else:
                out.append("</details>")
            i += 1
        elif ln.startswith("#"):
            lvl = len(ln) - len(ln.lstrip("#"))
            out.append(f"<h{lvl + 1}>{_inline(ln[lvl:].strip())}</h{lvl + 1}>")
            i += 1
        elif ln.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            rows = [r for r in rows if not all(re.fullmatch(r":?-{3,}:?", c) for c in r)]
            head = rows[0] if rows and any(rows[0]) else None
            body = rows[1:] if rows and (head or not any(rows[0])) else rows
            t = "<table>" + (("<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr>") if head else "")
            t += "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body) + "</table>"
            out.append(f'<div class="scroll">{t}</div>')
        elif ln.lstrip().startswith("- "):
            items: list[list] = []
            while i < len(lines) and lines[i].lstrip().startswith("- "):
                nested = lines[i].startswith("  ")
                text = _inline(lines[i].lstrip()[2:].strip())
                if nested and items:
                    items[-1][1].append(text)
                else:
                    items.append([text, []])
                i += 1
            out.append("<ul>" + "".join(f"<li>{t}" + (("<ul>" + "".join(f"<li>{c}</li>" for c in ch) + "</ul>") if ch else "") + "</li>" for t, ch in items) + "</ul>")
        else:
            para = [ln.strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith(("#", "|", "- ")):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out)


def fill_template(template: str, values: dict[str, str]) -> str:
    template = re.sub(r"<!--.*?-->", "", template, flags=re.S)
    unknown = sorted(set(re.findall(r"\{(\w+)\}", template)) - set(values))
    if unknown:  # a placeholder nobody computes would render as raw braces; say so instead
        values = {**values, **{k: na("not computed") for k in unknown}}
    return re.sub(r"\{(\w+)\}", lambda m: values[m.group(1)], template)


def build_lesson(runs: list[AccountRun], groups: list[GroupRun], benchmark: str, rf: Series | None, template: str | None = None,
                 index: Series | None = None) -> dict:
    """The lesson as HTML plus the points for its chart. Uses the whole-portfolio line (every account, transfers netted)."""
    whole = next((g for g in groups if g.kind == "all" and g.report is not None), None)
    ref, name = (whole.report, whole.name) if whole else (None, "")
    if ref is None:
        single = [r for r in runs if r.market and r.result is not None]
        if len(single) == 1:
            ref, name = single[0].result.report, single[0].account.label
    values: dict[str, str] = {"benchmark": benchmark, "portfolio_name": name or "your portfolio", "monthly_table_older": ""}
    raw: dict = {}
    if ref is None:
        why = "no whole-portfolio line was computed (it needs at least two accounts that could be combined)"
        for k in ("sharpe", "n_months", "start_month", "end_month", "benchmark_sharpe", "example_month", "ex_start_value", "ex_net_flow",
                  "ex_end_value", "ex_gain", "ex_return", "monthly_table", "n_within", "compounded_annual", "rf_annual_compounded", "rf_annual", "rf_month", "mean_excess_month",
                  "mean_excess_annual", "sd_month", "sd_annual", "sortino"):
            values[k] = na(why)
        values["estimate_note"] = ""
    else:
        fig = portfolio_figures(ref, rf, index)
        values.update(fig["fill"])
        raw = fig["raw"]
        values["estimate_note"] = ESTIMATE_NOTE
    values.update(account_pair(runs))
    excluded = [r.account.label for r in runs if not r.market]
    template = template if template is not None else TEMPLATE.read_text(encoding="utf-8")
    if excluded:
        values["excluded_accounts"] = ", ".join(excluded[:-1]) + (" and " if len(excluded) > 1 else "") + excluded[-1]
    else:  # nothing to explain: drop the bullet rather than render a nonsense sentence
        template = re.sub(r"^- \*\*Left out:\*\*.*\n?", "", template, flags=re.M)
    body = markdown_to_html(fill_template(template, values))
    marker = body.find("</p>", body.find("The Sharpe ratio is a slope"))
    if marker != -1:
        marker += 4
        body = body[:marker] + '\n<figure><div id="sharpechart"></div><figcaption id="sharpecap"></figcaption></figure>' + body[marker:]
    return {"html": body, "points": raw.get("points"), "raw": {k: v for k, v in raw.items() if k in ("sharpe", "sortino", "benchmark_sharpe")},
            "benchmark": benchmark}

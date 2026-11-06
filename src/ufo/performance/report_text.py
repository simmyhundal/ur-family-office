"""Pretty terminal report (rich): headline, comparison table, calendar years, and data checks. Local only."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ufo.performance.report_html import calendar_years, money, num, pct, spct
from ufo.performance.run import Result

BAR = 24


def _bar(v: float, scale: float, color: str) -> Text:
    n = min(BAR, round(abs(v) / scale * BAR)) if scale else 0
    return Text(("▐" * n) if v >= 0 else ("▌" * n), style=color)


def print_report(res: Result, console: Console | None = None) -> None:
    c = console or Console()
    r = res.report
    ex = r.excess_irr
    color = "green" if (ex or 0) >= 0 else "red"
    head = Text()
    head.append("Excess IRR  ", style="bold")
    head.append(spct(ex), style=f"bold {color}")
    head.append(f"\n{r.start} to {r.end}   ending value {money(r.end_value)}\n", style="dim")
    head.append(f"Your cash flows earned {pct(r.irr)} a year; the same flows in {res.benchmark} would have earned {pct(r.index_irr)}.")
    c.print(Panel(head, title="Fidelity performance", border_style=color, padding=(1, 2)))

    mx = r.mix
    t = Table(title=f"You vs {res.benchmark}" + (f" vs {mx.name}" if mx else ""), header_style="bold", show_lines=False)
    t.add_column("Measure")
    t.add_column("You", justify="right")
    t.add_column(res.benchmark, justify="right")
    if mx:
        t.add_column(mx.name, justify="right")
    add = lambda *cells, extra="": t.add_row(*cells, *([extra] if mx else []))
    add("IRR (money-weighted)", pct(r.irr), pct(r.index_irr), extra=pct(mx.irr) if mx else "")
    add("Excess IRR", spct(ex), "", extra=spct(mx.irr - r.index_irr) if mx and mx.irr is not None and r.index_irr is not None else "")
    add("Worth today (same deposits/withdrawals)", money(r.end_value), money(r.index_end_value), extra=money(mx.end_value) if mx else "")
    add("PME (Kaplan-Schoar), >1 beats index", num(r.pme, 3), "")
    add("Time-weighted return / yr (est.)", pct(r.twr_annual), pct(r.index_twr_annual), extra=pct(mx.twr_annual) if mx else "")
    add("Sharpe ratio (est.)", num(r.sharpe), num(r.index_sharpe), extra=num(mx.sharpe) if mx else "")
    add("Volatility / yr", pct(r.volatility), pct(r.index_volatility))
    add("Max drawdown", pct(r.max_drawdown), pct(r.index_max_drawdown), extra=pct(mx.max_drawdown) if mx else "")
    add("Beta / yearly alpha", f"{num(r.beta)} / {spct(r.alpha)}", "")
    c.print(t)

    cy = calendar_years(r.months, r.port_returns, r.index_returns)
    scale = max(abs(v) for _, a, b, _ in cy for v in (a, b)) or 1
    y = Table(title="Calendar years (* part year)", header_style="bold")
    for col in ("Year", "You", "", res.benchmark, "", "Diff"):
        y.add_column(col, justify="right" if col in ("You", res.benchmark, "Diff") else "left")
    for yr, a, b, n in cy:
        y.add_row(f"{yr}{'*' if n < 12 else ''}", spct(a), _bar(a, scale, "green"), spct(b), _bar(b, scale, "yellow"),
                  Text(spct(a - b), style="green" if a >= b else "red"))
    c.print(y)

    d = Table(title="Data checks: rebuilt value vs Fidelity's own totals", header_style="bold")
    for col in ("Date", "Source", "Fidelity", "Rebuilt", "Result"):
        d.add_column(col, justify="right" if col in ("Fidelity", "Rebuilt") else "left")
    for q in res.reconciliation:
        d.add_row(str(q["when"]), q["source"], f"{q['reference']:,.0f}", f"{q['rebuilt']:,.0f}",
                  Text(f"{'matches' if q['ok'] else 'check'} ({q['pct'] * 100:+.1f}%)", style="green" if q["ok"] else "yellow"))
    c.print(d)
    for n in res.notes + res.warnings:
        c.print(f"[dim]- {n}[/dim]")
    c.print("[dim]Time-weighted return and Sharpe rest on estimated month-end values. IRR does not.\nInformation, not investment advice.[/dim]")

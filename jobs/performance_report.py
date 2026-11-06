"""Fidelity performance report: excess IRR, Sharpe and comparison charts vs a total-market index. Read-only, local only.

  python -m jobs.performance_report --account 0042 --end 2026-10-31 --end-value 50000 \\
      --checkpoint 2025-12-31=48000:"statement, start of year"
Writes exports/performance-report.html (owner-only) and prints a summary. Nothing leaves the machine except ticker
symbols and date ranges sent to the price services.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from rich.console import Console

from ufo.performance.report_html import render
from ufo.performance.report_text import print_report
from ufo.performance.run import find, run
from ufo.providers.prices import PriceError, PriceStore, WebClient


def _checkpoint(s: str) -> tuple[date, float, str]:
    left, _, label = s.partition(":")
    d, _, v = left.partition("=")
    return date.fromisoformat(d), float(v), label or "statement"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", default="exports/*/History*.csv", help="glob of Fidelity activity-history CSVs")
    ap.add_argument("--snapshots", default="exports/snapshots/*.csv", help="glob of Fidelity positions CSVs (file names end in Mon-DD-YYYY)")
    ap.add_argument("--account", required=True, help="last digits of the account to analyze (matched against the account column)")
    ap.add_argument("--end", required=True, help="valuation date, YYYY-MM-DD")
    ap.add_argument("--end-value", type=float, required=True, help="the account's value on that date (from the statement)")
    ap.add_argument("--benchmark", default="VTI")
    ap.add_argument("--checkpoint", action="append", default=[], help="DATE=VALUE[:label] from a statement; repeatable")
    ap.add_argument("--out", default="exports/performance-report.html")
    ap.add_argument("--cache", default=".data/prices")
    a = ap.parse_args(argv)
    con = Console()
    hist, snaps = find(a.history), find(a.snapshots)
    if not hist:
        con.print(f"[red]No history files match {a.history}.[/red] Export the account's activity history from Fidelity into exports/.")
        return 2
    try:
        res = run(hist, snaps, a.account, date.fromisoformat(a.end), a.end_value, PriceStore(Path(a.cache), WebClient()),
                  a.benchmark, [_checkpoint(c) for c in a.checkpoint])
    except (PriceError, ValueError) as e:
        con.print(f"[red]{e}[/red]")
        return 2
    print_report(res, con)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(render(res))
    con.print(f"\nFull report with charts: [bold]{out}[/bold] (owner-only file; open it in a browser)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Suggested mix: maximize the Sharpe ratio, tested walk-forward (issue 130, milestone M12). Read-only, local only.

  python -m jobs.whatif_sharpe --funds IVV,IWM,SCHM,VGT,VXUS,XBI,VTI,BND [--lookback 60] [--rebalance 12] [--min 0 --max 40] \\
      [--start 2001-09] [--standin SCHM=IJH ...] [--current IVV=24,IWM=24,...] [--out exports/whatif-sharpe.md]

Computes the long-only efficient frontier and the max-Sharpe mix from monthly adjusted closes, then judges the optimizer
walk-forward: at each rebalance it sees only earlier data. Prints a summary and writes a report (owner-only, mode 0600).
No leverage. Nothing here places or suggests an order. Only ticker symbols and date ranges go to the price service.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from rich.console import Console

from ufo.performance.frontier import render_markdown, run_study
from ufo.performance.whatif import DEFAULT_STANDINS, build_panel, parse_mix, parse_standins, parse_ym
from ufo.providers.prices import PriceError, PriceStore, WebClient

STANDINS = {**DEFAULT_STANDINS, "BND": "VBMFX"}


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o600)


def main(argv: list[str] | None = None, store: PriceStore | None = None, today: date | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--funds", required=True, help="comma-separated tickers the optimizer may hold, e.g. IVV,IWM,VTI,BND")
    ap.add_argument("--lookback", type=int, default=60, help="months of history the optimizer sees (default 60)")
    ap.add_argument("--rebalance", type=int, default=12, help="months between rebalances (default 12)")
    ap.add_argument("--min", type=float, default=0.0, help="minimum weight per fund, percent (default 0)")
    ap.add_argument("--max", type=float, default=40.0, help="maximum weight per fund, percent (default 40)")
    ap.add_argument("--start", help="first month to use, YYYY-MM (default: the earliest month every fund or stand-in has prices)")
    ap.add_argument("--standin", action="append", default=[], metavar="FUND=STANDIN",
                    help="proxy used before FUND existed, repeatable; defaults: " + ", ".join(f"{k}={v}" for k, v in STANDINS.items()))
    ap.add_argument("--current", help='your current mix for comparison, e.g. "IVV=24,IWM=24,SCHM=24,VGT=10,VXUS=9,XBI=9"')
    ap.add_argument("--out", default="exports/whatif-sharpe.md")
    ap.add_argument("--root", default=".")
    ap.add_argument("--cache", default=".data/prices")
    a = ap.parse_args(argv)
    con = Console(highlight=False)
    today = today or date.today()
    root = Path(a.root)
    try:
        funds = list(dict.fromkeys(s.strip().upper() for s in a.funds.split(",") if s.strip()))
        if len(funds) < 2:
            raise ValueError("Give at least two funds.")
        if a.lookback < 24 or a.rebalance < 1:
            raise ValueError("Use a lookback of at least 24 months and a rebalance of at least 1.")
        current = parse_mix(a.current) if a.current else None
        standins = parse_standins(a.standin)
        for k, v in STANDINS.items():
            standins.setdefault(k, v)
        start = parse_ym(a.start) if a.start else None
    except ValueError as e:
        con.print(f"[red]{e}[/red]")
        return 2
    store = store or PriceStore(root / a.cache, WebClient(), today)
    symbols = list(dict.fromkeys([*funds, *(current or {}), "VTI", "BND"]))
    fetch_from = date(min(2000, (start // 12) if start else 2000), 1, 1)
    try:
        series = {s: store.series(s, fetch_from, today) for s in symbols}
        for s in dict.fromkeys(standins[s] for s in symbols if s in standins):
            if s not in series:
                try:
                    series[s] = store.series(s, fetch_from, today)
                except PriceError:
                    pass  # only needed before a fund existed; build_panel says if it was needed and is missing
        panel = build_panel(series, symbols, standins, start, today)
        rf = store.risk_free(fetch_from, today)
        study = run_study(panel, funds, rf, a.lookback, a.rebalance, a.min / 100, a.max / 100, current)
    except (PriceError, ValueError) as e:
        con.print(f"[red]{e}[/red]")
        return 1
    text = render_markdown(study, today)
    print(text)
    out = root / a.out
    write_private(out, text)
    con.print(f"\nWritten to [bold]{out}[/bold] (owner-only file).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

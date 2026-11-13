"""Run the performance report for every account in .data/accounts.json and print one table. Read-only, local only.

  python -m jobs.portfolio_compare [--benchmark VT] [--max-age-days 45]
Add accounts with: python -m ufo.setup accounts. The single-account jobs.performance_report keeps working.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from rich.console import Console

from ufo.accounts.registry import RegistryError, load_registry, registry_path
from ufo.performance.combine import combine_all
from ufo.performance.compare import MAX_VALUE_AGE_DAYS, print_table, run_all, unmatched_rows
from jobs.performance_report import NAMES
from ufo.performance.holdings import classes_path, load_classes, print_holdings
from ufo.performance.dashboard import BENCHMARKS, build_data, render as render_page, write
from ufo.providers.prices import PriceError, PriceStore, WebClient


def main(argv: list[str] | None = None, store: PriceStore | None = None, today: date | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--benchmark", default="VT", help="the benchmark selected when the page opens (the page can switch between VT, VTI, SPY, QQQ, AOR and BND)")
    ap.add_argument("--max-age-days", type=int, default=MAX_VALUE_AGE_DAYS)
    ap.add_argument("--also", action="append", default=[], metavar="[NAME=]SYMBOL", help='another comparison column, repeatable: "IVV" or "Wellesley=VWINX"')
    ap.add_argument("--out", default="exports/portfolio-compare.html", help="local dashboard (owner-only file); '' to skip")
    ap.add_argument("--root", default=".")
    ap.add_argument("--cache", default=".data/prices")
    ap.add_argument("--demo", default="", help=argparse.SUPPRESS)  # banner text for a page built from invented data (scripts/build_demo_dashboard.py)
    a = ap.parse_args(argv)
    con = Console()
    root = Path(a.root)
    try:
        reg = load_registry(registry_path(root))
    except RegistryError as e:
        con.print(f"[red]{e}[/red]")
        return 2
    if not reg.accounts:
        con.print("[red]No accounts yet.[/red] Add them with: python -m ufo.setup accounts")
        return 2
    store = store or PriceStore(Path(a.cache), WebClient())
    try:
        classes = load_classes(classes_path(root))
    except ValueError as e:
        con.print(f"[red]{e}[/red]")
        return 2
    runs = run_all(reg, root, store, a.benchmark, today, a.max_age_days)
    print_table(runs, a.benchmark, con, unmatched_rows(reg, root), combine_all(runs, store, a.benchmark))
    print_holdings(runs, classes, con)
    done = [r for r in runs if r.result]
    if a.out and done:
        extras_spec = {}
        for spec in a.also:
            name, eq, sym = spec.partition("=")
            sym = (sym if eq else name).strip().upper()
            extras_spec[(name if eq else NAMES.get(sym, sym)).strip()] = {sym: 1.0}
        asof = max(r.end for r in done)
        start = min(r.result.first_trade for r in done) - timedelta(days=5)
        try:
            series, _ = store.report([a.benchmark] + [s for w in extras_spec.values() for s in w], start, asof)
            extras = {n: (w, series) for n, w in extras_spec.items() if all(k in series for k in w)}
            alts = {}
            for sym, _ in BENCHMARKS:  # the picker's other benchmarks; one that cannot be loaded is left out of the picker
                if sym != a.benchmark:
                    try:
                        got, _w = store.report([sym], start, asof)
                        if sym in got:
                            alts[sym] = got[sym]
                    except (PriceError, KeyError, ValueError):
                        pass
            data = build_data(done, combine_all(done, store, a.benchmark, singletons=True), a.benchmark, series[a.benchmark], extras, asof, classes, store.risk_free(start, asof),
                              {a.benchmark: series[a.benchmark], **alts})
        except (PriceError, KeyError) as e:
            con.print(f"[red]Could not build the dashboard: {e}[/red]")
            return 1
        if a.demo:
            data["demo"] = a.demo
        out = root / a.out
        write(out, render_page(data))
        con.print(f"\nDashboard: [bold]{out}[/bold] (owner-only file; open it in a browser)")
    return 0 if all(not r.error for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())

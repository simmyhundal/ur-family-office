"""Run the performance report for every account in .data/accounts.json and print one table. Read-only, local only.

  python -m jobs.portfolio_compare [--benchmark VTI] [--max-age-days 45]
Add accounts with: python -m ufo.setup accounts. The single-account jobs.performance_report keeps working.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from rich.console import Console

from ufo.accounts.registry import RegistryError, load_registry, registry_path
from ufo.performance.combine import combine_all
from ufo.performance.compare import MAX_VALUE_AGE_DAYS, print_table, run_all, unmatched_rows
from ufo.providers.prices import PriceStore, WebClient


def main(argv: list[str] | None = None, store: PriceStore | None = None, today: date | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--benchmark", default="VTI")
    ap.add_argument("--max-age-days", type=int, default=MAX_VALUE_AGE_DAYS)
    ap.add_argument("--root", default=".")
    ap.add_argument("--cache", default=".data/prices")
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
    runs = run_all(reg, root, store, a.benchmark, today, a.max_age_days)
    print_table(runs, a.benchmark, con, unmatched_rows(reg, root), combine_all(runs, store, a.benchmark))
    return 0 if all(not r.error for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())

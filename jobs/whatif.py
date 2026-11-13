"""What-if: test a target mix against a benchmark honestly (issue 70, milestone M12). Read-only, local only.

  python -m jobs.whatif --mix IVV=24,IWM=24,SCHM=24,VGT=10,VXUS=9,XBI=9 --benchmark VTI --choice-date 2023-01 \\
      [--account <registry id>] [--start 2001-09] [--standin SCHM=IJH ...]

Rolling lump-sum windows (annual rebalancing, never-rebalanced as a sensitivity) with in-sample / out-of-sample splits, and with
--account a replay of that account's dated deposits and withdrawals at every start month, judged by ending value.
Prints a summary and writes exports/whatif.md (owner-only). Only ticker symbols and date ranges go to the price service.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from rich.console import Console

from ufo.accounts.registry import RegistryError, load_registry, registry_path
from ufo.performance.compare import run_account
from ufo.performance.whatif import (DEFAULT_STANDINS, build_panel, parse_mix, parse_standins, parse_ym, render_markdown,
                                    run_whatif)
from ufo.providers.prices import PriceError, PriceStore, WebClient


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o600)


def main(argv: list[str] | None = None, store: PriceStore | None = None, today: date | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mix", required=True, help='target mix, e.g. "IVV=24,IWM=24,SCHM=24,VGT=10,VXUS=9,XBI=9" (weights are normalized)')
    ap.add_argument("--benchmark", default="VTI")
    ap.add_argument("--choice-date", help="YYYY-MM when the mix was chosen: windows that ended by then are what a backtest could see; "
                                          "windows starting at or after it are out-of-sample")
    ap.add_argument("--account", help="registry id: replay this account's dated deposits and withdrawals")
    ap.add_argument("--start", help="first month to use, YYYY-MM (default: the earliest month every fund or stand-in has prices)")
    ap.add_argument("--standin", action="append", default=[], metavar="FUND=STANDIN",
                    help="proxy used before FUND existed, repeatable; defaults: " + ", ".join(f"{k}={v}" for k, v in DEFAULT_STANDINS.items()))
    ap.add_argument("--out", default="exports/whatif.md")
    ap.add_argument("--root", default=".")
    ap.add_argument("--cache", default=".data/prices")
    ap.add_argument("--max-age-days", type=int, default=45)
    a = ap.parse_args(argv)
    con = Console(highlight=False)
    today = today or date.today()
    root = Path(a.root)
    try:
        mix = parse_mix(a.mix)
        standins = parse_standins(a.standin)
        choice = parse_ym(a.choice_date) if a.choice_date else None
        start = parse_ym(a.start) if a.start else None
    except ValueError as e:
        con.print(f"[red]{e}[/red]")
        return 2
    bench = a.benchmark.strip().upper()
    store = store or PriceStore(Path(a.cache), WebClient(), today)
    flows, end, label = None, None, ""
    if a.account:
        try:
            acct = load_registry(registry_path(root)).get(a.account)
        except RegistryError as e:
            con.print(f"[red]{e}[/red]")
            return 2
        if acct is None:
            con.print(f"[red]No account '{a.account}' in the registry.[/red]")
            return 2
        run = run_account(acct, root, store, bench, today, a.max_age_days)
        if run.error:
            con.print(f"[red]{acct.label}: {run.error}[/red]")
            return 2
        flows = [(e.when, e.external_flow) for e in run.events if e.external_flow and e.when <= run.end]
        if not flows:
            con.print(f"[red]{acct.label}: no deposits or withdrawals to replay.[/red]")
            return 2
        end, label = run.end, acct.label
    symbols = list(dict.fromkeys([*mix, bench]))
    wanted = symbols + [standins[s] for s in symbols if s in standins]
    fetch_from = date(min(2000, (start // 12) if start else 2000), 1, 1)
    try:
        series = {s: store.series(s, fetch_from, today) for s in symbols}
        for s in dict.fromkeys(wanted):
            if s not in series:
                try:
                    series[s] = store.series(s, fetch_from, today)
                except PriceError:
                    pass  # a stand-in is only needed before a fund existed; build_panel says if it was needed and is missing
        panel = build_panel(series, symbols, standins, start, today)
        result = run_whatif(panel, mix, bench, choice, flows, end, label)
    except (PriceError, ValueError) as e:
        con.print(f"[red]{e}[/red]")
        return 1
    text = render_markdown(result, today)
    print(text)
    out = root / a.out
    write_private(out, text)
    con.print(f"\nWritten to [bold]{out}[/bold] (owner-only file).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

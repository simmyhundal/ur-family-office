"""Assemble a performance run for one Fidelity account: files in, a Result out. No printing here."""
from __future__ import annotations

import glob
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from ufo import importers
from ufo.performance import metrics as M
from ufo.performance.events import ParsedHistory
from ufo.performance.ledger import Checkpoint, Ledger, Snapshot, is_fixed_income
from ufo.providers.prices import PriceStore

SNAPSHOT_TOLERANCE = 0.02  # a positions export is priced intraday, so ~2% against a close is normal
STATEMENT_TOLERANCE = 0.005


class Result(BaseModel):
    report: M.Report
    reconciliation: list[dict]
    warnings: list[str]
    notes: list[str]
    benchmark: str
    income_credited: float
    events: int
    first_trade: date
    month_values: list[tuple[date, float]] = []  # every month-end with its value, including the first partial month the report drops


def _snapshot_date(path: str) -> date | None:
    m = re.search(r"([A-Z][a-z]{2}-\d\d-\d{4})", path)
    return datetime.strptime(m.group(1), "%b-%d-%Y").date() if m else None


def run(history_files: list[str], snapshot_files: list[str], account_mask: str, end: date, end_value: float,
        store: PriceStore, benchmark: str = "VTI", statement_values: list[tuple[date, float, str]] | None = None,
        mix: dict[str, float] | None = None, mix_name: str = "Target mix",
        also: list[tuple[str, dict[str, float], str]] | None = None) -> Result:
    """The single-account Fidelity entry point: a thin wrapper over `run_core` through the importer interface."""
    imp = importers.get("fidelity")
    hist = imp.parse(history_files)
    snaps = imp.positions(snapshot_files, account_mask)
    extra = [f"{Path(f).name}: no holdings for account ending {account_mask}." for f in sorted(snapshot_files)
             if _snapshot_date(f) and _snapshot_date(f) not in {s.when for s in snaps}]
    return run_core(hist, snaps, end, end_value, store, benchmark, statement_values, mix, mix_name, also, extra)


def run_core(hist: ParsedHistory, snapshots: list[Snapshot], end: date, end_value: float, store: PriceStore,
             benchmark: str = "VTI", statement_values: list[tuple[date, float, str]] | None = None,
             mix: dict[str, float] | None = None, mix_name: str = "Target mix",
             also: list[tuple[str, dict[str, float], str]] | None = None, extra_warnings: list[str] | None = None) -> Result:
    """Brokerage-neutral core: already-parsed events and snapshots in, a Result out. `mix` is the owner's own plan;
    `also` are extra comparisons as (name, weights, one-line description)."""
    if not hist.events:
        raise ValueError("No transactions found in the history files.")
    warnings = list(hist.warnings) + list(extra_warnings or [])
    symbols = sorted({e.symbol for e in hist.events if e.symbol and not is_fixed_income(e.symbol)})
    start = hist.first - timedelta(days=5)
    scen = ([(mix_name, mix, "plan", "")] if mix else []) + [(n, w, "benchmark", d) for n, w, d in (also or [])]
    wanted = sorted({sym for _, w, _, _ in scen for sym in w})
    prices, price_warnings = store.report(symbols + [benchmark] + wanted, start, end)
    warnings += price_warnings
    if benchmark not in prices:
        raise ValueError(f"Could not load the benchmark {benchmark}: {price_warnings}")
    rf = store.risk_free(start, end)
    ledger = Ledger(hist.events, prices)
    warnings += ledger.warnings

    checks = [(Checkpoint(when=sn.when - timedelta(days=1), value=sn.value, source="positions snapshot"), SNAPSHOT_TOLERANCE)
              for sn in snapshots if sn.value is not None]
    snaps = snapshots
    ledger.anchor(snaps)
    for d, v, src in statement_values or []:
        checks.append((Checkpoint(when=d, value=v, source=src), STATEMENT_TOLERANCE))
    rows = []
    for cp, tol in checks:
        rows += ledger.reconcile([cp], tolerance=tol)
    rows.sort(key=lambda r: r["when"])

    months = ledger.month_ends(None, end)
    values = [ledger.value_on(d).total for d in months]
    first_start = date(months[0].year, months[0].month, 1) - timedelta(days=1)
    rets = [ledger.holdings_return(prev, cur, M.monthly_rf(rf, prev))
            for prev, cur in zip([first_start] + months[:-1], months)]
    missing = [s for s in wanted if s not in prices]
    if missing:
        raise ValueError(f"Could not load prices for: {', '.join(missing)}")
    report = M.analyze(ledger.flows(), months, values, prices[benchmark], rf, end, end_value, returns=rets,
                       scenarios=scen, scenario_series=prices)
    notes = list(ledger.anchor_notes)
    notes.append("Monthly returns use what was held at the start of each month (price moves, cash at the T-bill rate), "
                 "so share counts that are slightly off change the weights, not the return.")
    if ledger.income_total():
        notes.append("The history omits dividends and interest; cash credits the export implies were counted as income "
                     "inside the return, never as contributions.")
    return Result(report=report, reconciliation=rows, warnings=warnings, notes=notes, benchmark=benchmark,
                  income_credited=ledger.income_total(), events=len(hist.events), first_trade=hist.first,
                  month_values=list(zip(months, values)))


def find(pattern: str) -> list[str]:
    return sorted(glob.glob(pattern))

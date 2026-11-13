"""Run the performance analysis for every account in the registry and collect one row each (issue 100).

Read-only and local. Accounts that cannot be computed (no files, no ending value, a stale value) are reported by name
rather than skipped silently. Prices come from one shared PriceStore (its disk cache fetches each symbol once).
"""
from __future__ import annotations

import glob
from datetime import date
from pathlib import Path

from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

from ufo import importers
from ufo.accounts.registry import Account, Registry
from ufo.performance.events import Event
from ufo.performance.holdings import Holding
from ufo.performance.report_html import money, pct, spct
from ufo.performance.run import Result, run_core
from ufo.providers.prices import PriceError, PriceStore

MAX_VALUE_AGE_DAYS = 45
SHORT_HISTORY_DAYS = 90


class AccountRun(BaseModel):
    account: Account
    result: Result | None = None
    events: list[Event] = []
    end: date | None = None
    end_value: float | None = None
    quality: str = ""  # "exact" | "estimated"
    flags: list[str] = []
    holdings: list[Holding] = []  # latest positions snapshot, when the importer offers one
    holdings_as_of: date | None = None
    anchors: dict[date, tuple[float, str]] = {}  # dated values the account itself supplies: statement or snapshot
    error: str = ""

    @property
    def net_contributions(self) -> float | None:
        r = self.result.report if self.result else None
        return None if r is None else r.contributed - r.withdrawn


def _files(root: Path, pattern: str) -> list[str]:
    return sorted(glob.glob(str(root / pattern))) if pattern else []


def ending(a: Account, snapshots, today: date, max_age: int) -> tuple[date, float, bool]:
    """(end date, end value, supplied-by-statement). Raises ValueError with a plain message."""
    if a.closed:
        return a.closed, 0.0, True
    ev = a.ending_value
    if ev is None:
        raise ValueError("no ending value in the registry")
    if ev.kind == "statement":
        d, v, stmt = ev.as_of, ev.value, True
    else:
        snaps = [s for s in snapshots if s.value is not None]
        if not snaps:
            raise ValueError("ending value is 'snapshot' but no positions snapshot with a value was found")
        last = max(snaps, key=lambda s: s.when)
        d, v, stmt = last.when, last.value, False
    if (today - d).days > max_age:
        raise ValueError(f"ending value is from {d}, older than the {max_age}-day limit; add a newer statement value")
    return d, v, stmt


def run_account(a: Account, root: Path, store: PriceStore, benchmark: str, today: date,
                max_age: int = MAX_VALUE_AGE_DAYS) -> AccountRun:
    out = AccountRun(account=a)
    try:
        imp = importers.get(a.source.importer)
        hist_files = _files(root, a.source.history_glob)
        if not hist_files:
            raise ValueError(f"no history files match {a.source.history_glob}")
        hist = imp.parse(hist_files, a.last_digits)
        if not hist.events:
            raise ValueError("no transactions found for this account")
        for e in hist.events:
            e.account_id = a.id
        snaps = imp.positions(_files(root, a.source.snapshot_glob), a.last_digits) if a.source.snapshot_glob else []
        if a.source.snapshot_glob and hasattr(imp, "holdings"):
            out.holdings_as_of, out.holdings = imp.holdings(_files(root, a.source.snapshot_glob), a.last_digits)
        end, value, stmt = ending(a, snaps, today, max_age)
        if hasattr(imp, "prices"):  # an importer that supplies its own unit prices (no tickers in the files)
            store.add_own(imp.prices(hist_files))
        stmts = imp.statement_values(_files(root, a.source.statement_glob)) if a.source.statement_glob and hasattr(imp, "statement_values") else []
        out.anchors = {sn.when: (sn.value, "snapshot") for sn in snaps if sn.value is not None}
        out.anchors.update({d: (v, "statement") for d, v, _ in stmts})
        res = run_core(hist, snaps, end, value, store, benchmark, statement_values=stmts)
    except (ValueError, KeyError, PriceError) as e:
        out.error = str(e).strip("'\"")
        return out
    out.result, out.events, out.end, out.end_value = res, hist.events, end, value
    bad = [q for q in res.reconciliation if not q["ok"]]
    out.quality = "exact" if stmt and not bad and not res.income_credited else "estimated"
    note = getattr(imp, "estimate_note", "")  # an importer whose statements leave flow dates or values inside a period unknown
    if note:
        out.quality = "estimated"
        out.flags.append(note)
    if (end - res.first_trade).days < SHORT_HISTORY_DAYS:
        out.flags.append("short history")
    if a.closed:
        out.flags.append("closed")
    return out


def unmatched_rows(reg: Registry, root: Path) -> list[str]:
    """Rows in a shared export whose account text matches no registry entry."""
    msgs = []
    seen: set[tuple[str, str]] = set()
    for a in reg.accounts:
        key = (a.source.importer, a.source.history_glob)
        if key in seen:
            continue
        seen.add(key)
        files = _files(root, a.source.history_glob)
        if not files:
            continue
        hist = importers.get(a.source.importer).parse(files)
        mine = [b.last_digits for b in reg.accounts if (b.source.importer, b.source.history_glob) == key and b.last_digits]
        stray = {e.account_ref for e in hist.events if e.account_ref and not any(e.account_ref.endswith(d) for d in mine)}
        for ref in sorted(stray):
            n = sum(1 for e in hist.events if e.account_ref == ref)
            msgs.append(f"{n} rows in {a.source.history_glob} are for an account ending {ref[-4:]} that is not in the registry.")
    return msgs


def run_all(reg: Registry, root: Path, store: PriceStore, benchmark: str = "VTI", today: date | None = None,
            max_age: int = MAX_VALUE_AGE_DAYS) -> list[AccountRun]:
    today = today or date.today()
    return [run_account(a, root, store, benchmark, today, max_age) for a in reg.accounts]


def print_table(runs: list[AccountRun], benchmark: str, console: Console | None = None, notes: list[str] | None = None,
                groups: list | None = None) -> None:
    c = console or Console()
    t = Table(title=f"All accounts vs {benchmark}", header_style="bold")
    for col, right in (("Account", False), ("Type", False), ("Value", True), ("Net in", True), ("IRR", True),
                       (f"Excess IRR vs {benchmark}", True), ("Data", False), ("Notes", False)):
        t.add_column(col, justify="right" if right else "left")
    for r in runs:
        a = r.account
        if r.error:
            t.add_row(a.label, a.wrapper.value, "", "", "", "", "[red]not computed[/red]", r.error)
            continue
        rep = r.result.report
        t.add_row(a.label, a.wrapper.value, money(r.end_value), ("-" if r.net_contributions < 0 else "") + money(abs(r.net_contributions)), pct(rep.irr), spct(rep.excess_irr),
                  r.quality, ", ".join(r.flags))
    for g in groups or []:
        if g.error or g.report is None:
            t.add_row(f"[bold]{g.name}[/bold]", "combined", "", "", "", "", "[red]not computed[/red]", g.error)
            continue
        rep = g.report
        net = rep.contributed - rep.withdrawn
        t.add_row(f"[bold]{g.name}[/bold]", "combined", money(g.end_value), ("-" if net < 0 else "") + money(abs(net)), pct(rep.irr),
                  spct(rep.excess_irr), g.quality, ", ".join([f"{len(g.transfers)} netted"] + ([g.note] if g.note else [])))
        notes = list(notes or []) + g.unmatched
    c.print(t)
    for n in dict.fromkeys(notes or []):
        c.print(f"[dim]- {n}[/dim]")
    c.print("[dim]Figures are before tax. IRR rests on exact dated flows plus the ending value.\nInformation, not investment advice.[/dim]")

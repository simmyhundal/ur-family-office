"""Run the performance analysis for every account in the registry and collect one row each (issue 100).

Read-only and local. Accounts that cannot be computed (no files, no ending value, a stale value) are reported by name
rather than skipped silently. Prices come from one shared PriceStore (its disk cache fetches each symbol once).
"""
from __future__ import annotations

import glob
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

from ufo import importers
from ufo.accounts.registry import Account, Registry
from ufo.performance.events import Event
from ufo.performance import metrics as M
from ufo.performance.holdings import Holding
from ufo.performance.report_html import money, pct, spct
from ufo.performance.run import Result, run_core
from ufo.providers.prices import PriceError, PriceStore, Series

MAX_VALUE_AGE_DAYS = 45
SHORT_HISTORY_DAYS = 90
NARROW_WIDTH = 120  # terminal columns below which the table shows fewer columns
HISTORY_GAP_DAYS = 7  # an ending value this many days after the last transaction may include activity the history lacks


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
    def holdings_note(self) -> str:
        """Why there is no holdings table for this account ('' when there is one or the run failed)."""
        if self.holdings or self.error:
            return ""
        if hasattr(importers.get(self.account.source.importer), "holdings") and self.account.source.snapshot_glob:
            return "holdings not available: no positions file lists this account"
        return "holdings not available: this brokerage's files do not list positions"

    @property
    def market(self) -> bool:
        return self.account.market

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


def _month_ends(first: date, end: date) -> list[date]:
    out, d = [], date(first.year, first.month, 1)
    while True:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        if nxt - timedelta(days=1) > end:
            return out
        out.append(nxt - timedelta(days=1))
        d = nxt


def nonmarket_result(hist, end: date, value: float, index: Series | None = None) -> Result:
    """A Result for an account with no market prices (a fixed annuity): IRR from the dated flows and the ending value only.
    Month-end values are the flows grown at that IRR (an estimate; exact at the end). With the benchmark's prices it also
    answers "what if the same flows had gone into the benchmark" (worth today, excess IRR), which needs no price history of
    the account. Measures that do (time-weighted return, Sharpe, volatility, drawdown, beta, alpha) stay empty."""
    flows = sorted((e.when, e.external_flow) for e in hist.events if e.external_flow)
    if not flows:
        raise ValueError("no deposits or withdrawals found for this account")
    irr = M.xirr(M.investor_flows(flows, end, value))
    months = _month_ends(flows[0][0], end)
    r = irr or 0.0
    values = [sum(a * (1 + r) ** ((m - d).days / 365) for d, a in flows if d <= m) for m in months]
    cf = M.index_counterfactual(flows, index, end) if index is not None else None
    cf_irr = cf.irr if cf else None
    rep = M.Report(start=flows[0][0], end=end, end_value=value, contributed=sum(a for _, a in flows if a > 0),
                   withdrawn=-sum(a for _, a in flows if a < 0), irr=irr, index_irr=cf_irr,
                   excess_irr=(irr - cf_irr) if irr is not None and cf_irr is not None else None, pme=None,
                   twr_annual=None, index_twr_annual=None, sharpe=None, index_sharpe=None, sortino=None, volatility=None,
                   index_volatility=None, max_drawdown=0.0, index_max_drawdown=0.0, beta=None, alpha=None,
                   index_end_value=cf.terminal_value if cf else 0.0, index_values=[], months=months, port_growth=[], index_growth=[], port_returns=[],
                   index_returns=[], flows_by_month=[], values=values)
    return Result(report=rep, reconciliation=[], warnings=list(hist.warnings), notes=[], benchmark="", income_credited=0.0,
                  events=len(hist.events), first_trade=hist.first, month_values=list(zip(months, values)))


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
        if not a.market:
            first = min(e.when for e in hist.events if e.external_flow) - timedelta(days=5) if any(e.external_flow for e in hist.events) else end
            try:
                bench, _ = store.report([benchmark], first, end)
            except PriceError:
                bench = {}
            out.result, out.events, out.end, out.end_value = nonmarket_result(hist, end, value, bench.get(benchmark)), hist.events, end, value
            out.quality = "exact" if stmt else "estimated"
            out.holdings, out.holdings_as_of = [Holding(symbol="Fixed annuity", value=value, fixed_annuity=True)], end
            if (end - out.result.first_trade).days < SHORT_HISTORY_DAYS:
                out.flags.append("short history")
            return out
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
    last = max(e.when for e in hist.events)
    if not a.closed and (end - last).days > HISTORY_GAP_DAYS:
        out.flags.append(f"history ends {last}, ending value is from {end}: anything in between is not in the figures; windows stop at the last month-end")
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
    narrow = c.width < NARROW_WIDTH  # the full table stays in the HTML dashboard; a narrow terminal drops Type and Net in and folds Data into Notes
    t = Table(title=f"All accounts vs {benchmark}", header_style="bold")
    cols = (("Account", False), ("Value", True), ("IRR", True), (f"Excess vs {benchmark}", True), ("Notes", False)) if narrow else \
        (("Account", False), ("Type", False), ("Value", True), ("Net in", True), ("IRR", True), (f"Excess IRR vs {benchmark}", True), ("Data", False), ("Notes", False))
    for col, right in cols:
        t.add_column(col, justify="right" if right else "left", overflow="fold" if col == "Notes" else "ellipsis", min_width=8 if col != "Notes" else 12)

    def add(label, typ, value, net, irr, excess, data, note, **kw):
        row = (label, value, irr, excess, ", ".join(x for x in (data, note) if x)) if narrow else (label, typ, value, net, irr, excess, data, note)
        t.add_row(*row, **kw)

    for r in runs:
        a = r.account
        if r.error:
            add(a.label, a.wrapper.value, "", "", "", "", "[red]not computed[/red]", r.error)
            continue
        rep = r.result.report
        add(a.label, a.wrapper.value, money(r.end_value), ("-" if r.net_contributions < 0 else "") + money(abs(r.net_contributions)), pct(rep.irr),
            spct(rep.excess_irr), r.quality, ", ".join(r.flags + (["no market prices: no time-weighted return, Sharpe or drawdown"] if not r.market else [])))
    first = True
    for g in groups or []:
        total = g.kind == "all"
        name = "Total, all accounts" if total else g.name
        if g.error or g.report is None:
            add(f"[bold]{name}[/bold]", "total" if total else "combined", "", "", "", "", "[red]not computed[/red]", g.error)
            continue
        rep = g.report
        net = rep.contributed - rep.withdrawn
        add(f"[bold]{name}[/bold]", "total" if total else "combined", money(g.end_value), ("-" if net < 0 else "") + money(abs(net)),
            pct(rep.irr), spct(rep.excess_irr), f"{g.quality}, as of {g.end}",
            ", ".join([f"{len(g.transfers)} netted"] + ([g.note] if g.note else [])), end_section=first and not total)
        first = False
        if total:
            t.rows[-1].end_section = True
        notes = list(notes or []) + g.unmatched
    tot = next((g for g in groups or [] if g.kind == "all" and g.report is not None), None)
    if tot is not None:
        notes = list(notes or []) + [
            f"Totals are valued on {tot.end}, the latest month-end every account covers; the account rows above use each account's own "
            "latest date, so the sums can differ. Non-market accounts (a fixed annuity) count in value and net in. Transfers between "
            "your own accounts net out of the total, so its Net in can differ from the sum of the rows."]
    c.print(t)
    for n in dict.fromkeys(notes or []):
        c.print(f"[dim]- {n}[/dim]")
    c.print("[dim]Figures are before tax. IRR rests on exact dated flows plus the ending value.\nInformation, not investment advice.[/dim]")

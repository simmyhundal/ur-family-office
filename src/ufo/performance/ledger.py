"""Rebuild one Fidelity account's value over time from its activity history plus historical prices.

Inputs: normalized events (providers/fidelity_history) and price series (providers/prices).
Outputs: external cash flows (contributions and withdrawals only) and the account value on any date.

How value is rebuilt
- Shares per symbol come from adding up buys and sells. They are valued at the actual close (split-adjusted only).
- Cash is Fidelity's core money-market balance. The history lists trades and transfers but not income (dividends,
  CD interest and maturities). Those show up as jumps in the running `Cash Balance` column. Each jump is credited as
  internal income, never as a contribution, and dated at a CD/T-bill maturity when one fits, else at the row's date.
- CDs and T-bills (CUSIP-style symbols) are valued at cost, accruing straight-line to proceeds at maturity.
Everything that could not be priced or explained is returned as a warning, never silently dropped.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta

from pydantic import BaseModel

from ufo.performance.events import Event, Kind
from ufo.providers.prices import Series

CUSIP = re.compile(r"^[0-9A-Z]{9}$")
MATURITY = re.compile(r"(\d+(?:\.\d+)?)%\s+(\d\d/\d\d/\d{4})")
EPS = 0.005


def is_fixed_income(symbol: str) -> bool:
    return bool(CUSIP.match(symbol)) and any(c.isdigit() for c in symbol)


class Bond(BaseModel):
    symbol: str
    bought: date
    cost: float
    par: float
    matures: date
    proceeds: float  # estimated cash at maturity (par plus simple interest)

    def value_on(self, day: date) -> float:
        if day < self.bought or day >= self.matures:
            return 0.0
        span = (self.matures - self.bought).days or 1
        return self.cost + (self.proceeds - self.cost) * (day - self.bought).days / span


class Credit(BaseModel):
    when: date
    amount: float
    why: str  # "maturity", "income", "opening"


class Checkpoint(BaseModel):
    when: date
    value: float
    source: str


class Snapshot(BaseModel):
    """Shares per symbol that Fidelity reported on a date (a positions export), in that date's share units."""
    when: date
    quantities: dict[str, float]
    value: float | None = None  # the brokerage's own total for the account on that date, when the file has it


class Breakdown(BaseModel):
    when: date
    holdings: float
    fixed_income: float
    cash: float
    unpriced: list[str] = []

    @property
    def total(self) -> float:
        return self.holdings + self.fixed_income + self.cash


class Ledger:
    def __init__(self, events: list[Event], prices: dict[str, Series]):
        self.events = sorted(events, key=lambda e: (e.when, e.seq))
        self.prices = prices
        self.warnings: list[str] = []
        self.bonds = self._bonds()
        self.credits = self._credits()
        self._dates = [e.when for e in self.events]
        self._cum_cash: list[float] = []
        run = 0.0
        for e in self.events:
            run += e.amount
            self._cum_cash.append(run)
        self.opening_cash = 0.0
        self._anchors: dict[str, list[tuple[date, float]]] = {}  # symbol -> [(day, missing shares)] from snapshots
        self.anchor_notes: list[str] = []

    # ---- external cash flows ----
    def flows(self) -> list[tuple[date, float]]:
        """(date, amount): + into the account (contribution), - out of it (withdrawal)."""
        return [(e.when, e.external_flow) for e in self.events if e.external_flow]

    # ---- fixed income ----
    def _bonds(self) -> list[Bond]:
        out = []
        for e in self.events:
            if e.kind != Kind.BUY or not is_fixed_income(e.symbol):
                continue
            m = MATURITY.search(" ".join(e.description.split()))
            if not m:
                self.warnings.append(f"{e.when}: could not read a maturity date for {e.symbol}; valued at cost.")
                continue
            rate, matures = float(m.group(1)) / 100, datetime.strptime(m.group(2), "%m/%d/%Y").date()
            par, cost = abs(e.quantity or 0.0), abs(e.amount)
            years = (matures - e.when).days / 365
            proceeds = par if rate == 0 else par * (1 + rate * years)
            out.append(Bond(symbol=e.symbol, bought=e.when, cost=cost, par=par, matures=matures, proceeds=proceeds))
        return out

    # ---- unlisted cash credits ----
    def _credits(self) -> list[Credit]:
        credits: list[Credit] = []
        prev_bal: float | None = None
        prev_day: date | None = None
        paid: set[int] = set()
        for e in self.events:
            if e.cash_balance is None:
                continue
            if prev_bal is None:
                opening = round(e.cash_balance - e.amount, 2)
                if abs(opening) > EPS:
                    credits.append(Credit(when=e.when, amount=opening, why="opening"))
            else:
                resid = round(e.cash_balance - (prev_bal + e.amount), 2)
                if abs(resid) > EPS:
                    due = [(i, b) for i, b in enumerate(self.bonds) if i not in paid and prev_day < b.matures <= e.when]
                    est = sum(b.proceeds for _, b in due)
                    scale = min(1.0, resid / est) if est > 0 and resid > 0 else 1.0
                    given = 0.0
                    if resid > 0:
                        for i, b in due:
                            amt = round(b.proceeds * scale, 2)
                            credits.append(Credit(when=b.matures, amount=amt, why="maturity"))
                            paid.add(i)
                            given += amt
                    rest = round(resid - given, 2)
                    if abs(rest) > EPS:
                        credits.append(Credit(when=e.when, amount=rest, why="income"))
            prev_bal, prev_day = e.cash_balance, e.when
        self._credit_days = sorted(c.when for c in credits)
        return credits

    def income_total(self) -> float:
        return round(sum(c.amount for c in self.credits if c.why == "income"), 2)

    # ---- value on a date ----
    def _split_factor(self, symbol: str, bought: date) -> float:
        """Shares after every split that came later, so old and new trades add up in today's units
        (matches the split-adjusted closes the price loader stores)."""
        series = self.prices.get(symbol)
        f = 1.0
        for d, ratio in (series.splits() if series else []):
            if d > bought:
                f *= ratio
        return f

    def anchor(self, snapshots: list[Snapshot]) -> None:
        """Correct share counts the history cannot explain (for example reinvested distributions or transfers that the
        export leaves out). At each snapshot the gap between Fidelity's shares and the rebuilt shares (as of the close
        before, since an export shows the start of that day) is recorded; between snapshots the gap is spread in a
        straight line from zero at the account's first trade, and held flat after the last one. The correction is an
        estimate between snapshots: reports must say so."""
        gaps: dict[str, list[tuple[date, float]]] = defaultdict(list)
        for snap in sorted(snapshots, key=lambda s: s.when):
            day = snap.when - timedelta(days=1)
            base = self._raw_quantities(day)
            for sym in set(base) | set(snap.quantities):
                units = snap.quantities.get(sym, 0.0) * self._split_after(sym, snap.when)
                gaps[sym].append((day, units - base.get(sym, 0.0)))
        self._anchors = dict(gaps)
        self.anchor_notes.append(f"Share counts were anchored to {len(snapshots)} Fidelity positions snapshots; "
                                 f"{sum(1 for v in gaps.values() if abs(v[-1][1]) > 0.5)} symbols needed a correction.")

    def _split_after(self, symbol: str, day: date) -> float:
        series = self.prices.get(symbol)
        f = 1.0
        for d, ratio in (series.splits() if series else []):
            if d > day:
                f *= ratio
        return f

    def _correction(self, symbol: str, day: date) -> float:
        pts = self._anchors.get(symbol)
        if not pts:
            return 0.0
        start = self.events[0].when
        knots = [(start, 0.0)] + pts
        if day <= knots[0][0]:
            return 0.0
        if day >= knots[-1][0]:
            return knots[-1][1]
        for (d0, v0), (d1, v1) in zip(knots, knots[1:]):
            if d0 <= day <= d1:
                span = (d1 - d0).days or 1
                return v0 + (v1 - v0) * (day - d0).days / span
        return 0.0

    def quantities(self, day: date) -> dict[str, float]:
        """Shares held on `day`, in today's (post-split) units, including snapshot anchoring when applied."""
        q = defaultdict(float, self._raw_quantities(day))
        for sym in self._anchors:
            q[sym] += self._correction(sym, day)
        return {s: v for s, v in q.items() if abs(v) > 1e-6}

    def _raw_quantities(self, day: date) -> dict[str, float]:
        q: dict[str, float] = defaultdict(float)
        for e in self.events:
            if e.when > day:
                break
            if e.kind in (Kind.BUY, Kind.SELL) and e.symbol and not is_fixed_income(e.symbol) and e.quantity:
                q[e.symbol] += e.quantity * self._split_factor(e.symbol, e.when)
        return {s: v for s, v in q.items() if abs(v) > 1e-6}

    def cash_on(self, day: date) -> float:
        i = bisect_right(self._dates, day)
        listed = self._cum_cash[i - 1] if i else 0.0
        return listed + sum(c.amount for c in self.credits if c.when <= day)

    def value_on(self, day: date) -> Breakdown:
        holdings, unpriced = 0.0, []
        for sym, qty in self.quantities(day).items():
            series = self.prices.get(sym)
            px = series.close_on_or_before(day) if series else None
            if px is None:
                unpriced.append(sym)
                continue
            holdings += qty * px
        fixed = sum(b.value_on(day) for b in self.bonds)
        return Breakdown(when=day, holdings=holdings, fixed_income=fixed, cash=self.cash_on(day), unpriced=unpriced)

    def holdings_return(self, prev: date, cur: date, rf_month: float = 0.0) -> float | None:
        """Return over a month from what was held at the start of it: each position's total return (dividends included), cash at the
        risk-free rate, CDs and T-bills by their accrual. Trades and withdrawals inside the month do not enter, so a
        share count that is a little off only shifts the weights, not the return. None if nothing was held."""
        start = self.value_on(prev)
        if start.total <= 1e-9:
            return None
        end = 0.0
        for sym, qty in self.quantities(prev).items():
            series = self.prices.get(sym)
            c0 = series.close_on_or_before(prev) if series else None
            a0, a1 = (series.on_or_before(prev), series.on_or_before(cur)) if series else (None, None)
            if c0 is None:
                continue
            # total return: dividends are in the adjusted-close ratio, so income counts like it does for the index
            end += qty * c0 * ((a1 / a0) if a0 and a1 else 1.0)
        for b in self.bonds:
            if b.bought <= prev < b.matures:
                end += b.value_on(cur) if cur < b.matures else b.proceeds
        end += start.cash * (1 + rf_month)
        return end / start.total - 1

    # ---- series ----
    def month_ends(self, start: date | None = None, end: date | None = None) -> list[date]:
        first, last = start or self.events[0].when, end or self.events[-1].when
        out, y, m = [], first.year, first.month
        while True:
            nxt = date(y + (m == 12), m % 12 + 1, 1)
            me = nxt - timedelta(days=1)
            if me >= first and me <= last:
                out.append(me)
            if me >= last:
                break
            y, m = nxt.year, nxt.month
        return out

    def reconcile(self, checkpoints: list[Checkpoint], tolerance: float = 0.01) -> list[dict]:
        rows = []
        for c in sorted(checkpoints, key=lambda c: c.when):
            b = self.value_on(c.when)
            diff = b.total - c.value
            rows.append({"when": c.when, "source": c.source, "reference": c.value, "rebuilt": b.total, "diff": diff,
                         "pct": diff / c.value if c.value else 0.0, "ok": abs(diff) <= abs(c.value) * tolerance,
                         "unpriced": b.unpriced})
        return rows

"""The Equitable importer: quarterly annuity-IRA statements (PDF, read with `pdftotext`) -> neutral events.

Each statement has `Statement Period: <Month DD, YYYY>- <Month DD, YYYY>`, an Account Activity Summary with a Quarter column
(`Contributions`, `Extra Credit and/or Earnings Bonus Amount`, `Current Total Account Value`) and an Account Summary of
variable investment options: `<5-digit fund #>  <name>  <units>  $<unit value>  $<account value>`. The funds have no ticker,
so each is keyed `EQ<fund #>` and priced from the unit values on the statements themselves (quarter-ends only).

What is exact and what is estimated:
- Exact: the account value at each quarter-end (the statement's own total; units x unit value equals it).
- Estimated: everything inside a quarter. Statements give no dates for contributions, so the quarter's contributions and
  extra-credit bonuses are dated at the quarter-end together with that quarter's unit changes. Unit changes are booked as
  buys or sells at the quarter-end unit value; whatever is left over after the stated contributions (charges taken in
  units, rebalancing at other prices) is booked as a fee or a small credit so cash stays at zero.
- The history opens at the end of the first statement's quarter: the units and value then are put in as one contribution.
- A missing quarter's statement is flagged; flows of that quarter show up in the next quarter's fee/credit line.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from ufo.importers import register
from ufo.performance.events import Event, Kind, ParsedHistory
from ufo.performance.ledger import Snapshot
from ufo.providers.prices import Point

PERIOD = re.compile(r"Statement Period:\s*([A-Z][a-z]+ \d+, \d{4})\s*-\s*([A-Z][a-z]+ \d+, \d{4})")
TOTAL = re.compile(r"Current Total Account Value\s+\$([\d,]+\.\d\d)")
FUND = re.compile(r"^\s*(\d{5})\s+(.+?)\s{2,}([\d,]+\.\d+)\s+\$([\d,]+\.\d+)\s+\$([\d,]+\.\d\d)", re.M)
FIRST_AMOUNT = re.compile(r"\$([\d,]+\.\d\d)")


def _day(s: str) -> date:
    return datetime.strptime(s, "%B %d, %Y").date()


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _text(path: str) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise ValueError("the pdftotext tool is needed to read Equitable statements (brew install poppler)")
    try:
        return subprocess.run([exe, "-layout", path, "-"], capture_output=True, text=True, timeout=60, check=True).stdout
    except (subprocess.SubprocessError, OSError) as e:
        raise ValueError(f"{Path(path).name}: could not read the PDF ({type(e).__name__})") from e


class Statement:
    def __init__(self, name: str, text: str):
        self.name = name
        m = PERIOD.search(text)
        self.start, self.end = (_day(m.group(1)), _day(m.group(2))) if m else (None, None)
        t = TOTAL.search(text)
        self.total = _num(t.group(1)) if t else None
        self.funds = {c: (_num(u), _num(p), _num(v)) for c, _n, u, p, v in FUND.findall(text)}  # code -> units, unit value, value
        self.flows = self._flows(text)

    @staticmethod
    def _flows(text: str) -> float:
        """Contributions plus extra credit / earnings bonus for the quarter (first Account Activity Summary)."""
        block = text.split("Account Activity Summary", 1)[-1][:1800]
        total = 0.0
        for ln in block.splitlines():
            s = ln.strip()
            if s.startswith(("Contributions", "Extra Credit")):
                m = FIRST_AMOUNT.search(s)
                if m:
                    total += _num(m.group(1))
        return total

    @property
    def ok(self) -> bool:
        return bool(self.end and self.total is not None and self.funds
                    and abs(sum(v for _, _, v in self.funds.values()) - self.total) < 0.05)


def _read(files: list[str]) -> tuple[list[Statement], list[str]]:
    warns, seen = [], {}
    for f in sorted(files):
        try:
            st = Statement(Path(f).name, _text(f))
        except ValueError as e:
            warns.append(str(e))
            continue
        if not st.ok:
            warns.append(f"{st.name}: not understood (no period, total or fund lines that add up); skipped.")
        elif st.end in seen:
            warns.append(f"{st.name}: same quarter as {seen[st.end].name}; skipped to avoid counting twice.")
        else:
            seen[st.end] = st
    return [seen[k] for k in sorted(seen)], warns


class EquitableImporter:
    name = "equitable"
    estimate_note = "quarterly statements: flows dated at quarter-end"

    def parse(self, files: list[str], account_digits: str = "") -> ParsedHistory:
        sts, warns = _read(files)
        ev: list[Event] = []

        def add(kind, when, **kw):
            ev.append(Event(when=when, kind=kind, seq=len(ev), source=self.name, **kw))

        prev: Statement | None = None
        for st in sts:
            if prev is None:
                add(Kind.CONTRIBUTION, st.end, amount=st.total, description="Opening value (first statement)")
                for code, (units, px, val) in st.funds.items():
                    add(Kind.BUY, st.end, symbol=f"EQ{code}", quantity=units, price=px, amount=-val, description="Opening units")
            else:
                if (st.start - prev.end).days > 7:
                    warns.append(f"{st.name}: the statement before it (period ending {prev.end + timedelta(days=0)}) is not the previous quarter; "
                                 "flows in the missing quarter are folded into this quarter's fee/credit line.")
                bought = 0.0
                for code in sorted(set(st.funds) | set(prev.funds)):
                    before = prev.funds.get(code, (0.0, 0.0, 0.0))[0]
                    units, px, _ = st.funds.get(code, (0.0, prev.funds[code][1] if code in prev.funds else 0.0, 0.0))
                    if abs(units - before) < 1e-9:
                        continue
                    amt = round((units - before) * px, 2)
                    bought += amt
                    add(Kind.BUY if units > before else Kind.SELL, st.end, symbol=f"EQ{code}", quantity=units - before,
                        price=px, amount=-amt, description="Unit change")
                if st.flows:
                    add(Kind.CONTRIBUTION, st.end, amount=st.flows, description="Contributions and bonus credits")
                rest = round(bought - st.flows, 2)  # cash the trades needed beyond the contributions; negative = left over (a charge taken in units)
                if rest > 0:
                    add(Kind.INTEREST, st.end, amount=rest, description="Residual credit (estimated)")
                elif rest < 0:
                    add(Kind.FEE, st.end, amount=rest, fees=-rest, description="Residual charges (estimated)")
            prev = st
        ev.sort(key=lambda e: (e.when, e.seq))
        return ParsedHistory(events=ev, warnings=warns, first=ev[0].when if ev else None, last=ev[-1].when if ev else None)

    def positions(self, files: list[str], account_digits: str = "") -> list[Snapshot]:
        return []

    def prices(self, files: list[str]) -> dict[str, list[Point]]:
        """Unit values from the statements: `EQ<fund #>` -> quarter-end points."""
        sts, _ = _read(files)
        out: dict[str, list[Point]] = {}
        for st in sts:
            for code, (_, px, _) in st.funds.items():
                out.setdefault(f"EQ{code}", []).append(Point(day=st.end, value=px, close=px))
        return out

    def statement_values(self, files: list[str]) -> list[tuple[date, float, str]]:
        sts, _ = _read(files)
        return [(s.end, s.total, "Equitable quarterly statement") for s in sts]


register(EquitableImporter())

"""The Voya importer: annual TransactionHistory CSVs (mutual funds in an IRA) -> neutral events.

File layout: a title line, a `Date Range :<tab>MM/DD/YYYY - MM/DD/YYYY` line, some blank quoted lines, then the header
`Activity Date,Activity,Fund,Money Source,# of Units,Unit Price,Amount` and rows (newest first). Activities seen:
CONTRIBUTION (money in, bought into a fund), DIVIDEND (reinvested at once), TRANSFER (a move between funds, cash-neutral),
OTHER (negative units = a fee taken in units; positive = a small credit). Every cash-in or cash-out row is paired with
the unit change it causes, so the cash balance stays at zero and only contributions and withdrawals are external.

Prices: the file has no tickers. Each fund is keyed by its Voya fund code ("VOYA<code>") and priced from the unit prices
in the file itself (sparse: quarterly plus dividend dates, so month-end values are estimates). To use real daily prices
put `fund_tickers.json` ({"<code>": "<TICKER>"}) next to the files; mapped funds are then priced from the price service.

Quarterly PDF statements give the account value (`statement_values`, via the `pdftotext` tool when installed).
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path

from ufo.importers import register
from ufo.performance.events import Event, Kind, ParsedHistory, merge_histories
from ufo.performance.ledger import Snapshot
from ufo.providers.prices import Point

RANGE = re.compile(r"Date Range\s*:\s*(\d\d/\d\d/\d{4})\s*-\s*(\d\d/\d\d/\d{4})")
BALANCE = re.compile(r"Account Balance on (\d\d/\d\d/\d{4})\s+\$([\d,]+\.\d\d)")
WITHDRAWALS = {"WITHDRAWAL", "DISTRIBUTION"}


def _us(s: str) -> date:
    return datetime.strptime(s, "%m/%d/%Y").date()


def _num(s: str) -> float:
    return float(s.replace(",", "").replace("$", "").strip())


class _File:
    def __init__(self, name: str, text: str):
        self.name, self.rows, self.start, self.end = name, [], None, None
        lines = text.splitlines()
        for ln in lines:
            m = RANGE.search(ln)
            if m:
                self.start, self.end = _us(m.group(1)), _us(m.group(2))
                break
        head = next((i for i, ln in enumerate(lines) if ln.startswith("Activity Date,")), None)
        self.header_found = head is not None
        if head is not None:
            self.rows = list(csv.DictReader(lines[head:]))


def _read(files: list[str]) -> list[_File]:
    return [_File(Path(f).name, Path(f).read_text(encoding="utf-8-sig")) for f in sorted(files)]


def _tickers(files: list[str]) -> dict[str, str]:
    if not files:
        return {}
    p = Path(files[0]).parent / "fund_tickers.json"
    try:
        return {str(k): str(v).strip().upper() for k, v in json.loads(p.read_text()).items()} if p.exists() else {}
    except (ValueError, OSError):
        return {}


def _dedupe(parts: list[_File], warnings: list[str]) -> list[_File]:
    """Never count a day twice: a file whose range is already covered is dropped; a partial overlap loses its rows
    on days an earlier file covers. Rows inside a file are never de-duplicated (two identical rows can be real)."""
    kept, covered = [], None
    for f in sorted(parts, key=lambda f: (f.start or date.max, -(f.end or date.min).toordinal())):
        if f.start is None or f.end is None:
            kept.append(f)
            continue
        if covered is not None and f.end <= covered:
            warnings.append(f"{f.name}: its date range is already covered by another file; skipped to avoid counting rows twice.")
            continue
        if covered is not None and f.start <= covered:
            f.rows = [r for r in f.rows if _row_date(r) is None or _row_date(r) > covered]
            warnings.append(f"{f.name}: overlaps an earlier file up to {covered}; the overlapping days were left out to avoid counting twice.")
        covered = f.end if covered is None else max(covered, f.end)
        kept.append(f)
    return kept


def _row_date(r: dict) -> date | None:
    try:
        return date.fromisoformat((r.get("Activity Date") or "").strip())
    except ValueError:
        return None


class VoyaImporter:
    name = "voya"

    def parse(self, files: list[str], account_digits: str = "") -> ParsedHistory:
        tick = _tickers(files)
        warnings: list[str] = []
        parts = _read(files)
        for f in parts:
            if not f.header_found:
                warnings.append(f"{f.name}: no 'Activity Date,Activity,...' header found; skipped.")
        parts = _dedupe([f for f in parts if f.header_found], warnings)
        histories = []
        for f in parts:
            events: list[Event] = []
            for n, r in enumerate(reversed(f.rows), start=1):  # newest-first in the file; seq is oldest-first
                evs = self._row(r, tick, len(events))
                if evs is None:
                    warnings.append(f"{f.name}: row dated {(r.get('Activity Date') or '?').strip()} ({(r.get('Activity') or '?').strip()}) not understood; skipped.")
                    continue
                events += evs
            events.sort(key=lambda e: (e.when, e.seq))
            histories.append(ParsedHistory(events=events, warnings=[], first=f.start or (events[0].when if events else None),
                                           last=f.end or (events[-1].when if events else None)))
        hist = merge_histories(histories)
        hist.warnings = warnings + hist.warnings
        return hist

    def _row(self, r: dict, tick: dict[str, str], seq0: int) -> list[Event] | None:
        when = _row_date(r)
        fund = (r.get("Fund") or "").strip()
        act = (r.get("Activity") or "").strip().upper()
        try:
            units, price, amt = _num(r["# of Units"]), _num(r["Unit Price"]), _num(r["Amount"])
        except (KeyError, ValueError):
            return None
        if when is None or not fund:
            return None
        code = fund.split()[0]
        sym = tick.get(code) or f"VOYA{code}"
        common = dict(when=when, symbol=sym, source=self.name, description=f"{act.title()} ({fund})")

        def ev(kind, i, **kw):
            return Event(kind=kind, seq=seq0 + i, **{**common, **kw})

        if act == "CONTRIBUTION":
            return [ev(Kind.CONTRIBUTION, 0, amount=abs(amt)), ev(Kind.BUY, 1, quantity=units, price=price, amount=-abs(amt))]
        if act == "DIVIDEND":
            return [ev(Kind.DIVIDEND, 0, amount=abs(amt)), ev(Kind.BUY, 1, quantity=units, price=price, amount=-abs(amt), description=f"Dividend reinvested ({fund})")]
        if act == "TRANSFER":  # between funds: cash-neutral
            return [ev(Kind.BUY if units > 0 else Kind.SELL, 0, quantity=units, price=price, description=f"Fund transfer ({fund})")]
        if act == "OTHER" and units < 0:  # a fee taken in units
            return [ev(Kind.FEE, 0, amount=-abs(amt), fees=abs(amt)), ev(Kind.SELL, 1, quantity=units, price=price, amount=abs(amt), description=f"Fee paid in units ({fund})")]
        if act == "OTHER" and units > 0:  # a small credit, kept inside the account
            return [ev(Kind.INTEREST, 0, amount=abs(amt)), ev(Kind.BUY, 1, quantity=units, price=price, amount=-abs(amt), description=f"Credit reinvested ({fund})")]
        if act in WITHDRAWALS and units < 0:
            return [ev(Kind.SELL, 0, quantity=units, price=price, amount=abs(amt)), ev(Kind.WITHDRAWAL, 1, amount=-abs(amt))]
        return None

    def positions(self, files: list[str], account_digits: str = "") -> list[Snapshot]:
        return []

    def prices(self, files: list[str]) -> dict[str, list[Point]]:
        """Unit prices from the file for funds that have no ticker mapping: symbol -> dated points."""
        tick = _tickers(files)
        out: dict[str, dict[date, Point]] = {}
        for f in _dedupe(_read(files), []):
            for r in f.rows:
                d, fund = _row_date(r), (r.get("Fund") or "").strip()
                try:
                    px = _num(r["Unit Price"])
                except (KeyError, ValueError):
                    continue
                if d is None or not fund or px <= 0 or tick.get(fund.split()[0]):
                    continue
                out.setdefault(f"VOYA{fund.split()[0]}", {})[d] = Point(day=d, value=px, close=px)
        return {s: sorted(p.values(), key=lambda x: x.day) for s, p in out.items()}

    def statement_values(self, files: list[str]) -> list[tuple[date, float, str]]:
        """(date, account value, label) from quarterly PDF statements: the closing balance of each. Needs `pdftotext`."""
        exe = shutil.which("pdftotext")
        out = []
        for f in sorted(files):
            if not exe:
                break
            try:
                text = subprocess.run([exe, "-layout", f, "-"], capture_output=True, text=True, timeout=60, check=True).stdout
            except (subprocess.SubprocessError, OSError):
                continue
            bal = parse_balances(text)
            if bal:
                d, v = max(bal)
                out.append((d, v, "Voya quarterly statement"))
        return out


def parse_balances(text: str) -> list[tuple[date, float]]:
    """Every 'Account Balance on <date> $<amount>' pair in a statement's text."""
    return sorted({(_us(d), _num(v)) for d, v in BALANCE.findall(text)})


register(VoyaImporter())

"""The Acorns importer: monthly PDF statements -> neutral events (read with the `pdftotext` tool).

Each statement has: `Statement Period M/D/YYYY - M/D/YYYY`; `Ending Balance (date)` and `Grand Total (date)` (the account
value, including cash pending settlement); a "Deposits and Withdrawals Summary" (dated rows, then a `Net ...` total);
a "Purchases and Sales Summary" in which `<TICKER> Dividend Reinvestment` rows are income that was reinvested; and a
"Transactions" table of every trade (`Bought` or `Sold`, with quantity, price and amount; the ticker is in brackets at the
end of the fund name, which may wrap to the next line). The monthly subscription is billed outside the account, so it is
not an event. Unpaid dividend cash ("Pending Cash") shows up as a dividend in the statement that reinvests it; on the
newest statement it is added as a dividend that stays in cash, so the rebuilt value can match the Grand Total.

Money in (ACH deposits, Acorns Earn credits) is a contribution; a withdrawal is a withdrawal. Each trade is paired with the
cash it uses, so only deposits and withdrawals cross the account boundary. Statements for the same period are read once.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path

from ufo.importers import register
from ufo.performance.events import Event, Kind, ParsedHistory, merge_histories
from ufo.performance.ledger import Snapshot

PERIOD = re.compile(r"Statement Period\s+(\d+/\d+/\d{4})\s*-\s*(\d+/\d+/\d{4})")
GRAND = re.compile(r"Grand Total \((\d+/\d+/\d{4})\)\s+\$([\d,]+\.\d\d)")
ROW = re.compile(r"^\s*(\d+/\d+/\d{4})\s+(.*?)\s+(-?\(?\$[\d,]+\.\d\d\)?)\s*$")
TRADE = re.compile(r"^\s*(\d+/\d+/\d{4})\s+\d+/\d+/\d{4}\s+(Bought|Sold)\s+(.*?)\s+([\d,]*\.\d+)\s+\$([\d,]+\.\d+)\s+\$([\d,]+\.\d\d)(?:\s+\w+)?\s*$")
TICKER = re.compile(r"\(([A-Z][A-Z0-9.]{0,5})\)")


def _us(s: str) -> date:
    return datetime.strptime(s, "%m/%d/%Y").date()


def _num(s: str) -> float:
    neg = "(" in s or s.startswith("-")
    v = float(re.sub(r"[^\d.]", "", s))
    return -v if neg else v


def _text(path: str) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise ValueError("the pdftotext tool is needed to read Acorns statements (brew install poppler)")
    try:
        return subprocess.run([exe, "-layout", path, "-"], capture_output=True, text=True, timeout=60, check=True).stdout
    except (subprocess.SubprocessError, OSError) as e:
        raise ValueError(f"{Path(path).name}: could not read the PDF ({type(e).__name__})") from e


def _section(text: str, title: str, stop: tuple[str, ...]) -> list[str]:
    lines, out, on = text.splitlines(), [], False
    for ln in lines:
        s = ln.strip()
        if s == title:
            on = True
        elif on and s in stop:
            break
        elif on:
            out.append(ln)
    return out


def parse_statement(text: str, name: str = "") -> tuple[tuple[date, date] | None, list[Event], float | None, list[str]]:
    """(period, events, grand total, warnings) for one statement's text."""
    warns: list[str] = []
    m = PERIOD.search(text)
    period = (_us(m.group(1)), _us(m.group(2))) if m else None
    g = GRAND.search(text)
    grand = _num(g.group(2)) if g else None
    ev: list[Event] = []

    def add(kind, when, **kw):
        ev.append(Event(when=when, kind=kind, seq=len(ev), source="acorns", **kw))

    for ln in _section(text, "Deposits and Withdrawals Summary", ("Purchases and Sales Summary",)):
        r = ROW.match(ln)
        if not r or r.group(2).startswith("Net "):
            continue
        amt, desc = _num(r.group(3)), r.group(2).strip()
        if "withdraw" in desc.lower() or amt < 0:
            add(Kind.WITHDRAWAL, _us(r.group(1)), amount=-abs(amt), description=desc)
        else:
            add(Kind.CONTRIBUTION, _us(r.group(1)), amount=abs(amt), description=desc)
    for ln in _section(text, "Purchases and Sales Summary", ("Transfers",)):
        r = ROW.match(ln)
        if r and "Dividend Reinvestment" in r.group(2):
            add(Kind.DIVIDEND, _us(r.group(1)), amount=abs(_num(r.group(3))), description=r.group(2).strip())
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        t = TRADE.match(ln)
        if not t:
            continue
        desc = t.group(3)
        tk = TICKER.search(desc) or (TICKER.search(lines[i + 1]) if i + 1 < len(lines) and not lines[i + 1].strip().startswith(("Page", "Acorns")) else None)
        if not tk:
            warns.append(f"{name}: a trade on {t.group(1)} has no ticker; skipped.")
            continue
        qty, price, amt = _num(t.group(4)), _num(t.group(5)), abs(_num(t.group(6)))
        if t.group(2) == "Bought":
            add(Kind.BUY, _us(t.group(1)), symbol=tk.group(1), quantity=qty, price=price, amount=-amt)
        else:
            add(Kind.SELL, _us(t.group(1)), symbol=tk.group(1), quantity=-qty, price=price, amount=amt)
    # Dividend cash is invested by the BUY rows (cash-neutral with the DIVIDEND rows above).
    # Pending cash only matters on the newest statement; the caller adds it there.
    return period, ev, grand, warns


def pending_cash(text: str, name: str = "") -> list[Event]:
    out: list[Event] = []
    for ln in _section(text, "Pending Cash", ("Corporate Actions",)):
        r = ROW.match(ln)
        if r and not r.group(2).startswith("Net "):
            out.append(Event(when=_us(r.group(1)), kind=Kind.DIVIDEND, amount=abs(_num(r.group(3))), seq=0,
                             source="acorns", description=r.group(2).strip()))
    return out


class AcornsImporter:
    name = "acorns"

    def _read(self, files: list[str]):
        seen: dict[tuple[date, date], tuple[str, str]] = {}
        warnings: list[str] = []
        for f in sorted(files):
            try:
                t = _text(f)
            except ValueError as e:
                warnings.append(str(e))
                continue
            m = PERIOD.search(t)
            if not m:
                warnings.append(f"{Path(f).name}: no 'Statement Period' found; skipped.")
                continue
            key = (_us(m.group(1)), _us(m.group(2)))
            if key in seen:
                warnings.append(f"{Path(f).name}: same period as {seen[key][0]}; skipped to avoid counting twice.")
                continue
            seen[key] = (Path(f).name, t)
        return seen, warnings

    def parse(self, files: list[str], account_digits: str = "") -> ParsedHistory:
        seen, warnings = self._read(files)
        histories = []
        for (a, b), (name, t) in sorted(seen.items()):
            _, ev, _, w = parse_statement(t, name)
            warnings += w
            ev.sort(key=lambda e: (e.when, e.seq))
            histories.append(ParsedHistory(events=ev, warnings=[], first=a, last=b))
        if seen:
            last_key = max(seen)
            extra = pending_cash(seen[last_key][1])
            if extra and histories:
                h = histories[-1]
                h.events = h.events + [x.model_copy(update={"seq": len(h.events) + i}) for i, x in enumerate(extra)]
        hist = merge_histories(histories) if histories else ParsedHistory(events=[], warnings=[], first=None, last=None)
        hist.warnings = warnings + hist.warnings
        return hist

    def positions(self, files: list[str], account_digits: str = "") -> list[Snapshot]:
        return []

    def statement_values(self, files: list[str]) -> list[tuple[date, float, str]]:
        """(period end, Grand Total, label) for each monthly statement; these are the month-end checkpoints."""
        seen, _ = self._read(files)
        out = []
        for (a, b), (name, t) in sorted(seen.items()):
            g = GRAND.search(t)
            if g:
                out.append((_us(g.group(1)), _num(g.group(2)), "Acorns monthly statement"))
        return out


register(AcornsImporter())

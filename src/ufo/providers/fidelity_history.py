"""Parse a Fidelity "Activity & Orders > History" CSV export into dated, normalized events.

Read-only and local: it turns a file the owner downloaded into events; it never talks to Fidelity.
The events feed the cash-flow ledger (issue 33) and the performance metrics (issue 34).

Rules (see issue 31):
- Contributions and withdrawals are the only *external* cash flows (money crossing the account boundary).
- Reinvested dividends are internal (cash moves from dividend to purchase inside the account).
- An in-kind transfer counts as a contribution/withdrawal at market value on its date.
- An action type we do not recognize is reported as a warning, never dropped silently.
- Several exports can overlap; `merge_histories` warns about overlaps instead of guessing which rows duplicate.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

from ufo.performance.events import EXTERNAL, Event, Kind, ParsedHistory, merge_histories  # noqa: F401  (re-exported: the model is brokerage-neutral now)
from ufo.providers.fidelity_csv import parse_number


HINT_PREFIXES = ("TRANSFERRED FROM", "TRANSFERRED TO", "TRANSFER OF ASSETS")


def _classify(action: str, has_symbol: bool) -> tuple[Kind | None, bool]:
    """Map Fidelity's free-text Action to (kind, in_kind). (None, False) means unrecognized."""
    a = " ".join(action.upper().split())
    if a.startswith("YOU BOUGHT"):
        return Kind.BUY, False
    if a.startswith("YOU SOLD"):
        return Kind.SELL, False
    if a.startswith("ELECTRONIC FUNDS TRANSFER RECEIVED") or a.startswith("DIRECT DEPOSIT"):
        return Kind.CONTRIBUTION, False
    if a.startswith("ELECTRONIC FUNDS TRANSFER PAID") or a.startswith("DIRECT DEBIT") or a.startswith("CHECK PAID"):
        return Kind.WITHDRAWAL, False
    if a.startswith("TRANSFERRED FROM"):
        return Kind.CONTRIBUTION, has_symbol
    if a.startswith("TRANSFERRED TO"):
        return Kind.WITHDRAWAL, has_symbol
    if a.startswith("CASH CONTRIBUTION"):  # IRA contributions, current or prior year
        return Kind.CONTRIBUTION, False
    if a.startswith("EARLY DIST") or a.startswith("NORMAL DIST"):  # IRA distributions to the owner
        return Kind.WITHDRAWAL, False
    if a.startswith("TRANSFER OF ASSETS ACAT RECEIVE"):  # an incoming account transfer; without a symbol it is a cash adjustment
        return (Kind.CONTRIBUTION, True) if has_symbol else (Kind.FEE, False)
    if a.startswith("REDEMPTION PAYOUT"):  # a CD or T-bill paid off at maturity
        return Kind.SELL, False
    if a.startswith("MERGER MER PAYOUT"):
        return Kind.SELL, False
    if a.startswith("MERGER MER FROM"):
        return Kind.BUY, False
    if a.startswith("DIVIDEND RECEIVED") or a.startswith("DISTRIBUTION") or "CAP GAIN" in a[:20]:
        return Kind.DIVIDEND, False
    if a.startswith("REINVESTMENT"):
        return Kind.REINVESTMENT, False
    if a.startswith("INTEREST EARNED") or a.startswith("INTEREST"):
        return Kind.INTEREST, False
    if a.startswith("FEE CHARGED") or "ADVISORY FEE" in a:
        return Kind.FEE, False
    if "SPLIT" in a:
        return Kind.SPLIT, False
    return None, False


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_fidelity_history(text: str) -> ParsedHistory:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    header_at = next((i for i, r in enumerate(rows) if r and r[0].strip().lower() == "run date"), None)
    if header_at is None:
        return ParsedHistory(events=[], warnings=["No 'Run Date' header found: is this a Fidelity activity-history CSV?"])
    header = [h.strip() for h in rows[header_at]]
    events: list[Event] = []
    warnings: list[str] = []
    dated_rows = [r for r in rows[header_at + 1:] if r and _parse_date(r[0]) is not None]
    newest_first = len(dated_rows) > 1 and _parse_date(dated_rows[0][0]) > _parse_date(dated_rows[-1][0])
    for n, row in enumerate(rows[header_at + 1:], start=header_at + 2):
        if not row or not any(c.strip() for c in row):
            continue
        d = dict(zip(header, row))
        when = _parse_date(d.get("Run Date", ""))
        if when is None:
            if d.get("Run Date", "").strip() and len(row) >= len(header) - 2:
                warnings.append(f"Line {n}: could not read the date {d['Run Date']!r}; row skipped.")
            continue  # footer / disclaimer text
        action = d.get("Action", "").strip()
        symbol = d.get("Symbol", "").strip()
        kind, in_kind = _classify(action, bool(symbol))
        if kind is None:
            warnings.append(f"Line {n}: unrecognized action {action[:40]!r}; row skipped. Please report it so it can be handled.")
            continue
        hint = action.upper().startswith(HINT_PREFIXES) and kind in (Kind.CONTRIBUTION, Kind.WITHDRAWAL)  # a move between accounts
        fees = (parse_number(d.get("Commission")) or 0.0) + (parse_number(d.get("Fees")) or 0.0)
        events.append(Event(
            when=when, kind=kind, symbol=symbol,
            quantity=parse_number(d.get("Quantity")), price=parse_number(d.get("Price")),
            amount=parse_number(d.get("Amount")) or 0.0, fees=fees, in_kind=in_kind, transfer_hint=hint,
            description=d.get("Description", "").strip(),
            cash_balance=parse_number(d.get("Cash Balance")),
            account_ref=(d.get("Account Number") or d.get("Account") or "").strip(),
            seq=-n if newest_first else n))
    events.sort(key=lambda e: (e.when, e.seq))
    for e in events:
        if e.in_kind and e.amount == 0.0 and e.quantity and e.price:
            e.amount = abs(e.quantity * e.price) * (1 if e.kind == Kind.CONTRIBUTION else -1)  # value at market on the date
        elif e.in_kind and e.amount == 0.0:
            warnings.append(f"{e.when}: in-kind transfer of {e.symbol} has no value; add it by hand.")
    return ParsedHistory(events=events, warnings=warnings,
                         first=events[0].when if events else None, last=events[-1].when if events else None)

"""The brokerage-neutral event model every importer emits (issue 99; see docs/event-model.md).

Ledger, metrics and reports only ever see these types, never a brokerage's file format.
"""
from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel


class Kind(str, Enum):
    BUY = "buy"
    SELL = "sell"
    CONTRIBUTION = "contribution"  # external, money in
    WITHDRAWAL = "withdrawal"  # external, money out
    DIVIDEND = "dividend"
    INTEREST = "interest"
    FEE = "fee"
    REINVESTMENT = "reinvestment"  # internal
    SPLIT = "split"


EXTERNAL = {Kind.CONTRIBUTION, Kind.WITHDRAWAL}


class Event(BaseModel):
    when: date
    kind: Kind
    symbol: str = ""
    quantity: float | None = None
    price: float | None = None
    amount: float = 0.0  # cash effect on the account, as in the file (money in positive)
    fees: float = 0.0
    in_kind: bool = False  # securities moved rather than cash
    description: str = ""
    cash_balance: float | None = None  # Fidelity's running cash (core money-market) balance after this row
    seq: int = 0  # position within a day, oldest first (the export is newest-first, so it is reversed)
    account_id: str = ""  # registry id of the account the row belongs to ("" when an importer is run on its own)
    account_ref: str = ""  # the account text exactly as the file gives it (digits/name), when a file holds several accounts
    source: str = ""  # importer name that produced the row, e.g. "fidelity"
    transfer_hint: bool = False  # the importer knows this contribution/withdrawal is a move between household accounts

    @property
    def cash_effect(self) -> float:
        """What the row did to the account's cash: `amount`, except that moving shares in kind moves no cash
        (the amount is only the shares' market value, kept for the external flow)."""
        return 0.0 if self.in_kind else self.amount

    @property
    def external_flow(self) -> float:
        """Signed value crossing the account boundary (+ in, - out); 0 for anything internal."""
        if self.kind == Kind.CONTRIBUTION:
            return abs(self.amount)
        if self.kind == Kind.WITHDRAWAL:
            return -abs(self.amount)
        return 0.0


class ParsedHistory(BaseModel):
    events: list[Event]
    warnings: list[str]
    first: date | None = None
    last: date | None = None


def merge_histories(parts: list[ParsedHistory]) -> ParsedHistory:
    """Combine several exports. Rows are never de-duplicated (two identical trades can be real);
    overlapping date ranges are reported so the owner can check for a repeated export."""
    dated = sorted((p for p in parts if p.first and p.last), key=lambda p: p.first)
    warnings = [w for p in parts for w in p.warnings]
    for a, b in zip(dated, dated[1:]):
        if b.first <= a.last:
            warnings.append(f"Exports overlap ({b.first} to {min(a.last, b.last)}): rows may be counted twice.")
    events = sorted((e for p in parts for e in p.events), key=lambda e: (e.when, e.seq))
    return ParsedHistory(events=events, warnings=warnings,
                         first=events[0].when if events else None, last=events[-1].when if events else None)


def split_by_account(hist: ParsedHistory, digits: str) -> ParsedHistory:
    """Keep the rows whose account text ends with `digits` (rows with no account text are kept: a single-account file)."""
    keep = [e for e in hist.events if not e.account_ref or e.account_ref.endswith(digits)]
    return ParsedHistory(events=keep, warnings=hist.warnings, first=keep[0].when if keep else None,
                         last=keep[-1].when if keep else None)

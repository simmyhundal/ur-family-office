"""Hand-entered bills and alert settings (v1). Loaded from a local JSON file, never committed.

Example .data/alert.json:
{
  "cushion": 1000,
  "next_topup": "2026-11-15",          # next paycheck or planned transfer in
  "account_mask": "1234",               # optional: which checking account (last digits)
  "bills": [
    {"name": "Rent", "amount": 1800, "due": "2026-11-01", "repeat": "monthly"},
    {"name": "Car insurance", "amount": 142.5, "due": "2026-11-09"}
  ]
}
"""
from __future__ import annotations

import calendar
import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class BillSpec(BaseModel):
    name: str
    amount: float
    due: date
    repeat: Literal["none", "monthly"] = "none"


class AlertConfig(BaseModel):
    cushion: float = 1000.0
    next_topup: date
    account_mask: str | None = None
    bills: list[BillSpec] = []


def load_config(path: str | Path) -> AlertConfig:
    return AlertConfig.model_validate(json.loads(Path(path).read_text()))


def _add_month(d: date, anchor_day: int) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, min(anchor_day, calendar.monthrange(y, m)[1]))


def occurrences(bill: BillSpec, start: date, end: date) -> list[date]:
    """Dates this bill falls due within [start, end] (inclusive). Monthly bills keep their original day."""
    if bill.repeat == "none":
        return [bill.due] if start <= bill.due <= end else []
    out: list[date] = []
    d = bill.due
    while d <= end:
        if d >= start:
            out.append(d)
        d = _add_month(d, bill.due.day)
    return out


def bills_due(bills: list[BillSpec], start: date, end: date) -> list[tuple[str, float, date]]:
    """(name, amount, due) for every occurrence in the window, earliest first; rent-like bills with the same date keep input order."""
    rows = [(b.name, b.amount, d) for b in bills for d in occurrences(b, start, end)]
    return sorted(rows, key=lambda r: r[2])

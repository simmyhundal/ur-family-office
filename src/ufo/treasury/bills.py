"""Hand-entered bills and alert settings (v1). Loaded from a local JSON file, never committed.

Example .data/alert.json:
{
  "cushion": 1000,                      # what Joint should still hold at the next top-up
  "next_topup": "2026-11-15",           # next paycheck or planned transfer in
  "joint_mask": "1234",                 # last digits of the Joint account (monitored)
  "personal_mask": "5678",              # last digits of the Personal account (funds the transfer)
  "personal_floor": 1500,               # Personal never drops below this
  "bills": [
    {"name": "Rent", "amount": 1800, "due": "2026-11-01", "repeat": "monthly"},
    {"name": "Car insurance", "amount": 142.5, "due": "2026-11-09"}
  ]
}
"""
from __future__ import annotations

import calendar
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


Repeat = Literal["none", "weekly", "biweekly", "semi_monthly", "monthly", "annually"]


class BillSpec(BaseModel):
    name: str
    amount: float
    due: date
    repeat: Repeat = "none"
    source: Literal["manual", "plaid"] = "manual"


class AlertConfig(BaseModel):
    cushion: float = 1000.0
    next_topup: date
    joint_mask: str
    personal_mask: str
    personal_floor: float = 1500.0
    bills: list[BillSpec] = []
    # Bill detection from Plaid recurring transactions (on the Joint account). Manual bills always win on overlap.
    detect_bills: bool = False
    include_early_detection: bool = False  # also count streams Plaid is not yet sure about
    ignore_streams: list[str] = []  # names (case-insensitive substrings) of detected streams to skip


def load_config(path: str | Path) -> AlertConfig:
    return AlertConfig.model_validate(json.loads(Path(path).read_text()))


def _add_month(d: date, anchor_day: int) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, min(anchor_day, calendar.monthrange(y, m)[1]))


def _add_year(d: date, anchor: date) -> date:
    y = d.year + 1
    return date(y, anchor.month, min(anchor.day, calendar.monthrange(y, anchor.month)[1]))


def next_due(d: date, bill: BillSpec) -> date:
    """The occurrence after d. Monthly/annual keep the original day (clamped to month end); semi-monthly is approximated as 15 days."""
    return {
        "weekly": lambda: d + timedelta(days=7),
        "biweekly": lambda: d + timedelta(days=14),
        "semi_monthly": lambda: d + timedelta(days=15),
        "monthly": lambda: _add_month(d, bill.due.day),
        "annually": lambda: _add_year(d, bill.due),
    }[bill.repeat]()


def occurrences(bill: BillSpec, start: date, end: date) -> list[date]:
    """Dates this bill falls due within [start, end] (inclusive)."""
    if bill.repeat == "none":
        return [bill.due] if start <= bill.due <= end else []
    out: list[date] = []
    d = bill.due
    while d <= end:
        if d >= start:
            out.append(d)
        d = next_due(d, bill)
    return out


def bills_due(bills: list[BillSpec], start: date, end: date) -> list[tuple[str, float, date]]:
    """(name, amount, due) for every occurrence in the window, earliest first; same-day bills keep input order."""
    rows = [(b.name, b.amount, d) for b in bills for d in occurrences(b, start, end)]
    return sorted(rows, key=lambda r: r[2])

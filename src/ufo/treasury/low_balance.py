"""Low-balance check: balance minus bills due before the next top-up, compared to a cushion.

Pure logic (no I/O) so every rule is unit-tested. The balance should be the *available* balance.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from .bills import AlertConfig, bills_due


class CheckResult(BaseModel):
    status: str  # "ok" | "low" | "stale_config"
    balance: float
    bills_total: float
    projected: float  # balance - bills_total: what is left at the next top-up
    cushion: float
    shortfall: float  # how far below the cushion (0 when ok)
    window_end: date
    bills: list[tuple[str, float, date]]
    first_bill_due: date | None = None
    message: str


def money(n: float) -> str:
    return f"-${-n:,.2f}" if n < 0 else f"${n:,.2f}"


def check_balance(balance: float, cfg: AlertConfig, today: date) -> CheckResult:
    if cfg.next_topup < today:
        return CheckResult(
            status="stale_config", balance=balance, bills_total=0, projected=balance, cushion=cfg.cushion, shortfall=0,
            window_end=cfg.next_topup, bills=[],
            message=f"UFO: your next_topup date ({cfg.next_topup:%b %d}) has passed; update the alert config so bills are counted.",
        )
    due = bills_due(cfg.bills, today, cfg.next_topup)
    total = round(sum(a for _, a, _ in due), 2)
    projected = round(balance - total, 2)
    shortfall = round(max(0.0, cfg.cushion - projected), 2)
    status = "low" if projected < cfg.cushion else "ok"
    first = due[0][2] if due else None
    if status == "low":
        listing = ", ".join(f"{n} {money(a)} ({d:%b %d})" for n, a, d in due) or "no bills"
        message = (
            f"UFO: checking is {money(balance)}. Due by {cfg.next_topup:%b %d}: {listing} = {money(total)}. "
            f"That leaves {money(projected)}, {money(shortfall)} under your {money(cfg.cushion)} cushion."
            + (f" Top up at least {money(shortfall)} before {first:%b %d}." if first else "")
        )
    else:
        message = f"UFO: checking {money(balance)}; after {money(total)} of bills by {cfg.next_topup:%b %d} you keep {money(projected)} (cushion {money(cfg.cushion)})."
    return CheckResult(status=status, balance=balance, bills_total=total, projected=projected, cushion=cfg.cushion,
                       shortfall=shortfall, window_end=cfg.next_topup, bills=due, first_bill_due=first, message=message)

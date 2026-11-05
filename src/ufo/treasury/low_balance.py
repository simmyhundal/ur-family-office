"""Low-balance check for the Joint account, with the exact transfer from Personal.

Joint balance minus bills due before the next top-up, compared to a cushion. When it falls short, the text says how much
to move from Personal (the shortfall rounded up to the next $10) while Personal keeps its minimum balance.
Pure logic (no I/O) so every rule is unit-tested. Balances should be *available* balances.
"""
from __future__ import annotations

import math
from datetime import date

from pydantic import BaseModel

from .bills import AlertConfig, bills_due


class CheckResult(BaseModel):
    status: str  # "ok" | "low" | "stale_config"
    joint_balance: float
    personal_balance: float
    bills_total: float
    projected: float  # joint balance after the bills: what is left at the next top-up
    cushion: float
    shortfall: float  # how far below the cushion (0 when ok)
    transfer_amount: float  # what to move from Personal to Joint (0 when ok)
    personal_sendable: float  # Personal balance above its floor
    personal_covers: bool  # can Personal cover the whole shortfall?
    uncovered: float  # shortfall Personal cannot cover
    window_end: date
    bills: list[tuple[str, float, date]]
    first_bill_due: date | None = None
    message: str  # full detail: only ever printed/stored locally
    public_message: str  # safe to send over a non-end-to-end-encrypted channel: no balances, amounts or account info


def money(n: float) -> str:
    return f"-${-n:,.2f}" if n < 0 else f"${n:,.2f}"


def round_up_to_10(n: float) -> float:
    return float(math.ceil(round(n, 2) / 10 - 1e-9) * 10)


def public_low(by: date, personal_covers: bool) -> str:
    """The only text that leaves this machine. Deliberately says nothing about balances, amounts or accounts."""
    msg = f"UFO: Joint may run short before {by:%b %d}. Please check your bank app."
    return msg if personal_covers else msg + " Personal may not be able to cover it."


def check_balance(joint: float, personal: float, cfg: AlertConfig, today: date) -> CheckResult:
    sendable = round(max(0.0, personal - cfg.personal_floor), 2)
    base = dict(joint_balance=joint, personal_balance=personal, cushion=cfg.cushion, window_end=cfg.next_topup,
                personal_sendable=sendable)
    if cfg.next_topup < today:
        return CheckResult(status="stale_config", bills_total=0, projected=joint, shortfall=0, transfer_amount=0,
                           personal_covers=True, uncovered=0, bills=[], **base,
                           message=f"UFO: your next_topup date ({cfg.next_topup:%b %d}) has passed; update the alert config so bills are counted.",
                           public_message="UFO: alert settings need an update (the next top-up date has passed). Bills are not being counted.")
    due = bills_due(cfg.bills, today, cfg.next_topup)
    total = round(sum(a for _, a, _ in due), 2)
    projected = round(joint - total, 2)
    shortfall = round(max(0.0, cfg.cushion - projected), 2)
    first = due[0][2] if due else None
    if shortfall == 0:
        msg = f"UFO: Joint {money(joint)}; after {money(total)} of bills by {cfg.next_topup:%b %d} it keeps {money(projected)} (cushion {money(cfg.cushion)})."
        return CheckResult(status="ok", bills_total=total, projected=projected, shortfall=0, transfer_amount=0,
                           personal_covers=True, uncovered=0, bills=due, first_bill_due=first, message=msg,
                           public_message=f"UFO: Joint is covered through {cfg.next_topup:%b %d}.", **base)

    wanted = round_up_to_10(shortfall)
    transfer = wanted if sendable >= wanted else (shortfall if sendable >= shortfall else sendable)
    covers = sendable >= shortfall
    uncovered = round(max(0.0, shortfall - sendable), 2)
    listing = ", ".join(f"{n} {money(a)} ({d:%b %d})" for n, a, d in due) or "no bills"
    by = f" before {first:%b %d}" if first else ""
    msg = (f"UFO: Joint is {money(joint)}. Due by {cfg.next_topup:%b %d}: {listing} = {money(total)}. "
           f"That leaves {money(projected)}, {money(shortfall)} under your {money(cfg.cushion)} cushion. ")
    if covers:
        msg += f"Move {money(transfer)} from Personal to Joint{by} (Personal keeps {money(personal - transfer)}, above its {money(cfg.personal_floor)} minimum)."
    elif transfer > 0:
        msg += (f"Personal can only send {money(transfer)} (it keeps a {money(cfg.personal_floor)} minimum), leaving {money(uncovered)} uncovered. "
                f"Move {money(transfer)} from Personal{by} and find {money(uncovered)} more.")
    else:
        msg += (f"Personal ({money(personal)}) has nothing above its {money(cfg.personal_floor)} minimum to send; "
                f"{money(uncovered)} is uncovered{by}.")
    return CheckResult(status="low", bills_total=total, projected=projected, shortfall=shortfall, transfer_amount=round(transfer, 2),
                       personal_covers=covers, uncovered=uncovered, bills=due, first_bill_due=first, message=msg,
                       public_message=public_low(first or cfg.next_topup, covers), **base)

"""Low-balance check for the Joint account, with the exact transfer from Personal.

Joint balance minus bills due before the next top-up, compared to a cushion. When it falls short, the text says how much
to move from Personal (the shortfall rounded up to the next $10) while Personal keeps its minimum balance.
Pure logic (no I/O) so every rule is unit-tested. Balances should be *available* balances.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from pydantic import BaseModel

from .bills import AlertConfig, bills_due


class CheckResult(BaseModel):
    status: str  # "ok" | "low" | "stale_config"
    joint_balance: float
    personal_balance: float
    bills_total: float
    projected: float  # Joint balance at the end of the window, after bills and deposits
    lowest_balance: float  # the lowest the running balance gets inside the window (this is what is compared to the cushion)
    lowest_on: date | None
    deposits: list[tuple[str, float, date]] = []
    cushion: float
    shortfall: float  # how far the lowest point is below the cushion (0 when ok)
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


ANTICIPATE_DAYS = 30  # card payments due within this many days are always counted, even past the look-ahead window


def effective_window_end(cfg: AlertConfig, today: date) -> date:
    """The look-ahead end date, extended so an upcoming credit-card payment is looked at early (with the deposits in between).
    A shortfall is then flagged while there is still time, not only in the last 14 days. Shared by the alert and the review script."""
    return max([cfg.window_end(today), *[b.due for b in cfg.bills if b.anticipate and today <= b.due <= today + timedelta(days=ANTICIPATE_DAYS)]])


def check_balance(joint: float, personal: float, cfg: AlertConfig, today: date) -> CheckResult:
    end = effective_window_end(cfg, today)
    due = bills_due(cfg.bills, today, end)
    deps = bills_due(cfg.scheduled_deposits, today, end)
    from_personal = round(sum(a for (n, a, d), spec in _deposit_specs(cfg, today, end) if spec.from_personal), 2)
    sendable = round(max(0.0, personal - cfg.personal_floor - from_personal), 2)
    base = dict(joint_balance=joint, personal_balance=personal, cushion=cfg.cushion, window_end=end, personal_sendable=sendable)
    if cfg.next_topup is not None and cfg.next_topup < today:
        return CheckResult(status="stale_config", bills_total=0, projected=joint, lowest_balance=joint, lowest_on=None, shortfall=0,
                           transfer_amount=0, personal_covers=True, uncovered=0, bills=[], **base,
                           message=f"UFO: your next_topup date ({cfg.next_topup:%b %d}) has passed; update or remove it so bills are counted.",
                           public_message="UFO: alert settings need an update (the end date of the look-ahead window has passed). Bills are not being counted.")

    # Walk the balance day by day. On the same day bills go first (conservative): an overdraft happens in the dip, not at the end.
    events = sorted([(d, 0, -a) for _, a, d in due] + [(d, 1, a) for _, a, d in deps], key=lambda e: (e[0], e[1]))
    bal, lowest, lowest_on = joint, joint, today
    for d, _, delta in events:
        bal = round(bal + delta, 2)
        if bal < lowest:
            lowest, lowest_on = bal, d
    total = round(sum(a for _, a, _ in due), 2)
    dep_total = round(sum(a for _, a, _ in deps), 2)
    shortfall = round(max(0.0, cfg.cushion - lowest), 2)
    first = due[0][2] if due else None
    common = dict(bills_total=total, projected=bal, lowest_balance=lowest, lowest_on=lowest_on, shortfall=shortfall, bills=due,
                  deposits=deps, first_bill_due=first, **base)
    if shortfall == 0:
        extra = f" and {money(dep_total)} of deposits" if deps else ""
        msg = f"UFO: Joint {money(joint)}; after {money(total)} of bills{extra} by {end:%b %d} it never drops below {money(lowest)} (cushion {money(cfg.cushion)})."
        return CheckResult(status="ok", transfer_amount=0, personal_covers=True, uncovered=0, message=msg,
                           public_message=f"UFO: Joint is covered through {end:%b %d}.", **common)

    wanted = round_up_to_10(shortfall)
    transfer = wanted if sendable >= wanted else (shortfall if sendable >= shortfall else sendable)
    covers = sendable >= shortfall
    uncovered = round(max(0.0, shortfall - sendable), 2)
    listing = ", ".join(f"{n} {money(a)} ({d:%b %d})" for n, a, d in due) or "no bills"
    by = f" before {(lowest_on if deps else first or end):%b %d}"
    if deps:
        dep_list = ", ".join(f"{n} {money(a)} ({d:%b %d})" for n, a, d in deps)
        msg = (f"UFO: Joint is {money(joint)}. Bills by {end:%b %d}: {listing} = {money(total)}. Scheduled deposits: {dep_list}. "
               f"At its lowest ({lowest_on:%b %d}) Joint holds {money(lowest)}, {money(shortfall)} under your {money(cfg.cushion)} cushion. ")
    else:
        msg = (f"UFO: Joint is {money(joint)}. Due by {end:%b %d}: {listing} = {money(total)}. "
               f"That leaves {money(bal)}, {money(shortfall)} under your {money(cfg.cushion)} cushion. ")
    if from_personal:
        msg += f"(Personal also funds {money(from_personal)} of scheduled deposits.) "
    if covers:
        msg += f"Move {money(transfer)} from Personal to Joint{by} (Personal keeps {money(personal - from_personal - transfer)}, above its {money(cfg.personal_floor)} minimum)."
    elif transfer > 0:
        msg += (f"Personal can only send {money(transfer)} (it keeps a {money(cfg.personal_floor)} minimum), leaving {money(uncovered)} uncovered. "
                f"Move {money(transfer)} from Personal{by} and find {money(uncovered)} more.")
    else:
        msg += (f"Personal ({money(personal)}) has nothing above its {money(cfg.personal_floor)} minimum to send; "
                f"{money(uncovered)} is uncovered{by}.")
    return CheckResult(status="low", transfer_amount=round(transfer, 2), personal_covers=covers, uncovered=uncovered, message=msg,
                       public_message=public_low(lowest_on if deps else (first or end), covers), **common)


def _deposit_specs(cfg: AlertConfig, today: date, end: date):
    """Pair every deposit occurrence in the window with the spec it came from (to know whether Personal funds it)."""
    for spec in cfg.scheduled_deposits:
        for row in bills_due([spec], today, end):
            yield row, spec

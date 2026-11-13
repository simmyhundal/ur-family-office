"""Combined lines for a group of accounts (all, by brokerage, by owner, by wrapper), issue 102 and decision 0011.

Transfers between two household accounts in the group are internal: a withdrawal from one and a deposit into the
other cancel and do not appear as a flow in the combined line (they stay external for each account alone). Matching
is by date window and amount (cash) or symbol and quantity (in-kind); the importer's `transfer_hint` is only a hint.
Transfer candidates that match nothing are listed, never guessed.
"""
from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel

from ufo.performance import metrics as M
from ufo.performance.compare import AccountRun
from ufo.performance.events import Event
from ufo.providers.prices import PriceError, PriceStore

WINDOW_DAYS = 5
CASH_TOLERANCE = 0.01  # a cash transfer's two sides may differ by 1% (or $1)
QTY_TOLERANCE = 1e-6
NONMARKET_NOTE = "includes non-market accounts"  # their flows are compared with the benchmark too, so the excess IRR is not like for like


class Transfer(BaseModel):
    out_account: str
    in_account: str
    out_date: date
    in_date: date
    amount: float
    symbol: str = ""


class GroupRun(BaseModel):
    kind: str  # all | brokerage | owner | wrapper
    name: str
    members: list[str]
    report: M.Report | None = None
    end: date | None = None
    end_value: float | None = None
    transfers: list[Transfer] = []
    unmatched: list[str] = []
    flows: list[tuple[date, float]] = []
    quality: str = "estimated"
    note: str = ""  # e.g. "as of the last common month-end"
    error: str = ""


def _compatible(out: Event, inn: Event) -> bool:
    if out.in_kind != inn.in_kind:
        return False
    if out.in_kind:
        q1, q2 = abs(out.quantity or 0.0), abs(inn.quantity or 0.0)
        return out.symbol == inn.symbol and q1 > 0 and abs(q1 - q2) <= QTY_TOLERANCE * max(q1, q2)
    a1, a2 = abs(out.amount), abs(inn.amount)
    return abs(a1 - a2) <= max(1.0, CASH_TOLERANCE * max(a1, a2))


def net_transfers(runs: list[AccountRun], window_days: int = WINDOW_DAYS) -> tuple[list[tuple[Event, Event]], list[str]]:
    """Pair withdrawals with deposits across different accounts. Returns (pairs, unmatched hinted candidates)."""
    ext = [e for r in runs for e in r.events if e.external_flow]
    outs = sorted((e for e in ext if e.external_flow < 0), key=lambda e: (e.when, e.seq))
    ins = [e for e in ext if e.external_flow > 0]
    used: set[int] = set()
    pairs: list[tuple[Event, Event]] = []
    for o in outs:
        best = None
        for i in ins:
            if id(i) in used or i.account_id == o.account_id or abs((i.when - o.when).days) > window_days or not _compatible(o, i):
                continue
            key = (abs((i.when - o.when).days), abs(abs(i.amount) - abs(o.amount)))
            if best is None or key < best[0]:
                best = (key, i)
        if best:
            used.add(id(best[1]))
            used.add(id(o))
            pairs.append((o, best[1]))
    unmatched = [f"{e.when} {e.account_id}: {'out' if e.external_flow < 0 else 'in'} {abs(e.amount):,.2f}"
                 f"{' ' + e.symbol if e.symbol else ''} looks like a transfer but matches nothing in this group"
                 for e in ext if e.transfer_hint and id(e) not in used and id(e) not in {id(o) for o, _ in pairs}]
    return pairs, unmatched


def combine(kind: str, name: str, runs: list[AccountRun], store: PriceStore, benchmark: str = "VTI") -> GroupRun:
    g = GroupRun(kind=kind, name=name, members=[r.account.id for r in runs])
    failed = [r for r in runs if r.result is None]
    if failed:
        g.error = "not computed: " + "; ".join(f"{r.account.label}: {r.error}" for r in failed)
        return g
    open_ = [r for r in runs if not r.account.closed]
    end = max((r.end for r in open_), default=max(r.end for r in runs))
    values_at: dict[str, float] = {}  # account id -> value on the common date
    exact = all(r.quality == "exact" for r in runs)
    if any(r.end != end for r in open_):
        # Ending values are on different dates: value everyone at the latest month-end they all cover.
        common = set.intersection(*(set(r.result.report.months) for r in open_))
        if not common:
            g.error = ("not computed: no month-end is covered by every account (" +
                       ", ".join(f"{r.account.label} from {r.result.report.months[0]} to {r.result.report.months[-1]}"
                                 for r in open_) + ")")
            return g
        end = max(common)
        exact = True
        for r in runs:
            if end in r.result.report.months:
                v, src = r.anchors.get(end) or (r.result.report.values[r.result.report.months.index(end)], "ledger")
                exact = exact and src == "statement"
            else:
                v = 0.0  # closed before the common date
            values_at[r.account.id] = v
        g.note = f"as of {end}, the last month-end every account covers"
    pairs, g.unmatched = net_transfers(runs)
    skip = {id(e) for pair in pairs for e in pair}
    g.transfers = [Transfer(out_account=o.account_id, in_account=i.account_id, out_date=o.when, in_date=i.when,
                            amount=abs(o.amount), symbol=o.symbol) for o, i in pairs]
    flows = sorted((e.when, e.external_flow) for r in runs for e in r.events
                   if e.external_flow and id(e) not in skip and e.when <= end)
    by_month: dict[date, float] = {}
    for r in runs:
        # every month-end of the member, including its first partial month (the report drops it because it has no return),
        # so a deposit and the value it bought land in the same month of the combined line
        for m, v in r.result.month_values or zip(r.result.report.months, r.result.report.values):
            if m > end:
                continue
            by_month[m] = by_month.get(m, 0.0) + v
    months = sorted(by_month)
    if not flows or not months:
        g.error = "not computed: no cash flows left after netting transfers"
        return g
    start = min(r.result.first_trade for r in runs) - timedelta(days=5)
    try:
        prices, warns = store.report([benchmark], start, end)
        if benchmark not in prices:
            raise ValueError(f"could not load the benchmark {benchmark}")
        rf = store.risk_free(start, end)
    except (PriceError, ValueError) as e:
        g.error = f"not computed: {e}"
        return g
    g.flows = flows
    g.end, g.end_value = end, (sum(values_at.values()) if values_at else sum(r.end_value for r in runs))
    g.report = M.analyze(flows, months, [by_month[m] for m in months], prices[benchmark], rf, end, g.end_value)
    g.quality = "exact" if exact else "estimated"
    if any(not r.market for r in runs):
        g.note = "; ".join(x for x in (g.note, NONMARKET_NOTE) if x)
    return g


def groups(runs: list[AccountRun], singletons: bool = False) -> list[tuple[str, str, list[AccountRun]]]:
    """The combined lines worth showing: everything, and each brokerage / owner / wrapper holding two or more accounts."""
    out = [("all", "All accounts", runs)] if len(runs) > 1 else []
    for kind, key in (("brokerage", lambda r: r.account.institution_name), ("owner", lambda r: r.account.owner),
                      ("wrapper", lambda r: r.account.wrapper.value)):
        by: dict[str, list[AccountRun]] = {}
        for r in runs:
            by.setdefault(key(r), []).append(r)
        out += [(kind, f"{kind}: {k}", v) for k, v in sorted(by.items()) if (len(v) > 1 or singletons) and (len(v) < len(runs) or singletons)]
    return out


def combine_all(runs: list[AccountRun], store: PriceStore, benchmark: str = "VTI", singletons: bool = False) -> list[GroupRun]:
    return [combine(k, n, rs, store, benchmark) for k, n, rs in groups(runs, singletons)]

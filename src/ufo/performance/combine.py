"""Combined lines for a group of accounts (all, by brokerage, by owner, by wrapper), issue 102 and decision 0011.

Transfers between two household accounts in the group are internal: a withdrawal from one and a deposit into the
other cancel and do not appear as a flow in the combined line (they stay external for each account alone). Matching
is by date window and amount (cash; to the cent unless an importer flagged it, then marked "assumed internal") or symbol and
quantity (in-kind, lots summed, longer window). Every netted pair is named in the output.
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
SHARE_WINDOW_DAYS = 14  # a move of shares between brokerages can take longer than a cash move
ASSUMED_TOLERANCE = 0.01  # an unflagged cash pair must match to the cent
QTY_TOLERANCE = 1e-6
NONMARKET_NOTE = "includes non-market accounts"  # their flows are compared with the benchmark too, so the excess IRR is not like for like


class Transfer(BaseModel):
    out_account: str
    in_account: str
    out_date: date
    in_date: date
    amount: float
    symbol: str = ""
    assumed: bool = False  # matched on date and amount alone (no importer flagged it)


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


def _cash_ok(out: Event, inn: Event, hinted: bool) -> bool:
    a1, a2 = abs(out.amount), abs(inn.amount)
    return abs(a1 - a2) <= (max(1.0, CASH_TOLERANCE * max(a1, a2)) if hinted else ASSUMED_TOLERANCE)


def _qty_ok(q1: float, q2: float) -> bool:
    return q1 > 0 and abs(q1 - q2) <= QTY_TOLERANCE * max(q1, q2)


class Match(BaseModel):
    """One internal transfer: the lots that left one account and the lots that arrived in another."""
    outs: list[Event]
    ins: list[Event]
    assumed: bool = False  # matched on date and amount alone: neither importer flagged it as a transfer


def net_transfers(runs: list[AccountRun], window_days: int = WINDOW_DAYS) -> tuple[list[Match], list[str]]:
    """Pair withdrawals with deposits across different accounts. Returns (matches, unmatched hinted candidates).

    Share (in-kind) moves match on fund and share count, with a longer window, and may be split into several lots on
    either side. Cash moves match when an importer flagged either side as a transfer (amounts within 1% or $1); an
    unflagged cash pair matches only to the cent and is marked `assumed` so it is named, never silent (issue 115)."""
    ext = [e for r in runs for e in r.events if e.external_flow]
    outs = sorted((e for e in ext if e.external_flow < 0), key=lambda e: (e.when, e.seq))
    ins = [e for e in ext if e.external_flow > 0]
    used: set[int] = set()
    matches: list[Match] = []
    for o in outs:  # one lot for one lot
        best = None
        for i in ins:
            if id(i) in used or id(o) in used or i.account_id == o.account_id or o.in_kind != i.in_kind:
                continue
            gap = abs((i.when - o.when).days)
            if o.in_kind:
                if gap > SHARE_WINDOW_DAYS or o.symbol != i.symbol or not _qty_ok(abs(o.quantity or 0.0), abs(i.quantity or 0.0)):
                    continue
                hinted = True
            else:
                hinted = o.transfer_hint or i.transfer_hint
                if gap > window_days or not _cash_ok(o, i, hinted):
                    continue
            key = (gap, abs(abs(i.amount) - abs(o.amount)))
            if best is None or key < best[0]:
                best = (key, i, hinted)
        if best:
            used |= {id(best[1]), id(o)}
            matches.append(Match(outs=[o], ins=[best[1]], assumed=not best[2]))
    # shares split into several lots on one side: match the totals per fund between two accounts
    rest_o = [e for e in outs if id(e) not in used and e.in_kind and e.symbol]
    rest_i = [e for e in ins if id(e) not in used and e.in_kind and e.symbol]
    for sym in sorted({e.symbol for e in rest_o}):
        for a in sorted({e.account_id for e in rest_o if e.symbol == sym}):
            for b in sorted({e.account_id for e in rest_i if e.symbol == sym and e.account_id != a}):
                lo = [e for e in rest_o if e.symbol == sym and e.account_id == a and id(e) not in used]
                li = [e for e in rest_i if e.symbol == sym and e.account_id == b and id(e) not in used]
                while lo and li:
                    first = lo[0].when
                    batch_o = [e for e in lo if (e.when - first).days <= SHARE_WINDOW_DAYS]
                    batch_i = [e for e in li if abs((e.when - first).days) <= 2 * SHARE_WINDOW_DAYS]
                    q_o = sum(abs(e.quantity or 0.0) for e in batch_o)
                    if not _qty_ok(q_o, sum(abs(e.quantity or 0.0) for e in batch_i)):
                        lo = lo[1:]  # this lot starts no batch that matches; try the next one
                        continue
                    matches.append(Match(outs=batch_o, ins=batch_i))
                    used |= {id(e) for e in batch_o + batch_i}
                    lo = [e for e in lo if id(e) not in used]
                    li = [e for e in li if id(e) not in used]
    unmatched = [f"{e.when} {e.account_id}: {'out' if e.external_flow < 0 else 'in'} {abs(e.amount):,.2f}"
                 f"{' ' + e.symbol if e.symbol else ''} looks like a transfer but matches nothing in this group"
                 for e in ext if e.transfer_hint and id(e) not in used]
    return matches, unmatched


def _lot_value(e: Event, unit: float) -> float:
    return abs(e.quantity or 0.0) * unit if e.in_kind else abs(e.amount)


def in_transit(matches: list[Match], months: list[date]) -> dict[date, float]:
    """Value that has left one account but not yet arrived in the other at each month-end, so the combined value does
    not show a dip that did not happen (issue 118). Valued from the outgoing lots' own amounts."""
    out: dict[date, float] = {}
    for m in matches:
        q = sum(abs(e.quantity or 0.0) for e in m.outs)
        total = sum(abs(e.amount) for e in m.outs)
        unit = total / q if q and m.outs[0].in_kind else 0.0
        for d in months:
            gone = sum(_lot_value(e, unit) for e in m.outs if e.when <= d)
            back = sum(_lot_value(e, unit) for e in m.ins if e.when <= d)
            if gone > back:
                out[d] = out.get(d, 0.0) + gone - back
    return out


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
    matches, g.unmatched = net_transfers(runs)
    skip = {id(e) for m in matches for e in m.outs + m.ins}
    g.transfers = [Transfer(out_account=m.outs[0].account_id, in_account=m.ins[0].account_id, out_date=min(e.when for e in m.outs),
                            in_date=max(e.when for e in m.ins), amount=sum(abs(e.amount) for e in m.outs), symbol=m.outs[0].symbol,
                            assumed=m.assumed) for m in matches]
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
    for d, v in in_transit(matches, months).items():
        by_month[d] += v
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

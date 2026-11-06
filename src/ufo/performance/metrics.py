"""Performance metrics: money-weighted (IRR), time-weighted, Sharpe and friends, and excess IRR vs an index.

Pure functions over dated cash flows and value series. No I/O. Definitions follow decision 0007:
  excess IRR = IRR of the real cash flows minus IRR of the same cash flows put into a total-market index (a public
  market equivalent). Sharpe is secondary.

Sign convention for IRR: the investor's view. Money put in is negative, money taken out is positive, and the ending
value counts as a final positive.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import mean, stdev

from pydantic import BaseModel

from ufo.providers.prices import Series

MIN_YEARS_FOR_ANNUALIZING = 1.0


# ---------- money-weighted ----------

def xirr(flows: list[tuple[date, float]]) -> float | None:
    """Annual rate r where sum(cf / (1+r)^(days/365)) = 0, or None when there is no sign change or no solution."""
    flows = sorted(flows)
    if len(flows) < 2 or not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return None
    t0 = flows[0][0]

    def npv(r: float) -> float:
        return sum(a / (1 + r) ** ((d - t0).days / 365) for d, a in flows)

    lo, hi = -0.999, 1.0
    f_lo, f_hi = npv(lo), npv(hi)
    while f_lo * f_hi > 0 and hi < 1e6:
        hi *= 4
        f_hi = npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def investor_flows(external: list[tuple[date, float]], end: date, end_value: float) -> list[tuple[date, float]]:
    """Ledger flows are + into the account. The investor puts that money in (negative) and gets the end value back."""
    return [(d, -a) for d, a in external] + [(end, end_value)]


class IndexResult(BaseModel):
    irr: float | None
    terminal_value: float
    note: str = ""


def index_counterfactual(external: list[tuple[date, float]], index: Series, end: date) -> IndexResult:
    """Put every contribution into the index and take every withdrawal out of it on the same dates."""
    units = 0.0
    for d, a in sorted(external):
        px = index.on_or_before(d)
        if px:
            units += a / px
    end_px = index.on_or_before(end)
    terminal = units * (end_px or 0.0)
    note = ""
    if terminal <= 0:
        note = "The withdrawals were larger than an index fund could have supported, so there is no meaningful index IRR."
        return IndexResult(irr=None, terminal_value=terminal, note=note)
    return IndexResult(irr=xirr(investor_flows(external, end, terminal)), terminal_value=terminal)


def ks_pme(external: list[tuple[date, float]], index: Series, end: date, end_value: float) -> float | None:
    """Kaplan-Schoar PME: (withdrawals and ending value grown by the index) / (contributions grown by the index).
    Above 1.0 means the family did better than the index with the same cash flows."""
    end_px = index.on_or_before(end)
    if not end_px:
        return None
    put_in = sum(a * end_px / index.on_or_before(d) for d, a in external if a > 0 and index.on_or_before(d))
    taken = sum(-a * end_px / index.on_or_before(d) for d, a in external if a < 0 and index.on_or_before(d)) + end_value
    return taken / put_in if put_in else None


# ---------- time-weighted ----------

class MonthReturn(BaseModel):
    end: date
    value: float
    flow: float
    ret: float | None


def monthly_returns(month_ends: list[date], values: list[float], external: list[tuple[date, float]]) -> list[MonthReturn]:
    """Modified Dietz per month: gain over (starting value + day-weighted flows). Income stays inside the return."""
    out = []
    prev_end, prev_val = None, 0.0
    for end, val in zip(month_ends, values):
        start = prev_end if prev_end else date(end.year, end.month, 1) - timedelta(days=1)
        span = (end - start).days
        flows = [(d, a) for d, a in external if start < d <= end]
        net = sum(a for _, a in flows)
        weighted = sum(a * (end - d).days / span for d, a in flows) if span else 0.0
        denom = prev_val + weighted
        ret = (val - prev_val - net) / denom if denom > 1e-9 else None
        out.append(MonthReturn(end=end, value=val, flow=net, ret=ret))
        prev_end, prev_val = end, val
    return out


def growth_index(returns: list[float | None]) -> list[float]:
    g, out = 1.0, []
    for r in returns:
        g *= 1 + (r or 0.0)
        out.append(g)
    return out


def annualize(total_growth: float, months: int) -> float | None:
    if months < 12 * MIN_YEARS_FOR_ANNUALIZING or total_growth <= 0:
        return None
    return total_growth ** (12 / months) - 1


def max_drawdown(index: list[float]) -> float:
    peak, worst = 1.0, 0.0
    for v in index:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


# ---------- risk-adjusted ----------

def monthly_rf(rf: Series, prev_end: date) -> float:
    """Monthly risk-free return from the annualized 3-month T-bill yield (percent) at the start of the month."""
    y = rf.on_or_before(prev_end)
    return (1 + (y or 0.0) / 100) ** (1 / 12) - 1


def sharpe(excess: list[float]) -> float | None:
    if len(excess) < 12:
        return None
    sd = stdev(excess)
    return mean(excess) / sd * math.sqrt(12) if sd > 1e-12 else None


def sortino(excess: list[float]) -> float | None:
    if len(excess) < 12:
        return None
    down = math.sqrt(mean(min(x, 0.0) ** 2 for x in excess))
    return mean(excess) / down * math.sqrt(12) if down > 1e-12 else None


def volatility(returns: list[float]) -> float | None:
    return stdev(returns) * math.sqrt(12) if len(returns) >= 12 else None


def beta_alpha(port: list[float], bench: list[float], rf: list[float]) -> tuple[float, float] | None:
    """OLS of monthly excess returns: (beta, annualized alpha)."""
    n = min(len(port), len(bench), len(rf))
    if n < 12:
        return None
    y = [p - r for p, r in zip(port[:n], rf[:n])]
    x = [b - r for b, r in zip(bench[:n], rf[:n])]
    mx, my = mean(x), mean(y)
    var = sum((a - mx) ** 2 for a in x)
    if var < 1e-12:
        return None
    beta = sum((a - mx) * (b - my) for a, b in zip(x, y)) / var
    return beta, (my - beta * mx) * 12


# ---------- the whole picture ----------

class Report(BaseModel):
    start: date
    end: date
    end_value: float
    contributed: float
    withdrawn: float
    irr: float | None
    index_irr: float | None
    index_note: str = ""
    excess_irr: float | None
    pme: float | None
    twr_annual: float | None
    index_twr_annual: float | None
    sharpe: float | None
    index_sharpe: float | None
    sortino: float | None
    volatility: float | None
    index_volatility: float | None
    max_drawdown: float
    index_max_drawdown: float
    beta: float | None
    alpha: float | None
    months: list[date]
    port_growth: list[float]
    index_growth: list[float]
    port_returns: list[float | None]
    index_returns: list[float]
    flows_by_month: list[float]
    values: list[float]


def analyze(external: list[tuple[date, float]], month_ends: list[date], values: list[float], index: Series,
            rf: Series, end: date, end_value: float, returns: list[float | None] | None = None) -> Report:
    """`returns` are optional month-by-month portfolio returns (e.g. holdings-based); otherwise modified Dietz."""
    ext = sorted(external)
    port = monthly_returns(month_ends, values, ext)
    if returns is not None:
        port = [m.model_copy(update={"ret": r}) for m, r in zip(port, returns)]
    # index monthly returns over the same month ends
    idx_prices = [index.on_or_before(d) for d in month_ends]
    idx_ret: list[float] = []
    for i, px in enumerate(idx_prices):
        prev = idx_prices[i - 1] if i else index.on_or_before(date(month_ends[0].year, month_ends[0].month, 1) - timedelta(days=1))
        idx_ret.append((px / prev - 1) if px and prev else 0.0)
    # use only months where the portfolio had capital, so both sides cover the same period
    keep = [i for i, m in enumerate(port) if m.ret is not None]
    p_r = [port[i].ret for i in keep]
    b_r = [idx_ret[i] for i in keep]
    r_f = [monthly_rf(rf, (month_ends[i - 1] if i else date(month_ends[0].year, month_ends[0].month, 1) - timedelta(days=1))) for i in keep]
    p_g, b_g = growth_index(p_r), growth_index(b_r)
    months = len(keep)
    p_ex = [p - r for p, r in zip(p_r, r_f)]
    b_ex = [b - r for b, r in zip(b_r, r_f)]
    irr = xirr(investor_flows(ext, end, end_value))
    idx = index_counterfactual(ext, index, end)
    ba = beta_alpha(p_r, b_r, r_f)
    return Report(
        start=ext[0][0] if ext else month_ends[0], end=end, end_value=end_value,
        contributed=sum(a for _, a in ext if a > 0), withdrawn=-sum(a for _, a in ext if a < 0),
        irr=irr, index_irr=idx.irr, index_note=idx.note,
        excess_irr=(irr - idx.irr) if irr is not None and idx.irr is not None else None,
        pme=ks_pme(ext, index, end, end_value),
        twr_annual=annualize(p_g[-1], months) if p_g else None, index_twr_annual=annualize(b_g[-1], months) if b_g else None,
        sharpe=sharpe(p_ex), index_sharpe=sharpe(b_ex), sortino=sortino(p_ex),
        volatility=volatility(p_r), index_volatility=volatility(b_r),
        max_drawdown=max_drawdown(p_g), index_max_drawdown=max_drawdown(b_g),
        beta=ba[0] if ba else None, alpha=ba[1] if ba else None,
        months=[month_ends[i] for i in keep], port_growth=p_g, index_growth=b_g, port_returns=p_r, index_returns=b_r,
        flows_by_month=[port[i].flow for i in keep], values=[port[i].value for i in keep])

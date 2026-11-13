"""Efficient frontier, the max-Sharpe mix, and the walk-forward test that says whether such a mix would have worked
(issue 130, milestone M12). Read-only, local only; nothing here places or suggests an order.

The hard rule: a mix chosen with hindsight is in-sample, and an optimizer is the worst case of that. So the optimizer is only
ever *judged* by walk-forward testing: at each rebalance date it sees only data before that date, picks a mix, holds it until
the next rebalance, and repeats. The in-sample best mix over the whole history is shown too, labelled as hindsight, so the gap
is visible. A backtest winner is never a prediction.

Pure Python (the project venv has no numpy). Works on monthly adjusted closes (dividends and expense ratios inside), before tax,
with no trading costs. Estimation: mean returns shrunk toward the grand mean, covariance shrunk toward a constant-correlation
target (Ledoit-Wolf style intensity). The optimizer is long-only with per-fund min and max weights.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean

from ufo.performance import metrics as M
from ufo.performance.whatif import DISCLAIMER, Panel, Summary, summarize, ym_label
from ufo.providers.prices import Series

MEAN_SHRINK = 0.5  # weight put on the grand mean when estimating each fund's mean return
CORR_SHRINK_MAX = 0.9
DEFAULT_LOOKBACK = 60
SENSITIVITY_LOOKBACKS = (36, 60, 120)
ROLLING_MONTHS = 60

ASSUMPTIONS = [
    "Before tax. Rebalancing in a taxable account realizes gains, which would be taxed; none of that is counted here.",
    "Monthly adjusted closes: dividends are reinvested and fund expense ratios are already inside the prices.",
    "No trading costs, spreads or minimums.",
    "Monthly steps; completed months only. Every strategy rebalances back to its weights on the same dates and drifts in between.",
    "Estimates use shrinkage: means are pulled halfway to the average of all funds, the covariance toward a constant correlation. "
    "This calms the optimizer; it does not make the estimates right.",
    "Long only, no leverage: weights are between the per-fund minimum and maximum and add to 100%.",
    "The cash rate is the 3-month Treasury bill (FRED DTB3) at the start of each month.",
]
SHARPE_NOTE = (
    "A higher Sharpe ratio means more return per unit of risk. That is not the same as more return. The max-Sharpe mix is the point on "
    "the frontier with the best ratio; it is not the point with the highest return. To earn more than that mix you must take more "
    "risk, either by holding more of the riskier funds along the frontier or by borrowing (leverage). This report never uses "
    "leverage, and a mix with a higher Sharpe ratio can still have a lower return, and can still lose money.")


# ---------- small linear algebra (n is about 10) ----------

Matrix = list[list[float]]


def matvec(a: Matrix, v: list[float]) -> list[float]:
    return [sum(x * y for x, y in zip(row, v)) for row in a]


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def mean_vec(rows: list[list[float]]) -> list[float]:
    n = len(rows)
    return [sum(r[j] for r in rows) / n for j in range(len(rows[0]))]


def sample_cov(rows: list[list[float]]) -> Matrix:
    n, p = len(rows), len(rows[0])
    mu = mean_vec(rows)
    c = [[0.0] * p for _ in range(p)]
    for r in rows:
        d = [r[j] - mu[j] for j in range(p)]
        for i in range(p):
            di = d[i]
            ci = c[i]
            for j in range(i, p):
                ci[j] += di * d[j]
    for i in range(p):
        for j in range(i, p):
            c[i][j] /= n - 1
            c[j][i] = c[i][j]
    return c


def shrink_cov(rows: list[list[float]]) -> tuple[Matrix, float]:
    """Sample covariance pulled toward a constant-correlation target; returns (matrix, intensity 0..1).
    Intensity is the Ledoit-Wolf estimate of estimation noise over distance from the target (Frobenius, ignoring the
    covariance-between-errors term, so a little conservative)."""
    n, p = len(rows), len(rows[0])
    s = sample_cov(rows)
    sd = [math.sqrt(max(s[i][i], 1e-18)) for i in range(p)]
    if p == 1:
        return s, 0.0
    rbar = sum(s[i][j] / (sd[i] * sd[j]) for i in range(p) for j in range(p) if i != j) / (p * (p - 1))
    t = [[s[i][i] if i == j else rbar * sd[i] * sd[j] for j in range(p)] for i in range(p)]
    mu = mean_vec(rows)
    d2 = sum((s[i][j] - t[i][j]) ** 2 for i in range(p) for j in range(p))
    # b2: average squared error of the per-month outer products around the sample covariance, divided by n
    b2 = 0.0
    for r in rows:
        d = [r[j] - mu[j] for j in range(p)]
        b2 += sum((d[i] * d[j] - s[i][j]) ** 2 for i in range(p) for j in range(p))
    b2 /= n * n
    delta = CORR_SHRINK_MAX if d2 <= 1e-30 else min(CORR_SHRINK_MAX, max(0.0, b2 / d2))
    return [[delta * t[i][j] + (1 - delta) * s[i][j] for j in range(p)] for i in range(p)], delta


def shrink_mean(mu: list[float], k: float = MEAN_SHRINK) -> list[float]:
    g = sum(mu) / len(mu)
    return [(1 - k) * m + k * g for m in mu]


# ---------- constrained optimizer ----------

def project(v: list[float], lo: list[float], hi: list[float]) -> list[float]:
    """Closest point to v with sum = 1 and lo <= w <= hi (bisection on the common shift)."""
    a, b = min(x - h for x, h in zip(v, hi)), max(x - l for x, l in zip(v, lo))
    for _ in range(80):
        tau = (a + b) / 2
        s = sum(min(h, max(l, x - tau)) for x, l, h in zip(v, lo, hi))
        if s > 1:
            a = tau
        else:
            b = tau
    tau = (a + b) / 2
    return [min(h, max(l, x - tau)) for x, l, h in zip(v, lo, hi)]


def check_bounds(n: int, lo: float, hi: float) -> None:
    if not 0 <= lo <= hi <= 1:
        raise ValueError("Weights must satisfy 0 <= min <= max <= 100%.")
    if n * hi < 1 - 1e-9:
        raise ValueError(f"A maximum of {hi * 100:.0f}% per fund cannot reach 100% with {n} funds.")
    if n * lo > 1 + 1e-9:
        raise ValueError(f"A minimum of {lo * 100:.0f}% per fund is more than 100% with {n} funds.")


def solve_utility(mu: list[float], cov: Matrix, lam: float, lo: list[float], hi: list[float],
                  w0: list[float] | None = None, iters: int = 1500) -> list[float]:
    """maximize mu'w - (lam/2) w'cov w over the box-simplex (accelerated projected gradient)."""
    n = len(mu)
    lmax = max(sum(abs(x) for x in row) for row in cov) * lam
    step = 1.0 / max(lmax, 1e-12)
    w = project(w0 if w0 is not None else [1.0 / n] * n, lo, hi)
    y, t = w[:], 1.0
    for _ in range(iters):
        g = matvec(cov, y)
        w_new = project([y[i] - step * (lam * g[i] - mu[i]) for i in range(n)], lo, hi)
        t_new = (1 + math.sqrt(1 + 4 * t * t)) / 2
        y = [w_new[i] + (t - 1) / t_new * (w_new[i] - w[i]) for i in range(n)]
        moved = max(abs(w_new[i] - w[i]) for i in range(n))
        w, t = w_new, t_new
        if moved < 1e-9:
            break
    return w


def port_stats(w: list[float], mu: list[float], cov: Matrix) -> tuple[float, float]:
    """(expected excess return, volatility) per month."""
    return dot(w, mu), math.sqrt(max(dot(w, matvec(cov, w)), 0.0))


def sharpe_of(w: list[float], mu: list[float], cov: Matrix) -> float:
    r, v = port_stats(w, mu, cov)
    return r / v if v > 1e-12 else float("-inf")


def min_variance(cov: Matrix, lo: list[float], hi: list[float]) -> list[float]:
    return solve_utility([0.0] * len(cov), cov, 1.0, lo, hi)


def max_sharpe(mu: list[float], cov: Matrix, lo: list[float], hi: list[float]) -> list[float]:
    """Long-only tangency mix: Sharpe is unimodal along the frontier, so scan risk aversion then refine."""
    xs = [-2 + 0.25 * i for i in range(25)]  # lam = 10**x, x in [-2, 4]
    w, best, best_i, cache = None, float("-inf"), 0, []
    for i, x in enumerate(xs):
        w = solve_utility(mu, cov, 10 ** x, lo, hi, w)
        cache.append(w)
        s = sharpe_of(w, mu, cov)
        if s > best:
            best, best_i = s, i
    a, b = xs[max(best_i - 1, 0)], xs[min(best_i + 1, len(xs) - 1)]
    phi = (math.sqrt(5) - 1) / 2
    c, d = b - phi * (b - a), a + phi * (b - a)
    start = cache[best_i]
    wc, wd = solve_utility(mu, cov, 10 ** c, lo, hi, start), solve_utility(mu, cov, 10 ** d, lo, hi, start)
    fc, fd = sharpe_of(wc, mu, cov), sharpe_of(wd, mu, cov)
    for _ in range(12):
        if fc > fd:
            b, d, wd, fd = d, c, wc, fc
            c = b - phi * (b - a)
            wc = solve_utility(mu, cov, 10 ** c, lo, hi, wd)
            fc = sharpe_of(wc, mu, cov)
        else:
            a, c, wc, fc = c, d, wd, fd
            d = a + phi * (b - a)
            wd = solve_utility(mu, cov, 10 ** d, lo, hi, wc)
            fd = sharpe_of(wd, mu, cov)
    cand = [(best, cache[best_i]), (fc, wc), (fd, wd)]
    return max(cand, key=lambda t: t[0])[1]


def max_return_at_vol(mu: list[float], cov: Matrix, lo: list[float], hi: list[float], vol: float) -> list[float]:
    """The frontier point with the highest return whose volatility does not exceed `vol` (monthly). If `vol` is above the
    riskiest corner this is the highest-return mix; if below the minimum-variance mix it is the minimum-variance mix."""
    mv = min_variance(cov, lo, hi)
    if port_stats(mv, mu, cov)[1] >= vol:
        return mv
    top = solve_utility(mu, cov, 1e-6, lo, hi)
    if port_stats(top, mu, cov)[1] <= vol:
        return top
    a, b = -6.0, 6.0  # log10(lam): vol falls as lam rises
    w = top
    for _ in range(24):
        m = (a + b) / 2
        w = solve_utility(mu, cov, 10 ** m, lo, hi, w)
        if port_stats(w, mu, cov)[1] > vol:
            a = m
        else:
            b = m
    return solve_utility(mu, cov, 10 ** b, lo, hi, w)


def frontier_points(mu: list[float], cov: Matrix, lo: list[float], hi: list[float], k: int = 9) -> list[list[float]]:
    """k mixes from minimum variance up to the highest-return corner, evenly spaced in volatility."""
    mv, top = min_variance(cov, lo, hi), solve_utility(mu, cov, 1e-6, lo, hi)
    v0, v1 = port_stats(mv, mu, cov)[1], port_stats(top, mu, cov)[1]
    if v1 - v0 < 1e-9:
        return [mv]
    return [mv] + [max_return_at_vol(mu, cov, lo, hi, v0 + (v1 - v0) * i / (k - 1)) for i in range(1, k - 1)] + [top]


# ---------- estimation from the panel ----------

def month_date(m: int) -> date:
    """Last day of month index m (year*12 + month-1)."""
    y, mo = divmod(m, 12)
    nxt = date(y + (mo + 1) // 12, (mo + 1) % 12 + 1, 1)
    return nxt - timedelta(days=1)


def returns_matrix(panel: Panel, syms: list[str], first: int, last: int) -> list[list[float]]:
    """Simple monthly returns of months first..last (month t = price t over price t-1)."""
    return [[panel.at(s, t) / panel.at(s, t - 1) - 1 for s in syms] for t in range(first, last + 1)]


def rf_list(rf: Series, first: int, last: int) -> list[float]:
    return [M.monthly_rf(rf, month_date(t - 1)) for t in range(first, last + 1)]


@dataclass
class Estimate:
    mu: list[float]  # shrunk monthly excess returns
    cov: Matrix
    delta: float
    first: int
    last: int


def estimate(panel: Panel, syms: list[str], rf: Series, first: int, last: int) -> Estimate:
    rows = returns_matrix(panel, syms, first, last)
    rfs = rf_list(rf, first, last)
    ex = [[x - r for x in row] for row, r in zip(rows, rfs)]
    cov, delta = shrink_cov(rows)
    return Estimate(shrink_mean(mean_vec(ex)), cov, delta, first, last)


def suggest(panel: Panel, syms: list[str], rf: Series, first: int, last: int, lo: float, hi: float) -> tuple[list[float], Estimate]:
    check_bounds(len(syms), lo, hi)
    est = estimate(panel, syms, rf, first, last)
    return max_sharpe(est.mu, est.cov, [lo] * len(syms), [hi] * len(syms)), est


# ---------- walk-forward ----------

@dataclass
class Decision:
    month: int  # the mix is held from the start of this month
    input_first: int
    input_last: int  # last month of data the optimizer saw: always before `month`
    weights: dict[str, float]


def decision_months(panel: Panel, lookback: int, rebalance: int) -> list[int]:
    """Months at whose start the mix is (re)chosen. The first needs `lookback` months of returns before it."""
    first = panel.first + lookback + 1
    return list(range(first, panel.complete_last + 1, rebalance))


def walk_forward(panel: Panel, syms: list[str], rf: Series, lookback: int, rebalance: int, lo: float, hi: float) -> list[Decision]:
    check_bounds(len(syms), lo, hi)
    out = []
    for d in decision_months(panel, lookback, rebalance):
        a, b = d - lookback, d - 1  # returns of months a..b only: month b's return ends at the end of month d-1
        w, _ = suggest(panel, syms, rf, a, b, lo, hi)
        out.append(Decision(d, a, b, dict(zip(syms, w))))
    return out


def simulate(panel: Panel, plan: list[tuple[int, dict[str, float]]], last: int) -> list[float]:
    """Monthly returns from plan[0]'s month through `last`. At each plan month the portfolio is reset to that mix, then
    drifts. A month's return uses prices from the end of the previous month to the end of that month."""
    plan = sorted(plan, key=lambda x: x[0])
    nxt, v, out, cur = 0, {}, [], None
    for t in range(plan[0][0], last + 1):
        if nxt < len(plan) and plan[nxt][0] == t:
            tot = sum(v.values()) if v else 1.0
            cur = plan[nxt][1]
            v = {s: tot * w for s, w in cur.items()}
            nxt += 1
        before = sum(v.values())
        for s in v:
            v[s] *= panel.at(s, t) / panel.at(s, t - 1)
        out.append(sum(v.values()) / before - 1)
    return out


def fixed_plan(months: list[int], weights: dict[str, float]) -> list[tuple[int, dict[str, float]]]:
    return [(m, dict(weights)) for m in months]


# ---------- statistics of a return series ----------

@dataclass
class Stats:
    months: int
    ann_return: float | None
    vol: float | None
    sharpe: float | None
    worst_fall: float


def stats(returns: list[float], rfs: list[float]) -> Stats:
    g, idx = 1.0, []
    for r in returns:
        g *= 1 + r
        idx.append(g)
    return Stats(len(returns), M.annualize(g, len(returns)), M.volatility(returns),
                 M.sharpe([r - f for r, f in zip(returns, rfs)]), M.max_drawdown(idx))


def rolling(strat: list[float], other: list[float], rfs: list[float], win: int = ROLLING_MONTHS) -> tuple[Summary, Summary]:
    """Strategy minus other over every `win`-month window: annualized return difference, and Sharpe difference."""
    rd, sd = [], []
    for s in range(0, len(strat) - win + 1):
        a, b, f = strat[s:s + win], other[s:s + win], rfs[s:s + win]
        sa, sb = stats(a, f), stats(b, f)
        if sa.ann_return is not None and sb.ann_return is not None:
            rd.append(sa.ann_return - sb.ann_return)
        if sa.sharpe is not None and sb.sharpe is not None:
            sd.append(sa.sharpe - sb.sharpe)
    return summarize(rd), summarize(sd)


# ---------- the full study ----------

@dataclass
class Run:
    lookback: int
    decisions: list[Decision]
    first: int  # first held month
    last: int
    series: dict[str, list[float]]  # strategy name -> monthly returns over first..last
    stats: dict[str, Stats]
    rfs: list[float]
    roll_ret: dict[str, Summary]
    roll_sharpe: dict[str, Summary]
    avg_turnover: float
    avg_weights: dict[str, float]


WF = "Walk-forward max-Sharpe"


def run_walk_forward(panel: Panel, funds: list[str], rf: Series, lookback: int, rebalance: int, lo: float, hi: float,
                     current: dict[str, float] | None) -> Run:
    decisions = walk_forward(panel, funds, rf, lookback, rebalance, lo, hi)
    if not decisions:
        raise ValueError(f"Not enough history for a {lookback}-month lookback: need more than {lookback + 1} months.")
    months = [d.month for d in decisions]
    last = panel.complete_last
    strategies: dict[str, list[tuple[int, dict[str, float]]]] = {
        WF: [(d.month, d.weights) for d in decisions],
        "VTI": fixed_plan(months, {"VTI": 1.0}),
        "Equal weight": fixed_plan(months, {s: 1 / len(funds) for s in funds}),
        "60/40 (VTI/BND)": fixed_plan(months, {"VTI": 0.6, "BND": 0.4}),
    }
    if current:
        strategies["Current mix"] = fixed_plan(months, current)
    series = {name: simulate(panel, plan, last) for name, plan in strategies.items()}
    rfs = rf_list(rf, months[0], last)
    st = {name: stats(r, rfs) for name, r in series.items()}
    rr, rs = {}, {}
    for name in series:
        if name != WF:
            rr[name], rs[name] = rolling(series[WF], series[name], rfs)
    prev = None
    turn = []
    for d in decisions:
        if prev is not None:
            turn.append(sum(abs(d.weights[s] - prev.weights[s]) for s in funds) / 2)
        prev = d
    avg_w = {s: mean(d.weights[s] for d in decisions) for s in funds}
    return Run(lookback, decisions, months[0], last, series, st, rfs, rr, rs, mean(turn) if turn else 0.0, avg_w)


@dataclass
class InSample:
    weights: dict[str, float]
    first: int
    last: int
    stats_all: Stats  # held fixed (annual rebalance) over the whole history
    stats_oos: Stats  # the same hindsight mix over the walk-forward period only
    est: Estimate


@dataclass
class Study:
    funds: list[str]
    panel: Panel
    lo: float
    hi: float
    rebalance: int
    lookback: int
    current: dict[str, float] | None
    now: dict[str, object]  # latest frontier summary
    main: Run
    sens: list[Run]
    insample: InSample


def run_study(panel: Panel, funds: list[str], rf: Series, lookback: int = DEFAULT_LOOKBACK, rebalance: int = 12,
              lo: float = 0.0, hi: float = 0.40, current: dict[str, float] | None = None,
              sens_lookbacks: tuple[int, ...] = SENSITIVITY_LOOKBACKS) -> Study:
    check_bounds(len(funds), lo, hi)
    n = len(funds)
    los, his = [lo] * n, [hi] * n
    last = panel.complete_last
    # the frontier as of the latest data: the last `lookback` months only
    est = estimate(panel, funds, rf, last - lookback + 1, last)
    ms = max_sharpe(est.mu, est.cov, los, his)
    mv = min_variance(est.cov, los, his)
    pts = frontier_points(est.mu, est.cov, los, his)
    now: dict[str, object] = {"est": est, "max_sharpe": ms, "min_var": mv, "frontier": pts}
    if current:
        cw = [current.get(s, 0.0) for s in funds]
        now["current_vec"] = cw
        now["same_vol"] = max_return_at_vol(est.mu, est.cov, los, his, port_stats(cw, est.mu, est.cov)[1])
    main = run_walk_forward(panel, funds, rf, lookback, rebalance, lo, hi, current)
    sens = [main if lb == lookback else run_walk_forward(panel, funds, rf, lb, rebalance, lo, hi, current)
            for lb in sens_lookbacks if lb == lookback or panel.complete_last - panel.first > lb + 12]
    # hindsight: best mix over the whole history, then judged on the same period the walk-forward was judged
    full_first, full_last = panel.first + 1, panel.complete_last
    wfull, efull = suggest(panel, funds, rf, full_first, full_last, lo, hi)
    wdict = dict(zip(funds, wfull))
    all_months = list(range(full_first, full_last + 1, rebalance))
    ret_all = simulate(panel, fixed_plan(all_months, wdict), full_last)
    rf_all = rf_list(rf, all_months[0], full_last)
    oos_months = [d.month for d in main.decisions]
    ret_oos = simulate(panel, fixed_plan(oos_months, wdict), full_last)
    ins = InSample(wdict, full_first, full_last, stats(ret_all, rf_all), stats(ret_oos, main.rfs), efull)
    return Study(funds, panel, lo, hi, rebalance, lookback, current, now, main, sens, ins)


# ---------- output ----------

def pct(x: float | None, d: int = 1, signed: bool = False) -> str:
    return "-" if x is None else (f"{x * 100:+.{d}f}%" if signed else f"{x * 100:.{d}f}%")


def num(x: float | None) -> str:
    return "-" if x is None else f"{x:.2f}"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    return (["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
            + ["| " + " | ".join(r) + " |" for r in rows])


def _mix(funds: list[str], w: list[float]) -> str:
    return ", ".join(f"{s} {x * 100:.0f}%" for s, x in zip(funds, w) if x >= 0.005) or "-"


def _row_stats(name: str, s: Stats) -> list[str]:
    return [name, pct(s.ann_return), pct(s.vol), num(s.sharpe), pct(s.worst_fall, 0)]


def _summ_row(name: str, a: Summary, b: Summary) -> list[str]:
    def p(x: float | None) -> str:
        return "-" if x is None else f"{x * 100:+.1f}"

    def q(x: float | None) -> str:
        return "-" if x is None else f"{x:+.2f}"
    return [name, str(a.n), pct(a.ahead, 0), p(a.median), p(a.p10), p(a.p90), pct(b.ahead, 0), q(b.median)]


def render_markdown(st: Study, today: date | None = None) -> str:
    p, funds, lo, hi = st.panel, st.funds, st.lo, st.hi
    m = st.main
    est: Estimate = st.now["est"]  # type: ignore[assignment]
    L = ["# Suggested mix: maximize the Sharpe ratio, tested walk-forward", "",
         f"Funds: {', '.join(funds)}. Weights {lo * 100:.0f}% to {hi * 100:.0f}% each, long only, no leverage.",
         f"History used: {ym_label(p.first)} to {ym_label(p.complete_last)} (completed months). Lookback {st.lookback} months, "
         f"rebalanced every {st.rebalance} months.", ""]
    if p.standins:
        L.append("**Stand-ins** (used before the fund existed, scaled to match at its first month): "
                 + "; ".join(f"{s} <- {x} (before {ym_label(p.real_first[s])})" for s, x in p.standins.items()))
    else:
        L.append("Stand-ins: none needed.")
    L += ["", "## What a Sharpe ratio is, and is not", "", SHARPE_NOTE, "",
          "## The most important result: did it work out of sample?", "",
          f"Every number in section 2 is **out of sample**: at each rebalance date the optimizer saw only the {st.lookback} months "
          f"before it. Section 1 is an estimate and section 3 is hindsight, and are labelled that way.", ""]
    # 1 frontier now
    L += [f"## 1. The frontier as estimated now ({ym_label(est.first)} to {ym_label(est.last)}, last {st.lookback} months)", "",
          "An estimate from recent history, not a forecast. Returns here are shrunk estimates (annual, in excess of cash) and "
          f"the covariance was shrunk with intensity {est.delta:.2f}.", ""]
    rows = []
    cur = st.now.get("current_vec")

    def line(label: str, w: list[float]) -> list[str]:
        r, v = port_stats(w, est.mu, est.cov)
        return [label, pct(r * 12), pct(v * math.sqrt(12)), num(sharpe_of(w, est.mu, est.cov)), _mix(funds, w)]
    if cur:
        rows.append(line("Current mix", cur))  # type: ignore[arg-type]
    rows.append(line("Max Sharpe (suggested by the optimizer)", st.now["max_sharpe"]))  # type: ignore[arg-type]
    rows.append(line("Minimum variance", st.now["min_var"]))  # type: ignore[arg-type]
    if cur:
        rows.append(line("Highest return at the current mix's volatility", st.now["same_vol"]))  # type: ignore[arg-type]
    L += _table(["Mix", "Est. excess return / yr", "Est. volatility / yr", "Est. Sharpe", "Weights"], rows) + [""]
    fr = [line(f"point {i + 1}", w) for i, w in enumerate(st.now["frontier"])]  # type: ignore[arg-type]
    L += ["Frontier, from least to most risk:", ""] + _table(["Point", "Est. excess return / yr", "Est. volatility / yr", "Est. Sharpe", "Weights"], fr) + [""]
    # 2 walk forward
    L += [f"## 2. Walk-forward test (out of sample), {ym_label(m.first)} to {ym_label(m.last)}", "",
          f"{len(m.decisions)} rebalances. Average one-way turnover per rebalance {pct(m.avg_turnover, 0)}; average weights: "
          + _mix(funds, [m.avg_weights[s] for s in funds]) + ".", ""]
    rows = [_row_stats(n, s) for n, s in m.stats.items()]
    L += _table(["Strategy", "Return / yr", "Volatility / yr", "Sharpe", "Worst fall"], rows) + [""]
    L += [f"### Rolling {ROLLING_MONTHS // 12}-year windows, walk-forward minus each comparison", "",
          "Return difference in percentage points per year; 'Sharpe ahead' is the share of windows with the higher Sharpe ratio. "
          "Windows overlap heavily, so these are not independent odds.", ""]
    rows = [_summ_row(n, m.roll_ret[n], m.roll_sharpe[n]) for n in m.roll_ret]
    L += _table(["Versus", "Windows", "Return ahead", "Median", "10th pct", "90th pct", "Sharpe ahead", "Median Sharpe diff"], rows) + [""]
    L += ["### Sensitivity to the lookback", "",
          "Each lookback is judged over its own out-of-sample period, so its VTI row covers the same months.", ""]
    rows = []
    for r in st.sens:
        w, v = r.stats[WF], r.stats["VTI"]
        rs = r.roll_ret["VTI"]
        rows.append([f"{r.lookback} months", f"{ym_label(r.first)}", pct(w.ann_return), num(w.sharpe), pct(v.ann_return), num(v.sharpe),
                     pct(rs.ahead, 0), f"{rs.median * 100:+.1f}" if rs.median is not None else "-"])
    L += _table(["Lookback", "From", "Walk-fwd return", "Walk-fwd Sharpe", "VTI return", "VTI Sharpe", "5y windows ahead of VTI", "Median diff (pts)"], rows) + [""]
    L += ["### Mixes the optimizer chose (the weights it used each time)", ""]
    rows = [[ym_label(d.month), f"{ym_label(d.input_first)} to {ym_label(d.input_last)}", _mix(funds, [d.weights[s] for s in funds])]
            for d in m.decisions]
    L += _table(["Held from", "Data it saw", "Mix"], rows) + [""]
    # 3 in sample
    i = st.insample
    L += ["## 3. In-sample hindsight (do not read this as a result)", "",
          f"The max-Sharpe mix over the **whole** history ({ym_label(i.first)} to {ym_label(i.last)}) was "
          f"**{_mix(funds, [i.weights[s] for s in funds])}**. Choosing it needed data from the future of every date in that history, "
          "so it could not have been chosen at the time.", ""]
    ws = m.stats[WF]
    rows = [["In-sample best mix, whole history (hindsight)", pct(i.stats_all.ann_return), num(i.stats_all.sharpe), pct(i.stats_all.worst_fall, 0)],
            [f"The same hindsight mix, {ym_label(m.first)} onward", pct(i.stats_oos.ann_return), num(i.stats_oos.sharpe), pct(i.stats_oos.worst_fall, 0)],
            [f"Walk-forward (out of sample), {ym_label(m.first)} onward", pct(ws.ann_return), num(ws.sharpe), pct(ws.worst_fall, 0)]]
    L += _table(["", "Return / yr", "Sharpe", "Worst fall"], rows) + [""]
    if i.stats_oos.sharpe is not None and ws.sharpe is not None:
        gap = i.stats_oos.sharpe - ws.sharpe
        L.append(f"Over the same months the hindsight mix's Sharpe ratio differs from the walk-forward one by {gap:+.2f}. "
                 "A hindsight mix is not guaranteed to win a given test (it is fixed, rebalanced on a schedule, and estimated with "
                 "shrinkage and weight caps), but only the walk-forward row could have been followed at the time.")
        L.append("")
    L += ["## Assumptions", ""] + [f"- {a}" for a in ASSUMPTIONS]
    L += ["- Anything chosen with hindsight is in-sample. Only section 2 says what would have happened after the choice, and even that is the past.",
          "- Nothing here places, prepares or recommends an order.", "", DISCLAIMER, ""]
    return "\n".join(L)


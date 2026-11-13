"""What-if: would a target mix have beaten a benchmark, tested honestly (issue 70, milestone M12). Read-only, local only.

Anything chosen with hindsight is in-sample, so nothing here reports one number. It reports:
  1. lump-sum rolling windows (3, 5, 10 years, every start month), mix minus benchmark, annualized, annual rebalancing and
     never-rebalanced, split by what a backtest at the choice date could see, out-of-sample, real funds vs stand-ins;
  2. a flow replay: an account's own dated deposits and withdrawals replayed at every start month in the mix and in the
     benchmark, judged by ending value (IRR on round-trip flows is unstable and is shown only when it agrees).

Everything works on monthly adjusted closes (dividends and expense ratios already inside), before tax, with no trading costs.
Pure functions; prices come in as `Series` and nothing here touches the network or the disk.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import median

from ufo.performance import metrics as M
from ufo.providers.prices import Series

DEFAULT_STANDINS = {"SCHM": "IJH", "VXUS": "EFA", "VGT": "IYW", "XBI": "IBB"}
HORIZONS = (36, 60, 120)  # months
DISCLAIMER = ("Information, not investment advice. Past performance does not predict future results; "
              "a backtest winner is not a prediction.")
ASSUMPTIONS = [
    "Before tax. Rebalancing realizes gains, which would be taxed in a taxable account; none of that is counted here.",
    "Monthly adjusted closes: dividends are reinvested and fund expense ratios are already inside the prices.",
    "No trading costs, spreads or minimums.",
    "Monthly steps. Rolling windows use completed months only; the flow replay also uses the latest price for the final partial month.",
    "Deposits are split by weight, withdrawals are taken pro rata, and the replay never rebalances.",
]
OVERLAP_NOTE = ("Windows that start a month apart overlap almost completely, so the 'ahead' shares above come from only a few "
                "independent periods. They are not odds.")


# ---------- months and prices ----------

def ym(d: date) -> int:
    return d.year * 12 + d.month - 1


def ym_label(m: int) -> str:
    return f"{m // 12}-{m % 12 + 1:02d}"


def parse_ym(text: str) -> int:
    try:
        y, m = text.strip().split("-")
        if not 1 <= int(m) <= 12:
            raise ValueError
        return int(y) * 12 + int(m) - 1
    except ValueError:
        raise ValueError(f"'{text}' is not a month; use YYYY-MM.") from None


def parse_mix(text: str) -> dict[str, float]:
    """'IVV=24,IWM=24' -> weights that sum to 1."""
    raw: dict[str, float] = {}
    for part in text.split(","):
        sym, eq, w = part.partition("=")
        sym = sym.strip().upper()
        if not sym:
            continue
        try:
            wt = float(w) if eq else 1.0
        except ValueError:
            raise ValueError(f"'{part.strip()}' is not SYMBOL=WEIGHT.") from None
        if wt <= 0:
            raise ValueError(f"The weight for {sym} must be above zero.")
        raw[sym] = raw.get(sym, 0.0) + wt
    if not raw:
        raise ValueError("The mix is empty. Give it as IVV=24,IWM=24,...")
    total = sum(raw.values())
    return {s: w / total for s, w in raw.items()}


def parse_standins(specs: list[str]) -> dict[str, str]:
    out = dict(DEFAULT_STANDINS)
    for s in specs:
        a, eq, b = s.partition("=")
        if not eq or not a.strip() or not b.strip():
            raise ValueError(f"'{s}' is not FUND=STANDIN.")
        out[a.strip().upper()] = b.strip().upper()
    return out


def monthly(series: Series) -> dict[int, float]:
    """Last adjusted close in each calendar month."""
    out: dict[int, float] = {}
    for p in sorted(series.points, key=lambda p: p.day):
        out[ym(p.day)] = p.value
    return out


@dataclass
class Panel:
    """Aligned monthly prices for every symbol over months first..last (inclusive)."""
    first: int
    last: int  # last month with a price (may be partial)
    complete_last: int  # last full month
    prices: dict[str, list[float]]
    real_first: dict[str, int]  # first month each symbol really traded
    standins: dict[str, str] = field(default_factory=dict)  # symbol -> stand-in used before it existed

    @property
    def real_start(self) -> int:
        """First month where every symbol is a real fund."""
        return max(self.real_first.values())

    def at(self, sym: str, m: int) -> float:
        return self.prices[sym][m - self.first]


def build_panel(series: dict[str, Series], symbols: list[str], standins: dict[str, str], start: int | None = None,
                today: date | None = None) -> Panel:
    """Splice stand-ins before a fund existed (scaled to match at the fund's first month). The panel starts at the
    requested month or, if later, the earliest month every symbol (or its stand-in) has a price."""
    syms = list(dict.fromkeys(symbols))
    mon = {s: monthly(series[s]) for s in syms if s in series and series[s].points}
    missing = [s for s in syms if s not in mon]
    if missing:
        raise ValueError(f"No prices for {', '.join(missing)}.")
    real_first = {s: min(mon[s]) for s in syms}
    ext_first = dict(real_first)
    for s in syms:
        st = standins.get(s)
        if st and st != s and st in series and series[st].points:
            mon.setdefault(st, monthly(series[st]))
            ext_first[s] = min(real_first[s], min(mon[st]))
    first = max(([start] if start is not None else []) + list(ext_first.values()))
    last = min(max(mon[s]) for s in syms)
    if last <= first:
        raise ValueError("Not enough overlapping price history for these funds.")

    def ffilled(name: str) -> dict[int, float]:
        m, out, cur = mon[name], {}, None
        lo = min(m)
        for t in range(lo, last + 1):
            cur = m.get(t, cur)
            out[t] = cur
        return out

    prices: dict[str, list[float]] = {}
    used: dict[str, str] = {}
    for s in syms:
        real = ffilled(s)
        if first >= real_first[s]:
            prices[s] = [real[t] for t in range(first, last + 1)]
            continue
        st = standins[s]
        sub = ffilled(st)
        ratio = real[real_first[s]] / sub[real_first[s]]
        prices[s] = [sub[t] * ratio if t < real_first[s] else real[t] for t in range(first, last + 1)]
        used[s] = st
    t = today or date.today()
    partial = last == ym(t)
    return Panel(first=first, last=last, complete_last=last - 1 if partial else last, prices=prices,
                 real_first=real_first, standins=used)


# ---------- statistics ----------

def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    pos = (len(v) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


@dataclass
class Summary:
    n: int
    ahead: float | None  # share of cases the mix was ahead
    median: float | None
    p10: float | None
    p90: float | None


def summarize(diffs: list[float]) -> Summary:
    if not diffs:
        return Summary(0, None, None, None, None)
    return Summary(len(diffs), sum(1 for d in diffs if d > 0) / len(diffs), median(diffs),
                   percentile(diffs, 0.10), percentile(diffs, 0.90))


# ---------- 1. lump-sum rolling windows ----------

@dataclass
class Window:
    start: int
    end: int
    diff: float  # mix minus benchmark, annualized
    real_only: bool  # no stand-in data inside the window


def growth(panel: Panel, weights: dict[str, float], s: int, e: int, rebalance: bool) -> float:
    """Growth of 1 from month s to month e; annual rebalancing back to the weights, or buy and hold."""
    v = dict(weights)
    for t in range(s + 1, e + 1):
        for sym in v:
            v[sym] *= panel.at(sym, t) / panel.at(sym, t - 1)
        if rebalance and (t - s) % 12 == 0 and t < e:
            tot = sum(v.values())
            v = {sym: tot * w for sym, w in weights.items()}
    return sum(v.values())


def rolling_windows(panel: Panel, weights: dict[str, float], bench: str, horizon: int, rebalance: bool) -> list[Window]:
    out = []
    for s in range(panel.first, panel.complete_last - horizon + 1):
        e = s + horizon
        gm = growth(panel, weights, s, e, rebalance)
        gb = growth(panel, {bench: 1.0}, s, e, False)
        yrs = horizon / 12
        out.append(Window(s, e, gm ** (1 / yrs) - gb ** (1 / yrs), s >= panel.real_start))
    return out


def window_subsets(wins: list[Window], choice: int | None) -> dict[str, list[float]]:
    subs = {"all windows": [w.diff for w in wins]}
    if choice is not None:
        subs["ended by choice date (visible then)"] = [w.diff for w in wins if w.end <= choice]
        subs["started at/after choice date (out-of-sample)"] = [w.diff for w in wins if w.start >= choice]
    subs["real funds only"] = [w.diff for w in wins if w.real_only]
    if choice is not None:
        subs["real funds only, ended by choice date"] = [w.diff for w in wins if w.real_only and w.end <= choice]
    subs["with stand-ins"] = [w.diff for w in wins if not w.real_only]
    return subs


# ---------- 2. flow replay ----------

def month_schedule(flows: list[tuple[date, float]]) -> tuple[dict[int, float], int]:
    """Net flow per month offset from the first flow's month, and that first month."""
    first = ym(min(d for d, _ in flows))
    sched: dict[int, float] = {}
    for d, a in flows:
        sched[ym(d) - first] = sched.get(ym(d) - first, 0.0) + a
    return sched, first


def replay(panel: Panel, weights: dict[str, float], sched: dict[int, float], s: int, end_offset: int) -> float | None:
    """Ending value of the schedule started at month s, or None when a withdrawal exceeds the balance."""
    units = {sym: 0.0 for sym in weights}
    for k in range(end_offset + 1):
        amt = sched.get(k, 0.0)
        if not amt:
            continue
        t = s + k
        if amt > 0:
            for sym, w in weights.items():
                units[sym] += w * amt / panel.at(sym, t)
        else:
            bal = sum(u * panel.at(sym, t) for sym, u in units.items())
            if -amt > bal + 1e-9:
                return None
            keep = 1 - (-amt / bal)
            units = {sym: u * keep for sym, u in units.items()}
    return sum(u * panel.at(sym, s + end_offset) for sym, u in units.items())


def trusted_irr(flows: list[tuple[date, float]], end: date, mix_value: float, bench_value: float) -> tuple[float, float] | None:
    """(mix IRR, benchmark IRR) only when both roots are bracketed and their difference has the sign of the
    ending-value difference; otherwise None and the ending value alone is the judge."""
    mi = M.xirr(M.investor_flows(flows, end, mix_value))
    bi = M.xirr(M.investor_flows(flows, end, bench_value))
    if mi is None or bi is None:
        return None
    dv, di = mix_value - bench_value, mi - bi
    if dv == 0 or di == 0 or (dv > 0) != (di > 0):
        return None
    return mi, bi


@dataclass
class ReplayResult:
    diffs: list[tuple[int, float]]  # (start month, mix ending value / benchmark ending value - 1)
    excluded: int  # starts dropped because a withdrawal exceeded the balance
    actual_start: int | None  # the account's real first-flow month, when the panel covers it
    actual_diff: float | None
    actual_percentile: float | None  # share of valid starts the actual start beat or tied (0-100)
    actual_mix_value: float | None = None
    actual_bench_value: float | None = None
    irr: tuple[float, float] | None = None
    irr_note: str = ""
    end_offset: int = 0  # months from a start to the end of the replay


def flow_replay(panel: Panel, weights: dict[str, float], bench: str, flows: list[tuple[date, float]], end: date) -> ReplayResult:
    sched, first_month = month_schedule(flows)
    end_offset = max(ym(end) - first_month, max(sched))
    bw = {bench: 1.0}
    diffs, excluded = [], 0
    vals: dict[int, tuple[float, float]] = {}
    for s in range(panel.first, panel.last - end_offset + 1):
        mv, bv = replay(panel, weights, sched, s, end_offset), replay(panel, bw, sched, s, end_offset)
        if mv is None or bv is None or bv <= 0:
            excluded += 1
            continue
        vals[s] = (mv, bv)
        diffs.append((s, mv / bv - 1))
    res = ReplayResult(diffs=diffs, excluded=excluded, actual_start=None, actual_diff=None, actual_percentile=None,
                       end_offset=end_offset)
    if first_month in vals:
        mv, bv = vals[first_month]
        d = mv / bv - 1
        allv = [x for _, x in diffs]
        below = sum(1 for x in allv if x < d - 1e-12)
        equal = sum(1 for x in allv if abs(x - d) <= 1e-12)
        res.actual_start, res.actual_diff = first_month, d
        res.actual_percentile = 100 * (below + equal / 2) / len(allv)
        res.actual_mix_value, res.actual_bench_value = mv, bv
        res.irr = trusted_irr(flows, end, mv, bv)
        res.irr_note = "" if res.irr else "IRR not shown: the flows have no single bracketed root or it disagrees with the ending value."
    return res


# ---------- running and rendering ----------

@dataclass
class WhatIf:
    mix: dict[str, float]
    benchmark: str
    panel: Panel
    choice: int | None
    rolling: dict[bool, dict[int, dict[str, Summary]]]  # rebalance? -> horizon -> subset -> summary
    replay: ReplayResult | None = None
    replay_subsets: dict[str, Summary] = field(default_factory=dict)
    account_label: str = ""
    replay_note: str = ""


def run_whatif(panel: Panel, mix: dict[str, float], bench: str, choice: int | None = None,
               flows: list[tuple[date, float]] | None = None, end: date | None = None, account_label: str = "") -> WhatIf:
    rolling: dict[bool, dict[int, dict[str, Summary]]] = {}
    for rebalance in (True, False):
        rolling[rebalance] = {}
        for h in HORIZONS:
            if panel.complete_last - panel.first < h:
                continue
            subs = window_subsets(rolling_windows(panel, mix, bench, h, rebalance), choice)
            rolling[rebalance][h] = {k: summarize(v) for k, v in subs.items()}
    out = WhatIf(mix=mix, benchmark=bench, panel=panel, choice=choice, rolling=rolling, account_label=account_label)
    if flows:
        out.replay = flow_replay(panel, mix, bench, flows, end or max(d for d, _ in flows))
        rs = out.replay.diffs
        out.replay_subsets = {"all starts": summarize([d for _, d in rs]),
                              "real funds only": summarize([d for s, d in rs if s >= panel.real_start])}
        if choice is not None:
            out.replay_subsets["real funds only, ended by choice date"] = summarize(
                [d for s, d in rs if s >= panel.real_start and s + out.replay.end_offset <= choice])
            out.replay_subsets["starting at/after choice date (out-of-sample)"] = summarize([d for s, d in rs if s >= choice])
    return out


def _pct(x: float | None, signed: bool = True) -> str:
    return "-" if x is None else (f"{x * 100:+.1f}" if signed else f"{x * 100:.0f}%")


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return lines + ["| " + " | ".join(r) + " |" for r in rows]


def render_markdown(w: WhatIf, today: date | None = None) -> str:
    p = w.panel
    mix = ", ".join(f"{s} {v * 100:.1f}%" for s, v in w.mix.items())
    L = ["# What-if: would this mix have worked?", "",
         f"Mix: {mix}", f"Benchmark: {w.benchmark} (100%)",
         f"History used: {ym_label(p.first)} to {ym_label(p.last)}"
         + (f" (last full month {ym_label(p.complete_last)})" if p.complete_last != p.last else ""),
         f"Choice date: {ym_label(w.choice)}" if w.choice is not None else "Choice date: not set (no in-sample / out-of-sample split)",
         ""]
    if p.standins:
        L.append("**Stand-ins** (used before the fund existed, scaled to match at its first month): "
                 + "; ".join(f"{s} <- {st} (before {ym_label(p.real_first[s])})" for s, st in p.standins.items()))
    else:
        L.append("Stand-ins: none needed; every fund is real for the whole history.")
    L += [f"Every window is real funds only from {ym_label(p.real_start)}.", ""]
    L += ["## 1. Lump-sum rolling windows", "",
          "One lump sum at each start month, held for the horizon. Figures are mix minus benchmark in percentage points per year; "
          "'ahead' is the share of windows the mix finished ahead.", ""]
    for rebalance, name in ((True, "Annual rebalancing"), (False, "Never rebalanced (sensitivity)")):
        rows = []
        for h, subs in w.rolling[rebalance].items():
            for sub, s in subs.items():
                rows.append([f"{h // 12}y", sub, str(s.n), _pct(s.ahead, False), _pct(s.median), _pct(s.p10), _pct(s.p90)])
        L += [f"### {name}", ""] + _table(["Horizon", "Windows", "n", "Ahead", "Median", "10th pct", "90th pct"], rows) + [""]
    L += [f"*{OVERLAP_NOTE}*", ""]
    if w.replay is not None:
        r = w.replay
        L += ["## 2. Replay of your cash flows", "",
              f"Account: {w.account_label or 'selected account'}. Its dated deposits and withdrawals, as month offsets, replayed from every "
              "start month into the mix and into the benchmark. Judged by **ending value** (mix vs benchmark, %), not IRR.", ""]
        rows = [[k, str(s.n), _pct(s.ahead, False), _pct(s.median), _pct(s.p10), _pct(s.p90)] for k, s in w.replay_subsets.items()]
        L += _table(["Starts", "n", "Mix ahead", "Median", "10th pct", "90th pct"], rows) + [""]
        L.append(f"Starts excluded because a withdrawal exceeded the balance: {r.excluded}.")
        if r.actual_start is not None:
            L.append(f"Your actual start ({ym_label(r.actual_start)}): the mix would have ended {_pct(r.actual_diff)}% "
                     f"vs the benchmark, better than {r.actual_percentile:.0f}% of all valid start months.")
            if r.irr:
                L.append(f"IRR (bracketed, agrees with ending values): mix {r.irr[0] * 100:.1f}% vs benchmark {r.irr[1] * 100:.1f}%.")
            else:
                L.append(r.irr_note)
        else:
            L.append("Your actual start month is outside the price history used here, so there is no percentile for it.")
        L += ["", f"*{OVERLAP_NOTE}*", ""]
    L += ["## Assumptions", ""] + [f"- {a}" for a in ASSUMPTIONS]
    L += ["- Anything chosen with hindsight is in-sample. Only the out-of-sample rows say what happened after the choice."]
    L += ["", DISCLAIMER, ""]
    return "\n".join(L)

"""The browser page (site/js/calc.mjs) must give the same numbers as the Python metrics for buy-and-hold with deposits.

All prices are invented (a seeded random walk). Skipped when node is not installed.
"""
import json
import math
import random
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from ufo.performance import metrics as M
from ufo.providers.prices import Point, Series

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _month_ends(n: int) -> list[date]:
    out, y, m = [], 2020, 12
    for _ in range(n):
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        out.append(date.fromordinal(nxt.toordinal() - 1))
        y, m = nxt.year, nxt.month
    return out


def _walk(seed: int, n: int, drift: float, vol: float) -> list[float]:
    rng = random.Random(seed)
    px, out = 100.0, []
    for _ in range(n):
        out.append(round(px, 6))
        px *= 1 + rng.gauss(drift, vol)
    return out


def _python_numbers(days, prices, weights, initial, monthly, rf):
    series = {s: Series(symbol=s, points=[Point(day=d, value=v) for d, v in zip(days, vals)]) for s, vals in prices.items()}
    external = [(days[0], initial)] + [(d, monthly) for d in days[1:] if monthly > 0]
    steps = M.basket_units(external, weights, series)
    values = [M.basket_value(steps, series, d) for d in days]
    mr = M.monthly_returns(days, values, sorted(external))
    rets = [m.ret for m in mr[1:]]
    rfm = (1 + rf / 100) ** (1 / 12) - 1
    growth = M.growth_index(rets)
    return {
        "endValue": values[-1],
        "annualReturn": M.annualize(growth[-1], len(rets)),
        "volatility": M.volatility(rets),
        "sharpe": M.sharpe([r - rfm for r in rets]),
        "maxDrawdown": M.max_drawdown(growth),
        "values": values,
    }


@pytest.mark.parametrize("monthly", [0, 250])
def test_buy_and_hold_matches_python(monthly):
    n = 61
    days = _month_ends(n)
    prices = {"AAA": _walk(1, n, 0.008, 0.04), "BBB": _walk(2, n, 0.004, 0.02), "CCC": _walk(3, n, 0.006, 0.05)}
    weights = {"AAA": 50.0, "BBB": 30.0, "CCC": 20.0}
    payload = {"prices": prices, "weights": weights, "initial": 10000, "monthly": monthly, "rf": 3.0}
    out = subprocess.run(["node", str(ROOT / "tests/site/parity_run.mjs")], input=json.dumps(payload), capture_output=True,
                         text=True, check=True).stdout
    js = json.loads(out)
    py = _python_numbers(days, prices, weights, 10000, monthly, 3.0)
    for key in ("endValue", "annualReturn", "volatility", "sharpe", "maxDrawdown"):
        assert js[key] == pytest.approx(py[key], rel=1e-9, abs=1e-12), key
    assert all(math.isclose(a, b, rel_tol=1e-9) for a, b in zip(js["values"], py["values"]))

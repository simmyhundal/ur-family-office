"""Metrics with known answers. All numbers are invented."""
import math
from datetime import date, timedelta

import pytest

from ufo.performance import metrics as M
from ufo.providers.prices import Point, Series


def _series(sym, start, daily_growth, days, base=100.0):
    pts = [Point(day=start + timedelta(days=i), value=base * (1 + daily_growth) ** i, close=base * (1 + daily_growth) ** i)
           for i in range(days)]
    return Series(symbol=sym, points=pts)


def test_xirr_one_year_ten_percent():
    r = M.xirr([(date(2020, 1, 1), -1000.0), (date(2021, 1, 1), 1100.0)])  # 366 days in a leap year
    assert r == pytest.approx(0.10, abs=0.002)


def test_xirr_with_a_withdrawal_in_the_middle():
    # put in 1000, take out 500 after a year, end with 660 a year later: (500/1.1 + 660/1.1^2) = 1000 -> r = 10%
    r = M.xirr([(date(2020, 1, 1), -1000.0), (date(2021, 1, 1), 500.0), (date(2022, 1, 1), 660.0)])
    assert r == pytest.approx(0.10, abs=0.003)


def test_xirr_needs_both_signs():
    assert M.xirr([(date(2020, 1, 1), -1000.0)]) is None
    assert M.xirr([(date(2020, 1, 1), -1000.0), (date(2021, 1, 1), -5.0)]) is None


def test_investor_flows_flip_signs_and_add_the_ending_value():
    f = M.investor_flows([(date(2020, 1, 1), 1000.0), (date(2020, 6, 1), -200.0)], date(2021, 1, 1), 900.0)
    assert [a for _, a in f] == [-1000.0, 200.0, 900.0]


def test_index_irr_equals_the_index_return_for_a_single_deposit():
    idx = _series("IDX", date(2020, 1, 1), 0.0003, 800)
    res = M.index_counterfactual([(date(2020, 1, 1), 1000.0)], idx, date(2021, 12, 31))
    expected = (1.0003 ** (date(2021, 12, 31) - date(2020, 1, 1)).days) ** (365 / (date(2021, 12, 31) - date(2020, 1, 1)).days) - 1
    assert res.irr == pytest.approx(expected, abs=0.002)


def test_excess_irr_is_zero_when_the_account_tracks_the_index():
    idx = _series("IDX", date(2020, 1, 1), 0.0003, 800)
    end = date(2021, 12, 31)
    ext = [(date(2020, 1, 1), 1000.0), (date(2020, 7, 1), 500.0)]
    twin = M.index_counterfactual(ext, idx, end)
    rep = M.analyze(ext, [date(2020, 1, 31), date(2020, 2, 29)], [1.0, 1.0], idx, _series("RF", date(2020, 1, 1), 0.0, 800), end, twin.terminal_value)
    assert rep.excess_irr == pytest.approx(0.0, abs=1e-6) and rep.pme == pytest.approx(1.0, abs=1e-6)


def test_index_that_cannot_support_the_withdrawals_is_explained():
    idx = _series("IDX", date(2020, 1, 1), 0.0, 400)
    res = M.index_counterfactual([(date(2020, 1, 1), 100.0), (date(2020, 6, 1), -500.0)], idx, date(2020, 12, 1))
    assert res.irr is None and "withdrawals" in res.note


def test_monthly_return_without_flows():
    r = M.monthly_returns([date(2020, 1, 31), date(2020, 2, 29)], [100.0, 110.0], [])
    assert r[0].ret is None and r[1].ret == pytest.approx(0.10)


def test_monthly_return_is_not_fooled_by_a_deposit():
    # 100 at the end of Jan, +50 deposited on Feb 15 (mid-month), 150 at the end of Feb: roughly no gain
    r = M.monthly_returns([date(2020, 1, 31), date(2020, 2, 29)], [100.0, 150.0], [(date(2020, 2, 15), 50.0)])
    assert abs(r[1].ret) < 1e-9


def test_growth_drawdown_and_annualize():
    g = M.growth_index([0.2, -0.25, 0.0])
    assert g == pytest.approx([1.2, 0.9, 0.9])
    assert M.max_drawdown([1.0, 1.2, 0.9, 1.0]) == pytest.approx(-0.25)
    assert M.annualize(1.21, 24) == pytest.approx(0.10)
    assert M.annualize(1.1, 6) is None  # too short to annualize


def test_sharpe_known_answer_and_guards():
    ex = [0.02, 0.0] * 6  # mean 1%, stdev ~1.04%
    assert M.sharpe(ex) == pytest.approx(0.01 / (0.0104446 ) * math.sqrt(12), rel=0.01)
    assert M.sharpe([0.01] * 12) is None  # no variation
    assert M.sharpe([0.01] * 5) is None  # too short
    assert M.sortino([0.02, -0.01] * 6) > 0


def test_beta_of_a_double_levered_index_is_two():
    b = [0.01, -0.02, 0.03, 0.0, 0.02, -0.01] * 2
    p = [2 * x for x in b]
    beta, alpha = M.beta_alpha(p, b, [0.0] * 12)
    assert beta == pytest.approx(2.0) and alpha == pytest.approx(0.0, abs=1e-9)


def test_risk_free_monthly_rate():
    rf = Series(symbol="DTB3", points=[Point(day=date(2020, 1, 2), value=12.0)])
    assert M.monthly_rf(rf, date(2020, 1, 31)) == pytest.approx(1.12 ** (1 / 12) - 1 if False else (1.12) ** (1 / 12) - 1)

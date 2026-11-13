"""Frontier, max-Sharpe and walk-forward on invented prices with known answers. No network, no real data."""
import random
from datetime import date

import pytest

from jobs import whatif_sharpe as job
from ufo.performance import frontier as F
from ufo.performance.whatif import build_panel, ym
from ufo.providers.prices import Point, PriceStore, Series


def make_series(sym, rets, first=(2000, 1)):
    y, m = first
    v, pts = 100.0, []
    for i, r in enumerate(rets):
        v *= 1 + r
        yy, mm = y + (m - 1 + i) // 12, (m - 1 + i) % 12 + 1
        pts.append(Point(day=date(yy, mm, 28), value=v))
    return Series(symbol=sym, points=pts)


def flat_rf(n=400, pct=0.0, first=(2000, 1)):
    y, m = first
    return Series(symbol="DTB3", points=[Point(day=date(y + (m - 1 + i) // 12, (m - 1 + i) % 12 + 1, 1), value=pct) for i in range(n)])


def gen(n, mu, sd, seed):
    rnd = random.Random(seed)
    return [rnd.gauss(mu, sd) for _ in range(n)]


def test_tangency_two_uncorrelated_assets_matches_closed_form():
    # excess means 0.01 and 0.005, vols 0.04 and 0.01, uncorrelated: w_i proportional to mu_i / var_i
    mu = [0.01, 0.005]
    cov = [[0.04 ** 2, 0.0], [0.0, 0.01 ** 2]]
    raw = [mu[0] / cov[0][0], mu[1] / cov[1][1]]
    expect = [x / sum(raw) for x in raw]
    w = F.max_sharpe(mu, cov, [0.0, 0.0], [1.0, 1.0])
    assert w == pytest.approx(expect, abs=2e-3)
    assert sum(w) == pytest.approx(1.0)


def test_max_weight_binds():
    mu = [0.01, 0.005]
    cov = [[0.04 ** 2, 0.0], [0.0, 0.01 ** 2]]
    w = F.max_sharpe(mu, cov, [0.0, 0.0], [0.05, 1.0])  # unconstrained answer is 11% in the first asset
    assert w[0] == pytest.approx(0.05, abs=1e-6)
    assert w[1] == pytest.approx(0.95, abs=1e-6)
    with pytest.raises(ValueError):
        F.check_bounds(2, 0.0, 0.4)  # two funds at 40% cannot reach 100%


def test_min_variance_known_answer_and_long_only():
    cov = [[0.04 ** 2, 0.0], [0.0, 0.01 ** 2]]
    w = F.min_variance(cov, [0.0, 0.0], [1.0, 1.0])
    iv = [1 / cov[0][0], 1 / cov[1][1]]
    assert w == pytest.approx([x / sum(iv) for x in iv], abs=1e-4)
    # negatively-weighted solution would exist if shorting were allowed; long-only keeps everything >= 0
    cov2 = [[0.01, 0.0099], [0.0099, 0.04]]
    assert min(F.min_variance(cov2, [0, 0], [1, 1])) >= -1e-12


def test_same_volatility_point_is_on_the_frontier_and_no_leverage():
    mu = [0.01, 0.005, 0.002]
    cov = [[0.0016, 0, 0], [0, 0.0001, 0], [0, 0, 0.0004]]
    lo, hi = [0.0] * 3, [1.0] * 3
    target = F.port_stats([0.5, 0.3, 0.2], mu, cov)[1]
    w = F.max_return_at_vol(mu, cov, lo, hi, target)
    assert F.port_stats(w, mu, cov)[1] == pytest.approx(target, rel=2e-2)
    assert F.port_stats(w, mu, cov)[0] >= F.port_stats([0.5, 0.3, 0.2], mu, cov)[0] - 1e-9
    assert sum(w) == pytest.approx(1.0) and min(w) >= -1e-12
    # above the riskiest corner it just returns the highest-return mix
    top = F.max_return_at_vol(mu, cov, lo, hi, 1.0)
    assert top[0] == pytest.approx(1.0, abs=1e-3)


def test_shrinkage_pulls_means_and_correlations_together():
    assert F.shrink_mean([0.0, 0.02]) == pytest.approx([0.005, 0.015])
    rows = [[a, a * 0.5 + b] for a, b in zip(gen(60, 0, 0.04, 1), gen(60, 0, 0.02, 2))]
    cov, delta = F.shrink_cov(rows)
    assert 0 <= delta <= F.CORR_SHRINK_MAX
    assert cov[0][1] == pytest.approx(cov[1][0])
    # with two assets the target is the sample correlation itself, so the shrunk matrix equals the sample matrix
    s = F.sample_cov(rows)
    assert cov[0][1] == pytest.approx(s[0][1])


def invented_panel(n=200):
    syms = {"AAA": gen(n, 0.010, 0.050, 11), "BBB": gen(n, 0.004, 0.012, 12), "CCC": gen(n, 0.006, 0.030, 13),
            "VTI": gen(n, 0.008, 0.045, 14), "BND": gen(n, 0.003, 0.010, 15)}
    series = {k: make_series(k, v) for k, v in syms.items()}
    panel = build_panel(series, list(syms), {}, None, date(2030, 1, 1))
    return panel


def test_walk_forward_uses_no_data_from_the_rebalance_month_or_later():
    panel = invented_panel()
    rf = flat_rf()
    dec = F.walk_forward(panel, ["AAA", "BBB", "CCC"], rf, 60, 12, 0.0, 1.0)
    assert dec
    for d in dec:
        assert d.input_last < d.month  # the optimizer's inputs end before the month the mix is first held
        assert d.input_last - d.input_first + 1 == 60
        assert d.input_first >= panel.first + 1
        assert sum(d.weights.values()) == pytest.approx(1.0)


def test_walk_forward_decisions_do_not_change_when_the_future_is_scrambled():
    base = invented_panel(150)
    rf = flat_rf()
    funds = ["AAA", "BBB", "CCC"]
    dec = F.walk_forward(base, funds, rf, 60, 12, 0.0, 1.0)
    cut = dec[2].month  # scramble every price from this month on; earlier decisions must not move
    alt = invented_panel(150)
    rnd = random.Random(99)
    for s in alt.prices:
        for t in range(cut - alt.first, len(alt.prices[s])):
            alt.prices[s][t] = alt.prices[s][t - 1] * (1 + rnd.gauss(0.05, 0.1))
    dec2 = F.walk_forward(alt, funds, rf, 60, 12, 0.0, 1.0)
    for a, b in zip(dec[:3], dec2[:3]):
        assert a.month == b.month
        for s in funds:
            assert a.weights[s] == pytest.approx(b.weights[s], abs=1e-9)


def test_simulate_drift_and_reset():
    panel = invented_panel(40)
    plan = [(panel.first + 5, {"AAA": 1.0}), (panel.first + 11, {"BBB": 1.0})]
    r = F.simulate(panel, plan, panel.first + 12)
    assert len(r) == 8
    assert r[0] == pytest.approx(panel.at("AAA", panel.first + 5) / panel.at("AAA", panel.first + 4) - 1)
    assert r[-1] == pytest.approx(panel.at("BBB", panel.first + 12) / panel.at("BBB", panel.first + 11) - 1)


def test_study_runs_and_report_has_required_parts(tmp_path):
    panel = invented_panel(150)
    rf = flat_rf()
    st = F.run_study(panel, ["AAA", "BBB", "CCC", "VTI", "BND"], rf, lookback=60, rebalance=12, lo=0.0, hi=0.6,
                     current={"AAA": 0.5, "CCC": 0.5}, sens_lookbacks=(36, 60))
    text = F.render_markdown(st)
    assert "Information, not investment advice. Past performance does not predict future results; a backtest winner is not a prediction." in text
    assert "out of sample" in text and "hindsight" in text and "never uses leverage" in text
    assert "Current mix" in text and "60/40" in text and "Equal weight" in text
    assert st.main.stats["Walk-forward max-Sharpe"].months == st.main.stats["VTI"].months


def test_job_writes_private_report(tmp_path):
    import csv
    cache = tmp_path / "prices"
    cache.mkdir()
    for k, seed, mu, sd in [("AAA", 1, .01, .05), ("BBB", 2, .004, .012), ("VTI", 3, .008, .045), ("BND", 4, .003, .01)]:
        rets = gen(150, mu, sd, seed)
        s = make_series(k, rets)
        with open(cache / f"{k}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "adj_close"])
            w.writerows((p.day.isoformat(), p.value) for p in s.points)
    rf = flat_rf(170)
    with open(cache / "DTB3.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "adj_close"])
        w.writerows((p.day.isoformat(), p.value) for p in rf.points)
    today = date(2016, 6, 1)
    store = PriceStore(cache, None, today)
    code = job.main(["--funds", "AAA,BBB,VTI,BND", "--max", "60", "--root", str(tmp_path), "--out", "out.md",
                     "--current", "AAA=1,BBB=1"], store=store, today=today)
    assert code == 0
    out = tmp_path / "out.md"
    assert out.exists() and (out.stat().st_mode & 0o777) == 0o600
    assert "Walk-forward" in out.read_text()


def test_ym_import_is_used():
    assert ym(date(2020, 1, 1)) == 2020 * 12

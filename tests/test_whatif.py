"""What-if backtest on invented prices and invented flows. No network, no real data."""
from datetime import date

import pytest

from jobs import whatif as job
from ufo.performance import whatif as W
from ufo.providers.prices import Point, PriceStore, Series


def series(sym, first_month, n, monthly_growth, base=100.0):
    """Month-end points from (year, month) first_month, n months, constant monthly growth."""
    y, m = first_month
    pts = []
    for i in range(n):
        yy, mm = y + (m - 1 + i) // 12, (m - 1 + i) % 12 + 1
        pts.append(Point(day=date(yy, mm, 28), value=base * (1 + monthly_growth) ** i))
    return Series(symbol=sym, points=pts)


def mon(y, m):
    return y * 12 + m - 1


def test_parse_mix_normalizes_and_rejects():
    assert W.parse_mix("aaa=3,BBB=1") == {"AAA": 0.75, "BBB": 0.25}
    with pytest.raises(ValueError):
        W.parse_mix("AAA=x")
    with pytest.raises(ValueError):
        W.parse_mix("")


def test_standin_flag_overrides_defaults():
    d = W.parse_standins(["SCHM=XYZ", "NEW=OLD"])
    assert d["SCHM"] == "XYZ" and d["VXUS"] == "EFA" and d["NEW"] == "OLD"


def test_standin_splice_scaled_and_named():
    # NEWF starts 2005-01 at 50; its stand-in OLDF (price 200 then) runs from 2003-01
    old = series("OLDF", (2003, 1), 60, 0.01, base=100.0)
    new = series("NEWF", (2005, 1), 36, 0.02, base=50.0)
    pan = W.build_panel({"OLDF": old, "NEWF": new}, ["NEWF"], {"NEWF": "OLDF"}, None, date(2030, 1, 1))
    assert pan.first == mon(2003, 1)
    assert pan.standins == {"NEWF": "OLDF"}
    assert pan.real_first["NEWF"] == mon(2005, 1)
    # continuous at the splice: the month before inception is the stand-in scaled by the ratio at inception
    i = mon(2005, 1) - pan.first
    ratio = 50.0 / (100.0 * 1.01 ** 24)
    assert pan.prices["NEWF"][i] == pytest.approx(50.0)
    assert pan.prices["NEWF"][i - 1] == pytest.approx(100.0 * 1.01 ** 23 * ratio)
    assert pan.real_start == mon(2005, 1)


def test_no_standin_when_start_is_after_inception_and_no_standin_means_later_start():
    old = series("OLDF", (2003, 1), 60, 0.01)
    new = series("NEWF", (2005, 1), 36, 0.02)
    pan = W.build_panel({"OLDF": old, "NEWF": new}, ["NEWF"], {"NEWF": "OLDF"}, mon(2005, 6), date(2030, 1, 1))
    assert pan.standins == {} and pan.first == mon(2005, 6)
    pan2 = W.build_panel({"NEWF": new}, ["NEWF"], {}, None, date(2030, 1, 1))
    assert pan2.first == mon(2005, 1) and pan2.standins == {}


def test_partial_final_month_excluded_from_windows():
    s = series("AAA", (2010, 1), 80, 0.01)  # ends 2016-08
    pan = W.build_panel({"AAA": s}, ["AAA"], {}, None, date(2016, 8, 15))
    assert pan.last == mon(2016, 8) and pan.complete_last == mon(2016, 7)
    wins = W.rolling_windows(pan, {"AAA": 1.0}, "AAA", 36, True)
    assert max(w.end for w in wins) == mon(2016, 7)


def test_rolling_windows_known_answer_and_rebalancing():
    a = series("AAA", (2010, 1), 100, 0.02)
    b = series("BBB", (2010, 1), 100, 0.0)
    pan = W.build_panel({"AAA": a, "BBB": b}, ["AAA", "BBB"], {}, None, date(2030, 1, 1))
    mix = {"AAA": 0.5, "BBB": 0.5}
    bh = W.rolling_windows(pan, mix, "BBB", 36, False)[0]
    rb = W.rolling_windows(pan, mix, "BBB", 36, True)[0]
    expect_bh = (0.5 * 1.02 ** 36 + 0.5) ** (1 / 3) - 1  # benchmark is flat
    assert bh.diff == pytest.approx(expect_bh)
    assert rb.diff < bh.diff  # rebalancing away from the winner trims a steadily rising fund
    assert len(W.rolling_windows(pan, mix, "BBB", 36, True)) == pan.complete_last - pan.first - 36 + 1


def test_choice_date_split_is_disjoint_by_construction():
    wins = [W.Window(s, s + 36, 0.01 * (i % 3 - 1), True) for i, s in enumerate(range(mon(2005, 1), mon(2005, 1) + 120))]
    choice = mon(2010, 1)
    subs = W.window_subsets(wins, choice)
    seen = subs["ended by choice date (visible then)"]
    oos = subs["started at/after choice date (out-of-sample)"]
    assert len(seen) == sum(1 for w in wins if w.end <= choice)
    assert len(oos) == sum(1 for w in wins if w.start >= choice)
    assert len(seen) + len(oos) < len(wins)  # windows straddling the choice date are in neither
    assert "ended by choice date (visible then)" not in W.window_subsets(wins, None)


def test_summarize():
    s = W.summarize([-0.02, 0.01, 0.02, 0.03])
    assert s.n == 4 and s.ahead == 0.75 and s.median == pytest.approx(0.015)
    assert W.summarize([]).n == 0


def pan_two(growth_a=0.01, growth_b=0.005, n=60):
    a, b = series("AAA", (2010, 1), n, growth_a), series("BBB", (2010, 1), n, growth_b)
    return W.build_panel({"AAA": a, "BBB": b}, ["AAA", "BBB"], {}, None, date(2030, 1, 1))


def test_replay_deposit_and_pro_rata_withdrawal():
    pan = pan_two()
    sched = {0: 1000.0, 12: -400.0}
    v = W.replay(pan, {"AAA": 1.0}, sched, pan.first, 24)
    bought = 1000.0 / pan.at("AAA", pan.first)
    held = bought * (1 - 400.0 / (bought * pan.at("AAA", pan.first + 12)))
    assert v == pytest.approx(held * pan.at("AAA", pan.first + 24))


def test_replay_clamps_withdrawal_larger_than_balance():
    pan = pan_two()
    assert W.replay(pan, {"AAA": 1.0}, {0: 100.0, 6: -500.0}, pan.first, 12) is None
    assert W.replay(pan, {"AAA": 1.0}, {0: 100.0, 6: -50.0}, pan.first, 12) is not None


def test_flow_replay_counts_excluded_and_actual_percentile():
    pan = pan_two(0.01, 0.005, n=60)
    flows = [(date(2010, 1, 10), 1000.0), (date(2010, 7, 10), 500.0)]
    r = W.flow_replay(pan, {"AAA": 1.0}, "BBB", flows, date(2011, 1, 20))
    assert r.excluded == 0 and r.actual_start == pan.first
    assert r.actual_diff > 0  # AAA always grows faster than BBB
    # constant growth means every start gives the same diff; the actual start ties with all, so it sits mid-distribution
    assert r.actual_percentile == pytest.approx(50.0)
    # withdrawal larger than anything deposited: every start is excluded and counted
    bad = W.flow_replay(pan, {"AAA": 1.0}, "BBB", [(date(2010, 1, 10), 100.0), (date(2010, 3, 10), -900.0)], date(2010, 6, 1))
    assert bad.diffs == [] and bad.excluded > 0 and bad.actual_percentile is None


def test_actual_start_percentile_ranks_among_starts():
    # AAA falls early then rises; later starts do better, so the first start ranks at the bottom
    pts_a = [Point(day=date(2010 + i // 12, i % 12 + 1, 28), value=v) for i, v in
             enumerate([100 - i for i in range(12)] + [88 + 5 * i for i in range(48)])]
    flat = series("BBB", (2010, 1), 60, 0.0)
    pan = W.build_panel({"AAA": Series(symbol="AAA", points=pts_a), "BBB": flat}, ["AAA", "BBB"], {}, None, date(2030, 1, 1))
    r = W.flow_replay(pan, {"AAA": 1.0}, "BBB", [(date(2010, 1, 5), 1000.0)], date(2011, 1, 5))
    assert r.actual_start == pan.first
    assert r.actual_percentile is not None and r.actual_percentile < 10


def test_actual_start_outside_panel_has_no_percentile():
    pan = pan_two()
    r = W.flow_replay(pan, {"AAA": 1.0}, "BBB", [(date(2005, 1, 5), 1000.0)], date(2005, 6, 1))
    assert r.actual_start is None and r.actual_percentile is None


def test_unbracketed_or_disagreeing_irr_falls_back_to_ending_value():
    flows = [(date(2010, 1, 1), 1000.0)]  # a single deposit
    assert W.trusted_irr(flows, date(2012, 1, 1), 0.0, 0.0) is None  # no positive flow: no root at all
    ok = W.trusted_irr(flows, date(2012, 1, 1), 1300.0, 1100.0)
    assert ok is not None and ok[0] > ok[1]
    # a mix ending value above the benchmark's but an IRR that does not agree is suppressed
    assert W.trusted_irr(flows, date(2012, 1, 1), 1300.0, 1300.0) is None


def test_round_trip_flows_report_ending_value_and_note():
    pan = pan_two()
    flows = [(date(2010, 1, 10), 1000.0), (date(2010, 12, 10), -990.0), (date(2011, 6, 10), 20.0)]
    r = W.flow_replay(pan, {"AAA": 1.0}, "BBB", flows, date(2011, 12, 20))
    assert r.actual_diff is not None
    if r.irr is None:
        assert "IRR not shown" in r.irr_note


def test_report_has_required_sections():
    a = series("AAA", (2004, 1), 160, 0.008)
    b = series("BBB", (2004, 1), 160, 0.006)
    pan = W.build_panel({"AAA": a, "BBB": b}, ["AAA", "BBB"], {}, None, date(2030, 1, 1))
    res = W.run_whatif(pan, {"AAA": 1.0}, "BBB", mon(2012, 1), [(date(2005, 1, 5), 100.0)], date(2007, 1, 5), "Test acct")
    txt = W.render_markdown(res)
    for needle in ("Annual rebalancing", "Never rebalanced", "out-of-sample", "Ahead", "ending value", "better than",
                   "not odds", "Before tax", "Information, not investment advice. Past performance does not predict future results; "
                   "a backtest winner is not a prediction."):
        assert needle in txt
    assert "3y" in txt and "10y" in txt


def test_job_writes_private_report_with_standin(tmp_path):
    class Fake:
        data = {"OLDF": series("OLDF", (2003, 1), 200, 0.007), "NEWF": series("NEWF", (2008, 1), 150, 0.009, base=40.0),
                "BNCH": series("BNCH", (2003, 1), 200, 0.006)}

        def fetch(self, symbol, start, end):
            return self.data[symbol].points

        def fetch_risk_free(self, start, end):
            return []

    store = PriceStore(tmp_path / "cache", Fake(), date(2020, 6, 1))
    code = job.main(["--mix", "NEWF=50,BNCH=50", "--benchmark", "BNCH", "--standin", "NEWF=OLDF", "--choice-date", "2015-01",
                     "--root", str(tmp_path)], store=store, today=date(2020, 6, 1))
    assert code == 0
    out = tmp_path / "exports" / "whatif.md"
    assert out.stat().st_mode & 0o777 == 0o600
    text = out.read_text()
    assert "NEWF <- OLDF" in text and "Information, not investment advice" in text


def test_real_funds_only_ended_by_choice_date_row():
    # stand-in covers 2004-2006; the fund is real from 2007-01
    old = series("OLDF", (2004, 1), 160, 0.005)
    new = series("NEWF", (2007, 1), 130, 0.007, base=40.0)
    bench = series("BNCH", (2004, 1), 160, 0.006)
    pan = W.build_panel({"OLDF": old, "NEWF": new, "BNCH": bench}, ["NEWF", "BNCH"], {"NEWF": "OLDF"}, None, date(2030, 1, 1))
    choice = mon(2013, 1)
    wins = W.rolling_windows(pan, {"NEWF": 1.0}, "BNCH", 36, True)
    subs = W.window_subsets(wins, choice)
    key = "real funds only, ended by choice date"
    want = [w.diff for w in wins if w.start >= mon(2007, 1) and w.end <= choice]
    assert want and subs[key] == want
    assert len(subs[key]) < len(subs["real funds only"]) and len(subs[key]) < len(subs["ended by choice date (visible then)"])
    assert key not in W.window_subsets(wins, None)
    res = W.run_whatif(pan, {"NEWF": 1.0}, "BNCH", choice, [(date(2005, 1, 5), 100.0), (date(2006, 1, 5), 50.0)], date(2007, 1, 5))
    r = res.replay
    n = sum(1 for s, _ in r.diffs if s >= mon(2007, 1) and s + r.end_offset <= choice)
    assert n > 0 and res.replay_subsets[key].n == n
    assert res.replay_subsets[key].n < res.replay_subsets["real funds only"].n
    assert key in W.render_markdown(res) and "shares above" in W.render_markdown(res)

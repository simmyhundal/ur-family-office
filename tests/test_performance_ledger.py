"""Ledger: shares, splits, CD accrual and maturity credits, unlisted income, snapshot anchoring. All data invented."""
from datetime import date

import pytest

from ufo.performance.ledger import Ledger, Snapshot, is_fixed_income
from ufo.providers.fidelity_history import Event, Kind
from ufo.providers.prices import Point, Series


def ev(d, kind, sym="", qty=None, px=None, amt=0.0, bal=None, desc="", seq=0):
    return Event(when=d, kind=kind, symbol=sym, quantity=qty, price=px, amount=amt, cash_balance=bal, description=desc, seq=seq)


def px(sym, rows, split=None):
    return Series(symbol=sym, points=[Point(day=d, value=v, close=v, split=split.get(d) if split else None) for d, v in rows])


D = date
BASE = [
    ev(D(2020, 1, 2), Kind.CONTRIBUTION, amt=1000.0, bal=1000.0),
    ev(D(2020, 1, 3), Kind.BUY, "ACME", 10, 50.0, -500.0, 500.0),
]
PRICES = {"ACME": px("ACME", [(D(2020, 1, 3), 50.0), (D(2020, 1, 31), 60.0), (D(2020, 2, 28), 70.0)])}


def test_value_is_shares_times_close_plus_cash():
    L = Ledger(BASE, PRICES)
    b = L.value_on(D(2020, 1, 31))
    assert (b.holdings, b.cash, b.total) == (600.0, 500.0, 1100.0)
    assert L.flows() == [(D(2020, 1, 2), 1000.0)]


def test_unpriced_symbol_is_reported_not_zeroed_silently():
    b = Ledger(BASE, {}).value_on(D(2020, 1, 31))
    assert b.unpriced == ["ACME"] and b.holdings == 0.0


def test_split_keeps_old_and_new_shares_in_the_same_units():
    prices = {"ACME": px("ACME", [(D(2020, 1, 3), 50.0 / 3), (D(2020, 1, 20), 17.0), (D(2020, 1, 31), 20.0)], split={D(2020, 1, 20): 3.0})}
    L = Ledger(BASE, prices)
    assert L.quantities(D(2020, 1, 31))["ACME"] == pytest.approx(30.0)  # 10 shares before a 3:1 split
    assert L.value_on(D(2020, 1, 31)).holdings == pytest.approx(600.0)


def test_cd_accrues_and_matures_into_cash():
    desc = "ALLY BK CD 2.00000% 01/02/2021"
    events = [
        ev(D(2020, 1, 2), Kind.CONTRIBUTION, amt=1000.0, bal=1000.0),
        ev(D(2020, 1, 2), Kind.BUY, "02007GPF4", 1000, 100.0, -1000.0, 0.0, desc, seq=1),
        ev(D(2021, 1, 15), Kind.CONTRIBUTION, amt=5.0, bal=1025.0),  # cash jumped by 1020 + 5 deposit => CD proceeds
    ]
    assert is_fixed_income("02007GPF4") and not is_fixed_income("ACME")
    L = Ledger(events, {})
    mid = L.value_on(D(2020, 7, 1))
    assert 1000.0 < mid.fixed_income < 1020.0 and mid.cash == 0.0
    after = L.value_on(D(2021, 1, 10))
    assert after.fixed_income == 0.0 and after.cash == pytest.approx(1020.0, abs=0.5)
    assert [c.why for c in L.credits] == ["maturity"]
    assert L.flows() == [(D(2020, 1, 2), 1000.0), (D(2021, 1, 15), 5.0)]  # the maturity is never a contribution


def test_unlisted_income_is_credited_internally():
    events = BASE + [ev(D(2020, 2, 10), Kind.SELL, "ACME", -5, 62.0, 310.0, 812.5)]  # cash jumped by 2.50 unlisted
    L = Ledger(events, PRICES)
    assert L.income_total() == 2.5 and L.flows() == [(D(2020, 1, 2), 1000.0)]
    assert L.cash_on(D(2020, 2, 10)) == pytest.approx(812.5)


def test_month_ends_cover_the_range():
    L = Ledger(BASE, PRICES)
    assert L.month_ends(D(2020, 1, 1), D(2020, 3, 31)) == [D(2020, 1, 31), D(2020, 2, 29), D(2020, 3, 31)]


def test_anchoring_repairs_shares_the_history_misses():
    L = Ledger(BASE, PRICES)  # rebuilt: 10 shares; Fidelity says 12 (a reinvestment the export omitted)
    L.anchor([Snapshot(when=D(2020, 2, 1), quantities={"ACME": 12.0})])
    assert L.quantities(D(2020, 1, 31))["ACME"] == pytest.approx(10 + 2 * 28 / 29, abs=0.2)  # ramps in
    assert L.quantities(D(2020, 2, 28))["ACME"] == pytest.approx(12.0)  # held flat after the last snapshot
    rows = L.reconcile([__import__("ufo.performance.ledger", fromlist=["Checkpoint"]).Checkpoint(when=D(2020, 1, 31), value=1220.0, source="x")], tolerance=0.02)
    assert rows[0]["ok"] and "anchored" in L.anchor_notes[0]


def test_reconcile_flags_a_miss():
    from ufo.performance.ledger import Checkpoint
    rows = Ledger(BASE, PRICES).reconcile([Checkpoint(when=D(2020, 1, 31), value=2000.0, source="stmt")])
    assert not rows[0]["ok"] and rows[0]["diff"] == pytest.approx(-900.0)

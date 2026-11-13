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
    desc = "EXAMPLE BK CD 3.10000% 01/02/2021"
    events = [
        ev(D(2020, 1, 2), Kind.CONTRIBUTION, amt=1000.0, bal=1000.0),
        ev(D(2020, 1, 2), Kind.BUY, "7ZQ4B91M3", 1000, 100.0, -1000.0, 0.0, desc, seq=1),
        ev(D(2021, 1, 15), Kind.CONTRIBUTION, amt=5.0, bal=1036.0),  # cash jumped by 1031 + 5 deposit => CD proceeds
    ]
    assert is_fixed_income("7ZQ4B91M3") and not is_fixed_income("ACME")
    L = Ledger(events, {})
    mid = L.value_on(D(2020, 7, 1))
    assert 1000.0 < mid.fixed_income < 1031.0 and mid.cash == 0.0
    after = L.value_on(D(2021, 1, 10))
    assert after.fixed_income == 0.0 and after.cash == pytest.approx(1031.0, abs=0.5)
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


# ---- issue 189: month-end values that overstated accounts (all rows invented) ----
from ufo.providers.fidelity_history import parse_fidelity_history  # noqa: E402

_H = ("Run Date,Action,Symbol,Description,Type,Exchange Quantity,Exchange Currency,Currency,Price,Quantity,Exchange Rate,"
      "Commission,Fees,Accrued Interest,Amount,Cash Balance,Settlement Date")


def _hist(*rows):
    return parse_fidelity_history("\n\n" + _H + "\n" + "\n".join(rows) + "\n")


@pytest.mark.parametrize("balance", ["", "0"])
def test_in_kind_shares_are_not_also_counted_as_cash(balance):
    """An IRA funded by shares moved in kind: the shares are the value; the market value on the transfer row is not cash."""
    p = _hist(f"03/01/2020,TRANSFERRED FROM VS Z00-000000-1 (Cash),ACMEX,ACME FUND,Cash,100,USD,USD,80,100,0,,,,,{balance},")
    prices = {"ACMEX": px("ACMEX", [(D(2020, 3, 1), 80.0), (D(2020, 3, 31), 81.0)])}
    L = Ledger(p.events, prices)
    L.anchor([Snapshot(when=D(2020, 4, 1), quantities={"ACMEX": 100.0})])
    b = L.value_on(D(2020, 3, 31))
    assert b.cash == 0.0 and b.holdings == pytest.approx(8100.0) and b.total == pytest.approx(8100.0)
    assert L.flows() == [(D(2020, 3, 1), 8000.0)]  # still a contribution for the return


def test_in_kind_shares_count_even_without_a_snapshot():
    p = _hist("03/01/2020,TRANSFERRED FROM VS Z00-000000-1 (Cash),ACMEX,ACME FUND,Cash,100,USD,USD,80,100,0,,,,,,")
    L = Ledger(p.events, {"ACMEX": px("ACMEX", [(D(2020, 3, 1), 80.0), (D(2020, 3, 31), 81.0)])})
    assert L.value_on(D(2020, 3, 31)).total == pytest.approx(8100.0)


CD_ROWS = [
    "01/02/2020,Electronic Funds Transfer Received (Cash),,No Description,Cash,40000,USD,USD,,40000,0,,,,40000.00,40000,",
    "01/03/2020,YOU BOUGHT EXAMPLE BK CD 3.10000% 07/03/2020 (7ZQ4B91M3) (Cash),7ZQ4B91M3,EXAMPLE BK CD 3.10000% 07/03/2020,Cash,10000,USD,USD,100,10000,0,,,,-10000.00,30000,",
    "01/03/2020,YOU BOUGHT TREASURY BILL 0.00000% 07/03/2020 (912796XX1) (Cash),912796XX1,UNITED STATES TREAS BILLS 0.000% 07/03/2020,Cash,10000,USD,USD,98,10000,0,,,,-9800.00,20200,",
    "07/03/2020,REDEMPTION PAYOUT EXAMPLE BK CD 3.10000% 07/03/2020 (7ZQ4B91M3) (Cash),7ZQ4B91M3,EXAMPLE BK CD 3.10000% 07/03/2020,Cash,-10000,USD,USD,100,-10000,0,,,,10000.00,,",
    "07/03/2020,REDEMPTION PAYOUT UNITED STATES TREAS BILLS 0.000% 07/03/2020 (912796XX1) (Cash),912796XX1,UNITED STATES TREAS BILLS 0.000% 07/03/2020,Cash,-10000,USD,USD,100,-10000,0,,,,10000.00,,",
    "07/03/2020,INTEREST EARNED EXAMPLE BK CD (7ZQ4B91M3) (Cash),7ZQ4B91M3,EXAMPLE BK CD,Cash,0,USD,USD,,0,0,,,,100.00,40300,",
]


def test_redeemed_cds_and_bills_leave_the_ledger_once():
    """Redemption rows with no Cash Balance must not be credited again when the next row's balance catches up."""
    L = Ledger(_hist(*CD_ROWS).events, {})
    after = L.value_on(D(2020, 7, 31))
    assert after.fixed_income == 0.0 and after.cash == pytest.approx(40300.0)
    assert not [c for c in L.credits if c.why == "maturity"]
    assert L.income_total() == 0.0

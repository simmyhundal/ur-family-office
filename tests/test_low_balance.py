from datetime import date

import pytest

from ufo.treasury.bills import AlertConfig, BillSpec, bills_due, occurrences
from ufo.treasury.low_balance import check_balance

TODAY = date(2026, 11, 3)


def cfg(**kw):
    base = dict(cushion=1000, next_topup=date(2026, 11, 15), bills=[
        BillSpec(name="Rent", amount=1800, due=date(2026, 11, 1), repeat="monthly"),
        BillSpec(name="Car insurance", amount=142.5, due=date(2026, 11, 9)),
        BillSpec(name="After paycheck", amount=500, due=date(2026, 11, 20)),
    ])
    base.update(kw)
    return AlertConfig(**base)


def test_low_when_balance_minus_bills_is_under_cushion():
    # Window 11/3..11/15: only car insurance counts (rent hit 11/1, next rent is 12/1, 11/20 is after top-up).
    r = check_balance(1100, cfg(), TODAY)
    assert r.status == "low" and r.bills_total == 142.5 and r.projected == 957.5 and r.shortfall == 42.5
    assert "Top up at least $42.50 before Nov 09" in r.message


def test_ok_when_enough_left():
    r = check_balance(2000, cfg(), TODAY)
    assert r.status == "ok" and r.shortfall == 0 and r.projected == 1857.5


def test_exactly_at_cushion_is_ok():
    assert check_balance(1142.5, cfg(), TODAY).status == "ok"


def test_rent_counts_when_it_is_still_ahead():
    r = check_balance(2500, cfg(), date(2026, 10, 28))  # window 10/28..11/15 includes rent 11/1 and insurance
    assert r.bills_total == 1942.5 and r.status == "low"
    assert [n for n, _, _ in r.bills] == ["Rent", "Car insurance"]


def test_bill_on_topup_day_is_included_and_after_is_not():
    c = cfg(bills=[BillSpec(name="A", amount=100, due=date(2026, 11, 15)), BillSpec(name="B", amount=100, due=date(2026, 11, 16))])
    assert check_balance(1500, c, TODAY).bills_total == 100


def test_stale_next_topup_is_flagged_not_silently_ok():
    r = check_balance(5000, cfg(next_topup=date(2026, 11, 1)), TODAY)
    assert r.status == "stale_config" and "has passed" in r.message


def test_monthly_repeat_keeps_day_and_clamps_to_month_end():
    b = BillSpec(name="Loan", amount=50, due=date(2026, 1, 31), repeat="monthly")
    assert occurrences(b, date(2026, 2, 1), date(2026, 4, 30)) == [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_bills_due_sorted_by_date():
    c = cfg(next_topup=date(2026, 12, 5))
    names = [(n, d.isoformat()) for n, _, d in bills_due(c.bills, TODAY, c.next_topup)]
    assert names == [("Car insurance", "2026-11-09"), ("After paycheck", "2026-11-20"), ("Rent", "2026-12-01")]


def test_no_bills_low_message_still_makes_sense():
    r = check_balance(500, cfg(bills=[]), TODAY)
    assert r.status == "low" and "no bills" in r.message


def test_overdrawn_projection_formats_as_negative_dollars():
    r = check_balance(1500, cfg(bills=[BillSpec(name="Rent", amount=1942.5, due=date(2026, 11, 5))]), TODAY)
    assert "leaves -$442.50" in r.message.replace("That leaves ", "leaves ")

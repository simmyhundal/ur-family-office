from datetime import date

from ufo.treasury.bills import AlertConfig, BillSpec, bills_due, occurrences
from ufo.treasury.low_balance import check_balance, round_up_to_10

TODAY = date(2026, 11, 3)


def cfg(**kw):
    base = dict(cushion=1000, next_topup=date(2026, 11, 15), joint_mask="1234", personal_mask="5678", personal_floor=1500, bills=[
        BillSpec(name="Rent", amount=1800, due=date(2026, 11, 1), repeat="monthly"),
        BillSpec(name="Car insurance", amount=142.5, due=date(2026, 11, 9)),
        BillSpec(name="After paycheck", amount=500, due=date(2026, 11, 20)),
    ])
    base.update(kw)
    return AlertConfig(**base)


def test_low_suggests_exact_shortfall_rounded_up_to_ten():
    # Window 11/3..11/15: only car insurance counts. 1100 - 142.5 = 957.5; shortfall 42.5 -> move $50.
    r = check_balance(1100, 4000, cfg(), TODAY)
    assert r.status == "low" and r.bills_total == 142.5 and r.projected == 957.5 and r.shortfall == 42.5
    assert r.transfer_amount == 50 and r.personal_covers and r.uncovered == 0
    assert "Move $50.00 from Personal to Joint before Nov 09" in r.message
    assert "Personal keeps $3,950.00" in r.message


def test_round_up_to_10():
    assert [round_up_to_10(x) for x in (42.5, 50, 50.01, 0.01, 1442.5)] == [50, 50, 60, 10, 1450]


def test_personal_floor_limits_what_can_be_sent():
    # shortfall 42.5; Personal 1520 keeps 1500, so it can send 20: partial transfer, 22.50 uncovered.
    r = check_balance(1100, 1520, cfg(), TODAY)
    assert not r.personal_covers and r.personal_sendable == 20 and r.transfer_amount == 20 and r.uncovered == 22.5
    assert "can only send $20.00" in r.message and "find $22.50 more" in r.message


def test_exact_shortfall_used_when_rounding_up_would_break_the_floor():
    # Personal can send exactly 45: covers the 42.5 shortfall but not the rounded $50, so move 42.5.
    r = check_balance(1100, 1545, cfg(), TODAY)
    assert r.personal_covers and r.transfer_amount == 42.5 and r.uncovered == 0


def test_personal_at_or_below_floor_has_nothing_to_send():
    r = check_balance(1100, 1500, cfg(), TODAY)
    assert r.transfer_amount == 0 and not r.personal_covers and r.uncovered == 42.5
    assert "nothing above its $1,500.00 minimum" in r.message
    assert check_balance(1100, 900, cfg(), TODAY).personal_sendable == 0


def test_ok_when_enough_left():
    r = check_balance(2000, 4000, cfg(), TODAY)
    assert r.status == "ok" and r.shortfall == 0 and r.transfer_amount == 0 and r.projected == 1857.5


def test_exactly_at_cushion_is_ok():
    assert check_balance(1142.5, 4000, cfg(), TODAY).status == "ok"


def test_rent_counts_when_it_is_still_ahead():
    r = check_balance(2500, 9000, cfg(), date(2026, 10, 28))  # window includes rent 11/1 and insurance
    assert r.bills_total == 1942.5 and r.status == "low"
    assert [n for n, _, _ in r.bills] == ["Rent", "Car insurance"]
    assert r.shortfall == 442.5 and r.transfer_amount == 450


def test_bill_on_topup_day_is_included_and_after_is_not():
    c = cfg(bills=[BillSpec(name="A", amount=100, due=date(2026, 11, 15)), BillSpec(name="B", amount=100, due=date(2026, 11, 16))])
    assert check_balance(1500, 4000, c, TODAY).bills_total == 100


def test_stale_next_topup_is_flagged_not_silently_ok():
    r = check_balance(5000, 4000, cfg(next_topup=date(2026, 11, 1)), TODAY)
    assert r.status == "stale_config" and "has passed" in r.message


def test_monthly_repeat_keeps_day_and_clamps_to_month_end():
    b = BillSpec(name="Loan", amount=50, due=date(2026, 1, 31), repeat="monthly")
    assert occurrences(b, date(2026, 2, 1), date(2026, 4, 30)) == [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_bills_due_sorted_by_date():
    c = cfg(next_topup=date(2026, 12, 5))
    names = [(n, d.isoformat()) for n, _, d in bills_due(c.bills, TODAY, c.next_topup)]
    assert names == [("Car insurance", "2026-11-09"), ("After paycheck", "2026-11-20"), ("Rent", "2026-12-01")]


def test_no_bills_low_message_still_makes_sense():
    r = check_balance(500, 4000, cfg(bills=[]), TODAY)
    assert r.status == "low" and "no bills" in r.message and r.transfer_amount == 500


def test_overdrawn_projection_formats_as_negative_dollars():
    r = check_balance(1500, 9000, cfg(bills=[BillSpec(name="Rent", amount=1942.5, due=date(2026, 11, 5))]), TODAY)
    assert "That leaves -$442.50" in r.message

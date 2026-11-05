from datetime import date

import pytest

from ufo.treasury import sources
from ufo.treasury.bills import AlertConfig, BillSpec, DepositSpec
from ufo.treasury.low_balance import check_balance

TODAY = date(2026, 11, 3)


def cfg(**kw):
    base = dict(cushion=1000, next_topup=date(2026, 11, 20), joint_mask="4821", personal_mask="7390", personal_floor=1500,
                bills=[BillSpec(name="Card payment", amount=1500, due=date(2026, 11, 8))])
    base.update(kw)
    return AlertConfig(**base)


def dep(due, amount=1800, **kw):
    return DepositSpec(name="Rent match", amount=amount, due=due, **kw)


def test_deposit_arriving_before_the_bill_prevents_the_alert():
    r = check_balance(1200, 9000, cfg(scheduled_deposits=[dep(date(2026, 11, 5))]), TODAY)  # 1200 + 1800 = 3000, then -1500 = 1500
    assert r.status == "ok" and r.lowest_balance == 1200 and r.projected == 1500


def test_deposit_arriving_after_the_bill_still_causes_the_dip():
    # bill on the 8th takes Joint to -300 before the deposit lands on the 10th: the end balance looks fine but the dip is real.
    r = check_balance(1200, 9000, cfg(scheduled_deposits=[dep(date(2026, 11, 10))]), TODAY)
    assert r.status == "low" and r.lowest_balance == -300 and r.lowest_on == date(2026, 11, 8) and r.projected == 1500
    assert r.shortfall == 1300 and r.transfer_amount == 1300
    assert "At its lowest (Nov 08) Joint holds -$300.00" in r.message and "Rent match $1,800.00 (Nov 10)" in r.message


def test_same_day_bills_are_counted_before_deposits():
    r = check_balance(1200, 9000, cfg(scheduled_deposits=[dep(date(2026, 11, 8))]), TODAY)
    assert r.lowest_balance == -300  # conservative: the bill clears first


def test_personal_sendable_is_reduced_by_deposits_it_funds():
    c = cfg(scheduled_deposits=[dep(date(2026, 11, 10))])
    r = check_balance(1200, 4000, c, TODAY)  # 4000 - 1500 floor - 1800 deposit = 700 sendable
    assert r.personal_sendable == 700 and not r.personal_covers and r.transfer_amount == 700 and r.uncovered == 600
    assert "Personal also funds $1,800.00 of scheduled deposits" in r.message
    r2 = check_balance(1200, 4000, cfg(scheduled_deposits=[dep(date(2026, 11, 10), from_personal=False)]), TODAY)
    assert r2.personal_sendable == 2500


def test_monthly_deposit_repeats_inside_the_window():
    c = cfg(next_topup=date(2026, 12, 20), scheduled_deposits=[dep(date(2026, 11, 2), repeat="monthly")])
    r = check_balance(5000, 9000, c, TODAY)
    assert [d.isoformat() for _, _, d in r.deposits] == ["2026-12-02"]


def test_no_deposits_behaves_like_before():
    r = check_balance(1100, 9000, cfg(bills=[BillSpec(name="B", amount=142.5, due=date(2026, 11, 9))]), TODAY)
    assert r.status == "low" and r.lowest_balance == r.projected == 957.5 and r.deposits == []


def test_lookahead_defaults_to_two_weeks_and_stale_check_only_applies_to_a_fixed_date():
    c = cfg(next_topup=None, bills=[BillSpec(name="Far", amount=5000, due=date(2026, 11, 30)), BillSpec(name="Near", amount=100, due=date(2026, 11, 10))])
    r = check_balance(3000, 9000, c, TODAY)
    assert r.window_end == date(2026, 11, 17) and r.bills_total == 100 and r.status == "ok"
    assert check_balance(3000, 9000, cfg(next_topup=date(2026, 11, 1)), TODAY).status == "stale_config"


def test_public_message_with_deposits_still_has_no_numbers_but_dates():
    import re

    r = check_balance(1200, 9000, cfg(scheduled_deposits=[dep(date(2026, 11, 10))]), TODAY)
    assert r.public_message == "UFO: Joint may run short before Nov 08. Please check your bank app."
    assert "$" not in r.public_message and all(len(x) <= 2 for x in re.findall(r"\d+", r.public_message))


# ---- rent defaults to $0 and is only detected when rent is paid from Joint
def stream(name, detailed, primary, amount=1800.0, nxt="2026-11-07"):
    return {"merchant_name": name, "is_active": True, "status": "MATURE", "frequency": "MONTHLY", "predicted_next_date": nxt,
            "last_amount": {"amount": amount}, "average_amount": {"amount": amount},
            "personal_finance_category": {"primary": primary, "detailed": detailed}}


RENT = stream("Landlord LLC", "RENT_AND_UTILITIES_RENT", "RENT_AND_UTILITIES")
NETFLIX = stream("Netflix", "ENTERTAINMENT_TV_AND_MOVIES", "ENTERTAINMENT", 15.49, "2026-11-12")


@pytest.fixture
def fake_plaid(monkeypatch):
    calls = []
    monkeypatch.setattr(sources, "get_recurring_outflows", lambda s, items, mask: calls.append(mask) or [RENT, NETFLIX])
    monkeypatch.setattr(sources, "get_credit_card_liabilities", lambda s, items, masks: [
        {"name": "Joint Card", "mask": "9999", "next_payment_due_date": "2026-11-12", "minimum_payment_amount": 40, "last_statement_balance": 2100.5}])
    return calls


def test_rent_counts_as_zero_by_default_and_recurring_detection_is_not_even_called(fake_plaid):
    bills, info, failures = sources.collect_bills(None, [], cfg(detect_bills=True, credit_card_masks=["9999"]), TODAY)
    assert [b.name for b in bills] == ["Card payment", "Joint Card …9999 payment"] and failures == []
    assert fake_plaid == [] and any("rent is not paid from Joint" in i for i in info)


def test_rent_is_detected_only_when_paid_from_joint(fake_plaid):
    bills, _, _ = sources.collect_bills(None, [], cfg(detect_bills=True, rent_paid_from_joint=True, credit_card_masks=["9999"]), TODAY)
    assert "Landlord LLC" in [b.name for b in bills] and "Netflix" not in [b.name for b in bills]  # other recurring stays off


def test_other_recurring_opt_in_still_excludes_rent_when_rent_is_not_from_joint(fake_plaid):
    bills, _, _ = sources.collect_bills(None, [], cfg(detect_bills=True, include_other_recurring=True, rent_streams=["landlord"]), TODAY)
    names = [b.name for b in bills]
    assert "Netflix" in names and "Landlord LLC" not in names


# ---- anticipate: a card payment due soon is looked at early
def test_card_payment_beyond_the_lookahead_is_still_anticipated():
    card = BillSpec(name="Card payment", amount=3000, due=date(2026, 11, 25), anticipate=True)  # 22 days out; look-ahead is 14
    c = cfg(next_topup=None, lookahead_days=14, bills=[card])
    r = check_balance(2500, 9000, c, TODAY)
    assert r.window_end == date(2026, 11, 25) and r.status == "low" and r.bills_total == 3000 and r.shortfall == 1500


def test_ordinary_bills_beyond_the_lookahead_are_still_ignored():
    far = BillSpec(name="Far bill", amount=3000, due=date(2026, 11, 25))
    r = check_balance(2500, 9000, cfg(next_topup=None, lookahead_days=14, bills=[far]), TODAY)
    assert r.status == "ok" and r.bills_total == 0


def test_a_card_payment_more_than_30_days_out_is_not_pulled_in():
    card = BillSpec(name="Card payment", amount=3000, due=date(2026, 12, 20), anticipate=True)
    assert check_balance(2500, 9000, cfg(next_topup=None, bills=[card]), TODAY).status == "ok"


def test_deposits_between_now_and_the_card_due_date_are_counted_when_anticipating():
    card = BillSpec(name="Card payment", amount=3000, due=date(2026, 11, 25), anticipate=True)
    c = cfg(next_topup=None, bills=[card], scheduled_deposits=[dep(date(2026, 11, 20), 1800)])
    r = check_balance(2500, 9000, c, TODAY)
    assert r.status == "ok" and r.lowest_balance == 1300  # 2500 + 1800 - 3000 = 1300, above the $1,000 cushion


def test_effective_window_matches_what_the_alert_uses():
    from ufo.treasury.low_balance import effective_window_end

    card = BillSpec(name="Card payment", amount=3000, due=date(2026, 11, 25), anticipate=True)
    c = cfg(next_topup=None, lookahead_days=14, bills=[card])
    assert effective_window_end(c, TODAY) == date(2026, 11, 25) == check_balance(2500, 9000, c, TODAY).window_end
    assert effective_window_end(cfg(next_topup=None, lookahead_days=14, bills=[]), TODAY) == date(2026, 11, 17)


def test_collect_bills_reports_what_it_found(fake_plaid):
    bills, info, _ = sources.collect_bills(None, [], cfg(detect_bills=True, credit_card_masks=["9999"]), TODAY)
    assert any(i.startswith("found: Joint Card …9999 payment, $2,100.50, due 2026-11-12") and "looked at early" in i for i in info)

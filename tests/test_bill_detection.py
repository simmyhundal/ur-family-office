from datetime import date

import pytest

from ufo.treasury.bills import AlertConfig, BillSpec, occurrences
from ufo.treasury.detect import classify, credit_card_bills, merge_bills, stream_to_bill, streams_to_bills
from ufo.treasury.low_balance import check_balance

TODAY = date(2026, 11, 3)


def stream(**kw):
    base = {"merchant_name": "Landlord LLC", "description": "ZELLE LANDLORD", "is_active": True, "status": "MATURE",
            "frequency": "MONTHLY", "predicted_next_date": "2026-11-07", "last_amount": {"amount": 1800.0}, "average_amount": {"amount": 1795.0},
            "personal_finance_category": {"primary": "RENT_AND_UTILITIES", "detailed": "RENT_AND_UTILITIES_RENT"}}
    base.update(kw)
    return base


def test_stream_becomes_a_bill_using_the_larger_amount():
    b, why = stream_to_bill(stream(last_amount={"amount": 1700.0}, average_amount={"amount": 1795.0}), TODAY)
    assert why is None and b.name == "Landlord LLC" and b.amount == 1795.0 and b.repeat == "monthly"
    assert b.due == date(2026, 11, 7) and b.source == "plaid"


@pytest.mark.parametrize("kw,reason", [
    ({"is_active": False}, "inactive"),
    ({"status": "TOMBSTONED"}, "stopped recurring"),
    ({"status": "EARLY_DETECTION"}, "early detection"),
    ({"personal_finance_category": {"primary": "TRANSFER_OUT", "detailed": "TRANSFER_OUT_ACCOUNT_TRANSFER"}}, "transfer"),
    ({"predicted_next_date": None}, "no predicted next date"),
    ({"personal_finance_category": {"primary": "ENTERTAINMENT", "detailed": "ENTERTAINMENT_TV_AND_MOVIES"}}, "not rent"),
    ({"personal_finance_category": {"primary": "LOAN_PAYMENTS", "detailed": "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"}}, "statement balance"),
    ({"predicted_next_date": "2026-10-01"}, "long past"),
    ({"last_amount": {"amount": 0}, "average_amount": {"amount": 0}}, "no amount"),
])
def test_non_bills_are_skipped_with_a_reason(kw, reason):
    b, why = stream_to_bill(stream(**kw), TODAY)
    assert b is None and reason in why


def test_ignore_list_and_early_detection_opt_in():
    assert stream_to_bill(stream(), TODAY, ignore=["landlord"])[0] is None
    assert stream_to_bill(stream(status="EARLY_DETECTION"), TODAY, include_early=True)[0] is not None


def test_recently_passed_prediction_counts_as_due_today():
    b, _ = stream_to_bill(stream(predicted_next_date="2026-11-01"), TODAY)  # 2 days ago: may not have posted yet
    assert b.due == TODAY


def test_rent_paid_by_zelle_counts_when_you_name_the_landlord():
    zelle = stream(personal_finance_category={"primary": "TRANSFER_OUT", "detailed": "TRANSFER_OUT_ACCOUNT_TRANSFER"})
    assert stream_to_bill(zelle, TODAY)[0] is None  # looks like a transfer
    b, _ = stream_to_bill(zelle, TODAY, rent_names=["landlord"])
    assert b is not None and classify(zelle, "Landlord LLC", ["landlord"]) == "rent"


def test_other_recurring_spend_is_a_later_stage_but_can_be_opted_in():
    netflix = stream(merchant_name="Netflix", personal_finance_category={"primary": "ENTERTAINMENT", "detailed": "ENTERTAINMENT_TV_AND_MOVIES"})
    assert stream_to_bill(netflix, TODAY)[0] is None
    assert stream_to_bill(netflix, TODAY, include_other=True)[0] is not None


def test_credit_card_bill_uses_statement_balance_and_due_date():
    cards = [{"name": "Chase Sapphire", "mask": "9999", "next_payment_due_date": "2026-11-12", "minimum_payment_amount": 40.0, "last_statement_balance": 1234.56}]
    bills, skipped = credit_card_bills(cards, TODAY)
    assert skipped == [] and bills[0].amount == 1234.56 and bills[0].due == date(2026, 11, 12) and bills[0].name == "Chase Sapphire …9999 payment"
    assert credit_card_bills(cards, TODAY, "minimum")[0][0].amount == 40.0


def test_credit_card_edge_cases():
    base = {"name": "Card", "mask": "1", "minimum_payment_amount": 0, "last_statement_balance": 0}
    assert "nothing due" in credit_card_bills([{**base, "next_payment_due_date": "2026-11-12"}], TODAY)[1][0]
    assert "no payment due date" in credit_card_bills([{**base, "last_statement_balance": 50, "next_payment_due_date": None}], TODAY)[1][0]
    overdue = credit_card_bills([{**base, "last_statement_balance": 50, "next_payment_due_date": "2026-10-20"}], TODAY)[0][0]
    assert overdue.due == TODAY  # past due: counts as due now


def test_manual_bills_win_over_detected_duplicates():
    manual = [BillSpec(name="Rent", amount=1800, due=date(2026, 11, 7), repeat="monthly")]
    detected, _ = streams_to_bills([stream(), stream(merchant_name="Netflix", last_amount={"amount": 15.49}, average_amount={"amount": 15.49},
                                                      predicted_next_date="2026-11-12", personal_finance_category={})], TODAY, include_other=True)
    merged, dropped = merge_bills(manual, detected)
    assert [b.name for b in merged] == ["Rent", "Netflix"]  # Landlord LLC dropped: same amount (+/-$1) and date (+/-3d) as Rent
    assert len(dropped) == 1 and "already covered by your manual bill 'Rent'" in dropped[0]


def test_name_match_also_dedupes():
    manual = [BillSpec(name="netflix", amount=20, due=date(2026, 11, 30))]
    detected, _ = streams_to_bills([stream(merchant_name="Netflix.com", predicted_next_date="2026-11-12")], TODAY)
    assert len(merge_bills(manual, detected)[0]) == 1


def test_weekly_biweekly_annual_repeat_inside_the_window():
    wk = BillSpec(name="Gym", amount=10, due=date(2026, 11, 4), repeat="weekly")
    bw = BillSpec(name="Cleaner", amount=60, due=date(2026, 11, 5), repeat="biweekly")
    an = BillSpec(name="Insurance", amount=900, due=date(2025, 11, 10), repeat="annually")
    assert occurrences(wk, TODAY, date(2026, 11, 20)) == [date(2026, 11, 4), date(2026, 11, 11), date(2026, 11, 18)]
    assert occurrences(bw, TODAY, date(2026, 11, 20)) == [date(2026, 11, 5), date(2026, 11, 19)]
    assert occurrences(an, TODAY, date(2026, 11, 20)) == [date(2026, 11, 10)]
    leap = BillSpec(name="Leap", amount=1, due=date(2024, 2, 29), repeat="annually")
    assert occurrences(leap, date(2026, 2, 1), date(2026, 3, 1)) == [date(2026, 2, 28)]


def test_detected_bills_feed_the_alert_end_to_end():
    cfg = AlertConfig(cushion=1000, next_topup=date(2026, 11, 15), joint_mask="1234", personal_mask="5678", personal_floor=1500)
    cfg.bills, _ = merge_bills([], streams_to_bills([stream()], TODAY)[0])
    r = check_balance(2000, 4000, cfg, TODAY)
    assert r.status == "low" and r.bills_total == 1800 and r.transfer_amount == 800

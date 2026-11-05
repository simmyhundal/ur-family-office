import re
from datetime import date

import pytest

from ufo.treasury.bills import AlertConfig, BillSpec
from ufo.treasury.low_balance import check_balance

TODAY = date(2026, 11, 3)


def cfg(**kw):
    base = dict(cushion=1000, next_topup=date(2026, 11, 15), joint_mask="4821", personal_mask="7390", personal_floor=1500,
                bills=[BillSpec(name="Rent", amount=1800, due=date(2026, 11, 7)), BillSpec(name="Chase Sapphire …9999 payment", amount=1234.56, due=date(2026, 11, 12))])
    base.update(kw)
    return AlertConfig(**base)


@pytest.mark.parametrize("joint,personal", [(1500, 4200), (1500, 1900), (1500, 1500), (123.45, 98765.43), (-50, 1500), (3000, 4200)])
def test_public_message_never_contains_money_balances_or_account_digits(joint, personal):
    r = check_balance(joint, personal, cfg(), TODAY)
    m = r.public_message
    assert "$" not in m
    digits = re.findall(r"\d+", m)
    assert all(len(d) <= 2 for d in digits), f"only day-of-month numbers are allowed, got {digits}"  # no balances, amounts or masks
    for secret in ("4821", "7390", "Rent", "Chase", "Sapphire", "9999", "1800", "1234"):
        assert secret not in m


def test_public_message_wording():
    low = check_balance(1500, 4200, cfg(), TODAY)
    assert low.public_message == "UFO: Joint may run short before Nov 07. Please check your bank app."
    weak = check_balance(1500, 1500, cfg(), TODAY)
    assert weak.public_message.endswith("Personal may not be able to cover it.")
    ok = check_balance(9000, 4200, cfg(), TODAY)
    assert ok.public_message == "UFO: Joint is covered through Nov 15." and "$" not in ok.public_message


def test_stale_config_public_message_has_no_details():
    r = check_balance(5000, 4000, cfg(next_topup=date(2026, 11, 1)), TODAY)
    assert r.status == "stale_config" and "$" not in r.public_message
    assert "Nov" not in r.public_message


def test_full_message_still_has_the_detail_locally():
    r = check_balance(1500, 4200, cfg(), TODAY)
    assert "$" in r.message and "from Personal to Joint" in r.message

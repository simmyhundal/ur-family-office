import pytest

from ufo.rebalance.engine import aggregate_by_symbol, plan_rebalance, plan_withdrawal


def by(plan):
    return {r["symbol"]: r for r in plan["rows"]}


def net(p):
    return abs(p["total_proceeds"] - p["total_buys"] - p["withdrawal"])


# Brokerage ...7693 as of 2026-10-21 (cash derived from the account balance).
P7693 = [
    {"symbol": "CASH", "quantity": 9039.87, "price": 1, "value": 9039.87, "is_cash": True},
    {"symbol": "IVV", "quantity": 22.458, "price": 770.01, "value": 17292.88},
    {"symbol": "SCHM", "quantity": 500.338, "price": 34.16, "value": 17091.54},
    {"symbol": "IWM", "quantity": 61.092, "price": 271.28, "value": 16573.03},
    {"symbol": "VGT", "quantity": 57.965, "price": 120.33, "value": 6974.92},
    {"symbol": "VXUS", "quantity": 75.223, "price": 83.29, "value": 6265.32},
    {"symbol": "XBI", "quantity": 41.348, "price": 147.86, "value": 6113.71},
]
W = {"IVV": 24, "IWM": 24, "SCHM": 24, "VGT": 10, "VXUS": 9, "XBI": 9}


def test_reproduces_the_redistribution_sheet(sheet):
    plan = plan_withdrawal(sheet["positions"], sheet["withdrawal"], targets=sheet["targets"])
    # The sheet's displayed rows sum a penny above its header, so allow 1-2 cents.
    assert abs(plan["starting_balance"] - 81692.31) <= 0.02
    assert abs(plan["ending_balance"] - 72694.86) <= 0.02
    r = by(plan)
    for s, v in sheet["expected_sell_value"].items():
        assert abs(r[s]["proceeds"] - v) <= 0.01, s
    for s, v in sheet["expected_sell_shares"].items():
        assert abs(r[s]["shares_to_sell"] - v) < 1e-3, s
    assert r["CASH"]["proceeds"] == 0.69
    assert r["VTWO"]["proceeds"] == 0
    assert abs(plan["shortfall"]) <= 0.02


def test_no_targets_trims_pro_rata(sheet):
    plan = plan_withdrawal(sheet["positions"], 8000)
    assert abs(plan["total_proceeds"] - 8000) <= 0.02
    r = by(plan)
    assert abs(r["XBI"]["proceeds"] / r["XBI"]["current_value"] - r["IVV"]["proceeds"] / r["IVV"]["current_value"]) < 1e-3


def test_underweight_positions_are_not_sold_and_others_make_up_the_difference():
    pos = [{"symbol": "A", "quantity": 10, "price": 100, "value": 1000}, {"symbol": "B", "quantity": 10, "price": 100, "value": 1000}]
    plan = plan_withdrawal(pos, 500, targets={"A": 80, "B": 20})  # ideal A=1200 is above current: frozen
    r = by(plan)
    assert r["A"]["proceeds"] == 0 and r["B"]["proceeds"] == 500
    assert plan["total_proceeds"] == 500
    assert "below target" in " ".join(plan["warnings"])


def test_whole_shares_round_down_and_report_the_shortfall():
    plan = plan_withdrawal([{"symbol": "A", "quantity": 10, "price": 300, "value": 3000}], 1000, targets={"A": 100}, whole_shares=True)
    assert plan["rows"][0]["shares_to_sell"] == 3
    assert plan["total_proceeds"] == 900 and plan["shortfall"] == 100
    assert "rounding" in " ".join(plan["warnings"])


def test_symbols_not_in_targets_are_left_untouched():
    pos = [{"symbol": "A", "quantity": 10, "price": 100, "value": 1000}, {"symbol": "B", "quantity": 10, "price": 100, "value": 1000}]
    r = by(plan_withdrawal(pos, 200, targets={"A": 100}))
    assert r["A"]["proceeds"] == 200 and r["B"]["proceeds"] == 0


def test_normalizes_targets_and_rejects_bad_input():
    pos = [{"symbol": "A", "quantity": 10, "price": 100, "value": 1000}, {"symbol": "B", "quantity": 10, "price": 100, "value": 1000}]
    assert "normalized" in plan_withdrawal(pos, 100, targets={"A": 1, "B": 1})["warnings"][0]
    with pytest.raises(ValueError, match="exceeds"):
        plan_withdrawal(pos, 5000)
    with pytest.raises(ValueError, match="positive"):
        plan_withdrawal(pos, -1)
    with pytest.raises(ValueError, match="negative"):
        plan_withdrawal(pos, 10, targets={"A": -5, "B": 105})


def test_aggregate_by_symbol_merges_accounts_and_cash():
    agg = aggregate_by_symbol([
        {"symbol": "IVV", "quantity": 1, "price": 700, "value": 700},
        {"symbol": "IVV", "quantity": 2, "price": 700, "value": 1400},
        {"symbol": "USD", "is_cash": True, "quantity": 5, "price": 1, "value": 5},
        {"symbol": "FDRXX", "is_cash": True, "quantity": 10, "price": 1, "value": 10},
    ])
    assert [(p["symbol"], p["quantity"], p["value"]) for p in agg] == [("IVV", 3, 2100), ("CASH", 15, 15)]


# ---------------------------------------------------------------- buys


def test_auto_cash_covers_withdrawal_and_leftover_buys_under_target_etfs_nothing_sold():
    plan = plan_rebalance(P7693, 8826.8, targets=W)
    assert plan["mode"] == "buy_only"
    r = by(plan)
    for s in ("IVV", "SCHM"):  # over target: untouched
        assert r[s]["proceeds"] + r[s]["buy_amount"] == 0
    assert all(x["symbol"] == "CASH" or x["proceeds"] == 0 for x in plan["rows"]), "nothing sold"
    assert r["IWM"]["buy_amount"] > r["XBI"]["buy_amount"] > r["VXUS"]["buy_amount"] > r["VGT"]["buy_amount"]  # bigger gap, bigger buy
    assert abs(plan["total_buys"] - 213.07) <= 0.02
    assert net(plan) <= 0.03
    assert plan["cash_after"] <= 0.02


def test_buy_only_with_whole_shares_buys_nothing_and_says_so():
    plan = plan_rebalance(P7693, 8826.8, targets=W, whole_shares=True)
    assert plan["total_buys"] == 0 and plan["cash_after"] == 213.07
    assert "not deployed" in " ".join(plan["warnings"])


def test_buy_only_without_targets_deploys_leftover_pro_rata():
    plan = plan_rebalance(P7693, 8000, mode="buy_only")
    assert net(plan) <= 0.03 and plan["total_buys"] > 0


def test_buy_only_refuses_when_cash_is_short_and_auto_falls_back_to_cash_plus_sells():
    with pytest.raises(ValueError, match="does not cover"):
        plan_rebalance(P7693, 12000, targets=W, mode="buy_only")
    plan = plan_rebalance(P7693, 12000, targets=W)
    assert plan["mode"] == "cash_then_sell"
    assert by(plan)["CASH"]["proceeds"] == 9039.87
    assert net(plan) <= 0.03 and plan["total_buys"] == 0


def test_full_mode_hits_targets_sells_overweight_buys_underweight():
    plan = plan_rebalance(P7693, 8826.8, targets={**W, "CASH": 0}, mode="full")
    r = by(plan)
    assert r["IVV"]["proceeds"] > 0 and r["XBI"]["buy_amount"] > 0
    assert net(plan) <= 0.03
    assert abs(r["IVV"]["post_pct"] - 24) < 0.05 and abs(r["XBI"]["post_pct"] - 9) < 0.05


def test_full_mode_whole_shares_never_sends_cash_negative():
    plan = plan_rebalance(P7693, 8826.8, targets=W, mode="full", whole_shares=True)
    assert plan["cash_after"] >= -0.005


def test_sell_only_mode_reports_zero_buys():
    plan = plan_rebalance(P7693, 3000, targets=W, mode="sell_only")
    assert plan["total_buys"] == 0 and abs(plan["total_proceeds"] - 3000) <= 0.02

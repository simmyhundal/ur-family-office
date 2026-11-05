import pytest

from ufo.providers.fidelity_csv import parse_fidelity_positions, parse_number
from ufo.rebalance.plan import plan_from_holdings

SAMPLE = (
    "﻿Account Number,Account Name,Symbol,Description,Quantity,Last Price,Last Price Change,Current Value,"
    "Today's Gain/Loss Dollar,Today's Gain/Loss Percent,Total Gain/Loss Dollar,Total Gain/Loss Percent,"
    "Percent Of Account,Cost Basis Total,Average Cost Basis,Type\r\n"
    'Z07917693,"Individual - TOD",SPAXX**,"HELD IN MONEY MARKET",,,,$9039.87,,,,,11.39%,,,Cash\r\n'
    'Z07917693,"Individual - TOD",IVV,"ISHARES CORE S&P 500 ETF",22.458,$771.50,+$1.49,"$17,326.34",+$33.46,+0.19%,+$1000.00,+6.1%,21.8%,"$16,326.34",$727.00,Cash\r\n'
    'Z19889154,"Individual - TOD",CLOV,"CLOVER HEALTH, INC",125,$4.50,-$0.04,$562.50,-$5.00,-0.88%,--,--,11%,--,--,Cash\r\n'
    "Z19889154,\"Individual - TOD\",Pending Activity,,,,,$-25.00,,,,,,,,\r\n"
    'Z19889154,"Individual - TOD",SPAXX**,"HELD IN MONEY MARKET",,,,$882.68,,,,,17%,,,Cash\r\n'
    "\r\n"
    '"The data and information in this spreadsheet is provided to you solely for your use."\r\n'
    '"Date downloaded Oct-21-2026 8:05 a.m ET"\r\n'
)


def test_numbers():
    assert parse_number("$1,234.50") == 1234.5
    assert parse_number("(12.00)") == -12
    assert parse_number("--") is None and parse_number("") is None


def test_fidelity_positions_export_to_holdings():
    holdings, warnings = parse_fidelity_positions(SAMPLE)
    assert len(holdings) == 4
    ivv = next(h for h in holdings if h["symbol"] == "IVV")
    assert (ivv["account_mask"], ivv["quantity"], ivv["price"], ivv["value"], ivv["cost_basis"]) == ("7693", 22.458, 771.5, 17326.34, 16326.34)
    cash = [(h["symbol"], h["account_mask"], h["value"], h["price"]) for h in holdings if h["is_cash"]]
    assert cash == [("CASH", "7693", 9039.87, 1.0), ("CASH", "9154", 882.68, 1.0)]
    assert next(h for h in holdings if h["symbol"] == "CLOV")["cost_basis"] is None
    assert "Pending activity" in " ".join(warnings)


def test_type_column_is_account_type_not_security_type():
    holdings, _ = parse_fidelity_positions(SAMPLE)
    assert [h["symbol"] for h in holdings if not h["is_cash"]] == ["IVV", "CLOV"]  # rows marked Type=Cash are still stocks


def test_rejects_non_fidelity_files():
    with pytest.raises(ValueError, match="header row"):
        parse_fidelity_positions("foo,bar\n1,2")


def test_x_from_154_all_cash_and_10x_from_693_in_one_call():
    holdings, _ = parse_fidelity_positions(SAMPLE)
    out = plan_from_holdings(holdings, {"base_all_cash_of": "154", "withdrawals": [
        {"account_mask": "154", "multiple": 1}, {"account_mask": "693", "multiple": 10}]})
    assert len(out["plans"]) == 2
    assert out["plans"][0]["withdrawal"] == 882.68
    assert out["plans"][1]["withdrawal"] == 8826.8
    assert out["summary"]["total_withdrawal"] == 9709.48


def test_all_cash_amount_and_bad_inputs():
    holdings, _ = parse_fidelity_positions(SAMPLE)
    assert plan_from_holdings(holdings, {"withdrawals": [{"account_mask": "9154", "amount": "all_cash"}]})["plans"][0]["withdrawal"] == 882.68
    with pytest.raises(ValueError, match="base"):
        plan_from_holdings(holdings, {"withdrawals": [{"account_mask": "9154", "multiple": 2}]})
    with pytest.raises(ValueError, match="No holdings"):
        plan_from_holdings(holdings, {"withdrawals": [{"account_mask": "0000", "amount": 5}]})

import pytest

from ufo.providers.fidelity_csv import parse_fidelity_positions, parse_number
from ufo.rebalance.plan import plan_from_holdings

# Invented data in the shape of Fidelity's Positions export (account numbers, balances and holdings are made up).
SAMPLE = (
    "\ufeffAccount Number,Account Name,Symbol,Description,Quantity,Last Price,Last Price Change,Current Value,"
    "Today's Gain/Loss Dollar,Today's Gain/Loss Percent,Total Gain/Loss Dollar,Total Gain/Loss Percent,"
    "Percent Of Account,Cost Basis Total,Average Cost Basis,Type\r\n"
    'Z00000101,"Individual - TOD",SPAXX**,"HELD IN MONEY MARKET",,,,$9000.00,,,,,36.0%,,,Cash\r\n'
    'Z00000101,"Individual - TOD",IVV,"ISHARES CORE S&P 500 ETF",20.000,$800.00,+$1.50,"$16,000.00",+$30.00,+0.19%,+$1000.00,+6.7%,64.0%,"$15,000.00",$750.00,Cash\r\n'
    'Z00000202,"Individual - TOD",ABCD,"EXAMPLE HOLDINGS, INC",100,$5.00,-$0.04,$500.00,-$5.00,-0.88%,--,--,36%,--,--,Cash\r\n'
    "Z00000202,\"Individual - TOD\",Pending Activity,,,,,$-25.00,,,,,,,,\r\n"
    'Z00000202,"Individual - TOD",SPAXX**,"HELD IN MONEY MARKET",,,,$900.00,,,,,64%,,,Cash\r\n'
    "\r\n"
    '"The data and information in this spreadsheet is provided to you solely for your use."\r\n'
    '"Date downloaded Jan-02-2026 8:05 a.m ET"\r\n'
)


def test_numbers():
    assert parse_number("$1,234.50") == 1234.5
    assert parse_number("(12.00)") == -12
    assert parse_number("--") is None and parse_number("") is None


def test_fidelity_positions_export_to_holdings():
    holdings, warnings = parse_fidelity_positions(SAMPLE)
    assert len(holdings) == 4
    ivv = next(h for h in holdings if h["symbol"] == "IVV")
    assert (ivv["account_mask"], ivv["quantity"], ivv["price"], ivv["value"], ivv["cost_basis"]) == ("0101", 20.0, 800.0, 16000.0, 15000.0)
    cash = [(h["symbol"], h["account_mask"], h["value"], h["price"]) for h in holdings if h["is_cash"]]
    assert cash == [("CASH", "0101", 9000.0, 1.0), ("CASH", "0202", 900.0, 1.0)]
    assert next(h for h in holdings if h["symbol"] == "ABCD")["cost_basis"] is None
    assert "Pending activity" in " ".join(warnings)


def test_type_column_is_account_type_not_security_type():
    holdings, _ = parse_fidelity_positions(SAMPLE)
    assert [h["symbol"] for h in holdings if not h["is_cash"]] == ["IVV", "ABCD"]  # rows marked Type=Cash are still stocks


def test_rejects_non_fidelity_files():
    with pytest.raises(ValueError, match="header row"):
        parse_fidelity_positions("foo,bar\n1,2")


def test_x_from_one_account_all_cash_and_10x_from_another_in_one_call():
    holdings, _ = parse_fidelity_positions(SAMPLE)
    out = plan_from_holdings(holdings, {"base_all_cash_of": "202", "withdrawals": [
        {"account_mask": "202", "multiple": 1}, {"account_mask": "101", "multiple": 10}]})
    assert len(out["plans"]) == 2
    assert out["plans"][0]["withdrawal"] == 900.0
    assert out["plans"][1]["withdrawal"] == 9000.0
    assert out["summary"]["total_withdrawal"] == 9900.0


def test_all_cash_amount_and_bad_inputs():
    holdings, _ = parse_fidelity_positions(SAMPLE)
    assert plan_from_holdings(holdings, {"withdrawals": [{"account_mask": "0202", "amount": "all_cash"}]})["plans"][0]["withdrawal"] == 900.0
    with pytest.raises(ValueError, match="base"):
        plan_from_holdings(holdings, {"withdrawals": [{"account_mask": "0202", "multiple": 2}]})
    with pytest.raises(ValueError, match="No holdings"):
        plan_from_holdings(holdings, {"withdrawals": [{"account_mask": "0000", "amount": 5}]})

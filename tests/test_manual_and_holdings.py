"""Bugs found on the first real M10 run, the manual importer and the holdings panel. All data is invented."""
import json
from datetime import date

import pytest
from rich.console import Console

from tests.test_fidelity_history import _csv
from ufo import importers
from ufo.accounts.registry import Account
from ufo.performance.compare import AccountRun
from ufo.performance.dashboard import build_data
from ufo.performance.events import Kind
from ufo.performance.holdings import Holding, classify, load_classes, print_holdings, summarize
from ufo.providers.fidelity_history import parse_fidelity_history


def _row(d, action, sym="", qty="0", amount="", price=""):
    return f"{d},{action},{sym},X,Cash,0,USD,USD,{price},{qty},0,,,,{amount},,"


def test_ira_and_transfer_actions_are_recognized():
    p = parse_fidelity_history(_csv(
        _row("02/09/2021", "CASH CONTRIBUTION CURRENT YEAR (Cash)", amount="1234"),
        _row("05/11/2021", "CASH CONTRIBUTION PRIOR YEAR (Cash)", amount="321"),
        _row("08/23/2021", "EARLY DIST NO EXCEPT EARLY DST/NO EXCP A1 /WEB (Cash)", amount="-456"),
        _row("07/14/2021", "TRANSFER OF ASSETS ACAT RECEIVE ACME FUND (ACMEX) (Cash)", "ACMEX", "20", "1777"),
        _row("07/14/2021", "TRANSFER OF ASSETS ACAT RECEIVE (Cash)", amount="-55"),
        _row("09/20/2021", "LONG-TERM CAP GAIN ACME FUND (ACMEX) (Cash)", "ACMEX", amount="17"),
        _row("11/03/2021", "DISTRIBUTION ACME FUND (ACMEX) (Cash)", "ACMEX", "80", "999"),
        _row("12/15/2021", "REDEMPTION PAYOUT ACME BK CD 1.1% 12/15/2021 (Cash)", "00000AAA1", "-800", "800", "1"),
        _row("03/02/2021", "MERGER MER FROM 26924G409#REOR OLD (NEWX) (Cash)", "NEWX", "2", "90"),
    ))
    assert not p.warnings
    kinds = {e.description or e.symbol or e.kind: e.kind for e in p.events}
    by_amount = {e.amount: e.kind for e in p.events if e.amount}
    assert by_amount[1234] == Kind.CONTRIBUTION and by_amount[321] == Kind.CONTRIBUTION
    assert by_amount[-456] == Kind.WITHDRAWAL
    assert by_amount[1777] == Kind.CONTRIBUTION and next(e for e in p.events if e.amount == 1777).in_kind
    assert by_amount[-55] == Kind.FEE
    assert by_amount[17] == Kind.DIVIDEND and by_amount[999] == Kind.DIVIDEND
    assert by_amount[800] == Kind.SELL and by_amount[90] == Kind.BUY
    assert kinds


def test_manual_importer_reads_contributions_and_withdrawals(tmp_path):
    f = tmp_path / "bonds.csv"
    f.write_text("# invented\ndate,kind,amount,description\n2021-03-10,contribution,\"2,500\",first\n2021-09-05,withdrawal,400,partial\nnot-a-date,contribution,1,x\n")
    h = importers.get("manual").parse([str(f)])
    assert [(e.when, e.kind, e.amount) for e in h.events] == [
        (date(2021, 3, 10), Kind.CONTRIBUTION, 2500.0), (date(2021, 9, 5), Kind.WITHDRAWAL, -400.0)]
    assert [e.external_flow for e in h.events] == [2500.0, -400.0]
    assert len(h.warnings) == 1 and "row 4" in h.warnings[0]
    assert h.first == date(2021, 3, 10) and h.last == date(2021, 9, 5)
    assert importers.get("manual").positions([str(f)]) == []


POS = ("Account number,Account name,Symbol,Description,Quantity,Last price,Last price change,Current value,"
       "Today's gain/loss dollar,Today's gain/loss percent,Total gain/loss dollar,Total gain/loss percent,"
       "Percent of account,Cost basis total,Average cost basis,Type\n"
       "Z00000042,Brokerage,ACMEX,ACME FUND,10,$50,$0,$500,$0,0%,$0,0%,50%,$400,$40,Cash\n"
       "Z00000042,Brokerage,ZZZX,MYSTERY FUND,5,$50,$0,$250,$0,0%,$0,0%,25%,$200,$40,Cash\n"
       "Z00000042,Brokerage,SPAXX**,HELD IN MONEY MARKET,,,,$250,$0,,,,25%,,,Cash\n"
       "Z00000077,Other,ACMEX,ACME FUND,1,$50,$0,$50,$0,0%,$0,0%,100%,$40,$40,Cash\n")


def test_fidelity_holdings_split_per_account_from_newest_snapshot(tmp_path):
    old, new = tmp_path / "Portfolio_Positions_Jan-01-2026.csv", tmp_path / "Portfolio_Positions_Feb-01-2026.csv"
    old.write_text(POS.replace("$500", "$100"))
    new.write_text(POS)
    d, hs = importers.get("fidelity").holdings([str(old), str(new)], "0042")
    assert d == date(2026, 2, 1)
    assert sorted((h.symbol, h.value, h.is_cash) for h in hs) == [("ACMEX", 500.0, False), ("CASH", 250.0, True), ("ZZZX", 250.0, False)]
    assert importers.get("fidelity").holdings([str(new)], "9999") == (None, [])


def test_classes_mapping_and_unclassified(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"acmex": "us_stock"}))
    m = load_classes(f)
    assert m == {"ACMEX": "us_stock"}
    hs = [Holding(symbol="ACMEX", value=500), Holding(symbol="ZZZX", value=250), Holding(symbol="CASH", value=250, is_cash=True),
          Holding(symbol="912796Z93", value=100)]
    assert [classify(h, m) for h in hs] == ["us_stock", "unclassified", "cash", "bonds"]
    s = summarize(hs, m)
    assert s["rows"][0]["symbol"] == "ACMEX" and s["total"] == 1100
    assert s["by_class"]["unclassified"] == pytest.approx(250 / 1100)
    assert load_classes(tmp_path / "missing.json") == {}
    f.write_text(json.dumps({"ACMEX": "stocks"}))
    with pytest.raises(ValueError, match="us_stock"):
        load_classes(f)
    f.write_text("{oops")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_classes(f)


def _run():
    a = Account.model_validate({"id": "a", "label": "Alpha", "brokerage": "fidelity", "last_digits": "0042",
                                "source": {"importer": "fidelity", "history_glob": "x"}})
    return AccountRun(account=a, holdings=[Holding(symbol="ACMEX", name="ACME FUND", value=750), Holding(symbol="ZZZX", value=250)],
                      holdings_as_of=date(2026, 2, 1))


def test_terminal_and_dashboard_show_holdings():
    con = Console(record=True, width=160)
    print_holdings([_run()], {"ACMEX": "us_stock"}, con)
    out = con.export_text()
    assert "ACMEX" in out and "75.0%" in out and "Unclassified" in out and "ZZZX" in out
    data = build_data([_run()], [], "IDX", [], {}, date(2026, 2, 1), {"ACMEX": "us_stock"})
    h = data["entities"][0]["holdings"]
    assert h["as_of"] == "2026-02-01" and h["by_class"]["us_stock"] == 0.75
    assert ["unclassified", "Unclassified"] in data["classes"]

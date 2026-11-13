"""The Acorns importer, on invented statement text with the same layout as the real PDFs."""
from datetime import date

from ufo import importers
from ufo.importers.acorns import AcornsImporter, parse_statement, pending_cash
from ufo.performance.events import Kind

STATEMENT = """Demo Securities, LLC
                          Statement Period                            5/1/2030 - 5/31/2030
Ending Balance (5/31/2030)                                 $1,100.00
Net Cash and/or Sales pending Settlement (5/31/2030)           $2.50
Grand Total (5/31/2030)                                    $1,102.50

Deposits and Withdrawals Summary
Transfer Date               Description                                                     Amount
5/3/2030                    ACH Deposit                                                     $100.00
5/10/2030                   Demo Earn Program                                                 $0.50
5/20/2030                   ACH Withdrawal                                                  ($20.00)
5/31/2030                   Net Deposits and Withdrawals                                    $80.50
                                                                 Page 5
Purchases and Sales Summary
Trade Date                  Description                                                   Amount
5/3/2030                    Portfolio Purchase                                              $100.00
5/12/2030                   AAAA Dividend Reinvestment                                       $1.00
5/31/2030                   Net Purchases and Sales                                      $81.00
Transfers
Date                 Description
Pending Cash
Cash Received Date          Description                                                    Amount
5/28/2030                   AAAA Dividend                                                    $2.50
5/31/2030                   Net Pending Cash Balance                                         $2.50
Corporate Actions
Transactions
Date         Settlement Date Activity        Description                             Quantity     Price   Amount         Portfolio Type
Securities Bought
5/3/2030     5/5/2030         Bought         Demo Alpha ETF (AAAA)                   2.00000    $30.00    $60.00              Base
5/3/2030     5/5/2030         Bought         Demo Beta Total Market Optimized        0.50000   $80.00    $40.00              Base
                                             (BBBB)
5/12/2030    5/14/2030        Bought         Demo Alpha ETF (AAAA)                   0.03333    $30.00     $1.00
Securities Sold
5/20/2030    5/22/2030        Sold           Demo Alpha ETF (AAAA)                   0.66667    $30.00    $20.00              Base
"""


def test_registered():
    assert "acorns" in importers.names()


def test_statement_events():
    period, ev, grand, warns = parse_statement(STATEMENT)
    assert period == (date(2030, 5, 1), date(2030, 5, 31)) and grand == 1102.5 and warns == []
    flows = sorted(e.amount for e in ev if e.kind in (Kind.CONTRIBUTION, Kind.WITHDRAWAL))
    assert flows == [-20.0, 0.5, 100.0]  # the earn credit counts as money in
    buys = {(e.symbol, e.quantity) for e in ev if e.kind == Kind.BUY}
    assert ("BBBB", 0.5) in buys  # ticker wrapped to the next line
    sell = next(e for e in ev if e.kind == Kind.SELL)
    assert sell.quantity == -0.66667 and sell.amount == 20.0
    assert [e.amount for e in ev if e.kind == Kind.DIVIDEND] == [1.0]
    assert [e.amount for e in pending_cash(STATEMENT)] == [2.5]


def test_trades_without_portfolio_type_column():
    t = STATEMENT.replace("              Base", "")
    _, ev, _, w = parse_statement(t)
    assert w == [] and sum(1 for e in ev if e.kind == Kind.BUY) == 3


def test_import_reads_pdfs(tmp_path, monkeypatch):
    from ufo.importers import acorns
    monkeypatch.setattr(acorns, "_text", lambda path: STATEMENT)
    files = [str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")]  # same period twice: counted once
    h = AcornsImporter().parse(files)
    assert any("same period" in w for w in h.warnings)
    assert sum(e.external_flow or 0 for e in h.events) == 80.5
    assert [e.amount for e in h.events if e.description == "AAAA Dividend"] == [2.5]  # newest statement's pending cash
    assert AcornsImporter().statement_values(files) == [(date(2030, 5, 31), 1102.5, "Acorns monthly statement")]

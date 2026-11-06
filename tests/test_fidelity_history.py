"""Fidelity activity-history parser. All data below is invented."""
from datetime import date

from ufo.providers.fidelity_history import Kind, ParsedHistory, merge_histories, parse_fidelity_history

HEADER = ("Run Date,Action,Symbol,Description,Type,Exchange Quantity,Exchange Currency,Currency,Price,"
          "Quantity,Exchange Rate,Commission,Fees,Accrued Interest,Amount,Cash Balance,Settlement Date")


def _csv(*rows: str) -> str:
    return "\n\n" + HEADER + "\n" + "\n".join(rows) + '\n\n\n"The data and information in this spreadsheet is provided for your use only."\n'


BUY = '03/01/2020,YOU BOUGHT ACME FUND (ACMEX) (Cash),ACMEX,ACME FUND,Cash,10,USD,USD,50,10,0,,,,-500.00,1000,03/03/2020'
SELL = '03/05/2020,YOU SOLD ACME FUND (ACMEX) (Cash),ACMEX,ACME FUND,Cash,-4,USD,USD,55,-4,0,,0.01,,219.99,1219.99,03/07/2020'
IN = '02/01/2020,Electronic Funds Transfer Received (Cash),,No Description,Cash,1500,USD,USD,,1500,0,,,,1500.00,1500,'
OUT = '04/01/2020,Electronic Funds Transfer Paid (Cash),,No Description,Cash,200,USD,USD,,200,0,,,,-200.00,1019.99,'
XFER = '04/02/2020,TRANSFERRED TO VS Z00-000000-0 (Cash),,No Description,Cash,300,USD,USD,,300,0,,,,-300.00,719.99,'
DIV = '04/03/2020,DIVIDEND RECEIVED ACME FUND (ACMEX) (Cash),ACMEX,ACME FUND,Cash,0,USD,USD,,0,0,,,,12.34,732.33,'
REINV = '04/03/2020,REINVESTMENT ACME FUND (ACMEX) (Cash),ACMEX,ACME FUND,Cash,0.2,USD,USD,61.7,0.2,0,,,,-12.34,719.99,'
IN_KIND = '05/01/2020,TRANSFERRED FROM VS Z00-000000-1 (Cash),ACMEX,ACME FUND,Cash,2,USD,USD,60,2,0,,,,,719.99,'


def test_basic_events_and_signs():
    p = parse_fidelity_history(_csv(BUY, SELL, IN, OUT))
    assert not p.warnings
    assert [e.kind for e in p.events] == [Kind.CONTRIBUTION, Kind.BUY, Kind.SELL, Kind.WITHDRAWAL]  # sorted by date
    assert p.first == date(2020, 2, 1) and p.last == date(2020, 4, 1)
    sell = p.events[2]
    assert (sell.symbol, sell.quantity, sell.amount, sell.fees) == ("ACMEX", -4.0, 219.99, 0.01)


def test_only_contributions_and_withdrawals_are_external():
    p = parse_fidelity_history(_csv(BUY, SELL, IN, OUT, XFER))
    assert [round(e.external_flow, 2) for e in p.events] == [1500.0, 0.0, 0.0, -200.0, -300.0]
    assert sum(e.external_flow for e in p.events) == 1000.0


def test_reinvested_dividend_is_internal():
    p = parse_fidelity_history(_csv(DIV, REINV))
    assert [e.kind for e in p.events] == [Kind.DIVIDEND, Kind.REINVESTMENT]
    assert all(e.external_flow == 0.0 for e in p.events)


def test_in_kind_transfer_is_valued_at_market_on_the_date():
    p = parse_fidelity_history(_csv(IN_KIND))
    e = p.events[0]
    assert e.kind == Kind.CONTRIBUTION and e.in_kind and e.amount == 120.0 and e.external_flow == 120.0
    assert not p.warnings


def test_in_kind_without_a_value_is_flagged():
    row = '05/01/2020,TRANSFERRED TO VS Z00-000000-1 (Cash),ACMEX,ACME FUND,Cash,,USD,USD,,,0,,,,,0,'
    p = parse_fidelity_history(_csv(row))
    assert any("no value" in w for w in p.warnings)


def test_unknown_action_is_reported_not_dropped_silently():
    p = parse_fidelity_history(_csv(BUY, '06/01/2020,MYSTERY ACTION (Cash),,x,Cash,0,USD,USD,,0,0,,,,5.00,0,'))
    assert len(p.events) == 1
    assert any("unrecognized action" in w and "Line" in w for w in p.warnings)


def test_footer_and_blank_lines_are_ignored_and_bad_dates_warn():
    p = parse_fidelity_history(_csv(BUY, '13/45/2020,YOU SOLD X,X,x,Cash,0,USD,USD,,0,0,,,,1,0,'))
    assert len(p.events) == 1
    assert any("could not read the date" in w for w in p.warnings)


def test_wrong_file_gets_a_plain_message():
    p = parse_fidelity_history("Account,Balance\n1,2\n")
    assert p.events == [] and "Run Date" in p.warnings[0]


def test_empty_export_is_fine():
    p = parse_fidelity_history(_csv())
    assert p.events == [] and p.first is None and not p.warnings


def test_merge_warns_on_overlap_and_keeps_every_row():
    a = parse_fidelity_history(_csv(IN, BUY))  # Feb 1 .. Mar 1
    b = parse_fidelity_history(_csv(BUY, SELL))  # Mar 1 .. Mar 5 (repeats the Mar 1 buy)
    m = merge_histories([b, a])
    assert len(m.events) == 4 and any("overlap" in w for w in m.warnings)
    c = parse_fidelity_history(_csv(OUT))
    assert not [w for w in merge_histories([a, c]).warnings if "overlap" in w]


def test_merge_empty_and_none_dated_parts():
    m = merge_histories([ParsedHistory(events=[], warnings=[]), parse_fidelity_history(_csv(IN))])
    assert len(m.events) == 1 and m.first == date(2020, 2, 1)


def test_newest_first_export_is_put_in_true_order_within_a_day_and_keeps_cash_balance():
    later = '03/05/2020,YOU SOLD ACME FUND (ACMEX) (Cash),ACMEX,ACME FUND,Cash,-4,USD,USD,55,-4,0,,,,220.00,1220,03/07/2020'
    earlier = '03/05/2020,YOU BOUGHT ACME FUND (ACMEX) (Cash),ACMEX,ACME FUND,Cash,4,USD,USD,50,4,0,,,,-200.00,1000,03/07/2020'
    older = '03/01/2020,Electronic Funds Transfer Received (Cash),,No Description,Cash,1200,USD,USD,,1200,0,,,,1200.00,1200,'
    p = parse_fidelity_history(_csv(later, earlier, older))  # Fidelity lists the newest row first
    assert [e.kind for e in p.events] == [Kind.CONTRIBUTION, Kind.BUY, Kind.SELL]
    assert [e.cash_balance for e in p.events] == [1200.0, 1000.0, 1220.0]

"""The Voya importer, on invented files with the same layout as the real export."""
import json
from datetime import date

from ufo import importers
from ufo.importers.voya import VoyaImporter, parse_balances
from ufo.performance.events import Kind
from ufo.performance.ledger import Ledger
from ufo.providers.prices import Point, PriceStore

HEAD = 'ZZ99Z9 ACME DEMO IRA\nDate Range :\t{a} - {b}\n"\n"\nActivity Date,Activity,Fund,Money Source,"# of Units",Unit Price,Amount\n'
A, B = "1111 Alpha Demo Fund R", "2222 Beta Demo Fund A"


def write(tmp_path, name, a, b, rows):
    p = tmp_path / name
    p.write_text(HEAD.format(a=a, b=b) + "\n".join(rows) + "\n")
    return str(p)


def test_registered():
    assert "voya" in importers.names()


def test_activities_map_to_neutral_events(tmp_path):
    f = write(tmp_path, "TransactionHistory.csv", "02/01/2015", "12/31/2015", [
        f"2015-06-30,OTHER,{A},IRA,-0.5,10,-5",
        f"2015-06-20,DIVIDEND,{A},IRA,1,10,10",
        f"2015-06-10,TRANSFER,{B},IRA,3,20,60",
        f"2015-06-10,TRANSFER,{A},IRA,-6,10,-60",
        f"2015-02-03,CONTRIBUTION,{A},IRA,100,10,1000",
        f"2015-06-01,OTHER,{A},IRA,0.01,10,0.1",
    ])
    h = VoyaImporter().parse([f])
    assert h.warnings == []
    assert [e.when for e in h.events] == sorted(e.when for e in h.events)
    flows = [e.external_flow for e in h.events if e.external_flow]
    assert flows == [1000.0]  # only the contribution crosses the boundary; dividends, fees, transfers do not
    assert abs(sum(e.amount for e in h.events)) < 1e-9  # every cash row is paired with its unit change
    assert {Kind.FEE, Kind.DIVIDEND, Kind.INTEREST} <= {e.kind for e in h.events}
    led = Ledger(h.events, {})
    q = led.quantities(date(2015, 12, 31))
    assert round(q["VOYA1111"], 4) == round(100 + 0.01 + 1 - 6 - 0.5, 4) and q["VOYA2222"] == 3


def test_unknown_activity_is_a_warning(tmp_path):
    f = write(tmp_path, "TransactionHistory.csv", "01/01/2015", "12/31/2015", [f"2015-03-03,MYSTERY,{A},IRA,1,10,10"])
    h = VoyaImporter().parse([f])
    assert h.events == [] and "MYSTERY" in h.warnings[0]


def test_withdrawal(tmp_path):
    f = write(tmp_path, "t.csv", "01/01/2015", "12/31/2015", [f"2015-03-03,WITHDRAWAL,{A},IRA,-2,10,-20"])
    assert [e.external_flow for e in VoyaImporter().parse([f]).events if e.external_flow] == [-20.0]


def test_repeated_and_overlapping_files_are_not_double_counted(tmp_path):
    rows = [f"2015-03-03,CONTRIBUTION,{A},IRA,10,10,100"]
    a = write(tmp_path, "TransactionHistory.csv", "01/01/2015", "12/31/2015", rows)
    dup = write(tmp_path, "TransactionHistory (1).csv", "01/01/2015", "12/31/2015", rows)
    part = write(tmp_path, "TransactionHistory (2).csv", "06/01/2015", "12/31/2016",
                 [f"2016-02-02,CONTRIBUTION,{A},IRA,10,10,100", f"2015-09-09,CONTRIBUTION,{A},IRA,10,10,100"])
    h = VoyaImporter().parse([a, dup, part])
    assert [e.external_flow for e in h.events if e.external_flow] == [100.0, 100.0]  # 2015-09-09 lies in file one's range
    assert sum("covered" in w for w in h.warnings) == 1 and sum("overlaps" in w for w in h.warnings) == 1


def test_unit_prices_become_a_series_and_tickers_override(tmp_path):
    f = write(tmp_path, "t.csv", "01/01/2015", "12/31/2015",
              [f"2015-06-01,DIVIDEND,{B},IRA,1,22,22", f"2015-03-03,CONTRIBUTION,{A},IRA,10,10,100"])
    imp = VoyaImporter()
    assert [(p.day, p.close) for p in imp.prices([f])["VOYA1111"]] == [(date(2015, 3, 3), 10.0)]
    (tmp_path / "fund_tickers.json").write_text(json.dumps({"1111": "dmoax"}))
    assert set(imp.prices([f])) == {"VOYA2222"}
    assert {e.symbol for e in imp.parse([f]).events if e.kind == Kind.BUY} == {"DMOAX", "VOYA2222"}


def test_store_serves_importer_prices_without_cache_or_network(tmp_path):
    s = PriceStore(tmp_path / "cache")
    s.add_own({"voya1111": [Point(day=date(2015, 3, 3), value=10, close=10), Point(day=date(2016, 1, 1), value=12, close=12)]})
    assert s.series("VOYA1111", date(2015, 1, 1), date(2015, 12, 31)).points[0].close == 10


def test_parse_balances():
    text = "Account Balance on 07/01/2015     $1,234.50\nxx\nAccount Balance on 09/30/2015                $1,300.00\n"
    assert parse_balances(text) == [(date(2015, 7, 1), 1234.5), (date(2015, 9, 30), 1300.0)]

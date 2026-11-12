"""The importer interface: Fidelity goes through it unchanged, and a toy second importer built from an invented CSV
produces events the ledger accepts."""
import csv
from datetime import date

from ufo import importers
from ufo.performance.events import Event, Kind, ParsedHistory
from ufo.performance.ledger import Ledger, Snapshot
from ufo.providers.fidelity_history import Event as FEvent, Kind as FKind, ParsedHistory as FParsed
from ufo.providers.prices import Point, Series


class ToyImporter:
    """date,type,symbol,qty,price,amount ; type is deposit|withdraw|buy|sell|transfer_in|transfer_out"""
    name = "toy"
    MAP = {"deposit": (Kind.CONTRIBUTION, False), "withdraw": (Kind.WITHDRAWAL, False), "buy": (Kind.BUY, False),
           "sell": (Kind.SELL, False), "transfer_in": (Kind.CONTRIBUTION, True), "transfer_out": (Kind.WITHDRAWAL, True)}

    def parse(self, files, account_digits=""):
        events = []
        for f in files:
            for n, r in enumerate(csv.DictReader(open(f)), 1):
                kind, hint = self.MAP[r["type"]]
                events.append(Event(when=date.fromisoformat(r["date"]), kind=kind, symbol=r["symbol"], seq=n,
                                    quantity=float(r["qty"]) if r["qty"] else None, amount=float(r["amount"]),
                                    transfer_hint=hint, source=self.name, in_kind=hint and bool(r["symbol"])))
        events.sort(key=lambda e: (e.when, e.seq))
        return ParsedHistory(events=events, warnings=[], first=events[0].when, last=events[-1].when)

    def positions(self, files, account_digits=""):
        return []


def test_fidelity_is_registered_and_old_imports_still_work():
    assert "fidelity" in importers.names()
    assert FEvent is Event and FKind is Kind and FParsed is ParsedHistory


def test_toy_importer_events_feed_the_ledger(tmp_path):
    f = tmp_path / "toy.csv"
    f.write_text("date,type,symbol,qty,price,amount\n2024-01-02,deposit,,,,1000\n2024-01-03,buy,ACME,10,,-500\n"
                 "2024-03-01,transfer_out,ACME,5,,-300\n")
    importers.register(ToyImporter())
    hist = importers.get("toy").parse([str(f)])
    assert [e.source for e in hist.events] == ["toy"] * 3
    prices = {"ACME": Series(symbol="ACME", points=[Point(day=date(2024, 1, 1), value=50.0, close=50.0),
                                                    Point(day=date(2024, 4, 1), value=60.0, close=60.0)])}
    led = Ledger(hist.events, prices)
    assert led.flows() == [(date(2024, 1, 2), 1000.0), (date(2024, 3, 1), -300.0)]
    assert led.value_on(date(2024, 3, 15)).holdings == 10 * 50.0  # in-kind share moves are fixed by snapshot anchoring, as for Fidelity
    assert hist.events[2].transfer_hint and hist.events[2].external_flow == -300.0  # still external for this account alone


def test_snapshot_value_is_optional():
    assert Snapshot(when=date(2024, 1, 1), quantities={}).value is None

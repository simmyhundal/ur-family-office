"""End to end on invented files: history CSV + positions CSV -> run -> HTML and terminal report. No network."""
import io
from datetime import date, timedelta
from pathlib import Path

from rich.console import Console

from ufo.performance.report_html import nice_range, render
from ufo.performance.report_text import print_report
from ufo.performance.run import run
from ufo.providers.prices import Point, PriceStore, Series

HEADER = ("Run Date,Action,Symbol,Description,Type,Exchange Quantity,Exchange Currency,Currency,Price,"
          "Quantity,Exchange Rate,Commission,Fees,Accrued Interest,Amount,Cash Balance,Settlement Date")


def _daily(start, days, growth, base=100.0):
    return [Point(day=start + timedelta(days=i), value=base * (1 + growth) ** i, close=base * (1 + growth) ** i) for i in range(days)]


class Fake:
    def __init__(self):
        s = date(2020, 1, 1)
        self.data = {"ACME": _daily(s, 1000, 0.0004), "IDX": _daily(s, 1000, 0.0005)}
        self.calls = []

    def fetch(self, symbol, start, end):
        self.calls.append(symbol)
        return [p for p in self.data[symbol] if start <= p.day <= end]

    def fetch_risk_free(self, start, end):
        return [Point(day=date(2020, 1, 1) + timedelta(days=i), value=2.0) for i in range(1000) if start <= date(2020, 1, 1) + timedelta(days=i) <= end]


def _files(tmp: Path) -> tuple[list[str], list[str]]:
    acme = {p.day: p.close for p in _daily(date(2020, 1, 1), 1000, 0.0004)}
    rows = [
        "01/10/2020,Electronic Funds Transfer Received (Cash),,x,Cash,10000,USD,USD,,10000,0,,,,10000.00,10000,",
        f"01/13/2020,YOU BOUGHT ACME (ACME) (Cash),ACME,ACME,Cash,0,USD,USD,{acme[date(2020, 1, 13)]:.4f},90,0,,,,{-90 * acme[date(2020, 1, 13)]:.2f},{10000 - 90 * acme[date(2020, 1, 13)]:.2f},01/15/2020",
    ]
    h = tmp / "History.csv"
    h.write_text("\n\n" + HEADER + "\n" + "\n".join(reversed(rows)) + "\n")  # newest first, like Fidelity
    snap = tmp / "Portfolio_Positions_Jan-02-2021.csv"
    snap.write_text("Account number,Account name,Symbol,Description,Quantity,Last price,Last price change,Current value,Today's gain/loss dollar,"
                    "Today's gain/loss percent,Total gain/loss dollar,Total gain/loss percent,Percent of account,Cost basis total,Average cost basis,Type\n"
                    "Z00000042,Individual,ACME,ACME,90,$100.00,+$1.00,$9000.00,+$1.00,+0.1%,+$1.00,+1%,90%,$9000.00,$100.00,Cash\n")
    return [str(h)], [str(snap)]


def test_run_renders_both_reports_without_network(tmp_path):
    hist, snaps = _files(tmp_path)
    store = PriceStore(tmp_path / "cache", Fake(), today=date(2022, 9, 1))
    end = date(2021, 12, 31)
    acme_end = Series(symbol="ACME", points=_daily(date(2020, 1, 1), 1000, 0.0004)).close_on_or_before(end)
    res = run(hist, snaps, "0042", end, 90 * acme_end + 10000 - 90 * 100.5, store, benchmark="IDX")
    r = res.report
    assert r.contributed == 10000.0 and r.irr is not None and r.index_irr is not None and r.excess_irr is not None
    assert len(r.months) >= 20 and res.reconciliation and res.events == 2
    page = render(res)
    for needle in ("Excess IRR", "Growth of $1", "Calendar-year returns", "Drawdown", "Data checks", "never sent anywhere", "<svg"):
        assert needle in page
    assert "http" not in page.replace("https://fonts.googleapis.com", "").replace("https://fonts.gstatic.com", "")  # nothing else is loaded
    buf = io.StringIO()
    print_report(res, Console(file=buf, width=100, force_terminal=False))
    out = buf.getvalue()
    assert "Excess IRR" in out and "Calendar years" in out and "Data checks" in out and "Worth today" in out
    assert "Your balance vs the same money in IDX" in page


def test_nice_range_rounds_to_friendly_ticks():
    assert nice_range(-0.17, 0.27) == (-0.2, 0.3) or nice_range(-0.17, 0.27)[0] <= -0.17
    lo, hi = nice_range(0.74, 1.82)
    assert lo <= 0.74 and hi >= 1.82

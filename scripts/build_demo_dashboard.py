"""Build the all-accounts dashboard for an invented household, to show the product without anyone's real data.

  python scripts/build_demo_dashboard.py [--out exports/demo-dashboard.html] [--asof 2026-10-30]

Every account, amount and date below is invented. Only public fund prices are used (the same price cache and
services as jobs.portfolio_compare). Writes Fidelity-format history files and a registry into a temporary folder,
runs the real pipeline on them and writes one self-contained HTML page. Information, not investment advice.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from jobs import portfolio_compare  # noqa: E402
from ufo.providers.prices import PriceStore, WebClient  # noqa: E402

HEADER = ("Run Date,Account Number,Action,Symbol,Description,Type,Exchange Quantity,Exchange Currency,Currency,Price,"
          "Quantity,Exchange Rate,Commission,Fees,Accrued Interest,Amount,Cash Balance,Settlement Date")

DEMO_NOTE = ("Demo: an invented household (Alex and Sam, four accounts) on real fund prices. With UFO you see your own accounts, "
             "analyzed on your computer; nothing is uploaded. Information, not investment advice.")

# Public facts about the funds (names and asset class), used for the holdings table.
FUNDS = {"IVV": ("ISHARES CORE S&P 500 ETF", "us_stock"), "IWM": ("ISHARES RUSSELL 2000 ETF", "us_stock"),
         "VXUS": ("VANGUARD TOTAL INTERNATIONAL STOCK ETF", "intl_stock"), "VTI": ("VANGUARD TOTAL STOCK MARKET ETF", "us_stock"),
         "VGT": ("VANGUARD INFORMATION TECHNOLOGY ETF", "us_stock"), "XBI": ("SPDR S&P BIOTECH ETF", "us_stock"),
         "ARKK": ("ARK INNOVATION ETF", "us_stock"), "AOR": ("ISHARES CORE 60/40 BALANCED ALLOCATION ETF", "balanced")}

# The invented household: (id, label, wrapper, owner, account number, start, plan)
# plan: list of (every_n_months, amount, {symbol: weight}); a negative amount is a withdrawal taken pro rata.
ACCOUNTS = [
    ("demo-taxable", "Joint brokerage", "taxable", "household", "Z00001001", date(2019, 3, 1),
     [(1, 800.0, {"IVV": .5, "IWM": .3, "VXUS": .2})], [(date(2023, 8, 15), -6000.0)]),
    ("demo-roth-a", "Alex Roth IRA", "roth_ira", "alex", "Z00001002", date(2020, 1, 1),
     [(12, 6000.0, {"VTI": 1.0})], []),
    ("demo-roth-b", "Sam Roth IRA", "roth_ira", "sam", "Z00001003", date(2021, 1, 1),
     [(12, 6000.0, {"VGT": .4, "XBI": .3, "ARKK": .3})], []),
    ("demo-ira", "Sam rollover IRA", "traditional_ira", "sam", "Z00001004", date(2018, 6, 1),
     [(1, 400.0, {"AOR": 1.0})], []),
]


def _months(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d = date(d.year + (d.month // 12), d.month % 12 + 1, 1)


def _row(d: date, acct: str, action: str, sym: str = "", price: float | None = None, qty: float | None = None, amount: float = 0.0) -> str:
    p = f"{price:.4f}" if price is not None else ""
    q = f"{qty:.6f}" if qty is not None else ""
    return f"{d:%m/%d/%Y},{acct},{action},{sym},x,Cash,0,USD,USD,{p},{q},0,,,,{amount:.2f},,"


def build(tmp: Path, store: PriceStore, asof: date) -> None:
    (tmp / "exports" / "demo").mkdir(parents=True)
    (tmp / ".data").mkdir()
    rows: list[str] = []
    registry = []
    positions = ["Account number,Account name,Symbol,Description,Quantity,Last price,Current value,Type"]
    for aid, label, wrapper, owner, num, start, plan, withdrawals in ACCOUNTS:
        syms = sorted({s for _, _, w in plan for s in w})
        series = {s: store.series(s, start - timedelta(days=10), asof) for s in syms}
        shares = {s: 0.0 for s in syms}
        value_end = 0.0
        for i, m in enumerate(_months(start, asof - timedelta(days=5))):
            day = m + timedelta(days=2)
            for every, amount, weights in plan:
                if i % every:
                    continue
                rows.append(_row(day, num, "Electronic Funds Transfer Received (Cash)", amount=amount))
                for s, w in weights.items():
                    px = series[s].close_on_or_before(day + timedelta(days=1))
                    q = amount * w / px
                    shares[s] += q
                    rows.append(_row(day + timedelta(days=1), num, f"YOU BOUGHT {s} ({s}) (Cash)", s, px, q, -amount * w))
            for wd, amt in withdrawals:
                if wd.year == m.year and wd.month == m.month:
                    total = sum(shares[s] * series[s].close_on_or_before(wd) for s in syms)
                    for s in syms:
                        px = series[s].close_on_or_before(wd)
                        q = shares[s] * (-amt) / total
                        shares[s] -= q
                        rows.append(_row(wd, num, f"YOU SOLD {s} ({s}) (Cash)", s, px, -q, q * px))
                    rows.append(_row(wd + timedelta(days=2), num, "Electronic Funds Transfer Paid (Cash)", amount=amt))
        value_end = sum(shares[s] * series[s].close_on_or_before(asof) for s in syms)
        for s in syms:
            px = series[s].close_on_or_before(asof)
            positions.append(f"{num},{label},{s},{FUNDS[s][0]},{shares[s]:.6f},${px:.2f},${shares[s] * px:.2f},Cash")
        registry.append(dict(id=aid, label=label, brokerage="fidelity", institution="Demo Brokerage", last_digits=num[-4:], wrapper=wrapper,
                             owner=owner, source={"importer": "fidelity", "history_glob": "exports/demo/History*.csv",
                                     "snapshot_glob": "exports/demo/Portfolio_Positions_*.csv"},
                             ending_value={"kind": "statement", "value": round(value_end, 2), "as_of": asof.isoformat()}))
    rows.sort(key=lambda r: (r[6:10], r[0:2], r[3:5]))
    (tmp / "exports" / "demo" / "History_demo.csv").write_text("\n" + HEADER + "\n" + "\n".join(reversed(rows)) + "\n")
    (tmp / "exports" / "demo" / f"Portfolio_Positions_{asof:%b-%d-%Y}.csv").write_text("\n".join(positions) + "\n")
    (tmp / ".data" / "asset_classes.json").write_text(json.dumps({k: v[1] for k, v in FUNDS.items()}))
    (tmp / ".data" / "accounts.json").write_text(json.dumps({"accounts": registry}, indent=1))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="exports/demo-dashboard.html")
    ap.add_argument("--asof", default="2026-10-30", help="the demo's 'today' (a trading day)")
    ap.add_argument("--cache", default=str(ROOT / ".data" / "prices"), help="price cache (public prices only)")
    a = ap.parse_args(argv)
    asof = date.fromisoformat(a.asof)
    store = PriceStore(Path(a.cache), WebClient())
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        build(tmp, store, asof)
        out = Path(a.out).resolve()
        return portfolio_compare.main(["--root", str(tmp), "--cache", a.cache, "--out", str(out), "--demo", DEMO_NOTE], store=store, today=asof + timedelta(days=1))


if __name__ == "__main__":
    raise SystemExit(main())

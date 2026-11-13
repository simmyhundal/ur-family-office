"""The combined line's monthly series on invented accounts: two accounts that hold the same fund and open in different
months, mid-month. The combined volatility and return must sit between its members' (they are perfectly correlated),
and no month may show an impossible swing from a deposit counted without the value it bought."""
from datetime import date, timedelta

from tests.test_importers import ToyImporter
from tests.test_portfolio_compare import TODAY, Fake, _daily
from ufo import importers
from ufo.accounts.registry import Registry
from ufo.performance.combine import combine
from ufo.performance.compare import run_all
from ufo.providers.prices import Point, PriceStore


def stepped():
    """A fund that moves on the first of each month: +5% in even months, -3% in odd ones (so volatility is not zero)."""
    pts, v, last = [], 100.0, None
    for i in range(1100):
        d = date(2020, 1, 1) + timedelta(days=i)
        if d.day == 1 and last != (d.year, d.month):
            v *= 1.05 if d.month % 2 == 0 else 0.97
            last = (d.year, d.month)
        pts.append(Point(day=d, value=v, close=v))
    return pts


def build(tmp_path):
    importers.register(ToyImporter())
    files = {"p": "date,type,symbol,qty,price,amount\n2020-03-17,deposit,,,,2000\n2020-03-18,buy,ACME,20,,-2000\n",
             "q": "date,type,symbol,qty,price,amount\n2020-05-09,deposit,,,,6000\n2020-05-10,buy,ACME,60,,-6000\n"}
    accts = []
    for k, text in files.items():
        (tmp_path / k).mkdir()
        (tmp_path / k / "x.csv").write_text(text)
        accts.append(dict(id=k, label=k.upper(), brokerage="toy", source={"importer": "toy", "history_glob": f"{k}/*.csv"},
                          ending_value={"kind": "statement", "value": 9000.0, "as_of": "2022-05-31"}))
    return Registry.model_validate({"accounts": accts})


def test_combined_point_sits_between_perfectly_correlated_members(tmp_path):
    fake = Fake()
    fake.data["ACME"] = stepped()
    fake.data["IDX"] = _daily(0.0005)
    st = PriceStore(tmp_path / "cache", fake, today=TODAY)
    runs = run_all(build(tmp_path), tmp_path, st, "IDX", TODAY)
    assert all(r.result for r in runs), [r.error for r in runs]
    g = combine("all", "All accounts", runs, st, "IDX")
    assert g.error == "" and g.report.volatility is not None
    vols = [r.result.report.volatility for r in runs]
    rets = [r.result.report.twr_annual for r in runs]
    tol = 0.02
    assert min(vols) - tol <= g.report.volatility <= max(vols) + tol
    assert min(rets) - tol <= g.report.twr_annual <= max(rets) + tol
    assert all(x is None or -1 < x < 1 for x in g.report.port_returns)
    # the first partial month of each member is in the combined series (value arrives with its deposit)
    assert g.report.months[0] <= date(2020, 3, 31)

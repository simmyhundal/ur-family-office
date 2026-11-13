"""A fixed annuity (market: false) on invented data: benchmark comparison from its flows, n/a for price-history measures, still in the totals."""
import json
import re

from rich.console import Console

from jobs import portfolio_compare
from tests.test_portfolio_compare import TODAY, setup, store
from ufo.accounts.registry import Registry
from ufo.performance.combine import combine_all
from ufo.performance.compare import print_table, run_all
from ufo.performance.dashboard import build_data, render
from ufo.performance.holdings import print_holdings


def _reg(tmp_path):
    reg = setup(tmp_path, "ac")
    (tmp_path / "man").mkdir()
    (tmp_path / "man" / "ann.csv").write_text("date,kind,amount,description\n2020-02-10,contribution,3000,deposit\n")
    ann = dict(id="ann", label="Annuity", brokerage="manual", wrapper="roth_ira", market=False,
               source={"importer": "manual", "history_glob": "man/ann.csv"},
               ending_value={"kind": "statement", "value": 3300.0, "as_of": "2022-05-31"})
    return Registry.model_validate({"accounts": [a.model_dump(mode="json") for a in reg.accounts] + [ann]})


def test_market_defaults_to_true():
    from ufo.accounts.registry import Account
    assert Account.model_fields["market"].default is True


def test_annuity_has_irr_but_no_benchmark_and_prices_untouched(tmp_path):
    reg = _reg(tmp_path)
    st, fake = store(tmp_path)
    runs = run_all(reg, tmp_path, st, "IDX", TODAY)
    ann = runs[-1]
    assert ann.error == "" and not ann.market
    rep = ann.result.report
    assert rep.irr is not None and 0.03 < rep.irr < 0.06 and rep.sharpe is None and rep.twr_annual is None and rep.volatility is None and rep.beta is None
    # the same deposit put into the benchmark gives a benchmark IRR, a worth-today and an excess IRR
    assert rep.index_irr is not None and rep.index_end_value > 0 and abs(rep.excess_irr - (rep.irr - rep.index_irr)) < 1e-12
    assert ann.net_contributions == 3000.0 and ann.end_value == 3300.0
    assert [h.symbol for h in ann.holdings] == ["Fixed annuity"]
    # month-end values grow to the ending value's neighbourhood
    assert rep.values[0] > 3000 and abs(rep.values[-1] - 3300) < 30


def test_table_and_holdings_show_na_and_one_line(tmp_path):
    reg = _reg(tmp_path)
    st, _ = store(tmp_path)
    runs = run_all(reg, tmp_path, st, "IDX", TODAY)
    out = Console(record=True, width=240)
    print_table(runs, "IDX", out, [], combine_all(runs, st, "IDX"))
    print_holdings(runs, {}, out)
    text = out.export_text()
    line = next(ln for ln in text.splitlines() if "Annuity" in ln and "roth_ira" in ln)
    assert "n/a" not in line and "$3,300" in line and "$3,000" in line
    assert "Fixed annuity" in text


def test_annuity_counts_in_all_accounts(tmp_path):
    reg = _reg(tmp_path)
    st, _ = store(tmp_path)
    runs = run_all(reg, tmp_path, st, "IDX", TODAY)
    allg = next(g for g in combine_all(runs, st, "IDX") if g.name == "All accounts")
    assert allg.error == "" and allg.report.irr is not None
    assert allg.report.contributed >= 3000.0
    without = next(g for g in combine_all(runs[:-1], st, "IDX") if g.name == "All accounts")
    assert allg.end_value > without.end_value and (allg.report.contributed - without.report.contributed) == 3000.0


def test_dashboard_annuity_has_benchmark_but_no_price_history_measures(tmp_path):
    reg = _reg(tmp_path)
    st, _ = store(tmp_path)
    runs = run_all(reg, tmp_path, st, "IDX", TODAY)
    series, _ = st.report(["IDX"], TODAY.replace(year=2019), TODAY)
    data = build_data(runs, combine_all(runs, st, "IDX", singletons=True), "IDX", series["IDX"], {}, TODAY)
    ann = next(e for e in data["entities"] if e["label"] == "Annuity")
    assert ann["market"] is False and ann["bench"] == []
    for w in ann["windows"].values():
        if w:
            assert w["irr"] is not None
            assert w["excess"] is not None and w["bench_end"] is not None and w["bench_irr"] is not None
            assert all(w[k] is None for k in ("twr", "sharpe", "dd"))
    assert ann["holdings"]["rows"][0]["symbol"] == "Fixed annuity"
    render(data)


def test_job_runs_end_to_end(tmp_path, monkeypatch):
    reg = _reg(tmp_path)
    (tmp_path / ".data").mkdir()
    (tmp_path / ".data" / "accounts.json").write_text(reg.model_dump_json())
    st, _ = store(tmp_path)
    assert portfolio_compare.main(["--root", str(tmp_path), "--benchmark", "IDX", "--out", "dash.html"], store=st, today=TODAY) in (0, 1)
    page = (tmp_path / "dash.html").read_text()
    blob = json.loads(re.search(r'id="data" type="application/json">(.*?)</script>', page, re.S).group(1))
    assert any(e["label"] == "Annuity" and not e["market"] for e in blob["entities"])

"""Every account in one run, on invented files: two accounts from one Fidelity export, one from a toy importer. No network."""
from datetime import date, timedelta

from rich.console import Console

from jobs import portfolio_compare
from ufo import importers
from ufo.accounts.registry import Registry, registry_path
from ufo.performance.compare import run_all, unmatched_rows
from ufo.providers.prices import Point, PriceStore
from tests.test_importers import ToyImporter

HEADER = ("Run Date,Account Number,Action,Symbol,Description,Type,Exchange Quantity,Exchange Currency,Currency,Price,"
          "Quantity,Exchange Rate,Commission,Fees,Accrued Interest,Amount,Cash Balance,Settlement Date")
TODAY = date(2022, 6, 1)


def _daily(growth, base=100.0):
    return [Point(day=date(2020, 1, 1) + timedelta(days=i), value=base * (1 + growth) ** i, close=base * (1 + growth) ** i) for i in range(1000)]


class Fake:
    def __init__(self):
        self.data = {"ACME": _daily(0.0004), "IDX": _daily(0.0005)}
        self.calls = []

    def fetch(self, symbol, start, end):
        self.calls.append(symbol)
        return [p for p in self.data[symbol] if start <= p.day <= end]

    def fetch_risk_free(self, start, end):
        return [Point(day=date(2020, 1, 1) + timedelta(days=i), value=2.0) for i in range(1000)]


def row(d, acct, action, sym="", price="", qty="", amount=""):
    return f"{d},{acct},{action},{sym},x,Cash,0,USD,USD,{price},{qty},0,,,,{amount},,"


def setup(tmp_path, accounts):
    (tmp_path / "fid").mkdir(exist_ok=True)
    rows = [
        row("01/10/2020", "Z00000042", "Electronic Funds Transfer Received (Cash)", amount="10000"),
        row("01/13/2020", "Z00000042", "YOU BOUGHT ACME (ACME) (Cash)", "ACME", "100.5", "90", "-9045"),
        row("02/03/2020", "Z00000077", "Electronic Funds Transfer Received (Cash)", amount="5000"),
        row("06/30/2021", "Z00000077", "Electronic Funds Transfer Paid (Cash)", amount="-5100"),
        row("03/03/2020", "Z00000099", "Electronic Funds Transfer Received (Cash)", amount="1"),  # in no registry entry
    ]
    (tmp_path / "fid" / "History.csv").write_text("\n" + HEADER + "\n" + "\n".join(reversed(rows)) + "\n")
    (tmp_path / "toy").mkdir(exist_ok=True)
    (tmp_path / "toy" / "t.csv").write_text("date,type,symbol,qty,price,amount\n2020-03-02,deposit,,,,2000\n2020-03-03,buy,ACME,10,,-1000\n")
    importers.register(ToyImporter())
    base = {"importer": "fidelity", "history_glob": "fid/History*.csv"}
    defs = {
        "a": dict(id="a", label="Alpha", brokerage="fidelity", last_digits="0042", source=base,
                  ending_value={"kind": "statement", "value": 12000.0, "as_of": "2022-05-31"}),
        "b": dict(id="b", label="Beta", brokerage="fidelity", last_digits="0077", source=base, closed="2021-06-30"),
        "c": dict(id="c", label="Gamma", brokerage="toy", wrapper="roth_ira", source={"importer": "toy", "history_glob": "toy/*.csv"},
                  ending_value={"kind": "statement", "value": 1500.0, "as_of": "2022-05-31"}),
    }
    return Registry.model_validate({"accounts": [defs[k] for k in accounts]})


def store(tmp_path):
    f = Fake()
    return PriceStore(tmp_path / "cache", f, today=TODAY), f


def test_three_accounts_two_from_one_export_one_from_the_toy_importer(tmp_path):
    reg = setup(tmp_path, "abc")
    st, fake = store(tmp_path)
    runs = run_all(reg, tmp_path, st, "IDX", TODAY)
    assert [r.error for r in runs] == ["", "", ""]
    a, b, c = runs
    assert a.result.report.contributed == 10000.0 and a.quality == "exact"
    assert b.end == date(2021, 6, 30) and b.end_value == 0.0 and "closed" in b.flags
    assert b.result.report.withdrawn == 5100.0 and b.result.report.irr is not None
    assert c.account.wrapper.value == "roth_ira" and c.result.report.contributed == 2000.0
    assert {e.account_id for e in a.events} == {"a"}  # the other accounts' rows were split away
    assert fake.calls.count("ACME") <= 3 and fake.calls.count("IDX") <= 3
    out = Console(record=True, width=200)
    from ufo.performance.compare import print_table
    print_table(runs, "IDX", out)
    text = out.export_text()
    assert "Alpha" in text and "Beta" in text and "Gamma" in text and "Information, not investment advice" in text


def test_missing_ending_value_names_the_account_and_does_not_compute(tmp_path):
    reg = setup(tmp_path, "ac")
    reg.accounts[0].ending_value = None
    st, _ = store(tmp_path)
    a, c = run_all(reg, tmp_path, st, "IDX", TODAY)
    assert a.result is None and "no ending value" in a.error and c.result is not None


def test_stale_ending_value_is_refused(tmp_path):
    reg = setup(tmp_path, "a")
    st, _ = store(tmp_path)
    (a,) = run_all(reg, tmp_path, st, "IDX", date(2022, 8, 30))
    assert a.result is None and "older than" in a.error


def test_missing_files_and_short_history_are_plain(tmp_path):
    reg = setup(tmp_path, "a")
    reg.accounts[0].source.history_glob = "nowhere/*.csv"
    st, _ = store(tmp_path)
    assert "no history files match" in run_all(reg, tmp_path, st, "IDX", TODAY)[0].error
    reg2 = setup(tmp_path, "c")
    reg2.accounts[0].ending_value.as_of = date(2020, 4, 1)
    (c,) = run_all(reg2, tmp_path, st, "IDX", date(2020, 4, 20))
    assert "short history" in c.flags


def test_rows_for_unknown_accounts_are_reported(tmp_path):
    reg = setup(tmp_path, "ab")
    assert any("not in the registry" in m for m in unmatched_rows(reg, tmp_path))


def test_job_prints_the_table_and_reports_a_bad_registry(tmp_path, capsys):
    reg = setup(tmp_path, "abc")
    p = registry_path(tmp_path)
    p.parent.mkdir()
    p.write_text(reg.model_dump_json())
    st, _ = store(tmp_path)
    assert portfolio_compare.main(["--root", str(tmp_path), "--benchmark", "IDX"], st, TODAY) == 0
    p.write_text("{bad")
    assert portfolio_compare.main(["--root", str(tmp_path)], st, TODAY) == 2

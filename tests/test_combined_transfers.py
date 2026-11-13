"""Combined-view transfer matching on invented accounts (issues 115 to 120): unflagged amount-only pairs are named as
assumed and match only to the cent, multi-lot share moves net out, a transfer spanning a month end leaves no dip, and
each note prints once with its groups."""
from datetime import date

from rich.console import Console

from tests.test_importers import ToyImporter
from tests.test_portfolio_compare import TODAY, store
from ufo import importers
from ufo.accounts.registry import Registry
from ufo.performance.combine import combine, combine_all, in_transit, net_transfers
from ufo.performance.compare import print_table, run_all
from ufo.providers.fidelity_history import parse_fidelity_history

HEAD = "date,type,symbol,qty,price,amount\n"


def build(tmp_path, files):
    importers.register(ToyImporter())
    accts = []
    for k, text in files.items():
        (tmp_path / k).mkdir(exist_ok=True)
        (tmp_path / k / "x.csv").write_text(HEAD + text)
        d = dict(id=k, label=k.upper(), brokerage="toy", owner="partner" if k == "c" else "owner", source={"importer": "toy", "history_glob": f"{k}/*.csv"},
                 ending_value={"kind": "statement", "value": 9000.0, "as_of": "2022-05-31"})
        accts.append(d)
    return Registry.model_validate({"accounts": accts})


def runs_for(tmp_path, files):
    st, _ = store(tmp_path)
    return st, run_all(build(tmp_path, files), tmp_path, st, "IDX", TODAY)


def test_unflagged_pair_is_named_assumed_and_unrelated_amounts_do_not_net(tmp_path):
    files = {"a": "2020-02-03,deposit,,,,10000\n2021-04-01,withdraw,,,,-5000\n2021-05-01,withdraw,,,,-2000\n",
             "b": "2020-03-02,deposit,,,,4000\n2021-04-03,deposit,,,,5000\n2021-05-02,deposit,,,,2003\n"}
    st, runs = runs_for(tmp_path, files)
    matches, _ = net_transfers(runs)
    assert len(matches) == 1 and matches[0].assumed and abs(matches[0].outs[0].amount) == 5000.0  # the 2003 vs 2000 pair is not netted
    g = combine("all", "All accounts", runs, st, "IDX")
    assert [t.assumed for t in g.transfers] == [True]
    out = Console(record=True, width=200)
    print_table(runs, "IDX", out, [], [g])
    assert "assumed internal" in out.export_text()


def test_flagged_pair_matches_within_one_percent_and_is_not_assumed(tmp_path):
    files = {"a": "2020-02-03,deposit,,,,10000\n2021-04-01,transfer_out,,,,-5000\n",
             "b": "2020-03-02,deposit,,,,4000\n2021-04-03,transfer_in,,,,4980\n"}
    _, runs = runs_for(tmp_path, files)
    matches, _ = net_transfers(runs)
    assert len(matches) == 1 and not matches[0].assumed


def test_fidelity_transfer_rows_are_flagged():
    head = "Run Date,Account,Action,Symbol,Description,Type,Quantity,Price ($),Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date\n"
    rows = ("04/02/2020,Z00000001,TRANSFERRED TO VS Z00-000000-0 (Cash),,No Description,Cash,300,,,,,-300.00,719.99,\n"
            "04/03/2020,Z00000001,Electronic Funds Transfer Received (Cash),,No Description,Cash,100,,,,,100.00,819.99,\n")
    ev = parse_fidelity_history(head + rows).events
    assert [(e.kind.value, e.transfer_hint) for e in ev] == [("withdrawal", True), ("contribution", False)]


def test_unmatched_fidelity_style_transfer_shows_in_notes(tmp_path):
    files = {"a": "2020-02-03,deposit,,,,10000\n2021-04-01,transfer_out,,,,-777\n", "b": "2020-03-02,deposit,,,,4000\n"}
    st, runs = runs_for(tmp_path, files)
    g = combine("all", "All accounts", runs, st, "IDX")
    assert len(g.unmatched) == 1 and "777.00" in g.unmatched[0]


def test_multi_lot_share_transfer_nets_out_eight_days_apart(tmp_path):
    files = {"a": "2020-02-03,deposit,,,,10000\n2021-04-01,transfer_out,ACME,3,,-300\n2021-04-02,transfer_out,ACME,2,,-200\n",
             "b": "2020-03-02,deposit,,,,4000\n2021-04-10,transfer_in,ACME,5,,500\n"}
    st, runs = runs_for(tmp_path, files)
    matches, un = net_transfers(runs)
    assert len(matches) == 1 and len(matches[0].outs) == 2 and len(matches[0].ins) == 1 and un == []
    g = combine("all", "All accounts", runs, st, "IDX")
    assert g.error == "" and len(g.transfers) == 1 and g.transfers[0].amount == 500.0
    assert g.report.withdrawn == 0.0  # the move is internal: no outflow in the combined line


def test_share_lots_that_do_not_add_up_stay_unmatched(tmp_path):
    files = {"a": "2020-02-03,deposit,,,,10000\n2021-04-01,transfer_out,ACME,3,,-300\n2021-04-02,transfer_out,ACME,2,,-200\n",
             "b": "2020-03-02,deposit,,,,4000\n2021-04-10,transfer_in,ACME,4,,400\n"}
    _, runs = runs_for(tmp_path, files)
    matches, un = net_transfers(runs)
    assert matches == [] and len(un) == 3


def test_transfer_spanning_a_month_end_leaves_combined_value_unchanged(tmp_path):
    files = {"a": "2020-02-03,deposit,,,,10000\n2021-01-30,transfer_out,,,,-1000\n",
             "b": "2020-03-02,deposit,,,,4000\n2021-02-03,transfer_in,,,,1000\n"}
    st, runs = runs_for(tmp_path, files)
    matches, _ = net_transfers(runs)
    jan = date(2021, 1, 31)
    assert in_transit(matches, [jan, date(2021, 2, 28)]) == {jan: 1000.0}
    g = combine("all", "All accounts", runs, st, "IDX")
    i = g.report.months.index(jan)
    members = sum(r.result.report.values[r.result.report.months.index(jan)] for r in runs)
    assert abs(g.report.values[i] - (members + 1000.0)) < 1e-6


def test_each_unmatched_note_prints_once_with_its_groups(tmp_path):
    files = {"a": "2020-02-03,deposit,,,,10000\n2021-04-01,transfer_out,,,,-777\n", "b": "2020-03-02,deposit,,,,4000\n",
             "c": "2020-03-02,deposit,,,,4000\n"}
    st, runs = runs_for(tmp_path, files)
    groups = combine_all(runs, st, "IDX")
    assert sum(len(g.unmatched) for g in groups) > 1  # the same transfer is in several groups
    out = Console(record=True, width=300)
    print_table(runs, "IDX", out, [], groups)
    text = out.export_text()
    assert text.count("777.00") == 1 and "(in All accounts, " in text

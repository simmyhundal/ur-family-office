"""Combined lines on invented accounts: an in-kind transfer and a cash transfer between two accounts net out; a closed
account contributes its history up to closing. The combined IRR equals the IRR computed by hand on the netted flows."""
from datetime import date

from tests.test_importers import ToyImporter
from tests.test_portfolio_compare import TODAY, store
from ufo import importers
from ufo.accounts.registry import Registry
from ufo.performance import metrics as M
from ufo.performance.combine import combine, combine_all, net_transfers
from ufo.performance.compare import run_all

FILES = {
    "a": ("date,type,symbol,qty,price,amount\n2020-02-03,deposit,,,,10000\n2020-02-04,buy,ACME,50,,-5000\n"
          "2021-01-04,withdraw,,,,-500\n2021-06-01,transfer_out,ACME,5,,-520\n2021-06-15,transfer_out,,,,-50\n"),
    "b": "date,type,symbol,qty,price,amount\n2020-03-02,deposit,,,,4000\n2021-01-06,deposit,,,,500\n2021-06-02,transfer_in,ACME,5,,515\n",
    "c": "date,type,symbol,qty,price,amount\n2020-02-10,deposit,,,,3000\n2021-03-01,withdraw,,,,-3100\n",
}


def build(tmp_path):
    importers.register(ToyImporter())
    accts = []
    for k, text in FILES.items():
        (tmp_path / k).mkdir(exist_ok=True)
        (tmp_path / k / "x.csv").write_text(text)
        d = dict(id=k, label=k.upper(), brokerage="toy", owner="owner" if k != "b" else "partner",
                 source={"importer": "toy", "history_glob": f"{k}/*.csv"})
        d["wrapper"] = "roth_ira" if k == "b" else "taxable"
        if k == "c":
            d["closed"] = "2021-03-01"
        else:
            d["ending_value"] = {"kind": "statement", "value": 9000.0 if k == "a" else 5000.0, "as_of": "2022-05-31"}
        accts.append(d)
    return Registry.model_validate({"accounts": accts})


def test_transfers_net_out_and_combined_irr_matches_hand_calculation(tmp_path):
    st, _ = store(tmp_path)
    runs = run_all(build(tmp_path), tmp_path, st, "IDX", TODAY)
    assert all(r.result for r in runs), [r.error for r in runs]
    g = combine("all", "All accounts", runs, st, "IDX")
    assert g.error == ""
    # matched: the cash move (2 days apart) and the in-kind move of 5 ACME (different values on each side)
    assert {(t.amount, t.symbol) for t in g.transfers} == {(500.0, ""), (520.0, "ACME")}
    # the 50 outflow that matches nothing is listed, not guessed
    assert len(g.unmatched) == 1 and "50.00" in g.unmatched[0]
    by_hand = [(date(2020, 2, 3), 10000.0), (date(2020, 3, 2), 4000.0), (date(2020, 2, 10), 3000.0),
               (date(2021, 3, 1), -3100.0), (date(2021, 6, 15), -50.0)]
    assert g.end == date(2022, 5, 31) and g.end_value == 14000.0
    expected = M.xirr(M.investor_flows(sorted(by_hand), g.end, 14000.0))
    assert abs(g.report.irr - expected) < 1e-9
    assert g.report.contributed == 17000.0 and g.report.withdrawn == 3150.0
    # each account alone still sees the transfer as an external flow
    a = next(r for r in runs if r.account.id == "a")
    assert -520.0 in [e.external_flow for e in a.events]


def test_group_with_different_end_dates_or_failed_member_is_refused_by_name(tmp_path):
    st, _ = store(tmp_path)
    reg = build(tmp_path)
    reg.accounts[1].ending_value.as_of = date(2022, 5, 20)
    runs = run_all(reg, tmp_path, st, "IDX", TODAY)
    g = combine("all", "All", runs, st, "IDX")
    assert g.error == "" and g.end == date(2022, 4, 30) and "last month-end every account covers" in g.note
    assert g.quality == "estimated" and all(f[0] <= g.end for f in g.flows)
    reg.accounts[0].ending_value = None
    runs = run_all(reg, tmp_path, st, "IDX", TODAY)
    err = combine("all", "All", runs, st, "IDX").error
    assert "A:" in err and "no ending value" in err


def test_groups_by_owner_and_wrapper_only_when_two_or_more(tmp_path):
    st, _ = store(tmp_path)
    runs = run_all(build(tmp_path), tmp_path, st, "IDX", TODAY)
    names = [g.name for g in combine_all(runs, st, "IDX")]
    assert names == ["All accounts", "owner: owner", "wrapper: taxable"]  # partner and roth_ira hold one account each


def test_only_matching_opposite_flows_in_different_accounts_pair_up(tmp_path):
    st, _ = store(tmp_path)
    runs = run_all(build(tmp_path), tmp_path, st, "IDX", TODAY)
    pairs, _ = net_transfers([r for r in runs if r.account.id in ("a", "c")])  # no counterpart in this group
    assert pairs == []


def test_group_with_no_common_month_end_is_refused_by_name(tmp_path):
    st, _ = store(tmp_path)
    reg = build(tmp_path)
    reg.accounts[1].ending_value.as_of = date(2022, 5, 20)
    runs = run_all(reg, tmp_path, st, "IDX", TODAY)
    runs[1].result.report.months = [date(2030, 1, 31)]  # invented: B covers only a later month
    err = combine("all", "All", runs, st, "IDX").error
    assert "no month-end is covered by every account" in err and "B from" in err

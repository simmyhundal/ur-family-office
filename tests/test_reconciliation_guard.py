"""Issue 189: an account whose rebuilt values do not match its own snapshots or statements is labeled, left out of
windowed figures and combined lines, and named there. All data invented."""
from rich.console import Console

from tests.test_combined_view import build
from tests.test_portfolio_compare import TODAY, store
from ufo.performance import compare as C
from ufo.performance.combine import combine_all
from ufo.performance.compare import UNRECONCILED, print_table, run_all
from ufo.performance.dashboard import build_data, render as render_page


def _runs(tmp_path):
    st, _ = store(tmp_path)
    return st, run_all(build(tmp_path), tmp_path, st, "IDX", TODAY)


def test_a_rebuild_more_than_two_percent_off_is_flagged(tmp_path, monkeypatch):
    real = C.run_core

    def off(*a, **k):
        res = real(*a, **k)
        res.reconciliation = [{"when": TODAY, "source": "positions snapshot", "reference": 1000.0, "rebuilt": 1500.0,
                               "diff": 500.0, "pct": 0.5, "ok": False, "unpriced": []}]
        return res
    monkeypatch.setattr(C, "run_core", off)
    _, runs = _runs(tmp_path)
    assert all(r.unreconciled and r.quality == UNRECONCILED for r in runs if r.result)
    assert "+50%" in runs[0].unreconciled


def test_a_rebuild_within_two_percent_is_trusted(tmp_path, monkeypatch):
    real = C.run_core

    def near(*a, **k):
        res = real(*a, **k)
        res.reconciliation = [{"when": TODAY, "source": "positions snapshot", "reference": 1000.0, "rebuilt": 1015.0,
                               "diff": 15.0, "pct": 0.015, "ok": True, "unpriced": []}]
        return res
    monkeypatch.setattr(C, "run_core", near)
    _, runs = _runs(tmp_path)
    assert not any(r.unreconciled for r in runs)


def test_unreconciled_account_is_named_and_left_out_of_groups_windows_and_terminal(tmp_path):
    st, runs = _runs(tmp_path)
    a = next(r for r in runs if r.account.id == "a")
    a.unreconciled, a.quality = "the rebuilt value is +50% from the positions snapshot", UNRECONCILED
    groups = combine_all(runs, st, "IDX", singletons=True)
    allg = next(g for g in groups if g.kind == "all")
    assert allg.excluded == ["A"] and "left out, does not reconcile: A" in allg.note and "a" in allg.members
    data = build_data([r for r in runs if r.result], groups, "IDX", st.report(["IDX"], TODAY.replace(year=2019), TODAY)[0]["IDX"], {}, TODAY)
    ea = next(e for e in data["entities"] if e["label"] == "A")
    assert ea["unreconciled"] and ea["months"] is None
    assert ea["windows"]["1y"] is None and ea["windows"]["inception"]["twr"] is None and ea["windows"]["inception"]["irr"] is not None
    page = render_page(data)
    assert "does not reconcile" in page
    out = Console(record=True, width=200)
    print_table(runs, "IDX", out, None, groups)
    assert "does not reconcile" in out.export_text()

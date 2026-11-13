"""Dashboard polish (issue 138) on invented data: entities in fund names, holdings gaps, fund classes, narrow terminal,
institution grouping, the non-market combined label, and numbered risk labels."""
import json
import re
import shutil
import subprocess

from rich.console import Console

from tests.test_dashboard import make
from tests.test_nonmarket_account import _reg
from tests.test_portfolio_compare import TODAY, setup, store
from ufo.accounts.registry import Registry
from ufo.performance.combine import combine_all, groups
from ufo.performance.compare import print_table, run_all
from ufo.performance.holdings import Holding, classify, print_holdings

NODE = shutil.which("node")


def test_fund_name_entities_are_unescaped():
    h = Holding(symbol="ACME", name="ACME S&amp;P 500 INDEX", value=10.0)
    assert h.name == "ACME S&P 500 INDEX"


def test_global_and_balanced_funds_get_their_own_classes():
    assert classify(Holding(symbol="ZZZZX", name="Acme World Stock Fund", value=1), {}) == "global_stock"
    assert classify(Holding(symbol="ZZZYX", name="Acme Balanced Fund", value=1), {}) == "balanced"
    assert classify(Holding(symbol="ZZZWX", name="Acme Total International Stock", value=1), {}) == "unclassified"
    assert classify(Holding(symbol="ZZZZX", name="Acme World Stock Fund", value=1), {"ZZZZX": "us_stock"}) == "us_stock"


def test_account_without_holdings_says_so(tmp_path):
    reg = setup(tmp_path, "abc")  # account c uses the toy importer, which lists no positions
    st, _ = store(tmp_path)
    runs = run_all(reg, tmp_path, st, "IDX", TODAY)
    toy = runs[2]
    assert "not available" in toy.holdings_note
    out = Console(record=True, width=200)
    print_holdings(runs, {}, out)
    assert "holdings not available" in out.export_text()


def test_narrow_terminal_drops_columns_keeps_values(tmp_path):
    reg = setup(tmp_path, "abc")
    st, _ = store(tmp_path)
    runs = run_all(reg, tmp_path, st, "IDX", TODAY)
    narrow, wide = Console(record=True, width=80), Console(record=True, width=200)
    print_table(runs, "IDX", narrow, [], combine_all(runs, st, "IDX"))
    print_table(runs, "IDX", wide, [], combine_all(runs, st, "IDX"))
    assert "Type" in wide.export_text() and "Type" not in narrow.export_text()
    assert "IRR" in narrow.export_text()


def test_institution_groups_manual_accounts_and_defaults_to_brokerage(tmp_path):
    reg = _reg(tmp_path)
    assert all(a.institution_name == a.brokerage for a in reg.accounts)
    d = [a.model_dump(mode="json") for a in reg.accounts]
    d[-1]["institution"] = "Acme Insurance"
    reg2 = Registry.model_validate({"accounts": d})
    assert reg2.accounts[-1].institution_name == "acme insurance"
    st, _ = store(tmp_path)
    runs = run_all(reg2, tmp_path, st, "IDX", TODAY)
    assert not any(n == "brokerage: manual" for _, n, _ in groups(runs, singletons=True))
    assert any(n == "brokerage: acme insurance" for _, n, _ in groups(runs, singletons=True))


def test_combined_rows_with_a_nonmarket_account_are_labelled(tmp_path):
    reg = _reg(tmp_path)
    st, _ = store(tmp_path)
    runs = run_all(reg, tmp_path, st, "IDX", TODAY)
    allg = next(g for g in combine_all(runs, st, "IDX") if g.name == "All accounts")
    assert "includes non-market accounts" in allg.note
    without = next(g for g in combine_all(runs[:-1], st, "IDX") if g.name == "All accounts")
    assert "non-market" not in without.note


def test_risk_chart_uses_numbered_labels_with_a_legend(tmp_path):
    _, out = make(tmp_path, also=["ACME"])
    page = out.read_text()
    script = page.split("<script>")[1].split("</script>")[0]
    blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
    harness = f"""
const els = {{}};
const el = id => els[id] || (els[id] = {{innerHTML:'', textContent:'', hidden:false, querySelectorAll:()=>[], set onchange(f){{}}}});
global.document = {{getElementById: id => id==='data' ? {{textContent: {json.dumps(blob)}}} : el(id),
  querySelector: s => el(s), querySelectorAll: () => [], documentElement: {{}}}};
{script}
const h = els['#risk'].innerHTML;
const texts = [...h.matchAll(/<text class="axis"[^>]*y="[^"]*">(\\d+)<\\/text>/g)].map(m => m[1]);
console.log(texts.length > 1, h.includes('<ol'), h.includes('All accounts'), !h.includes('· S '));
"""
    f = tmp_path / "h.js"
    f.write_text(harness)
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["true"] * 4

"""Risk vs return scatter (issue 129) on invented data: whole portfolio and benchmarks plotted, non-market account listed, not plotted."""
import re
import shutil
import subprocess

import pytest

from jobs import portfolio_compare
from tests.test_dashboard import data_of, make
from tests.test_nonmarket_account import _reg
from tests.test_portfolio_compare import TODAY, store
from ufo.accounts.registry import registry_path

NODE = shutil.which("node")


def test_points_for_accounts_all_and_benchmarks(tmp_path):
    code, out = make(tmp_path, also=["ACME"])
    assert code == 0
    page = out.read_text()
    assert "Risk versus return" in page and 'id="risk"' in page
    risk = data_of(page)["risk"]
    by = {p["label"]: p for p in risk["points"]}
    assert by["All accounts"]["kind"] == "all" and by["IDX"]["kind"] == "benchmark" and by["ACME"]["kind"] == "benchmark"
    for p in by.values():
        assert p["vol"] >= 0 and p["ret"] is not None
    assert by["A"]["kind"] == "account" and by["A"]["exact"] in (True, False)
    assert "Information, not investment advice" in page


def test_non_market_account_is_listed_not_plotted(tmp_path):
    reg = _reg(tmp_path)
    p = registry_path(tmp_path)
    p.parent.mkdir(exist_ok=True)
    p.write_text(reg.model_dump_json())
    st, _ = store(tmp_path)
    assert portfolio_compare.main(["--root", str(tmp_path), "--benchmark", "IDX"], st, TODAY) == 0
    risk = data_of((tmp_path / "exports" / "portfolio-compare.html").read_text())["risk"]
    assert "Annuity" not in {p["label"] for p in risk["points"]}
    assert ["Annuity", "non-market account: no volatility"] in risk["left_off"]
    assert "All accounts" in {p["label"] for p in risk["points"]}


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_chart_renders_in_page_script(tmp_path):
    _, out = make(tmp_path, also=["ACME"])
    page = out.read_text()
    script = page.split("<script>")[1].split("</script>")[0]
    blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
    import json
    harness = f"""
const els = {{}};
const el = id => els[id] || (els[id] = {{innerHTML:'', textContent:'', hidden:false, querySelectorAll:()=>[], set onchange(f){{}}}});
global.document = {{getElementById: id => id==='data' ? {{textContent: {json.dumps(blob)}}} : el(id),
  querySelector: s => el(s), querySelectorAll: () => [], documentElement: {{}}}};
{script}
const h = els['#risk'].innerHTML;
console.log(h.includes('<svg'), h.includes('All accounts'), h.includes('IDX'), h.includes('<title>'), h.includes('class="hollow"')||h.includes('class="solid"'));
"""
    f = tmp_path / "h.js"
    f.write_text(harness)
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["true"] * 5

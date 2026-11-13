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
    risk = data_of(page)["risk"]["inception"]
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
    risk = data_of((tmp_path / "exports" / "portfolio-compare.html").read_text())["risk"]["inception"]
    assert "Annuity" not in {p["label"] for p in risk["points"]}
    assert ["Annuity", "non-market account: no volatility", "account", ""] in risk["left_off"]
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


def test_every_window_has_chart_and_risk_data(tmp_path):
    _, out = make(tmp_path)
    d = data_of(out.read_text())
    assert set(d["risk"]) == {"ytd", "1y", "3y", "5y", "inception"}
    a = next(e for e in d["entities"] if e["label"] == "A" and e["kind"] == "account")
    w = a["windows"]["1y"]
    assert len(w["chart"]["months"]) == len(w["chart"]["values"]) == len(w["chart"]["bench"]) and w["chart"]["months"][0] >= "2000"
    assert len(w["chart"]["months"]) < len(a["months"])  # cropped to the window
    assert set(w["risk"]) == {"vol", "ret", "sharpe"}
    assert all(p["kind"] in ("account", "group", "all", "benchmark") for p in d["risk"]["1y"]["points"])


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_charts_follow_window_and_grouping(tmp_path):
    import json
    _, out = make(tmp_path)
    page = out.read_text()
    script = page.split("<script>")[1].split("</script>")[0]
    blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
    harness = f"""
const els = {{}};
const el = id => els[id] || (els[id] = {{innerHTML:'', textContent:'', hidden:false, querySelectorAll:()=>[], set onchange(f){{}}}});
global.document = {{getElementById: id => id==='data' ? {{textContent: {json.dumps(blob)}}} : el(id),
  querySelector: s => el(s), querySelectorAll: () => [], documentElement: {{}}}};
{script}
const out = {{}};
const snap = () => [els['#lines'].innerHTML.length, (els['#risk'].innerHTML.match(/class="pt pt-account"/g)||[]).length, (els['#risk'].innerHTML.match(/class="pt pt-group"/g)||[]).length];
win='inception'; grp='accounts'; draw(); out.acct = snap();
win='1y'; draw(); out.acct1y = snap();
win='inception'; grp='owner'; draw(); out.owner = snap();
for (const g of ['all','brokerage','owner','wrapper']) {{ grp=g; win='inception'; draw(); out['acct_in_'+g] = snap()[1]; }}
console.log(JSON.stringify(out));
"""
    f = tmp_path / "h.js"
    f.write_text(harness)
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["acct"][0] != o["acct1y"][0]  # the value chart changed with the window
    assert all(o["acct_in_" + g] == 0 for g in ("all", "brokerage", "owner", "wrapper"))  # combined views show no individual account points
    assert o["acct"][2] == 0 and o["owner"][1] == 0  # accounts view has no group points; group view has no account points

"""The comparison dashboard from an invented three-account registry: data for every window and grouping, a 0600 file,
and the page script runs (checked with node when available)."""
import json
import re
import shutil
import stat
import subprocess

import pytest

from jobs import portfolio_compare
from tests.test_combined_view import build
from tests.test_portfolio_compare import TODAY, store
from ufo.accounts.registry import registry_path

NODE = shutil.which("node")


def make(tmp_path, capsys=None, also=()):
    reg = build(tmp_path)
    p = registry_path(tmp_path)
    p.parent.mkdir(exist_ok=True)
    p.write_text(reg.model_dump_json())
    st, _ = store(tmp_path)
    args = ["--root", str(tmp_path), "--benchmark", "IDX"] + [x for a in also for x in ("--also", a)]
    code = portfolio_compare.main(args, st, TODAY)
    return code, tmp_path / "exports" / "portfolio-compare.html"


def data_of(page):
    return json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1).replace("<\\/", "</"))


def test_one_command_writes_a_private_page_with_every_window_and_grouping(tmp_path):
    code, out = make(tmp_path, also=["ACME"])
    assert code == 0 and out.exists()
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    page = out.read_text()
    assert "Information, not investment advice" in page
    d = data_of(page)
    labels = {e["label"] for e in d["entities"]}
    assert {"A", "B", "C", "All accounts", "wrapper: taxable", "owner: owner"} <= labels
    a = next(e for e in d["entities"] if e["label"] == "A" and e["kind"] == "account")
    assert set(a["windows"]) == {"ytd", "1y", "3y", "5y", "inception"}
    assert a["windows"]["inception"]["irr"] is not None and a["windows"]["5y"] is None  # started in 2020: does not cover 5y
    assert a["windows"]["1y"] is not None and a["windows"]["1y"]["exact"] is False
    c = next(e for e in d["entities"] if e["label"] == "C" and e["kind"] == "account")
    assert c["closed"] and c["windows"]["1y"] is None and c["windows"]["inception"]["value"] == 0.0
    assert d["extras"] == ["ACME"] and "ACME" in a["windows"]["inception"]["extras"]
    assert 'id="hold"' in page  # the holdings panel replaces the old "not shown" note


def test_no_external_requests_in_the_page(tmp_path):
    _, out = make(tmp_path)
    page = out.read_text()
    assert not re.search(r"<link[^>]+href=|<script[^>]+src=|@import|fetch\(|XMLHttpRequest", page)


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_page_script_renders_every_window_and_grouping(tmp_path):
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
const rs = () => D.entities;
for (const g of ['accounts','all','brokerage','owner','wrapper']) for (const [w] of D.windows) {{ grp=g; win=w; draw(); }}
grp='accounts'; win='inception'; draw();
console.log(els['#tbl'].innerHTML.includes('<td>A</td>'), els['#bars'].innerHTML.includes('<svg'), els['#lines'].innerHTML.includes('polyline'));
"""
    f = tmp_path / "h.js"
    f.write_text(harness)
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "true true true"


def test_total_row_and_subtotals_in_page_script(tmp_path):
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
for (const g of ['accounts','owner','all']) {{ grp=g; win='inception'; draw();
  out[g] = [(els['#tbl'].innerHTML.match(/class="total"/g)||[]).length, (els['#tbl'].innerHTML.match(/class="sub"/g)||[]).length, els['#totnote'].textContent]; }}
console.log(JSON.stringify(out));
"""
    f = tmp_path / "h2.js"
    f.write_text(harness)
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["accounts"][:2] == [1, 0] and o["owner"][0] == 1 and o["owner"][1] >= 1 and o["all"][0] == 0
    assert "The total is valued on" in o["accounts"][2] and "Non-market" in o["accounts"][2]
    assert "subtotal" in o["owner"][2]


def test_combined_rows_compute_for_a_window_when_the_common_month_end_is_before_today(tmp_path, monkeypatch):
    """Reproduces the YTD bug: a combined line valued at an earlier common month-end used to show 'does not cover this window'."""
    from datetime import timedelta
    real = portfolio_compare.build_data
    monkeypatch.setattr(portfolio_compare, "build_data", lambda runs, groups, bm, idx, ex, asof, *a, **k: real(runs, groups, bm, idx, ex, asof + timedelta(days=60), *a, **k))
    _, out = make(tmp_path)
    d = data_of(out.read_text())
    tot = next(e for e in d["entities"] if e["kind"] == "group" and e["groupKind"] == "all")
    w = tot["windows"]["ytd"]
    assert w is not None and w["exact"] is False and w["open"] is not None
    # the opening value is the sum of the members' month-end values at the opening month
    members = [e for e in d["entities"] if e["kind"] == "account" and e["label"] in tot["members"]]
    opening = sum(e["values"][e["months"].index(w["open"])] for e in members if w["open"] in e["months"])
    assert w["chart"]["values"][0] == pytest.approx(opening, abs=0.02)
    assert w["chart"]["months"][-1] == tot["as_of"] and w["value"] == tot["windows"]["inception"]["value"]
    assert tot["windows"]["5y"] is None  # a measure the history cannot cover stays n/a, the row itself still renders

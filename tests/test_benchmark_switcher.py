"""The benchmark picker on invented data: every benchmark is precomputed, the alternatives equal a hand calculation
against that benchmark's own prices, and the page switches the table, totals and every chart."""
import json
import re
import shutil
import subprocess
from datetime import date

import pytest

from jobs import portfolio_compare
from tests.test_combined_view import build
from tests.test_dashboard import data_of
from tests.test_portfolio_compare import TODAY, Fake, _daily
from ufo.accounts.registry import registry_path
from ufo.performance import metrics as M
from ufo.providers.prices import PriceStore

NODE = shutil.which("node")


def make(tmp_path):
    fake = Fake()
    fake.data.update({"VT": _daily(0.0003), "SPY": _daily(0.0007)})  # QQQ, AOR, BND cannot be loaded: left out of the picker
    st = PriceStore(tmp_path / "cache", fake, today=TODAY)
    p = registry_path(tmp_path)
    p.parent.mkdir(exist_ok=True)
    p.write_text(build(tmp_path).model_dump_json())
    assert portfolio_compare.main(["--root", str(tmp_path), "--benchmark", "IDX"], st, TODAY) == 0
    return (tmp_path / "exports" / "portfolio-compare.html").read_text(), st


def test_picker_lists_loadable_benchmarks_with_the_cli_one_selected_first(tmp_path):
    page, _ = make(tmp_path)
    d = data_of(page)
    assert [b[0] for b in d["benchmarks"]] == ["IDX", "VT", "SPY"] and d["benchmark"] == "IDX"
    assert dict(d["benchmarks"])["VT"] == "Market (VT)"
    assert set(d["lessons"]) == {"VT", "SPY"} and 'id="bms"' in page


def test_alternative_benchmark_numbers_match_a_hand_calculation(tmp_path):
    page, st = make(tmp_path)
    d = data_of(page)
    a = next(e for e in d["entities"] if e["label"] == "A" and e["kind"] == "account")
    spy, _ = st.report(["SPY"], date(2019, 12, 1), date(2022, 5, 31))
    flows = [(date(2020, 2, 3), 10000.0), (date(2021, 1, 4), -500.0), (date(2021, 6, 1), -520.0), (date(2021, 6, 15), -50.0)]
    cf = M.index_counterfactual(flows, spy["SPY"], date(2022, 5, 31))
    w = a["bm"]["SPY"]["inception"]
    assert w["bench_end"] == pytest.approx(cf.terminal_value) and w["bench_irr"] == pytest.approx(cf.irr)
    assert w["excess"] == pytest.approx(a["windows"]["inception"]["irr"] - cf.irr)
    assert len(w["bench"]) == len(a["months"])
    assert a["bm"]["SPY"]["1y"]["excess"] != a["windows"]["1y"]["excess"]  # a different benchmark gives a different windowed excess
    assert "SPY" in d["risk"]["inception"]["bm"] and "IDX" in d["risk"]["inception"]["bm"] and "VT" in d["risk"]["1y"]["bm"]
    assert d["lessons"]["SPY"]["raw"]["benchmark_sharpe"] != d["lesson"]["raw"]["benchmark_sharpe"]


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_page_switches_table_totals_and_charts(tmp_path):
    page, _ = make(tmp_path)
    script = page.split("<script>")[1].split("</script>")[0]
    blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
    harness = f"""
const els = {{}};
const el = id => els[id] || (els[id] = {{innerHTML:'', textContent:'', hidden:false, querySelectorAll:()=>[], set onchange(f){{}}}});
global.document = {{getElementById: id => id==='data' ? {{textContent: {json.dumps(blob)}}} : el(id),
  querySelector: s => el(s), querySelectorAll: () => [], documentElement: {{}}}};
{script}
const snap = () => ({{tbl: els['#tbl'].innerHTML, bars: els['#bars'].innerHTML, lines: els['#lines'].innerHTML, risk: els['#risk'].innerHTML, key: els['#key'].innerHTML}});
const out = {{}};
for (const [w, g] of [['inception','accounts'],['1y','all']]) {{
  win = w; grp = g; bm = 'IDX'; draw(); const a = snap();
  bm = 'SPY'; draw(); const b = snap();
  out[w] = {{tbl: a.tbl !== b.tbl, bars: a.bars !== b.bars, lines: a.lines !== b.lines, risk: a.risk !== b.risk, head: b.tbl.includes('(SPY)'), key: b.key.includes('SPY')}};
}}
bm = 'SPY'; tab = 'sharpe'; draw(); out.lesson = els['#lesson'].innerHTML.includes('SPY');
console.log(JSON.stringify(out));
"""
    f = tmp_path / "s.js"
    f.write_text(harness)
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    for w in ("inception", "1y"):
        assert o[w]["tbl"] and o[w]["head"] and o[w]["lines"] and o[w]["bars"], (w, o[w])
    assert o["inception"]["key"] and o["lesson"]

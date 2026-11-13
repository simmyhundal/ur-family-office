"""The phone-first overview (balance, one chart, where the money came from, account cards, mix, detail sheet) on invented data.
Same figures as the table, honest labels: estimated, closed, non-market and errored accounts stay visible and labelled."""
import json
import re
import shutil
import subprocess

import pytest

from jobs import portfolio_compare
from tests.test_dashboard import data_of, make
from tests.test_nonmarket_account import _reg
from tests.test_portfolio_compare import TODAY, store
from ufo.performance import dashboard

NODE = shutil.which("node")


def run_page(tmp_path, page, body, name="o.js"):
    """Run the page script in node against a thin DOM stub, then `body`; returns the parsed JSON it prints."""
    script = page.split("<script>")[1].split("</script>")[0]
    blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
    harness = f"""
const els = {{}};
const el = id => els[id] || (els[id] = {{innerHTML:'', textContent:'', hidden:false, querySelectorAll:()=>[], set onchange(f){{}}}});
global.document = {{getElementById: id => id==='data' ? {{textContent: {json.dumps(blob)}}} : el(id),
  querySelector: s => el(s), querySelectorAll: () => [], documentElement: {{}}}};
{script}
{body}
"""
    f = tmp_path / name
    f.write_text(harness)
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_deposits_and_withdrawals_add_up_to_net_in_for_every_window(tmp_path):
    _, out = make(tmp_path)
    d = data_of(out.read_text())
    seen = 0
    for e in d["entities"]:
        for k, w in (e.get("windows") or {}).items():
            if w is None:
                continue
            assert w["dep"] >= 0 and w["wd"] >= 0
            assert w["dep"] - w["wd"] == pytest.approx(w["net_in"], abs=0.01), (e["label"], k)
            seen += 1
    assert seen > 10
    a = next(e for e in d["entities"] if e["label"] == "A" and e["kind"] == "account")["windows"]["inception"]
    assert a["dep"] == pytest.approx(10000.0) and a["wd"] == pytest.approx(1070.0)  # the invented flows of account A


def test_combined_line_counts_its_own_flows_not_the_sum_of_its_members(tmp_path):
    """Internal transfers net out of a combined line, so its deposits can be less than the members' deposits added up."""
    _, out = make(tmp_path)
    d = data_of(out.read_text())
    tot = next(e for e in d["entities"] if e["kind"] == "group" and e["groupKind"] == "all")["windows"]["inception"]
    members = [e for e in d["entities"] if e["kind"] == "account" and e.get("windows")]
    assert tot["dep"] - tot["wd"] == pytest.approx(tot["net_in"], abs=0.01)
    assert tot["dep"] <= sum(m["windows"]["inception"]["dep"] for m in members) + 0.01


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_overview_cards_match_rows_and_carry_honest_labels(tmp_path):
    _, out = make(tmp_path)
    page = out.read_text()
    o = run_page(tmp_path, page, """
const res = {};
for (const g of ['accounts','all','brokerage','owner','wrapper']) for (const [w] of D.windows) {
  grp=g; win=w; draw();
  const c = els['#cards'].innerHTML;
  res[g+'/'+w] = [(c.match(/class="acct"/g)||[]).length, rows().length,
    rows().filter(e => !e.error && e.windows && WS(e) && isEst(e, WS(e))).length, (c.match(/chip est/g)||[]).length];
}
grp='accounts'; win='inception'; draw();
res.closed = els['#cards'].innerHTML.includes('Closed');
win='5y'; draw(); res.notOpen = els['#cards'].innerHTML.includes('Not open for this whole period');
win='inception'; draw();
res.hero = els['#hero'].innerHTML; res.src = els['#src'].innerHTML; res.chart = els['#chart'].innerHTML;
console.log(JSON.stringify(res));
""")
    for k, (cards, nrows, est, chips) in ((k, v) for k, v in o.items() if "/" in k):
        assert cards == nrows, k            # one card per row of the table, none filtered out
        assert chips == est, k              # every estimated row says so on its card
    assert o["closed"] and o["notOpen"]
    assert "Estimated" in o["hero"] or "Exact" in o["hero"]
    assert "the same money in" in o["hero"] and "Deposits" in o["src"] and "Withdrawals" in o["src"]
    assert 'class="ar-line"' in o["chart"] and 'id="sc-hero"' in o["chart"]


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_sources_add_up_to_the_value_shown(tmp_path):
    """Opening value + deposits - withdrawals + investment gain = the value, in every window the total covers."""
    _, out = make(tmp_path)
    page = out.read_text()
    o = run_page(tmp_path, page, """
const res = {};
for (const [w] of D.windows) { win=w; draw(); res[w] = els['#src'].innerHTML; }
console.log(JSON.stringify(res));
""")
    d = data_of(page)
    tot = next(e for e in d["entities"] if e["kind"] == "group" and e["groupKind"] == "all")
    checked = 0
    for k, html in o.items():
        w = tot["windows"][k]
        if w is None:
            continue
        nums = {m.group(1): float(m.group(2).replace("−", "-").replace("$", "").replace(",", "").replace("+", ""))
                for m in re.finditer(r'data-k="(\w+)".*?<b[^>]*>([^<]+)</b>', html)}
        total = sum(v for key, v in nums.items())
        assert total == pytest.approx(w["value"], abs=len(nums)), (k, nums)  # each figure is rounded to the dollar
        checked += 1
    assert checked >= 2


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_nonmarket_and_errored_accounts_stay_visible_and_labelled(tmp_path):
    reg = _reg(tmp_path)
    (tmp_path / ".data").mkdir()
    (tmp_path / ".data" / "accounts.json").write_text(reg.model_dump_json())
    st, _ = store(tmp_path)
    portfolio_compare.main(["--root", str(tmp_path), "--benchmark", "IDX", "--out", "dash.html"], store=st, today=TODAY)
    data = data_of((tmp_path / "dash.html").read_text())
    data["entities"].insert(0, {"label": "Broken", "kind": "account", "groupKind": "", "error": "no history file found", "flags": [], "type": "taxable"})
    page = dashboard.render(data)
    o = run_page(tmp_path, page, """
grp='accounts'; win='inception'; draw();
const ann = D.entities.find(e => e.label === 'Annuity');
console.log(JSON.stringify({cards: els['#cards'].innerHTML, hero: els['#hero'].innerHTML, mix: els['#mix'].innerHTML,
  sheet: sheetHtml(ann), broken: sheetHtml(D.entities[0])}));
""")
    assert "Not computed" in o["cards"] and "no history file found" in o["cards"]
    assert "No market prices" in o["cards"]
    assert "non-market" in o["hero"]                      # the total says it includes a non-market account
    assert "Fixed annuity" in o["mix"]
    assert "non-market account: no prices" in o["sheet"]  # n/a reasons shown on screen, not only in a tooltip
    assert "Not computed: no history file found" in o["broken"]


def test_page_footer_keeps_the_disclaimer_and_pre_tax_note():
    page = dashboard.render({"asof": "2026-01-01", "benchmark": "VT", "entities": []})
    foot = page.split('<footer class="foot">')[1].split("</footer>")[0]
    assert "Information, not investment advice. Past performance does not predict future results." in foot
    assert "before tax" in foot and "local only, never sent anywhere" in foot
    assert "prefers-reduced-motion" in page


def test_overview_labels_accounts_that_do_not_reconcile():
    """Issue 189's guard must stay visible in the redesigned overview: cards, the detail sheet and a partial total."""
    from ufo.performance.dashboard import JS
    assert "Does not reconcile" in JS and "e.unreconciled" in JS
    assert "t.excluded" in JS and "Partial" in JS

"""The 'How Sharpe works' tab on invented data: placeholders all filled, the lesson's Sharpe equals the dashboard's and
metrics.sharpe(), n/a with a reason when something cannot be computed, and the slope chart renders."""
import json
import re
import shutil
import subprocess
from datetime import date, timedelta
from statistics import mean, stdev
from types import SimpleNamespace

import pytest

from tests.test_dashboard import data_of, make
from tests.test_nonmarket_account import _reg
from tests.test_portfolio_compare import TODAY, store
from jobs import portfolio_compare
from ufo.accounts.registry import registry_path
from ufo.performance import metrics as M
from ufo.performance import sharpe_lesson as S
from ufo.providers.prices import Point, Series

NODE = shutil.which("node")


def month_ends(n, start=date(2020, 1, 31)):
    out, d = [], start
    for _ in range(n):
        out.append(d)
        nxt = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        d = (nxt + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return out


def fake_report(n=18):
    months = month_ends(n)
    rets = [0.01 + 0.02 * ((i * 7) % 5 - 2) / 2 for i in range(n)]
    idx = [0.008 + 0.015 * ((i * 3) % 4 - 1.5) / 1.5 for i in range(n)]
    vals = [1000.0 * (1 + i / 10) for i in range(n)]
    return SimpleNamespace(months=months, port_returns=rets, index_returns=idx, values=vals, flows_by_month=[50.0] * n), months


def flat_rf(months, pct=3.6):
    return Series(symbol="RF", points=[Point(day=date(2019, 12, 31), value=pct)] + [Point(day=m, value=pct) for m in months])


def test_figures_match_metrics_sharpe_exactly():
    rep, months = fake_report()
    rf = flat_rf(months)
    out = S.portfolio_figures(rep, rf)
    rfm = M.monthly_rf(rf, date(2020, 1, 31))
    ex = [r - rfm for r in rep.port_returns]
    assert out["raw"]["sharpe"] == M.sharpe(ex) == mean(ex) / stdev(ex) * 12 ** 0.5
    assert out["fill"]["sharpe"] == f"{M.sharpe(ex):.2f}"
    assert out["fill"]["mean_excess_month"] == f"{mean(ex) * 100:.2f}%"
    assert out["fill"]["sd_month"] == f"{stdev(ex) * 100:.2f}%"
    # the slope of each chart line is the Sharpe ratio
    p = out["raw"]["points"]
    assert (p["portfolio"]["ret"] - p["rf"]) / p["portfolio"]["vol"] == pytest.approx(out["raw"]["sharpe"])
    bex = [b - rfm for b in rep.index_returns]
    assert (p["benchmark"]["ret"] - p["rf"]) / p["benchmark"]["vol"] == pytest.approx(M.sharpe(bex))
    assert out["fill"]["monthly_table"].count("\n| ") == 12 + 0  # header row plus 12 months, separator excluded by the prefix


def test_example_month_and_table():
    rep, months = fake_report()
    f = S.portfolio_figures(rep, flat_rf(months))["fill"]
    assert f["example_month"] == months[-1].strftime("%B %Y") and f["ex_net_flow"] == "+$50"
    assert f["ex_return"].startswith(("+", "-")) and f["n_months"] == "18"


def test_na_with_reason_when_rf_missing_or_history_short():
    rep, months = fake_report()
    f = S.portfolio_figures(rep, None)["fill"]
    assert f["sharpe"].startswith("n/a⟦") and "T-bill" in f["sharpe"]
    short, m2 = fake_report(6)
    f = S.portfolio_figures(short, flat_rf(m2))["fill"]
    assert f["sharpe"].startswith("n/a⟦") and "12 months" in f["sharpe"]
    assert re.sub(r"n/a⟦.*?⟧", "", f["sharpe"]) == ""


def test_markdown_subset_and_na_rendering():
    h = S.markdown_to_html("## Title\n\n| | |\n|---|---|\n| a | **b** |\n\n- one\n  - nested\n- two\n\nText *it* and n/a⟦no data⟧ <b>")
    assert "<h3>Title</h3>" in h and "<td>a</td><td><strong>b</strong></td>" in h and "<th>" not in h
    assert "<ul><li>one<ul><li>nested</li></ul></li><li>two</li></ul>" in h
    assert 'title="no data">n/a</span>' in h and "&lt;b&gt;" in h


def _page(tmp_path, **kw):
    _, out = make(tmp_path, **kw)
    return out.read_text()


def test_lesson_has_no_unfilled_placeholders_and_equals_dashboard_sharpe(tmp_path):
    page = _page(tmp_path)
    d = data_of(page)
    html = d["lesson"]["html"]
    assert not re.search(r"\{\w+\}", html) and "How the Sharpe ratio is calculated" in html
    tot = next(e for e in d["entities"] if e["kind"] == "group" and e["groupKind"] == "all")
    dash = tot["windows"]["inception"]["sharpe"]
    assert dash is not None and d["lesson"]["raw"]["sharpe"] == pytest.approx(dash, abs=1e-12)
    assert f"<strong>{dash:.2f}</strong>" in html
    assert 'id="sharpechart"' in html and 'id="tab-sharpe"' in page
    assert "Information, not investment advice" in html


def test_nonmarket_account_listed_as_excluded_and_dropped_when_none(tmp_path):
    reg = _reg(tmp_path)
    p = registry_path(tmp_path)
    p.parent.mkdir(exist_ok=True)
    p.write_text(reg.model_dump_json())
    st, _ = store(tmp_path)
    assert portfolio_compare.main(["--root", str(tmp_path), "--benchmark", "IDX"], st, TODAY) == 0
    html = data_of((tmp_path / "exports" / "portfolio-compare.html").read_text())["lesson"]["html"]
    assert "Annuity" in html and "have no market prices" in html
    rest = tmp_path / "other"
    rest.mkdir()
    html2 = data_of(_page(rest))["lesson"]["html"]
    assert "Left out" not in html2


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_sharpe_tab_renders_chart_with_lines(tmp_path):
    page = _page(tmp_path)
    script = page.split("<script>")[1].split("</script>")[0]
    blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
    harness = f"""
const els = {{}};
const el = id => els[id] || (els[id] = {{innerHTML:'', textContent:'', hidden:false, querySelectorAll:()=>[], set onchange(f){{}}}});
global.document = {{getElementById: id => id==='data' ? {{textContent: {json.dumps(blob)}}} : el(id),
  querySelector: s => el(s), querySelectorAll: () => [], documentElement: {{}}}};
{script}
tab='sharpe'; draw();
// the lesson html is set on #lesson; put the chart target in place the way the browser would
els['#sharpechart'] = {{innerHTML:''}}; els['#sharpecap'] = {{textContent:''}}; sharpeTab();
const h = els['#sharpechart'].innerHTML;
console.log(h.includes('<svg'), (h.match(/<line x1=/g)||[]).length >= 2, h.includes('Risk-free'), els['#tab-main'].hidden, els['#tab-sharpe'].hidden);
"""
    f = tmp_path / "t.js"
    f.write_text(harness)
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["true", "true", "true", "true", "false"]


def test_lesson_period_toggle_sanity_check_and_compounding():
    rep, months = fake_report(30)
    rf = flat_rf(months)
    f = S.portfolio_figures(rep, rf)["fill"]
    rfm = M.monthly_rf(rf, date(2020, 1, 31))
    ex = [r - rfm for r in rep.port_returns]
    m, sd = mean(ex), stdev(ex)
    assert f["n_within"] == str(sum(1 for x in ex if abs(x - m) <= sd))
    g = 1.0
    for r in rep.port_returns:
        g *= 1 + r
    assert f["compounded_annual"] == f"{(g ** (12 / 30) - 1) * 100:.2f}%"
    assert f["rf_annual_compounded"] == f"{((1 + rfm) ** 12 - 1) * 100:.2f}%" and f["rf_annual"] == f"{rfm * 12 * 100:.2f}%"
    assert f["monthly_table"].count("\n| ") == 12  # last twelve visible
    older = f["monthly_table_older"]
    assert older.startswith("::: details Show all 30 months") and older.count("\n| ") == 19  # header plus the 18 older months and older.endswith(":::")
    assert S.portfolio_figures(*fake_report(10)[:1], flat_rf(fake_report(10)[1]))["fill"]["monthly_table_older"] == ""


def test_rendered_lesson_has_toggle_period_sentences_and_the_compounding_paragraph(tmp_path):
    html = data_of(_page(tmp_path))["lesson"]["html"]
    assert "<details><summary>Show all " in html and "</details>" in html
    assert html.count("Over all ") >= 2 and "of the average (about 68% would be typical)" in html
    assert "Why times 12 and not compounded?" in html and "Sharpe, 1994" in html
    assert not re.search(r"\{\w+\}", html)

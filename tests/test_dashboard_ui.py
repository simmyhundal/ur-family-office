"""Dashboard UI fixes on invented data: the scrub caption stays one short line (issue 195), Details reads in plain words
with readable dates and fine print (issue 196), and the header uses the site's own brand mark (issue 197)."""
import base64
import re
import shutil
from pathlib import Path

import pytest

from tests.test_dashboard import make
from tests.test_dashboard_overview import run_page
from ufo.performance import dashboard

NODE = shutil.which("node")
SITE_IMG = Path(__file__).resolve().parent.parent / "site" / "img"
SCRUB_MAX = 34  # fits one line at 320px wide in the 13.5px caption


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_scrub_caption_is_one_short_line_for_every_month(tmp_path):
    _, out = make(tmp_path)
    o = run_page(tmp_path, out.read_text(), """
const caps = [];
for (const g of ['accounts','all']) for (const [w] of D.windows) { grp=g; win=w;
  for (const e of D.entities) { const v = view(e); if (!v) continue;
    for (let i = 0; i < v.months.length; i++) caps.push(scrubCap(v, i)); } }
bm = 'VT';
const big = {months: ['2024-03-31', '2026-10-30'], values: [1234567, 1234567], bench: [9876543, 9876543]};
caps.push(scrubCap(big, 0), scrubCap(big, 1), scrubCap({months: ['2024-03-31', '2024-04-30'], values: [1, 2], bench: []}, 0));
console.log(JSON.stringify(caps));
""")
    assert len(o) > 20
    assert max(len(c) for c in o) <= SCRUB_MAX, max(o, key=len)
    assert all("\n" not in c for c in o)
    assert o[-3] == "Mar 2024 · est. · VT $9.88M" and o[-2] == "Oct 30, 2026 · latest · VT $9.88M" and o[-1] == "Mar 2024 · est."


def test_balance_and_caption_never_wrap():
    css = dashboard.PAGE_CSS
    bal = re.search(r"\.bal\{([^}]*)\}", css).group(1)
    sub = re.search(r"\.balsub\{([^}]*)\}", css).group(1)
    assert "white-space:nowrap" in bal and "tabular-nums" in bal
    for rule in ("white-space:nowrap", "text-overflow:ellipsis", "height:20px", "tabular-nums"):
        assert rule in sub


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_plain_labels_and_readable_dates(tmp_path):
    _, out = make(tmp_path)
    o = run_page(tmp_path, out.read_text(), """
console.log(JSON.stringify({
  roth: plain('wrapper: roth_ira', 'wrapper'), trad: plain('wrapper: traditional_ira', 'wrapper'), tax: plain('wrapper: taxable', 'wrapper'),
  other: plain('wrapper: other', 'wrapper'), brk: plain('brokerage: fidelity', 'brokerage'), own: plain('owner: household', 'owner'),
  all: plain('All accounts', 'all'), acct: plain('Joint brokerage', ''),
  t1: typeOf('roth_ira'), t2: typeOf('traditional_ira'), t3: typeOf('taxable'), t4: typeOf('other'), t5: typeOf('combined'),
  d: fmtDate('2019-03-03'), m: fmtMon('2019-03-03'), s: isoD('history ends 2026-09-30, ending value is from 2026-10-30')}));
""")
    assert (o["roth"], o["trad"], o["tax"], o["other"]) == ("Roth IRA", "Traditional IRA", "Taxable", "Other")
    assert (o["brk"], o["own"], o["all"], o["acct"]) == ("Fidelity", "Household", "All accounts", "Joint brokerage")
    assert (o["t1"], o["t2"], o["t3"], o["t4"], o["t5"]) == ("Roth IRA", "Traditional IRA", "Taxable", "Other", "Combined")
    assert o["d"] == "Mar 3, 2019" and o["m"] == "Mar 2019"
    assert o["s"] == "history ends Sep 30, 2026, ending value is from Oct 30, 2026"


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_details_table_has_no_machine_keys_or_iso_dates_and_explains_every_na(tmp_path):
    _, out = make(tmp_path)
    o = run_page(tmp_path, out.read_text(), """
const res = {};
for (const g of ['accounts','all','brokerage','owner','wrapper']) for (const [w] of D.windows) {
  grp=g; win=w; draw(); res[g+'/'+w] = [els['#tbl'].innerHTML, els['#tblnotes'].innerHTML, els['#totnote'].textContent, els['#wins2'].innerHTML]; }
console.log(JSON.stringify(res));
""")
    for k, (tbl, notes, tot, wins) in o.items():
        text = re.sub(r"<[^>]+>", " ", tbl)                 # visible text only; ISO dates may stay in attributes
        assert not re.search(r"\d{4}-\d{2}-\d{2}", text + tot + re.sub(r"<[^>]+>", " ", notes)), k
        assert not re.search(r"\b(roth_ira|traditional_ira|wrapper:|brokerage:|owner:)", text), k
        assert re.search(r"Exact|Estimated|Does not reconcile|n/a: ", tbl), k   # every row says how sure it is, or why it is empty
        # every n/a carries a numbered note, and every number has its line in the fine print
        assert tbl.count(">n/a<") == len(re.findall(r">n/a<button[^>]*data-act=\"fn\"", tbl)), k
        for n in set(re.findall(r'data-act="fn" data-k="(\d+)"', tbl)):
            assert f'id="fn-{n}"' in notes, (k, n)
        assert ">All<" in wins and ">YTD<" in wins            # the same short period pills as Overview


def _norm(svg: str) -> str:
    return re.sub(r"\s+", " ", svg).strip()


def test_dashboard_logo_matches_the_site():
    """One source of truth: the dashboard's copy of the brand mark must equal site/img (the site track owns the logo)."""
    assert _norm(dashboard.BRAND_LOGO_SVG) == _norm((SITE_IMG / "logo.svg").read_text())
    assert _norm(dashboard.BRAND_FAVICON_SVG) == _norm((SITE_IMG / "favicon.svg").read_text())


def test_page_uses_the_brand_logo_and_favicon_inline():
    page = dashboard.render({"asof": "2026-01-01", "benchmark": "VT", "entities": []})
    assert dashboard.LOGO in page and 'aria-hidden="true"' in dashboard.LOGO and "ufo-beam" in dashboard.LOGO
    m = re.search(r'<link rel="icon" type="image/svg\+xml" href="data:image/svg\+xml;base64,([^"]+)">', page)
    assert m and _norm(base64.b64decode(m.group(1)).decode()) == _norm((SITE_IMG / "favicon.svg").read_text())
    assert 'viewBox="0 0 16 16" aria-hidden' not in page   # the old hand-drawn mark is gone

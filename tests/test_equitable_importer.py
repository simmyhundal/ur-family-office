"""The Equitable importer, on invented statement text with the same layout as the real quarterly PDFs."""
from datetime import date

from ufo import importers
from ufo.importers import equitable
from ufo.importers.equitable import EquitableImporter, Statement
from ufo.performance.events import Kind

TEMPLATE = """Quarterly Account Review
Statement Period:
{period}
Account Activity Summary                                                {q}
Beginning Account Value {begin}                                                      $100.00
Contributions                                                                                ${contrib}                                ${contrib}             $5.00
Extra Credit and/or Earnings Bonus Amount                                                    $0.00                              $1.00              $2.00
Variable Investment Option Results                                                       $3.00
Current Total Account Value                                                             ${total}
 Fund        Asset Class/                                               Accumulation                 Unit                Account
 {a}
               Large Cap
 09001         DEMO/Alpha Fund                                            {ua}               ${pa}                ${va}
               Mid Cap
 09002         DEMO/Beta Fund                                                 {ub}               ${pb}              ${vb}
"""


def stmt(period, contrib, ua, pa, ub, pb):
    va, vb = round(ua * pa, 2), round(ub * pb, 2)
    return TEMPLATE.format(period=period, q="", begin="x", contrib=f"{contrib:.2f}", total=f"{va + vb:,.2f}", a="",
                           ua=f"{ua:.4f}", pa=f"{pa:.6f}", va=f"{va:,.2f}", ub=f"{ub:.4f}", pb=f"{pb:.6f}", vb=f"{vb:,.2f}")


def fix(monkeypatch, texts):
    monkeypatch.setattr(equitable, "_text", lambda path: texts[path])
    return list(texts)


Q1 = stmt("January 01, 2030- March 31, 2030", 0, 10, 10.0, 5, 20.0)  # 200
Q2 = stmt("April 01, 2030- June 30, 2030", 100, 12, 11.0, 6, 21.0)  # 258: 100 of new money, units 2+1 at quarter-end prices
Q4 = stmt("October 01, 2030- December 31, 2030", 0, 12, 12.0, 6, 22.0)  # 3rd quarter's statement is missing


def test_registered():
    assert "equitable" in importers.names()


def test_statement_parse():
    s = Statement("q.pdf", Q2)
    assert (s.start, s.end) == (date(2030, 4, 1), date(2030, 6, 30)) and s.ok
    assert s.flows == 100.0 and sorted(s.funds) == ["09001", "09002"]


def test_events_keep_cash_at_zero_and_value_matches(monkeypatch):
    files = fix(monkeypatch, {"q1": Q1, "q2": Q2, "q4": Q4})
    h = EquitableImporter().parse(files)
    assert any("not the previous quarter" in w for w in h.warnings)
    assert abs(sum(e.amount for e in h.events)) < 0.011  # every trade is paired with the cash behind it
    assert [e.external_flow for e in h.events if e.external_flow] == [200.0, 100.0]
    imp = EquitableImporter()
    assert set(imp.prices(files)) == {"EQ09001", "EQ09002"}
    assert imp.statement_values(files)[-1] == (date(2030, 12, 31), 12 * 12.0 + 6 * 22.0, "Equitable quarterly statement")


def test_duplicate_period_and_garbage_are_skipped(monkeypatch):
    files = fix(monkeypatch, {"a": Q1, "b": Q1, "c": "nothing useful"})
    h = EquitableImporter().parse(files)
    assert any("same quarter" in w for w in h.warnings) and any("not understood" in w for w in h.warnings)
    assert [e.kind for e in h.events].count(Kind.CONTRIBUTION) == 1

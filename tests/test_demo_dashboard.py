"""The demo dashboard (invented household) and the phone layout hooks. No network: a fake price client."""
from datetime import date, timedelta

from ufo.providers.prices import Point
from scripts import build_demo_dashboard as demo


class Fake:
    def fetch(self, symbol, start, end):
        g = 0.0002 + (sum(map(ord, symbol)) % 7) * 0.00005
        return [Point(day=date(2017, 1, 1) + timedelta(days=i), value=100 * (1 + g) ** i, close=100 * (1 + g) ** i)
                for i in range(3700) if start <= date(2017, 1, 1) + timedelta(days=i) <= end]

    def fetch_risk_free(self, start, end):
        return [Point(day=date(2017, 1, 1) + timedelta(days=i), value=2.0) for i in range(3700)]


def test_demo_page_is_labelled_and_has_phone_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "WebClient", Fake)
    out = tmp_path / "demo.html"
    assert demo.main(["--out", str(out), "--asof", "2026-10-30", "--cache", str(tmp_path / "prices")]) == 0
    page = out.read_text()
    assert 'class="demo"' in page and "invented household" in page
    assert "invented demo data" in page and "local only, never sent anywhere" not in page
    assert 'id="hero"' in page and "function hero()" in page          # dollar headline
    assert "@media (max-width:640px)" in page and "td.dataset.l=" in page  # table becomes cards on phones
    assert "CW($('#lines'))" in page                                   # charts drawn at the container's width
    for label in ("Joint brokerage", "Alex Roth IRA", "Sam Roth IRA", "Sam rollover IRA"):
        assert label in page


def test_real_page_keeps_the_local_only_promise(tmp_path, monkeypatch):
    from ufo.performance import dashboard
    page = dashboard.render({"asof": "2026-01-01", "benchmark": "VT", "entities": []})
    assert "local only, never sent anywhere" in page and 'class="demo"' not in page

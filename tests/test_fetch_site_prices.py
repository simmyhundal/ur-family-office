"""The site's price builder, run against a fake client with invented prices."""
import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

from ufo.providers.prices import Point, PriceError, PriceStore

spec = importlib.util.spec_from_file_location("fetch_site_prices", Path(__file__).resolve().parents[1] / "scripts" / "fetch_site_prices.py")
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)


class Fake:
    """Daily prices (no weekends) from each symbol's own start date; symbols in `broken` fail."""
    def __init__(self, starts, broken=()):
        self.starts, self.broken = starts, set(broken)

    def fetch(self, symbol, start, end):
        if symbol in self.broken:
            raise PriceError("no data")
        first = max(start, self.starts.get(symbol, start))
        pts, d, v = [], first, 100.0
        while d <= end:
            if d.weekday() < 5:
                pts.append(Point(day=d, value=v))
                v *= 1.0003
            d += timedelta(days=1)
        return pts

    def fetch_risk_free(self, start, end):
        if getattr(self, "no_rf", False):
            raise PriceError("no rate")
        return [Point(day=start + timedelta(days=i * 10), value=4.0 + i * 0.01) for i in range(((end - start).days // 10) + 1)]


def _universe(n):
    return [["SPY", "S&P 500"]] + [[f"T{i:02d}", f"Fund {i}"] for i in range(n - 1)]


def test_builds_month_ends_and_blanks_for_late_starters(tmp_path):
    uni = _universe(25)
    fake = Fake({"T01": date(2024, 6, 10)})
    doc = F.build(uni, PriceStore(tmp_path, fake, today=date(2025, 3, 20)), date(2024, 1, 1), date(2025, 3, 20))
    assert doc["dates"][0] == "2024-01-31" and doc["dates"][-1] == "2025-03-20"  # last month is partial: last obs so far
    assert all(len(v) == len(doc["dates"]) for v in doc["series"].values())
    late = doc["series"]["T01"]
    assert late[:5] == [None] * 5 and late[5] is not None  # nothing before June 2024; June has a value
    assert doc["labels"]["SPY"] == "S&P 500"


def test_failed_tickers_are_skipped_but_reported(tmp_path):
    doc = F.build(_universe(25), PriceStore(tmp_path, Fake({}, broken={"T03"}), today=date(2025, 3, 20)), date(2024, 1, 1), date(2025, 3, 20))
    assert "T03" not in doc["series"] and any(s.startswith("T03") for s in doc["skipped"])


def test_too_few_tickers_raises(tmp_path):
    with pytest.raises(PriceError, match="Only"):
        F.build(_universe(25), PriceStore(tmp_path, Fake({}, broken={f"T{i:02d}" for i in range(10)}), today=date(2025, 3, 20)), date(2024, 1, 1), date(2025, 3, 20))


def test_missing_benchmark_raises(tmp_path):
    with pytest.raises(PriceError):
        F.build(_universe(25), PriceStore(tmp_path, Fake({}, broken={"SPY"}), today=date(2025, 3, 20)), date(2024, 1, 1), date(2025, 3, 20))


def test_single_page_build_inlines_everything():
    spec2 = importlib.util.spec_from_file_location("build_single_page", Path(__file__).resolve().parents[1] / "scripts" / "build_single_page.py")
    B = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(B)
    out = B.build('{"dates":["2024-01-31"],"labels":{"A":"</script>"},"series":{"A":[1]}}')
    assert "<style>" in out and "globalThis.UFO_DATA" in out and 'src="js/app.js"' not in out and "export " not in out and "import {" not in out
    assert "</script>\"" not in out.split("globalThis.UFO_DATA")[1].split("</script>")[0]  # data cannot close the tag early


def test_presets_are_well_formed():
    import json
    root = Path(__file__).resolve().parents[1] / "site" / "data"
    universe = {s for s, _ in json.loads((root / "universe.json").read_text())}
    presets = json.loads((root / "presets.json").read_text())
    assert presets and all(p["name"] for p in presets)
    for p in presets:
        assert abs(sum(p["weights"].values()) - 100) < 1e-9, p["name"]
        assert set(p["weights"]) <= universe, p["name"]  # every fund has prices in the universe


def test_cash_rate_is_aligned_to_the_dates_and_optional(tmp_path):
    uni = _universe(25)
    doc = F.build(uni, PriceStore(tmp_path / "a", Fake({}), today=date(2025, 3, 20)), date(2024, 1, 1), date(2025, 3, 20))
    assert len(doc["rf"]) == len(doc["dates"]) and all(4.0 <= v < 6.0 for v in doc["rf"])
    broken = Fake({})
    broken.no_rf = True
    doc2 = F.build(uni, PriceStore(tmp_path / "b", broken, today=date(2025, 3, 20)), date(2024, 1, 1), date(2025, 3, 20))
    assert doc2["rf"] is None and any("cash rate" in s for s in doc2["skipped"])

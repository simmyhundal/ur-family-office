"""Historical price loader. Fake client, invented data, no network."""
from datetime import date, datetime, timezone

import pytest

from ufo.providers.prices import (
    Point, PriceError, PriceStore, Series, WebClient, parse_fred_csv, parse_yahoo_chart,
)


def _ts(y, m, d):
    return int(datetime(y, m, d, 14, 30, tzinfo=timezone.utc).timestamp())


def _days(*rows):
    return [Point(day=date(y, m, d), value=v) for (y, m, d, v) in rows]


class FakeClient:
    def __init__(self, data=None, rf=None, fail=False):
        self.data, self.rf, self.fail, self.calls = data or {}, rf or [], fail, []

    def fetch(self, symbol, start, end):
        self.calls.append((symbol, start, end))  # the only things that ever leave the machine
        if self.fail:
            raise PriceError("Could not reach the price service (check the internet connection).")
        if symbol not in self.data:
            raise PriceError(f"No price data for {symbol}.")
        return [p for p in self.data[symbol] if start <= p.day <= end]

    def fetch_risk_free(self, start, end):
        self.calls.append(("RF", start, end))
        return self.rf


DAILY = _days((2020, 1, 2, 100.0), (2020, 1, 3, 101.0), (2020, 1, 6, 102.0), (2020, 1, 31, 110.0))


def test_parse_yahoo_uses_adjusted_close_and_skips_nulls():
    payload = {"chart": {"result": [{"timestamp": [_ts(2020, 1, 2), _ts(2020, 1, 3), _ts(2020, 1, 6)],
                                      "indicators": {"quote": [{"close": [1, 2, 3]}], "adjclose": [{"adjclose": [99.5, None, 101.25]}]}}]}}
    pts = parse_yahoo_chart(payload, "ACMEX")
    assert [(p.day, p.value) for p in pts] == [(date(2020, 1, 2), 99.5), (date(2020, 1, 6), 101.25)]


def test_parse_yahoo_error_is_readable():
    bad = {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found, symbol may be delisted"}}}
    with pytest.raises(PriceError, match="No price data for ZZZ.*delisted"):
        parse_yahoo_chart(bad, "ZZZ")


def test_parse_fred_skips_holiday_dots():
    pts = parse_fred_csv("observation_date,DTB3\n2020-01-01,.\n2020-01-02,1.54\n2020-01-03,1.52\n")
    assert [(p.day, p.value) for p in pts] == [(date(2020, 1, 2), 1.54), (date(2020, 1, 3), 1.52)]


def test_value_on_or_before_for_month_end():
    s = Series(symbol="ACMEX", points=DAILY)
    assert s.on_or_before(date(2020, 1, 4)) == 101.0  # weekend uses Friday
    assert s.on_or_before(date(2020, 1, 31)) == 110.0
    assert s.on_or_before(date(2019, 12, 31)) is None


def test_gaps_are_reported():
    s = Series(symbol="ACMEX", points=DAILY)
    g = s.gaps(date(2020, 1, 2), date(2020, 1, 31))
    assert g == ["ACMEX: no prices from 2020-01-06 to 2020-01-31."]
    assert any("start" in w for w in s.gaps(date(2019, 6, 1), date(2020, 1, 31)))
    assert any("end" in w for w in s.gaps(date(2020, 1, 2), date(2020, 6, 30)))
    assert "no prices" in Series(symbol="X", points=[]).gaps(date(2020, 1, 1), date(2020, 2, 1))[0]


def test_cache_prevents_a_second_fetch_and_only_symbols_and_dates_are_sent(tmp_path):
    c = FakeClient({"ACMEX": DAILY})
    store = PriceStore(tmp_path, c, today=date(2020, 2, 1))
    a = store.series("acmex", date(2020, 1, 2), date(2020, 1, 31))
    b = store.series("ACMEX", date(2020, 1, 2), date(2020, 1, 31))
    assert a == b and len(a.points) == 4
    assert c.calls == [("ACMEX", date(2020, 1, 2), date(2020, 1, 31))]  # one call, symbol + dates only
    assert (tmp_path / "ACMEX.csv").exists()


def test_csv_fallback_works_with_no_client(tmp_path):
    (tmp_path / "ACMEX.csv").write_text("date,adj_close\n2020-01-02,100.0\n2020-01-31,110.0\n")
    s = PriceStore(tmp_path, None, today=date(2020, 2, 1)).series("ACMEX", date(2020, 1, 2), date(2020, 1, 31))
    assert [p.value for p in s.points] == [100.0, 110.0]


def test_no_cache_and_no_client_says_what_to_do(tmp_path):
    with pytest.raises(PriceError, match="ACMEX.csv"):
        PriceStore(tmp_path, None).series("ACMEX", date(2020, 1, 2), date(2020, 1, 31))


def test_offline_with_a_cache_uses_it_and_reports_gaps(tmp_path):
    PriceStore(tmp_path, FakeClient({"ACMEX": DAILY}), today=date(2020, 2, 1)).series("ACMEX", date(2020, 1, 2), date(2020, 1, 31))
    offline = PriceStore(tmp_path, FakeClient(fail=True), today=date(2020, 6, 30))
    series, warnings = offline.report(["ACMEX"], date(2020, 1, 2), date(2020, 6, 30))
    assert len(series["ACMEX"].points) == 4 and any("end" in w for w in warnings)


def test_offline_with_no_cache_raises_a_plain_message(tmp_path):
    with pytest.raises(PriceError, match="Could not reach"):
        PriceStore(tmp_path, FakeClient(fail=True)).series("ACMEX", date(2020, 1, 2), date(2020, 1, 31))


def test_report_turns_failures_into_warnings(tmp_path):
    store = PriceStore(tmp_path, FakeClient({"ACMEX": DAILY}), today=date(2020, 2, 1))
    series, warnings = store.report(["ACMEX", "nope", "acmex", " "], date(2020, 1, 2), date(2020, 1, 31))
    assert list(series) == ["ACMEX"] and any(w.startswith("NOPE: No price data") for w in warnings)


def test_risk_free_is_cached_like_prices(tmp_path):
    rf = _days((2020, 1, 2, 1.54), (2020, 1, 3, 1.52), (2020, 1, 31, 1.55))
    c = FakeClient(rf=rf)
    store = PriceStore(tmp_path, c, today=date(2020, 2, 1))
    s1 = store.risk_free(date(2020, 1, 2), date(2020, 1, 31))
    s2 = store.risk_free(date(2020, 1, 2), date(2020, 1, 31))
    assert s1 == s2 and len(c.calls) == 1 and (tmp_path / "DTB3.csv").exists()


def test_bad_fallback_file_is_explained(tmp_path):
    (tmp_path / "ACMEX.csv").write_text("day,price\n1,2\n")
    with pytest.raises(PriceError, match="date,adj_close"):
        PriceStore(tmp_path, None).series("ACMEX", date(2020, 1, 2), date(2020, 1, 31))


def test_web_client_errors_are_plain(monkeypatch):
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.URLError("dns")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(PriceError, match="Could not reach"):
        WebClient().fetch("ACMEX", date(2020, 1, 2), date(2020, 1, 31))


def test_each_host_gets_the_user_agent_it_accepts(monkeypatch):
    seen = {}

    class Resp:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self.body

    def fake_open(req, timeout):
        seen[req.host] = (req.get_header("User-agent"), req.get_header("Accept"))
        return Resp(b"observation_date,DTB3\n2020-01-02,1.5\n" if "fred" in req.host else
                    b'{"chart":{"result":[{"timestamp":[1577975400],"indicators":{"adjclose":[{"adjclose":[9.5]}]}}]}}')
    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    c = WebClient()
    assert c.fetch_risk_free(date(2020, 1, 1), date(2020, 1, 31))[0].value == 1.5
    assert c.fetch("ACMEX", date(2020, 1, 1), date(2020, 1, 31))[0].value == 9.5
    assert seen["fred.stlouisfed.org"] == ("ur-family-office-price-loader/0.1", "*/*")
    assert seen["query1.finance.yahoo.com"] == ("Mozilla/5.0", "*/*")

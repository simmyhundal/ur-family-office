"""Historical prices for performance reports: dividend-adjusted closes and a risk-free rate.

Privacy: only a ticker symbol and a date range ever leave the machine. Never amounts, accounts or quantities.
This is *historical* data, separate from live prices for rebalancing (issue 2).

Layers:
  PriceClient (Protocol)  -> where bytes come from (Yahoo chart API, FRED CSV, or a fake in tests)
  PriceStore              -> local cache in `.data/prices/` plus a CSV fallback so it works offline
  Series                  -> sorted points with gap reporting and "value on or before a date"

Offline fallback: drop `SYMBOL.csv` (columns `date,adj_close`, ISO dates) into the cache folder and it is used as is.
"""
from __future__ import annotations

import csv
import json
import urllib.error
import urllib.parse
import urllib.request
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

RISK_FREE_ID = "DTB3"  # FRED: 3-month Treasury bill, secondary market rate (annualized, percent)
GAP_DAYS = 7  # a hole longer than this between points is reported (long weekends and holidays are normal)


class PriceError(Exception):
    """A readable failure (no network, unknown symbol, bad file). Never contains secrets."""


class Point(BaseModel):
    day: date
    value: float  # adjusted close (dividends and splits reinvested), or an annualized % for the risk-free series


class Series(BaseModel):
    symbol: str
    points: list[Point]

    def on_or_before(self, day: date) -> float | None:
        """Last known value on or before `day` (month-end valuation uses this), or None before the first point."""
        days = [p.day for p in self.points]
        i = bisect_right(days, day)
        return self.points[i - 1].value if i else None

    def gaps(self, start: date, end: date) -> list[str]:
        """Human-readable holes: late start, early end, and any run longer than GAP_DAYS."""
        if not self.points:
            return [f"{self.symbol}: no prices between {start} and {end}."]
        out = []
        first, last = self.points[0].day, self.points[-1].day
        if first > start + timedelta(days=GAP_DAYS):
            out.append(f"{self.symbol}: prices start {first}, after the requested {start}.")
        if last < end - timedelta(days=GAP_DAYS):
            out.append(f"{self.symbol}: prices end {last}, before the requested {end}.")
        for a, b in zip(self.points, self.points[1:]):
            if (b.day - a.day).days > GAP_DAYS:
                out.append(f"{self.symbol}: no prices from {a.day} to {b.day}.")
        return out


class PriceClient(Protocol):
    def fetch(self, symbol: str, start: date, end: date) -> list[Point]: ...
    def fetch_risk_free(self, start: date, end: date) -> list[Point]: ...


# ---- parsing (pure, tested with invented payloads) ----

def parse_yahoo_chart(payload: dict, symbol: str) -> list[Point]:
    try:
        r = payload["chart"]["result"][0]
        stamps = r.get("timestamp") or []
        adj = r["indicators"]["adjclose"][0]["adjclose"]
    except (KeyError, IndexError, TypeError):
        err = (payload.get("chart") or {}).get("error") if isinstance(payload, dict) else None
        raise PriceError(f"No price data for {symbol}" + (f" ({err.get('description')})" if isinstance(err, dict) else "") + ".")
    pts = [Point(day=datetime.fromtimestamp(t, tz=timezone.utc).date(), value=float(v))
           for t, v in zip(stamps, adj) if v is not None]
    return sorted(pts, key=lambda p: p.day)


def parse_fred_csv(text: str) -> list[Point]:
    pts = []
    for row in csv.DictReader(text.splitlines()):
        d, v = (row.get("observation_date") or row.get("DATE") or "").strip(), (row.get(RISK_FREE_ID) or "").strip()
        if not d or v in ("", "."):  # FRED marks holidays with "."
            continue
        pts.append(Point(day=date.fromisoformat(d), value=float(v)))
    return sorted(pts, key=lambda p: p.day)


# ---- the real network client ----

class WebClient:
    """Yahoo's public chart endpoint (no key) and FRED's public CSV. Both are unofficial or best-effort: failures are
    reported plainly and the CSV fallback in PriceStore keeps the report possible offline."""
    # Yahoo turns away non-browser agents; FRED stalls browser-looking ones that do not behave like a browser. So each
    # host gets the header it accepts (measured against both on 2026-11-05).
    YAHOO_UA = "Mozilla/5.0"
    FRED_UA = "ur-family-office-price-loader/0.1"

    def _get(self, url: str, user_agent: str) -> bytes:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            raise PriceError(f"The price service answered {e.code}.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise PriceError("Could not reach the price service (check the internet connection).") from None

    def fetch(self, symbol: str, start: date, end: date) -> list[Point]:
        p1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
        p2 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()) + 86400
        q = urllib.parse.urlencode({"period1": p1, "period2": p2, "interval": "1d", "events": "div,splits"})
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{q}"
        try:
            payload = json.loads(self._get(url, self.YAHOO_UA))
        except ValueError:
            raise PriceError(f"Unreadable answer for {symbol}.") from None
        return parse_yahoo_chart(payload, symbol)

    def fetch_risk_free(self, start: date, end: date) -> list[Point]:
        q = urllib.parse.urlencode({"id": RISK_FREE_ID, "cosd": start.isoformat(), "coed": end.isoformat()})
        return parse_fred_csv(self._get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?{q}", self.FRED_UA).decode("utf-8", "replace"))


# ---- cache + fallback ----

def _read_csv(path: Path) -> list[Point]:
    pts = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                pts.append(Point(day=date.fromisoformat(row["date"].strip()), value=float(row["adj_close"])))
            except (KeyError, ValueError):
                raise PriceError(f"{path.name}: expected columns date,adj_close with ISO dates.") from None
    return sorted(pts, key=lambda p: p.day)


def _write_csv(path: Path, pts: list[Point]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "adj_close"])
        w.writerows((p.day.isoformat(), repr(p.value)) for p in pts)


class PriceStore:
    def __init__(self, cache_dir: Path, client: PriceClient | None = None, today: date | None = None):
        self.dir, self.client, self.today = Path(cache_dir), client, today or date.today()

    def _load(self, name: str, start: date, end: date, fetch) -> list[Point]:
        path = self.dir / f"{name.upper()}.csv"
        have = _read_csv(path) if path.exists() else []
        # The cache is enough when it reaches the requested window; ends within a week of a weekend/holiday count.
        covers = bool(have) and have[0].day <= start + timedelta(days=GAP_DAYS) and have[-1].day >= min(end, self.today) - timedelta(days=GAP_DAYS)
        if not covers and self.client is not None:
            try:
                fresh = fetch()
            except PriceError:
                if not have:
                    raise
                fresh = []  # offline but something is cached: use it, gaps get reported
            if fresh:
                have = sorted({p.day: p for p in have + fresh}.values(), key=lambda p: p.day)
                _write_csv(path, have)
        elif not covers and not have:
            raise PriceError(f"No cached prices for {name} and no price service configured. Add {path.name} (date,adj_close) to {self.dir}.")
        return [p for p in have if start <= p.day <= end]

    def series(self, symbol: str, start: date, end: date) -> Series:
        sym = symbol.strip().upper()
        return Series(symbol=sym, points=self._load(sym, start, end, lambda: self.client.fetch(sym, start, end)))

    def risk_free(self, start: date, end: date) -> Series:
        return Series(symbol=RISK_FREE_ID, points=self._load(RISK_FREE_ID, start, end, lambda: self.client.fetch_risk_free(start, end)))

    def report(self, symbols: list[str], start: date, end: date) -> tuple[dict[str, Series], list[str]]:
        """Load every symbol; a failure or a gap becomes a warning instead of stopping the whole report."""
        out, warnings = {}, []
        for s in dict.fromkeys(x.strip().upper() for x in symbols if x.strip()):
            try:
                out[s] = self.series(s, start, end)
                warnings += out[s].gaps(start, end)
            except PriceError as e:
                warnings.append(f"{s}: {e}")
        return out, warnings

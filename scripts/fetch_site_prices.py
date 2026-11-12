"""Build site/data/prices.json: month-end adjusted closes for the tickers in site/data/universe.json.

Run by the GitHub Actions workflow before the site is deployed (it has open network; the output is not committed).
Run: python scripts/fetch_site_prices.py [--years 6] [--out site/data/prices.json]
Exits non-zero when too little came back, so a bad run never replaces a working site with an empty one.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ufo.providers.prices import PriceError, PriceStore, WebClient  # noqa: E402

MIN_SYMBOLS = 20
REQUIRED = "SPY"


def month_ends(points) -> dict[str, tuple[date, float]]:
    """Last observation in each calendar month, keyed 'YYYY-MM'."""
    out: dict[str, tuple[date, float]] = {}
    for p in sorted(points, key=lambda p: p.day):
        out[p.day.strftime("%Y-%m")] = (p.day, p.value)
    return out


def build(universe: list[list[str]], store: PriceStore, start: date, end: date, pause: float = 0.0) -> dict:
    """Pure-ish: all network goes through `store`. Returns the JSON document; raises PriceError if it is too thin."""
    per, skipped = {}, []
    for sym, _name in universe:
        try:
            per[sym] = month_ends(store.series(sym, start, end).points)
        except PriceError as e:
            skipped.append(f"{sym}: {e}")
        if pause:
            time.sleep(pause)
    if REQUIRED not in per or len(per) < MIN_SYMBOLS:
        raise PriceError(f"Only {len(per)} of {len(universe)} tickers came back (need {REQUIRED} and {MIN_SYMBOLS}+): " + "; ".join(skipped[:5]))
    months = sorted(per[REQUIRED])  # SPY's calendar: every month it has a price
    dates = [per[REQUIRED][m][0].isoformat() for m in months]
    series = {s: [round(m[k][1], 4) if k in m else None for k in months] for s, m in per.items()}
    names = dict(universe)
    return {"asOf": dates[-1], "source": "Yahoo Finance adjusted closes, fetched by GitHub Actions", "dates": dates,
            "labels": {s: names[s] for s in series}, "series": series, "skipped": skipped}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=11)  # the page offers up to 10 years
    ap.add_argument("--out", default=str(ROOT / "site" / "data" / "prices.json"))
    a = ap.parse_args()
    universe = json.loads((ROOT / "site" / "data" / "universe.json").read_text())
    end = date.today()
    start = end - timedelta(days=365 * a.years + 45)
    with tempfile.TemporaryDirectory() as cache:
        try:
            doc = build(universe, PriceStore(Path(cache), WebClient()), start, end, pause=0.3)
        except PriceError as e:
            print(f"Price fetch failed: {e}", file=sys.stderr)
            return 1
    Path(a.out).write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    print(f"wrote {a.out}: {len(doc['series'])} tickers, {len(doc['dates'])} months to {doc['asOf']}; skipped {len(doc['skipped'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

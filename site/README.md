# Mix vs benchmark (prototype)

A static page: type your mix of funds, pick a benchmark, and see how it would have done side by side. **Nothing is
deployed.** Everything runs in the browser (no server, no analytics, no network calls except loading the demo prices),
so a portfolio never leaves the visitor's machine. This is the spike for issues 56 (browser or server) and 58 (demo on a
sample portfolio).

- `index.html`, `style.css`, `js/app.js`: the page. `js/calc.mjs`: the maths (pure functions, shared with the tests).
- `data/demo-prices.json`: **invented** month-end prices for six fictional funds (`python scripts/make_demo_prices.py`).
  No real prices are shipped, which avoids the licensing question in issue 57. Visitors can load their own CSV
  (`date,SYM1,SYM2` or `date,symbol,price`) in the browser.
- Try it: `cd site && python -m http.server 8000`, then open http://localhost:8000.

## Tests
- `node --test tests/site/calc.test.mjs`: known answers (hand-computed rebalancing, CSV handling, edge cases).
- `pytest tests/test_site_parity.py`: buy-and-hold results match `src/ufo/performance/metrics.py` to 1e-9 on invented
  prices, with and without monthly deposits (skipped if node is missing).

## Not decided yet
Whether this goes on a public site is for issues 55 (direction and privacy promise), 61 (hosting) and 62 (legal review).
Real prices for a public version are issue 57. The display is information only; keep the disclaimer.

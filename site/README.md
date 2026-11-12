# Portfolio vs benchmark

A static page: enter a mix of funds, pick a benchmark (SPY by default), see the result side by side. Runs in the browser; no server.

- `js/calc.mjs` is the maths, `js/app.js` the page. `data/universe.json` lists the tickers offered.
- **Prices:** `scripts/fetch_site_prices.py` writes `data/prices.json` (not committed). The GitHub Actions workflow runs it on every deploy and on weekdays, then publishes `site/` to Pages. Without that file the page uses invented demo prices (`scripts/make_demo_prices.py`). Visitors can also load their own CSV.
- **One-time setup:** Settings > Pages > Source: GitHub Actions. Private repos need a plan that includes Pages for private repos.
- **Locally:** `cd site && python -m http.server 8000`.
- **Tests:** `node --test tests/site/calc.test.mjs` and `pytest` (parity with `src/ufo/performance/metrics.py`, and the price builder).
- Information only, not advice.

# UFO site

A small multi-page static site. Enter a mix of funds, pick a benchmark (SPY by default), see the result side by side. Runs in the browser; nothing is uploaded; no server, no analytics, no external resources.

## Page map
Each page is `folder/index.html` with relative links, so it works under `/ur-family-office/`.
- `index.html`: Home. Hero, three benefit cards, one button to `try/?sample=1`, a link to Learn. No tables.
- `try/`: the tool. Headline result and one chart first; "Show details" (full metrics, month table), "Your mix and settings" (mix editor, benchmark, history, style, deposits) and "Use your own prices (CSV)" are disclosures. `?sample=1` loads the sample portfolio.
- `learn/`: lesson index. `learn/sharpe/`: "How Sharpe works", one card per step with Back and Next (arrow keys too), including the portfolio-theory steps. It runs on the mix last loaded on Try in this tab (kept in `sessionStorage`), else the sample.
- `about/`: how it works, limits, not advice.
- `teach/` (instructor session plan, pilot request), `pricing/` (from `data/plans.json`), `signup/` (waitlist form), `privacy/`, `terms/` (both drafts pending legal review).
- **Config (M13):** `data/site.json` (name, wordmark, tagline, contact email, `signup_endpoint`, `checkout_urls`). `js/chrome.mjs` renders the header and footer on every page from it; `js/config.mjs`, `js/plans.mjs`, `js/signup.mjs` hold the testable logic (`tests/site/config.test.mjs`). A plan's `checkout_url` (plans.json, or `checkout_urls` in site.json) turns its button into a payment link; the sign-up form sends nothing while `signup_endpoint` is empty. See decision 0012.
- Shared: `style.css` (one accent, system fonts, light and dark, reduced-motion safe), `js/util.mjs` (helpers, sample, scroll reveal), `js/data.mjs` (loads `../data/*.json` relative to `js/`, so any page depth works), `js/app.js` (Try), `js/lesson.mjs` + `js/learn.mjs` (lesson), `js/calc.mjs` (the maths, unchanged).

- `js/calc.mjs` is the maths, `js/app.js` the page. `data/universe.json` lists the tickers offered.
- **Prices:** `scripts/fetch_site_prices.py` writes `data/prices.json` (not committed). The GitHub Actions workflow runs it on every deploy and on weekdays, then publishes `site/` to Pages. Without that file the page uses invented demo prices (`scripts/make_demo_prices.py`). Visitors can also load their own CSV.
- **Copy of the prices:** each workflow run also pushes `prices.json` to the `prices` branch. `scripts/build_single_page.py PRICES OUT.html` builds the **Try page** as one file (style, scripts and prices inlined; the nav links to other pages are dropped).
- **Pages:** on (Settings > Pages > Source: GitHub Actions). Address: https://simmyhundal.github.io/ur-family-office/
- **Locally:** `cd site && python -m http.server 8000` (page paths work at the root too, since all links are relative).
- **Tests:** `node --test tests/site/calc.test.mjs` and `pytest` (parity with `src/ufo/performance/metrics.py`, and the price builder).
- Information only, not advice.

## Sample portfolio and "How Sharpe works"
- **Try it with a sample portfolio** loads an invented "Sample MBA student" ($2,000 to start, $500 a month into VTI 50 / VXUS 20 / BND 20 / QQQ 10) against the default benchmark, on the real bundled prices (the demo funds when only demo data exists). It is labelled as a sample; editing anything clears the label.
- **How Sharpe works** (now its own page, `learn/sharpe/`) walks the loaded mix through the same steps as `docs/lessons/sharpe-ratio.md`: monthly returns with a worked month, minus T-bills, average x12, volatility x sqrt(12) with the one-SD count, divide, the compounding note, then the portfolio-theory part (a 50/50 blend of the mix's two largest funds, and Sharpe as a slope). With a user CSV there is no cash rate, so the steps after the monthly table show n/a.
- The math lives in `calc.mjs` (`sharpeSteps`, `blend5050`, `correlation`, `priceReturns`) with node tests; no new network calls.

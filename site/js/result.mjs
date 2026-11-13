// One result, computed the same way on every page (Home preview, Try, the Sharpe lesson). Pure: no DOM, no network.
import { compare, sliceFor, normalizeWeights } from "./calc.mjs";

export const OTHER = ["SPY", "VTI", "QQQ", "IWM", "AGG"]; // Try's "other benchmarks" table; they also set the shared window
// The invented sample person. The prices are real (bundled); the person is not.
export const SAMPLE = {
  real: { weights: { VTI: 50, VXUS: 20, BND: 20, QQQ: 10 } },
  demo: { weights: { DEMOUS: 60, DEMOBD: 30, DEMOGD: 10 } },
  initial: 2000, monthly: 500, years: 5, name: "Sample MBA student",
};

export const defaultBenchmark = (series) => ("SPY" in series ? "SPY" : Object.keys(series)[0]);

/** The sample as a full configuration for these prices (real funds when they are there, else the demo funds). */
export function sampleConfig(data) {
  const has = (x) => x in data.series;
  const pick = Object.keys(SAMPLE.real.weights).every(has) ? SAMPLE.real : SAMPLE.demo;
  if (!Object.keys(pick.weights).every(has)) return null;
  return { weights: { ...pick.weights }, benchmark: defaultBenchmark(data.series), initial: SAMPLE.initial, monthly: SAMPLE.monthly,
    strategy: "hold", years: SAMPLE.years, name: SAMPLE.name };
}

/** Mix vs benchmark over the window Try uses: from the latest start among the mix, the benchmark and the other benchmarks. */
export function runResult(data, cfg) {
  const mix = cfg.weights, bench = cfg.benchmark;
  normalizeWeights(mix);
  const unknown = [...Object.keys(mix), bench].filter((x) => !(x in data.series));
  if (unknown.length) throw new Error(`No prices for ${unknown.join(", ")}. Pick from the list, or use your own CSV.`);
  const others = OTHER.filter((x) => x in data.series);
  const needed = [...new Set([...Object.keys(mix), bench, ...others])];
  const slice = sliceFor(data, needed, cfg.years);
  if (slice.dates.length < 3) throw new Error("Not enough months of prices to compare.");
  const r = compare({ prices: slice.series, mix, benchmark: bench, initial: cfg.initial, monthly: cfg.monthly || 0, strategy: cfg.strategy || "hold", rf: slice.rf });
  return { r, slice, others, mix, bench };
}

/** The headline numbers a result screen shows (Home preview and Try read the same object). */
export function headline({ r, slice, bench }, name) {
  const m = r.mix.m, b = r.bench.m;
  return { name, bench, mixAnnual: m.annualReturn, benchAnnual: b.annualReturn, mixSharpe: m.sharpe, benchSharpe: b.sharpe,
    diff: m.endValue - b.endValue, mixEnd: m.endValue, benchEnd: b.endValue, putIn: m.putIn,
    from: slice.dates[0], to: slice.dates.at(-1), months: m.months };
}

/** What to do next, given the result. Plain information, never a recommendation to buy or sell. */
export function nextStep(h) {
  const ahead = h.diff > 0, even = h.diff === 0;
  const s = h.mixSharpe, sb = h.benchSharpe, bothSharpe = s != null && sb != null;
  let title, body;
  if (even) { title = `Level with ${h.bench}.`; body = "Same money at the end. The difference is in the ride."; }
  else if (!ahead) {
    title = `${h.name || "Your mix"} trailed ${h.bench}.`;
    body = bothSharpe && s > sb ? "It earned less, but with more return for each unit of risk." : "Was it the funds, the timing, or the risk you took?";
  } else {
    title = `${h.name || "Your mix"} beat ${h.bench}.`;
    body = bothSharpe && s < sb ? "But it took more risk for each unit of return." : "And it earned more for each unit of risk.";
  }
  return { tone: even ? "even" : ahead ? "ahead" : "behind", title, body,
    ask: "Want to see what would have lowered risk across all your accounts? That’s Plus." };
}

/** The Home page preview: the sample, run exactly as Try runs it, plus the value series for the small chart. */
export function previewModel(data) {
  const cfg = sampleConfig(data);
  if (!cfg) return null;
  const res = runResult(data, cfg);
  return { ...headline(res, cfg.name), years: cfg.years,
    mixValues: res.r.mix.sim.values, benchValues: res.r.bench.sim.values, putValues: res.r.mix.sim.contributed };
}

/** SVG path data for value series in a W x H box (shared y scale, 6% headroom). */
export function linePaths(seriesList, W, H, pad = 6) {
  const all = seriesList.flat(), top = Math.max(...all) * 1.06, n = seriesList[0].length;
  const x = (i) => (i / (n - 1)) * W, y = (v) => H - pad - (v / top) * (H - 2 * pad);
  return seriesList.map((v) => v.map((val, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(val).toFixed(1)}`).join(""));
}

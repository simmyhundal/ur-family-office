// Loads the bundled prices (the files the workflow writes to site/data/). Paths resolve from js/, so any page depth works.
const url = (name) => new URL("../data/" + name, import.meta.url).href;

export async function getJson(name) {
  const res = await fetch(url(name));
  if (!res.ok) throw new Error(name + " " + res.status);
  return res.json();
}

// -> { data: {dates, series, rf}, labels, demo, source, presets }
export async function loadPrices() {
  let d, demo = false;
  if (globalThis.UFO_DATA) d = globalThis.UFO_DATA; // set by scripts/build_single_page.py (one-file copy)
  else try { d = await getJson("prices.json"); } catch { d = await getJson("demo-prices.json"); demo = true; }
  let presets = [];
  if (!demo) { try { presets = globalThis.UFO_PRESETS || await getJson("presets.json"); } catch { /* no presets is fine */ } }
  const has = (x) => x in d.series;
  return {
    data: { dates: d.dates, series: d.series, rf: d.rf ?? null }, // rf: cash rate in % a year
    labels: d.labels || {}, demo,
    source: d.asOf ? `Prices to ${d.asOf}.` : "",
    presets: presets.filter((p) => Object.keys(p.weights).every(has)),
  };
}

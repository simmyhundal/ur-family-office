// Loads the bundled prices (the files the workflow writes to site/data/). Paths resolve from js/, so any page depth works.
// Completed months only: a month that has not ended yet is dropped before anything is computed.
import { completedMonths, localToday, throughLabel } from "./calc.mjs";
const url = (name) => new URL("../data/" + name, import.meta.url).href;

export async function getJson(name) {
  const res = await fetch(url(name));
  if (!res.ok) throw new Error(name + " " + res.status);
  return res.json();
}

// -> { data: {dates, series, rf}, labels, demo, source, through, presets }
export async function loadPrices(today = localToday()) {
  let d, demo = false;
  if (globalThis.UFO_DATA) d = globalThis.UFO_DATA; // set by scripts/build_single_page.py (one-file copy)
  else try { d = await getJson("prices.json"); } catch { d = await getJson("demo-prices.json"); demo = true; }
  let presets = [];
  if (!demo) { try { presets = globalThis.UFO_PRESETS || await getJson("presets.json"); } catch { /* no presets is fine */ } }
  const has = (x) => x in d.series;
  const data = completedMonths({ dates: d.dates, series: d.series, rf: d.rf ?? null }, today); // rf: cash rate in % a year
  const through = data.dates.length ? throughLabel(data.dates.at(-1)) : "";
  return {
    data, labels: d.labels || {}, demo, through,
    source: demo || !through ? "" : `Prices through ${through}.`,
    presets: presets.filter((p) => Object.keys(p.weights).every(has)),
  };
}

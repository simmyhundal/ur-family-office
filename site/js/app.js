// The page. All data stays in the browser: no network calls except loading the bundled demo prices.
import { compare, parsePricesCsv, sliceFor } from "./calc.mjs";
import { $, el, svg, money, pct, spct, monthYear, revealOnScroll, saveMix, SAMPLE } from "./util.mjs";
import { loadPrices } from "./data.mjs";
import { savePortfolio, listPortfolios, renamePortfolio, deletePortfolio, clearEverything } from "./portfolios.mjs";
import { parsePositions, TEMPLATE_CSV } from "./positions.mjs";
import { encodeShare, decodeShare, cardContent } from "./share.mjs";

const TIPS = {
  gain: "Ending value minus the money you put in, before taxes.",
  year: "How fast the investments grew each year, as if $1 had stayed in the whole time. Your deposits and timing don't flatter it. Needs 12 months of history.",
  ups: "How much the monthly returns swing, shown as a yearly figure (volatility). Higher means a bumpier ride.",
  fall: "The biggest drop from a previous high point, before it recovered (maximum drawdown).",
  sharpe: "Return above a safe cash rate (3-month Treasury bills) for each unit of ups and downs. Higher is better: below 0.5 is weak, around 1 is good, above 2 is rare. Needs 12 months of history.",
  ends: "What the money would be worth on the last date, before taxes.",
};
const tip = (label, key) => el("span", { class: "tip", tabindex: "0", "data-tip": TIPS[key], "aria-description": TIPS[key] }, label);

const state = { years: 5, data: null, labels: {}, demo: true, source: "", rows: [], presets: [], mixName: "Your mix", sample: false };
const OTHER = ["SPY", "VTI", "QQQ", "IWM", "AGG"]; // shown in the "other benchmarks" table when the data has them

async function load() {
  const p = await loadPrices();
  state.data = p.data; state.labels = p.labels; state.demo = p.demo; state.source = p.source;
  const has = (x) => x in p.data.series;
  state.presets = p.presets;
  state.rows = p.demo ? [{ sym: "DEMOUS", w: 60 }, { sym: "DEMOBD", w: 30 }, { sym: "DEMOGD", w: 10 }]
    : state.presets.length ? rowsOf(state.presets[0]) : starter();
  state.mixName = state.presets.length && !p.demo ? state.presets[0].name : "Your mix";
  $("benchmark").value = has("SPY") ? "SPY" : Object.keys(p.data.series)[0];
  setup();
  const shared = decodeShare(location.search);
  if (shared) applyConfig({ ...shared, name: "Shared mix" }, { fromLink: true });
  else if (new URLSearchParams(location.search).get("sample") === "1") loadSample();
  renderSaved();
}

const symbols = () => Object.keys(state.data.series);
const rowsOf = (p) => Object.entries(p.weights).map(([sym, w]) => ({ sym, w }));
const starter = () => (["VTI", "BND"].every((x) => x in state.data.series) ? [{ sym: "VTI", w: 60 }, { sym: "BND", w: 40 }]
  : symbols().slice(0, 2).map((sym, i) => ({ sym, w: i ? 40 : 60 })));
function markCustom() { state.sample = false; state.mixName = "Your mix"; $("preset").value = "custom"; }

function setup() {
  $("data-banner").textContent = state.demo
    ? "Demo data: invented funds, not real prices."
    : state.source || `Your file: ${symbols().length} funds.`;
  $("sample-note").hidden = !state.sample;
  $("reset-data").hidden = state.demo && !$("csv").value;
  $("tickers").replaceChildren(...symbols().map((s) => el("option", { value: s }, state.labels[s] || "")));
  state.rows = state.rows.filter((r) => symbols().includes(r.sym));
  if (!state.rows.length) state.rows = [{ sym: symbols()[0], w: 100 }];
  const pre = $("preset");
  pre.replaceChildren(...state.presets.map((p, i) => el("option", { value: String(i) }, p.name)), el("option", { value: "custom" }, "Your own"));
  pre.value = state.mixName === "Your mix" ? "custom" : String(state.presets.findIndex((p) => p.name === state.mixName));
  pre.closest("label").hidden = !state.presets.length;
  renderRows();
  render();
}

function renderRows() {
  const box = $("rows");
  box.replaceChildren();
  state.rows.forEach((row, i) => {
    const sel = el("input", { list: "tickers", autocomplete: "off", spellcheck: "false", value: row.sym, "aria-label": `Fund ${i + 1}`, placeholder: "Ticker" });
    sel.addEventListener("input", () => { row.sym = sel.value.trim().toUpperCase(); markCustom(); render(); });
    const w = el("input", { type: "number", min: "0", max: "100", step: "1", value: String(row.w), "aria-label": `Weight ${i + 1}, percent` });
    w.addEventListener("input", () => { row.w = Number(w.value); markCustom(); render(); });
    const rm = el("button", { type: "button", class: "rm", "aria-label": `Remove fund ${i + 1}` }, "×");
    rm.addEventListener("click", () => { state.rows.splice(i, 1); markCustom(); renderRows(); render(); });
    box.append(el("div", { class: "mix-row" }, sel, w, rm));
  });
}

function mixWeights() {
  const out = {};
  for (const r of state.rows) if (r.w > 0) out[r.sym] = (out[r.sym] || 0) + r.w;
  return out;
}

let lastR = null; // the latest result, for the share card

function render() {
  const err = $("error");
  err.textContent = "";
  const total = state.rows.reduce((s, r) => s + (r.w > 0 ? r.w : 0), 0);
  $("weight-note").textContent = total === 100 ? "" : `Adds up to ${Math.round(total * 10) / 10}%, scaled to 100%.`;
  try {
    const initial = Number($("initial").value);
    const monthly = Number($("monthly").value) || 0;
    if (!(initial > 0)) throw new Error("Enter a starting amount above zero.");
    const mix = mixWeights();
    const bench = $("benchmark").value.trim().toUpperCase();
    const unknown = [...Object.keys(mix), bench].filter((x) => !(x in state.data.series));
    if (unknown.length) throw new Error(`No prices for ${unknown.join(", ")}. Pick from the list, or use your own CSV.`);
    const others = OTHER.filter((x) => x in state.data.series);
    const needed = [...new Set([...Object.keys(mix), bench, ...others])];
    const data = sliceFor(state.data, needed, state.years);
    if (data.dates.length < 3) throw new Error("Not enough months of prices to compare.");
    const r = compare({ prices: data.series, mix, benchmark: bench, initial, monthly, strategy: $("strategy").value, rf: data.rf });
    draw({ r, dates: data.dates, monthly, bench, limitedBy: data.limitedBy, years: state.years });
    drawOthers({ data, mix, others, initial, monthly, mixEnd: r.mix.m.endValue });
    drawSummary({ r, bench });
    lastR = { r, bench, mix, years: state.years, strategy: $("strategy").value, initial, monthly };
    if (!$("share-panel").hidden) drawSharePanel();
    saveMix({ rows: state.rows, benchmark: bench, initial, monthly, strategy: $("strategy").value, years: state.years, name: state.mixName, sample: state.sample });
  } catch (e) {
    err.textContent = e.message;
    for (const id of ["verdict", "period-line", "chart-desc", "headline", "headline-sub"]) $(id).textContent = "";
    for (const id of ["cards", "chart", "legend", "table-wrap", "benchmarks"]) $(id).replaceChildren();
  }
}

// The first thing a visitor sees: one headline number and one chart.
function drawSummary({ r, bench }) {
  const a = r.mix.m.annualReturn, b = r.bench.m.annualReturn;
  if (a == null || b == null) {
    $("headline").textContent = `${state.mixName} ended at ${money(r.mix.m.endValue)}; ${bench} at ${money(r.bench.m.endValue)}.`;
    $("headline-sub").textContent = "A yearly rate needs 12 months of prices; open the details for the rest.";
    return;
  }
  $("headline").textContent = `${state.mixName} vs ${bench}: ${spct(a)} vs ${spct(b)} a year`;
  const diff = r.mix.m.endValue - r.bench.m.endValue;
  $("headline-sub").textContent = diff === 0 ? "The same result." : `${state.mixName} finished ${money(Math.abs(diff))} ${diff > 0 ? "ahead of" : "behind"} ${bench}. Before taxes and costs.`;
}

function card(kind, title, m) {
  const rows = [
    ["Gain", (m.gain >= 0 ? "+" : "") + money(m.gain)],
    ["Per year", m.annualReturn == null ? "n/a" : spct(m.annualReturn)],
    ["Ups and downs", m.volatility == null ? "n/a" : pct(m.volatility)],
    ["Worst fall", pct(m.maxDrawdown)],
    ["Sharpe ratio", m.sharpe == null ? "n/a" : m.sharpe.toFixed(2)],
  ];
  const keys = ["gain", "year", "ups", "fall", "sharpe"];
  const dl = el("dl");
  rows.forEach(([k, v], i) => dl.append(el("dt", {}, tip(k, keys[i])), el("dd", {}, v)));
  return el("div", { class: `card ${kind}` }, el("h3", {}, title), el("div", { class: "hero" }, money(m.endValue)), dl);
}

function draw({ r, dates, monthly, bench, limitedBy, years }) {
  const { mix, bench: b } = r;
  $("period-line").textContent = `${monthYear(dates[0])} to ${monthYear(dates.at(-1))}.` +
    (limitedBy ? ` Starts when ${limitedBy} does.` : years < 99 && mix.m.months < years * 12 ? " That is all the history there is." : "") + ` Put in ${money(mix.m.putIn)}.`;
  const mixName = state.mixName, benchName = bench;
  $("cards").replaceChildren(card("mix", mixName, mix.m), card("bench", benchName, b.m));
  const diff = mix.m.endValue - b.m.endValue;
  $("verdict").textContent = diff === 0 ? "Same result."
    : `${mixName} finished ${money(Math.abs(diff))} ${diff > 0 ? "ahead of" : "behind"} ${bench}. Worst fall: ${pct(Math.abs(mix.m.maxDrawdown))} vs ${pct(Math.abs(b.m.maxDrawdown))}.`;
  drawChart({ dates, series: [{ name: mixName, key: "mix", color: "var(--mix)", v: mix.sim.values }, { name: benchName, key: "bench", color: "var(--bench)", v: b.sim.values }], put: monthly > 0 ? mix.sim.contributed : null });
  drawTable(dates, mixName, benchName, mix.sim.values, b.sim.values, monthly > 0 ? mix.sim.contributed : null);
}

// ---------- chart ----------
let lastChart = null;
const PL = 64, PR = 16, PT = 20, PB = 28;

function niceTicks(max) {
  const raw = max / 4, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= raw);
  const out = [];
  for (let v = 0; ; v += step) { out.push(v); if (v >= max) break; }
  return out;
}

function drawOthers({ data, mix, others, initial, monthly, mixEnd }) {
  const box = $("benchmarks");
  if (others.length < 2) { box.replaceChildren(); return; }
  const rows = others.map((b) => {
    const m = compare({ prices: data.series, mix, benchmark: b, initial, monthly, strategy: $("strategy").value }).bench.m;
    const d = mixEnd - m.endValue;
    return el("tr", {}, el("td", {}, b), el("td", {}, money(m.endValue)), el("td", {}, m.annualReturn == null ? "n/a" : spct(m.annualReturn)), el("td", {}, (d >= 0 ? "+" : "-") + money(Math.abs(d))));
  });
  const head = el("tr", {}, ...["Benchmark", "Ends at", "Per year", `${state.mixName} vs it`].map((t, i) => el("th", { scope: "col" }, i === 1 ? tip(t, "ends") : i === 2 ? tip(t, "year") : t)));
  box.replaceChildren(el("h3", {}, "Other benchmarks"), el("table", {}, el("thead", {}, head), el("tbody", {}, ...rows)));
}

function drawChart({ dates, series, put }) {
  lastChart = { dates, series, put };
  const W = Math.max(300, Math.round($("chart").clientWidth || 760)), H = W < 520 ? 240 : 300; // drawn at real size so text stays readable
  const all = series.flatMap((s) => s.v).concat(put || []);
  const ticks = niceTicks(Math.max(...all) * 1.05);
  const top = ticks.at(-1), n = dates.length;
  const x = (i) => PL + (i / (n - 1)) * (W - PL - PR);
  const y = (v) => PT + (1 - v / top) * (H - PT - PB);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true", focusable: "false" });
  for (const t of ticks) {
    root.append(svg("line", { class: "grid", x1: PL, x2: W - PR, y1: y(t), y2: y(t) }));
    const lab = svg("text", { class: "axis-text", x: PL - 8, y: y(t) + 4, "text-anchor": "end" });
    lab.textContent = money(t);
    root.append(lab);
  }
  for (let i = 0; i < n; i += W < 520 ? 24 : 12) {
    const lab = svg("text", { class: "axis-text", x: x(i), y: H - 8, "text-anchor": i === 0 ? "start" : x(i) > W - PR - 40 ? "end" : "middle" });
    lab.textContent = monthYear(dates[i]);
    root.append(lab);
  }
  const path = (v) => v.map((val, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(val).toFixed(1)}`).join("");
  // a soft fill under the first line (the mix), drawn behind the lines
  const grad = svg("linearGradient", { id: "mix-fill", x1: 0, y1: 0, x2: 0, y2: 1 });
  grad.append(svg("stop", { offset: 0, "stop-color": series[0].color, "stop-opacity": 0.22 }), svg("stop", { offset: 1, "stop-color": series[0].color, "stop-opacity": 0 }));
  const defs = svg("defs"); defs.append(grad);
  root.append(defs, svg("path", { d: `${path(series[0].v)}L${x(n - 1).toFixed(1)},${y(0).toFixed(1)}L${x(0).toFixed(1)},${y(0).toFixed(1)}Z`, fill: "url(#mix-fill)" }));
  if (put) root.append(svg("path", { d: path(put), fill: "none", stroke: "var(--put)", "stroke-width": 2, "stroke-dasharray": "5 4" }));
  for (const s of [...series].reverse()) root.append(svg("path", { d: path(s.v), fill: "none", stroke: s.color, "stroke-width": s === series[0] ? 3 : 2.25, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  // direct end labels (selective): the final value of each line
  const ends = series.map((s) => ({ s, yy: y(s.v.at(-1)) })).sort((a, b) => a.yy - b.yy);
  if (ends.length === 2 && ends[1].yy - ends[0].yy < 14) ends[1].yy = ends[0].yy + 14;
  for (const { s, yy } of W < 520 ? [] : ends) { // narrow screens: the cards already show these
    const t = svg("text", { x: W - PR - 4, y: yy - 6, "text-anchor": "end", "font-size": 12, "font-weight": 600, fill: "var(--ink)" });
    t.textContent = money(s.v.at(-1));
    root.append(t);
  }
  const cross = svg("line", { y1: PT, y2: H - PB, stroke: "var(--ink-2)", "stroke-width": 1, visibility: "hidden" });
  const dots = series.map((s) => svg("circle", { r: 5, fill: s.color, stroke: "var(--surface)", "stroke-width": 2, visibility: "hidden" }));
  root.append(cross, ...dots);
  const tip = el("div", { class: "tooltip", hidden: "" });
  const chart = $("chart");
  chart.replaceChildren(root, tip);

  let idx = n - 1;
  const show = (i) => {
    idx = Math.max(0, Math.min(n - 1, i));
    const px = x(idx);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
    series.forEach((s, k) => { dots[k].setAttribute("cx", px); dots[k].setAttribute("cy", y(s.v[idx])); dots[k].setAttribute("visibility", "visible"); });
    tip.replaceChildren(el("b", {}, monthYear(dates[idx])),
      ...series.map((s) => el("div", {}, el("span", { class: "k", style: `background:${s.color}` }), `${s.name}: ${money(s.v[idx])}`)),
      ...(put ? [el("div", {}, el("span", { class: "k", style: "background:var(--put)" }), `Put in: ${money(put[idx])}`)] : []));
    tip.hidden = false;
    const box = chart.getBoundingClientRect(), scale = box.width / W; // 1 unless the page was resized since the draw
    const left = px * scale + 12;
    tip.style.left = (left + tip.offsetWidth > box.width ? px * scale - tip.offsetWidth - 12 : left) + "px";
    tip.style.top = Math.round(box.width * (H / W) * 0.55) + "px"; // lower part of the plot: the lines stay visible
  };
  const hide = () => { cross.setAttribute("visibility", "hidden"); dots.forEach((d) => d.setAttribute("visibility", "hidden")); tip.hidden = true; };
  chart.onpointermove = (e) => { const b = chart.getBoundingClientRect(); show(Math.round(((e.clientX - b.left) / b.width * W - PL) / (W - PL - PR) * (n - 1))); };
  chart.onpointerleave = hide;
  chart.onfocus = () => show(idx);
  chart.onblur = hide;
  chart.onkeydown = (e) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, PageDown: -12, PageUp: 12 }[e.key];
    if (e.key === "Home") { e.preventDefault(); show(0); } else if (e.key === "End") { e.preventDefault(); show(n - 1); }
    else if (step) { e.preventDefault(); show(idx + step); }
  };

  $("legend").replaceChildren(
    ...series.map((s) => el("span", {}, el("i", { style: `background:${s.color}` }), s.name)),
    ...(put ? [el("span", {}, el("i", { style: "background:var(--put)" }), "Put in")] : []));
  const a = series[0], b = series[1];
  $("chart-desc").textContent = `${state.mixName} goes from ${money(a.v[0])} to ${money(a.v.at(-1))}; the benchmark from ${money(b.v[0])} to ${money(b.v.at(-1))}. Arrow keys step through months.`;
}

function drawTable(dates, an, bn, a, b, put) {
  const head = ["Month", an, bn, ...(put ? ["Put in"] : [])];
  const table = el("table", {}, el("thead", {}, el("tr", {}, ...head.map((h) => el("th", { scope: "col" }, h)))));
  const body = el("tbody");
  dates.forEach((d, i) => body.append(el("tr", {}, el("td", {}, monthYear(d)), el("td", {}, money(a[i])), el("td", {}, money(b[i])), ...(put ? [el("td", {}, money(put[i]))] : []))));
  table.append(body);
  $("table-wrap").replaceChildren(el("div", { class: "table-scroll" }, table));
}

// ---------- sample portfolio ----------
// An invented person with invented deposits; the prices are the real bundled ones (or the demo set when running on demo data).
function loadSample() {
  const pick = Object.keys(SAMPLE.real.weights).every((x) => x in state.data.series) ? SAMPLE.real : SAMPLE.demo;
  if (!Object.keys(pick.weights).every((x) => x in state.data.series)) { $("error").textContent = "The sample needs the built-in prices; click “Back to built-in prices” first."; return; }
  state.rows = rowsOf(pick); state.mixName = SAMPLE.name; state.sample = true;
  $("initial").value = SAMPLE.initial; $("monthly").value = SAMPLE.monthly; $("strategy").value = "hold";
  state.years = 5;
  document.querySelectorAll(".seg button").forEach((o) => o.setAttribute("aria-pressed", String(o.dataset.years === "5")));
  setup();
  $("preset").value = "custom";
}

// ---------- apply a saved mix or a shared link ----------
function applyConfig(c, { fromLink = false } = {}) {
  const have = symbols();
  const rows = Object.entries(c.weights).filter(([sym]) => have.includes(sym)).map(([sym, w]) => ({ sym, w }));
  const missing = Object.keys(c.weights).filter((x) => !have.includes(x));
  if (!rows.length) { $("error").textContent = "None of those funds have prices in the current data."; return; }
  state.rows = rows; state.mixName = c.name || "Your mix"; state.sample = false;
  if (c.benchmark && have.includes(c.benchmark)) $("benchmark").value = c.benchmark;
  if (c.strategy) $("strategy").value = c.strategy;
  if (c.initial > 0) $("initial").value = c.initial;
  if (c.monthly != null && !fromLink) $("monthly").value = c.monthly;
  if (fromLink) { $("initial").value = 10000; $("monthly").value = 0; }
  if (c.years) state.years = c.years;
  document.querySelectorAll(".seg button").forEach((o) => o.setAttribute("aria-pressed", String(Number(o.dataset.years) === state.years)));
  setup();
  $("preset").value = "custom";
  $("link-note").hidden = !fromLink;
  if (missing.length) $("error").textContent = `No prices for ${missing.join(", ")}; left out.`;
}

// ---------- save / my portfolios (this browser only) ----------
const store = () => { try { return localStorage; } catch { return null; } };
function currentConfig() {
  return { name: state.mixName === "Your mix" ? "My mix" : state.mixName, weights: mixWeights(), benchmark: $("benchmark").value.trim().toUpperCase(),
    years: state.years, strategy: $("strategy").value, initial: Number($("initial").value), monthly: Number($("monthly").value) || 0 };
}
function renderSaved() {
  const st = store(), list = $("saved-list");
  const items = st ? listPortfolios(st) : [];
  $("saved-empty").hidden = items.length > 0;
  list.replaceChildren(...items.map((p) => {
    const open = el("button", { type: "button", class: "secondary" }, "Open");
    open.addEventListener("click", () => { applyConfig(p); $("save-status").textContent = `Opened “${p.name}”.`; });
    const ren = el("button", { type: "button", class: "secondary", "aria-label": `Rename ${p.name}` }, "Rename");
    ren.addEventListener("click", () => { const n = prompt("Name for this mix", p.name); if (n) { renamePortfolio(st, p.id, n); renderSaved(); } });
    const del = el("button", { type: "button", class: "secondary", "aria-label": `Delete ${p.name}` }, "Delete");
    del.addEventListener("click", () => { deletePortfolio(st, p.id); renderSaved(); });
    const n = Object.keys(p.weights).length;
    return el("li", {}, el("div", {}, el("div", { class: "nm" }, p.name), el("div", { class: "sub" }, `${n} fund${n === 1 ? "" : "s"} vs ${p.benchmark || "n/a"}, ${p.years >= 99 ? "all history" : p.years + "y"}`)), el("div", { class: "acts" }, open, ren, del));
  }));
}
$("save-mix").addEventListener("click", () => {
  const st = store();
  if (!st) { $("save-status").textContent = "This browser isn't allowing saving."; return; }
  try {
    const cfg = currentConfig();
    const name = prompt("Name for this mix", cfg.name);
    if (name === null) return;
    savePortfolio(st, { ...cfg, name });
    renderSaved();
    $("save-status").textContent = "Saved on this device. Find it under “Your mix and settings”, My portfolios.";
  } catch (e) { $("save-status").textContent = e.message; }
});
$("clear-all").addEventListener("click", () => {
  if (!confirm("Remove every saved mix and setting from this device? This can't be undone.")) return;
  let n = 0;
  try { n = clearEverything(localStorage, sessionStorage).length; } catch { /* storage blocked: nothing saved */ }
  renderSaved();
  $("save-status").textContent = n ? "Cleared everything saved on this device." : "Nothing was saved on this device.";
});

// ---------- positions CSV -> mix ----------
async function loadPositions(file) {
  const msg = $("positions-msg");
  try {
    const res = parsePositions(await file.text(), symbols());
    applyConfig({ weights: res.weights, name: "My holdings" });
    markCustom(); state.mixName = "My holdings"; render();
    msg.textContent = `Loaded ${Object.keys(res.weights).length} holdings from a ${res.format === "fidelity" ? "Fidelity positions" : "template"} file as percentages. ${res.notes.join(" ")}`;
    $("error").textContent = "";
  } catch (e) { msg.textContent = e.message; }
}
$("positions").addEventListener("change", (e) => { if (e.target.files[0]) loadPositions(e.target.files[0]); });
const drop = $("drop");
for (const ev of ["dragenter", "dragover"]) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); });
for (const ev of ["dragleave", "drop"]) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); });
drop.addEventListener("drop", (e) => { const f = e.dataTransfer?.files?.[0]; if (f) loadPositions(f); });
$("template-dl").addEventListener("click", (e) => {
  e.preventDefault();
  const url = URL.createObjectURL(new Blob([TEMPLATE_CSV], { type: "text/csv" }));
  const a = el("a", { href: url, download: "positions-template.csv" });
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});

// ---------- share link and card (percentages only) ----------
function shareConfig() {
  return { weights: mixWeights(), benchmark: lastR.bench, years: lastR.years, strategy: lastR.strategy };
}
function drawSharePanel() {
  if (!lastR) return;
  const cfg = shareConfig();
  const link = `${location.origin}${location.pathname}?${encodeShare(cfg)}`;
  $("share-link").value = link;
  const n = Object.keys(cfg.weights).length;
  $("share-what").textContent = `The link carries ${n} holding${n === 1 ? "" : "s"} as percentages, the benchmark (${cfg.benchmark}), the time window and the style. It does not carry dollar amounts, deposits or your mix's name. The card below is exactly what the image will show.`;
  const m = lastR.r.mix.m, b = lastR.r.bench.m;
  const c = cardContent({ ...cfg, mixAnnual: m.annualReturn, benchAnnual: b.annualReturn, mixSharpe: m.sharpe, benchSharpe: b.sharpe });
  paintCard($("share-card"), c);
}
function paintCard(cv, c) {
  const g = cv.getContext("2d"), css = getComputedStyle(document.documentElement), v = (k) => css.getPropertyValue(k).trim();
  const W = cv.width, H = cv.height, font = "ui-rounded, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
  g.fillStyle = v("--surface") || "#fff"; g.fillRect(0, 0, W, H);
  g.fillStyle = v("--mix") || "#5b3fe0"; g.fillRect(0, 0, 14, H);
  g.textBaseline = "alphabetic";
  const t = (txt, x, y, size, color, weight = 600) => { g.font = `${weight} ${size}px ${font}`; g.fillStyle = color; g.fillText(txt, x, y); };
  t(c.title, 70, 110, 54, v("--ink") || "#13132b", 750);
  t(c.window, 70, 160, 28, v("--ink-2") || "#54577a", 500);
  t(c.mixLine, 70, 300, 96, v("--mix") || "#5b3fe0", 750);
  t(c.benchLine, 70, 370, 40, v("--bench") || "#c2410c");
  t(c.sharpeLine, 70, 430, 36, v("--ink") || "#13132b", 600);
  t(c.mixText, 70, 505, 28, v("--ink-2") || "#54577a", 500);
  t(c.foot, 70, 580, 22, v("--ink-2") || "#54577a", 500);
}
$("share-open").addEventListener("click", () => {
  const open = $("share-panel").hidden;
  $("share-panel").hidden = !open;
  $("share-open").setAttribute("aria-expanded", String(open));
  if (open) drawSharePanel();
});
$("share-copy").addEventListener("click", async () => {
  const inp = $("share-link");
  try { await navigator.clipboard.writeText(inp.value); $("save-status").textContent = "Link copied."; }
  catch { inp.select(); $("save-status").textContent = "Press Ctrl/Cmd+C to copy the selected link."; }
});
$("share-png").addEventListener("click", () => {
  $("share-card").toBlob((blob) => {
    const url = URL.createObjectURL(blob);
    const a = el("a", { href: url, download: "my-mix-vs-benchmark.png" });
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
});

// ---------- events ----------
let resizeTimer = null, lastWidth = 0;
new ResizeObserver(() => {
  const w = $("chart").clientWidth;
  if (!lastChart || !w || w === lastWidth) return;
  lastWidth = w;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => drawChart(lastChart), 100);
}).observe($("chart"));
$("preset").addEventListener("change", () => {
  const p = state.presets[Number($("preset").value)];
  state.rows = p ? rowsOf(p) : starter();
  state.mixName = p ? p.name : "Your mix";
  renderRows(); render();
});
$("add-row").addEventListener("click", () => {
  const used = new Set(state.rows.map((r) => r.sym));
  state.rows.push({ sym: symbols().find((s) => !used.has(s)) || symbols()[0], w: 10 });
  markCustom(); renderRows(); render();
});
for (const id of ["benchmark", "strategy", "initial", "monthly"]) $(id).addEventListener("input", render);
document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
  state.years = Number(b.dataset.years);
  document.querySelectorAll(".seg button").forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
  render();
}));
$("toggle-table").addEventListener("click", () => {
  const open = $("table-wrap").hidden;
  $("table-wrap").hidden = !open;
  $("toggle-table").setAttribute("aria-expanded", String(open));
  $("toggle-table").textContent = open ? "Hide table" : "Show table";
});
$("csv").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const parsed = parsePricesCsv(await file.text());
    if (parsed.dates.length < 13) throw new Error("Need at least 13 months of prices that every fund shares.");
    state.data = { dates: parsed.dates, series: parsed.series, rf: null }; // no cash rate in a CSV, so no Sharpe
    state.labels = {}; state.demo = false; state.source = ""; state.presets = []; state.mixName = "Your mix";
    const names = Object.keys(parsed.series);
    state.rows = names.slice(0, 2).map((s, i) => ({ sym: s, w: i ? 40 : 60 }));
    $("benchmark").value = names[0];
    setup();
  } catch (err) {
    $("error").textContent = err.message;
  }
});
$("sample").addEventListener("click", loadSample);
$("reset-data").addEventListener("click", () => { $("csv").value = ""; load(); });

revealOnScroll();
load().catch((e) => { $("error").textContent = "Could not load prices: " + e.message; });

// The Sharpe lesson: one card per step, Back and Next. Runs on the mix loaded on the Try page (this tab), else the sample.
import { compare, sliceFor } from "./calc.mjs";
import { $, revealOnScroll, loadMix, SAMPLE } from "./util.mjs";
import { loadPrices } from "./data.mjs";
import { lessonSteps } from "./lesson.mjs";

let steps = [], at = 0;

function show(i, focus = true) {
  at = Math.max(0, Math.min(steps.length - 1, i));
  const s = steps[at];
  $("step-count").textContent = `Step ${at + 1} of ${steps.length}`;
  $("progress").style.width = `${((at + 1) / steps.length) * 100}%`;
  $("progress-bar").setAttribute("aria-valuenow", String(at + 1));
  $("progress-bar").setAttribute("aria-valuemax", String(steps.length));
  $("step-tag").textContent = s.tag || "Sharpe ratio";
  $("step-title").textContent = s.title;
  $("step-body").replaceChildren(...s.body);
  $("back").disabled = at === 0;
  $("next").hidden = at === steps.length - 1;
  $("done").hidden = at !== steps.length - 1;
  const card = $("step-card");
  card.classList.remove("swap"); void card.offsetWidth; card.classList.add("swap");
  if (focus) $("step-title").focus();
}

function build(p) {
  const saved = loadMix();
  const has = (x) => x in p.data.series;
  const real = Object.keys(SAMPLE.real.weights).every(has);
  let cfg = saved && saved.rows.every((r) => has(r.sym)) && has(saved.benchmark) ? saved : null;
  if (!cfg) {
    const w = real ? SAMPLE.real.weights : SAMPLE.demo.weights;
    cfg = { rows: Object.entries(w).map(([sym, w]) => ({ sym, w })), benchmark: has("SPY") ? "SPY" : Object.keys(p.data.series)[0],
      initial: SAMPLE.initial, monthly: SAMPLE.monthly, strategy: "hold", years: 5, name: SAMPLE.name, sample: true };
  }
  const mix = {};
  for (const r of cfg.rows) if (r.w > 0) mix[r.sym] = (mix[r.sym] || 0) + r.w;
  const data = sliceFor(p.data, [...new Set([...Object.keys(mix), cfg.benchmark])], cfg.years);
  const r = compare({ prices: data.series, mix, benchmark: cfg.benchmark, initial: cfg.initial, monthly: cfg.monthly, strategy: cfg.strategy, rf: data.rf });
  $("which").textContent = cfg.sample
    ? `Running on a sample portfolio: an invented person who starts with $${SAMPLE.initial.toLocaleString("en-US")} and adds $${SAMPLE.monthly} a month. The prices are real; the person is not.`
    : `Running on the mix you loaded on the Try page (${cfg.name}) against ${cfg.benchmark}.`;
  steps = lessonSteps({ r, data, mix, bench: cfg.benchmark, monthly: cfg.monthly, name: cfg.name });
}

$("back").addEventListener("click", () => show(at - 1));
$("next").addEventListener("click", () => show(at + 1));
document.addEventListener("keydown", (e) => {
  if (e.target.closest("input,select,textarea,summary") || !steps.length) return;
  if (e.key === "ArrowRight") show(at + 1); else if (e.key === "ArrowLeft") show(at - 1);
});
revealOnScroll();
loadPrices().then((p) => { build(p); show(0, false); $("lesson").hidden = false; })
  .catch((e) => { $("which").textContent = "Could not load prices: " + e.message; });

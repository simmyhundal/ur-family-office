// The Sharpe lesson: one card per step, Back and Next. Runs on the mix loaded on the Try page (this tab), else the sample,
// through the same runResult() as Try, so the two numbers on the first card are the ones Try shows.
import { $, revealOnScroll, loadMix } from "./util.mjs";
import { loadPrices } from "./data.mjs";
import { runResult, sampleConfig } from "./result.mjs";
import { lessonSteps } from "./lesson.mjs";

let steps = [], extra = [], at = 0;

function show(i, focus = true) {
  at = Math.max(0, Math.min(steps.length - 1, i));
  const s = steps[at];
  $("step-count").textContent = `${at + 1} of ${steps.length}`;
  $("progress").style.width = `${((at + 1) / steps.length) * 100}%`;
  $("progress-bar").setAttribute("aria-valuenow", String(at + 1));
  $("progress-bar").setAttribute("aria-valuemax", String(steps.length));
  $("step-tag").textContent = s.tag || "Sharpe ratio";
  $("step-title").textContent = s.title;
  $("step-body").replaceChildren(...s.body);
  $("back").disabled = at === 0;
  const last = at === steps.length - 1;
  $("next").hidden = last || s.end;
  $("done").hidden = !(last || s.end);
  $("further").hidden = !(s.end && steps.length === mainLength && extra.length);
  const card = $("step-card");
  card.classList.remove("swap"); void card.offsetWidth; card.classList.add("swap");
  if (focus) $("step-title").focus();
}

let mainLength = 0;
function build(p) {
  const saved = loadMix();
  const has = (x) => x in p.data.series;
  let cfg = null;
  if (saved && saved.rows?.length && saved.rows.every((r) => has(r.sym)) && has(saved.benchmark)) {
    const weights = {};
    for (const r of saved.rows) if (r.w > 0) weights[r.sym] = (weights[r.sym] || 0) + r.w;
    cfg = { weights, benchmark: saved.benchmark, initial: saved.initial, monthly: saved.monthly, strategy: saved.strategy, years: saved.years, name: saved.name };
  }
  if (!cfg) cfg = sampleConfig(p.data);
  const res = runResult(p.data, cfg);
  ({ steps, extra } = lessonSteps({ r: res.r, data: res.slice, mix: res.mix, bench: res.bench, monthly: cfg.monthly, name: cfg.name }));
  mainLength = steps.length;
}

$("back").addEventListener("click", () => show(at - 1));
$("next").addEventListener("click", () => show(at + 1));
$("further").addEventListener("click", () => { steps = steps.concat(extra); show(at + 1); });
document.addEventListener("keydown", (e) => {
  if (e.target.closest("input,select,textarea,summary") || !steps.length) return;
  if (e.key === "ArrowRight" && !$("next").hidden) show(at + 1); else if (e.key === "ArrowLeft") show(at - 1);
});
revealOnScroll();
loadPrices().then((p) => { build(p); show(0, false); $("lesson").hidden = false; $("loading").hidden = true; })
  .catch((e) => { $("loading").textContent = "Could not load prices: " + e.message; });

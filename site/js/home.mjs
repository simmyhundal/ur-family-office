// Home: the hero preview is the sample portfolio, computed at load from the same prices and the same code as Try,
// so the two pages always agree. Also the Plus mock-up's what-if toggle (invented numbers, labelled illustrative).
import { $, spct, money, revealOnScroll } from "./util.mjs";
import { loadPrices } from "./data.mjs";
import { previewModel, linePaths, SAMPLE } from "./result.mjs";
import { throughLabel } from "./calc.mjs";

revealOnScroll();

async function preview() {
  const p = await loadPrices();
  const m = previewModel(p.data);
  if (!m || m.mixAnnual == null) return;
  $("pv-m").textContent = spct(m.mixAnnual); $("pv-b").textContent = spct(m.benchAnnual);
  $("pv-bench").textContent = m.bench; $("pv-bench2").textContent = m.bench;
  $("pv-chip").textContent = `${m.years} years · through ${throughLabel(m.to)}`;
  const lead = m.diff === 0 ? `Level with ${m.bench}.` : `${m.diff > 0 ? "Ahead of" : "Behind"} ${m.bench} by ${money(Math.abs(m.diff))}.`;
  $("pv-sub").textContent = `${lead} ${money(SAMPLE.initial)} to start, then ${money(SAMPLE.monthly)} a month. Before taxes and costs.`;
  if (m.mixSharpe != null) {
    $("pv-sharpe").textContent = `Sharpe ${m.mixSharpe.toFixed(2)}`;
    $("pv-sharpe-sub").textContent = m.benchSharpe != null ? `${m.bench}: ${m.benchSharpe.toFixed(2)}` : "Return per unit of risk";
  }
  const [mix, bench, put] = linePaths([m.mixValues, m.benchValues, m.putValues], 480, 190);
  $("pv-mline").setAttribute("d", mix); $("pv-bline").setAttribute("d", bench); $("pv-put").setAttribute("d", put);
  $("pv-fill").setAttribute("d", `${mix}L480,190L0,190Z`);
  $("pv").classList.add("ready");
}
preview().catch(() => { /* the placeholders stay; the card still opens Try */ });

// Plus mock-up: one what-if, invented numbers.
const WHAT = {
  off: { ret: "+7.9%", sh: "0.71", risk: "14.2%", out: "Tap to compare. Illustrative numbers." },
  on: { ret: "+7.6%", sh: "0.76", risk: "12.6%", out: "Risk −1.6 pts, return −0.3 pts, Sharpe +0.05. Illustrative." },
};
const btn = $("whatif");
if (btn) btn.addEventListener("click", () => {
  const on = btn.getAttribute("aria-pressed") !== "true";
  btn.setAttribute("aria-pressed", String(on));
  const w = on ? WHAT.on : WHAT.off;
  $("ph-ret").textContent = w.ret; $("ph-sh").textContent = w.sh; $("ph-risk").textContent = w.risk; $("whatif-out").textContent = w.out;
  btn.closest(".phone-screen").classList.toggle("what", on);
});

// Small helpers shared by the pages. No network, no storage beyond sessionStorage for the loaded mix.
export const $ = (id) => document.getElementById(id);
export const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) (k === "class" ? (n.className = v) : n.setAttribute(k, v));
  for (const kid of kids) n.append(kid);
  return n;
};
const NS = "http://www.w3.org/2000/svg";
export const svg = (tag, attrs = {}) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};
export const money = (x) => (x < 0 ? "-" : "") + "$" + Math.round(Math.abs(x)).toLocaleString("en-US");
export const pct = (x, d = 1) => (x == null || Number.isNaN(x) ? "n/a" : (x * 100).toFixed(d) + "%");
export const spct = (x, d = 1) => (x == null ? "n/a" : (x >= 0 ? "+" : "") + (x * 100).toFixed(d) + "%");
export const monthYear = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" });

// Gentle fade-in on scroll. The CSS only hides .reveal when <html class="js"> is set and motion is allowed.
export function revealOnScroll() {
  const items = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in globalThis) || matchMedia("(prefers-reduced-motion: reduce)").matches) { items.forEach((n) => n.classList.add("in")); return; }
  const io = new IntersectionObserver((entries) => entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: 0.12 });
  items.forEach((n) => io.observe(n));
}

// The mix a visitor loaded on the Try page, kept for this tab only so the lesson can run on it.
const KEY = "ufo-mix";
export const saveMix = (m) => { try { sessionStorage.setItem(KEY, JSON.stringify(m)); } catch { /* private mode: fine */ } };
export const loadMix = () => { try { return JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch { return null; } };


// Site configuration: defaults, validation and loading. Pure logic, no DOM, so node can test it.
export const DEFAULTS = Object.freeze({
  name: "UFO", wordmark: "UFO", tagline: "See how your investments really did",
  contact_email: "", signup_endpoint: "", checkout_urls: {},
});

const str = (v, fallback) => (typeof v === "string" && v.trim() ? v.trim() : fallback);
// Only https links may be an endpoint or a checkout link; anything else counts as "not set".
export const httpsUrl = (v) => {
  if (typeof v !== "string" || !v.trim()) return "";
  try { const u = new URL(v.trim()); return u.protocol === "https:" ? u.href : ""; } catch { return ""; }
};
const email = (v) => (typeof v === "string" && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim()) ? v.trim() : "");

export function mergeConfig(raw) {
  const r = raw && typeof raw === "object" ? raw : {};
  const checkout = {};
  if (r.checkout_urls && typeof r.checkout_urls === "object") {
    for (const [id, u] of Object.entries(r.checkout_urls)) { const ok = httpsUrl(u); if (ok) checkout[id] = ok; }
  }
  const name = str(r.name, DEFAULTS.name);
  return {
    name,
    wordmark: str(r.wordmark, name),
    tagline: str(r.tagline, DEFAULTS.tagline),
    contact_email: email(r.contact_email),
    signup_endpoint: httpsUrl(r.signup_endpoint),
    checkout_urls: checkout,
  };
}

// Reads a JSON file; any failure gives the defaults so pages still work.
export async function loadJson(path, fetchFn = fetch) {
  const res = await fetchFn(path);
  if (!res.ok) throw new Error(path + " " + res.status);
  return res.json();
}
export async function loadSiteConfig(path, fetchFn = fetch) {
  try { return mergeConfig(await loadJson(path, fetchFn)); } catch { return mergeConfig(null); }
}

export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Header and footer markup. `root` is the site root as a URL prefix ("../" etc.); `current` is a nav key.
export const NAV = [["try", "Try it"], ["learn", "Learn"], ["teach", "Teach"], ["pricing", "Pricing"], ["about", "About"]];
export function headerHtml(cfg, root, current) {
  const links = NAV.map(([k, label]) => `<a href="${root}${k}/"${k === current ? ' aria-current="page"' : ""}>${label}</a>`).join("");
  return `<div class="wrap">
  <a class="wordmark" href="${root}" aria-label="${esc(cfg.name)}, home">${esc(cfg.wordmark)}<span>.</span></a>
  <nav aria-label="Main">${links}<a class="nav-cta" href="${root}signup/"${current === "signup" ? ' aria-current="page"' : ""}>Sign up</a></nav>
</div>`;
}
export function footerHtml(cfg, root) {
  const contact = cfg.contact_email ? ` · <a href="mailto:${esc(cfg.contact_email)}">${esc(cfg.contact_email)}</a>` : "";
  return `<div class="wrap">
  <p><b>Information, not investment advice.</b> Results are before taxes and trading costs, and past results don’t predict future ones.</p>
  <p>Prices: month-end adjusted closes, refreshed on weekdays. Cash rate: 3-month Treasury bills from FRED.</p>
  <p class="foot-links"><a href="${root}pricing/">Pricing</a> · <a href="${root}privacy/">Privacy</a> · <a href="${root}terms/">Terms</a> · <a href="${root}about/">About</a>${contact}</p>
</div>`;
}

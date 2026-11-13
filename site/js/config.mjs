// Site configuration: defaults, validation and loading. Pure logic, no DOM, so node can test it.
export const DEFAULTS = Object.freeze({
  name: "UFO", wordmark: "UFO", tagline: "A higher view of your money", logo: "img/logo.svg",
  legal_name: "Mycorrhiza Partners LLC DBA Ur Family Office",
  contact_email: "", signup_endpoint: "", checkout_urls: {},
  founder: { name: "", photo: "", linkedin: "" },
});
// Tagline alternatives considered (issue 175): "See every investment from above", "Your whole portfolio, in one orbit",
// "Out-of-this-world clarity for down-to-earth money". The copyright year in the footer.
export const YEAR = 2026;

const str = (v, fallback) => (typeof v === "string" && v.trim() ? v.trim() : fallback);
// Only https links may be an endpoint or a checkout link; anything else counts as "not set".
export const httpsUrl = (v) => {
  if (typeof v !== "string" || !v.trim()) return "";
  try { const u = new URL(v.trim()); return u.protocol === "https:" ? u.href : ""; } catch { return ""; }
};
// The logo is a path inside the site (e.g. "img/logo.svg"): no scheme, no "//", no "..", so it cannot point elsewhere.
export const sitePath = (v, fallback) =>
  typeof v === "string" && /^[A-Za-z0-9_-][A-Za-z0-9_./-]*\.(svg|png|jpe?g)$/.test(v.trim()) && !v.includes("..") && !v.includes("//") ? v.trim() : fallback;
const email = (v) => (typeof v === "string" && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim()) ? v.trim() : "");

// The founder card: a name, a photo inside the site, and an https LinkedIn link (empty hides the link).
function founderOf(f) {
  const o = f && typeof f === "object" ? f : {};
  return { name: str(o.name, ""), photo: sitePath(o.photo, ""), linkedin: httpsUrl(o.linkedin) };
}
export const copyright = (cfg) => `© ${YEAR} ${cfg.legal_name}`;

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
    logo: sitePath(r.logo, DEFAULTS.logo),
    legal_name: str(r.legal_name, DEFAULTS.legal_name),
    contact_email: email(r.contact_email),
    signup_endpoint: httpsUrl(r.signup_endpoint),
    checkout_urls: checkout,
    founder: founderOf(r.founder),
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
// The header shows the logo and the tagline (the name is only in the link's label); the footer shows the logo and the name.
export const NAV = [["try", "Try it"], ["learn", "Learn"], ["teach", "Teach"], ["pricing", "Pricing"], ["about", "About"]];
const mark = (cfg, root, size) => `<img class="brand-mark" src="${esc(root + cfg.logo)}" alt="" width="${size}" height="${size}">`;
export function headerHtml(cfg, root, current) {
  const links = NAV.map(([k, label]) => `<a href="${root}${k}/"${k === current ? ' aria-current="page"' : ""}>${label}</a>`).join("");
  return `<div class="wrap head-row">
  <a class="brand" href="${root}" aria-label="${esc(cfg.name)}, home">${mark(cfg, root, 36)}<span class="brand-tag">${esc(cfg.tagline)}</span></a>
  <nav class="main-nav" aria-label="Main">${links}</nav>
  <a class="nav-cta" href="${root}signup/"${current === "signup" ? ' aria-current="page"' : ""}>Sign up</a>
</div>`;
}
export function footerHtml(cfg, root) {
  const contact = cfg.contact_email ? `<a href="mailto:${esc(cfg.contact_email)}">${esc(cfg.contact_email)}</a>` : "";
  return `<div class="wrap foot-grid">
  <div class="foot-brand"><a class="brand" href="${root}">${mark(cfg, root, 32)}<span class="brand-name">${esc(cfg.wordmark)}</span></a>
    <p>${esc(cfg.tagline)}. Compare a mix of funds with the market, privately, in your browser.</p></div>
  <nav class="foot-col" aria-label="Product"><h2>Product</h2><a href="${root}try/">Try it</a><a href="${root}learn/">Learn</a><a href="${root}teach/">For instructors</a><a href="${root}pricing/">Pricing</a></nav>
  <nav class="foot-col" aria-label="Company"><h2>Company</h2><a href="${root}about/">About</a><a href="${root}privacy/">Privacy</a><a href="${root}terms/">Terms</a><a href="${root}signup/">Sign up</a>${contact}</nav>
</div>
<div class="wrap foot-legal">
  <p><b>Information, not investment advice.</b> Results are before taxes and trading costs, and past results don’t predict future ones.</p>
  <p>Prices: month-end adjusted closes, completed months only. Cash rate: 3-month Treasury bills from FRED.</p>
  <p class="copy">${esc(copyright(cfg))}</p>
</div>`;
}

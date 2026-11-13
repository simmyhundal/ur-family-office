// Renders the header and footer from data/site.json on every page, and sets the document title suffix.
import { loadSiteConfig, headerHtml, footerHtml } from "./config.mjs";

const root = new URL("../", import.meta.url).pathname;
const rel = location.pathname.startsWith(root) ? location.pathname.slice(root.length) : "";
export const currentKey = rel.split("/")[0] || "home";
export const cfg = await loadSiteConfig(new URL("../data/site.json", import.meta.url).href);
const prefix = new URL("../", import.meta.url).href;
const head = document.querySelector("header.site-head"), foot = document.querySelector("footer.site-foot");
if (head) head.innerHTML = headerHtml(cfg, prefix, currentKey);
if (foot) foot.innerHTML = footerHtml(cfg, prefix);
document.title = document.title.replace(/UFO/g, cfg.name);

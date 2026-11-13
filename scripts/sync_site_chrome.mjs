// Run: node scripts/sync_site_chrome.mjs   (after editing site/data/site.json or js/config.mjs)
// Re-renders the static header and footer of every page from site.json, so pages without JS (and the one-file copy) match.
import { readFileSync, writeFileSync } from "node:fs";
import { execSync } from "node:child_process";
const site = process.argv[2] || new URL("../site", import.meta.url).pathname;
const { mergeConfig, headerHtml, footerHtml } = await import(site + "/js/config.mjs");
const cfg = mergeConfig(JSON.parse(readFileSync(site + "/data/site.json", "utf8")));
for (const f of execSync(`find ${site} -name index.html`).toString().trim().split("\n")) {
  const rel = f.slice(site.length + 1); const depth = rel.split("/").length - 1;
  const root = "../".repeat(depth); const key = depth ? rel.split("/")[0] : "home";
  let s = readFileSync(f, "utf8");
  s = s.replace(/<header class="site-head">[\s\S]*?<\/header>/, `<header class="site-head">${headerHtml(cfg, root, key)}</header>`);
  s = s.replace(/<footer class="site-foot">[\s\S]*?<\/footer>/, `<footer class="site-foot">${footerHtml(cfg, root)}</footer>`);
  writeFileSync(f, s);
}

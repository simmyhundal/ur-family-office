"""Build ONE self-contained HTML file of the Try page (site/try/) plus a prices file (for hosts that serve a single page).

Run: python scripts/build_single_page.py PRICES_JSON OUT_HTML
The prices are embedded in the page, so the copy is a snapshot: rebuild it to refresh.
"""
import json
import re
import sys
from urllib.parse import quote
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site"


MODULES = ["calc.mjs", "util.mjs", "data.mjs", "result.mjs", "portfolios.mjs", "positions.mjs", "share.mjs"]  # then app.js; keep in step with its imports


def _strip(src: str) -> str:
    src = re.sub(r"^import .*?;\n", "", src, flags=re.M)
    return re.sub(r"^export ", "", src, flags=re.M)


def build(prices_json: str, presets_json: str | None = None) -> str:
    """The Try page (site/try/index.html) as one file: style, scripts and prices inlined; site navigation links removed."""
    html = (SITE / "try" / "index.html").read_text()
    css = (SITE / "style.css").read_text()
    code = "\n".join(_strip((SITE / "js" / m).read_text()) for m in [*MODULES, "app.js"])
    data = json.dumps(json.loads(prices_json), separators=(",", ":")).replace("</", "<\\/")
    html = html.replace('<link rel="stylesheet" href="../style.css">', f"<style>\n{css}</style>")
    tools = (SITE / "css" / "try-tools.css").read_text()
    html = html.replace('<link rel="stylesheet" href="../css/try-tools.css">', f"<style>\n{tools}</style>")
    logo = "data:image/svg+xml," + quote((SITE / "img" / "logo.svg").read_text().strip(), safe=" =:/'")
    icon = "data:image/svg+xml," + quote((SITE / "img" / "favicon.svg").read_text().strip(), safe=" =:/'")
    html = html.replace('href="../img/favicon.svg"', f'href="{icon}"').replace('src="../img/logo.svg"', f'src="{logo}"')
    html = html.replace('<script type="module" src="../js/chrome.mjs"></script>\n', "")  # header and footer are already in the page
    presets = presets_json if presets_json is not None else (SITE / "data" / "presets.json").read_text()
    presets = json.dumps(json.loads(presets), separators=(",", ":")).replace("</", "<\\/")
    script = f"<script>globalThis.UFO_DATA = {data}; globalThis.UFO_PRESETS = {presets};</script>\n<script type=\"module\">\n{code}</script>"
    out = html.replace('<script type="module" src="../js/app.js"></script>', script)
    out = re.sub(r"<nav .*?</nav>", "", out, flags=re.S)  # the other pages are not in the copy
    out = re.sub(r'href="\.\./[^"]*"', 'href="https://simmyhundal.github.io/ur-family-office/"', out)
    assert 'src="../js/app.js"' not in out and 'href="../style.css"' not in out, "page structure changed; update the builder"
    assert "../css/" not in out and "../img/" not in out and "chrome.mjs" not in out, "page structure changed; update the builder"
    return out


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(build(Path(sys.argv[1]).read_text()))

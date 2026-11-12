"""Build ONE self-contained HTML file from site/ plus a prices file (for hosts that serve a single page).

Run: python scripts/build_single_page.py PRICES_JSON OUT_HTML
The prices are embedded in the page, so the copy is a snapshot: rebuild it to refresh.
"""
import json
import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site"


def build(prices_json: str, presets_json: str | None = None) -> str:
    html = (SITE / "index.html").read_text()
    css = (SITE / "style.css").read_text()
    calc = re.sub(r"^export ", "", (SITE / "js" / "calc.mjs").read_text(), flags=re.M)
    app = re.sub(r"^import .*?;\n", "", (SITE / "js" / "app.js").read_text(), count=1, flags=re.M)
    data = json.dumps(json.loads(prices_json), separators=(",", ":")).replace("</", "<\\/")
    html = html.replace('<link rel="stylesheet" href="style.css">', f"<style>\n{css}</style>")
    presets = presets_json if presets_json is not None else (SITE / "data" / "presets.json").read_text()
    presets = json.dumps(json.loads(presets), separators=(",", ":")).replace("</", "<\\/")
    script = f"<script>globalThis.UFO_DATA = {data}; globalThis.UFO_PRESETS = {presets};</script>\n<script type=\"module\">\n{calc}\n{app}</script>"
    out = html.replace('<script type="module" src="js/app.js"></script>', script)
    assert 'src="js/app.js"' not in out and "href=\"style.css\"" not in out, "page structure changed; update the builder"
    return out


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(build(Path(sys.argv[1]).read_text()))

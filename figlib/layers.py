"""Split an HTML+SVG figure into per-click layers for a deck built with figlib.outline.

    python -m figlib.layers build fig.html L1 L2 L3    # -> fig_L1.svg, fig_L2.svg, fig_L3.svg
    python -m figlib.layers anim fig.html              # -> fig_<layer>.png ..., fig_anim.json

`build`: panels that appear one per click. The figure groups its content in <g id="L1">,
<g id="L2">, ... and gives its white background rect id="bg". For each layer this exports
<stem>_<Lk>.svg: the page with every OTHER layer removed (and, after the first, the background
too, so layers 2.. are transparent), via a temporary <stem>_<Lk>.html and export_svg. In
the outline: `figure: fig_L1.svg`, then one `build: fig_Lk.svg` per later layer.

`anim`: things that move. The figure puts each moving or appearing object in its own
<g data-layer="id"> and defines

    window.ANIM = {canvas: [w, h], layers: [ids, bottom to top],
                   steps: [click: [phase: [effect]]]}      effect = [kind, layer, ms, dx, dy]
    window.ANIM_STATE = k => ...                           draw the picture after k clicks

with kind "in", "out" or "move" (dx, dy in canvas units). This writes one full-canvas PNG per
layer (Chromium at 3x; every layer but the first transparent), the manifest <stem>_anim.json
(`animation:` in the outline), and preview frames <stem>_preview/<k>.png for looking at the
clicks, which no PDF render can show.

Both outputs are generated: re-run after every edit of the HTML, never edit them. Needs the
`html` extra (Playwright + Chromium). Generalised 2026-11-23 from the generals talk's
make_build_layers / make_anim_layers scripts (wuhrlab admin/generals/slides/py/).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from figlib import export_svg, fonts


def build(html: Path, layers: list[str], *, export: bool = True) -> list[Path]:
    """Write <stem>_<layer>.html for each layer and (by default) export each to SVG.
    Returns the SVGs, or the HTML variants with export=False."""
    src = Path(html).resolve()
    text = src.read_text(encoding="utf-8")
    out = []
    for k, lay in enumerate(layers):
        drop = [la for la in layers if la != lay] + ([] if k == 0 else ["bg"])
        # Removed after the page's own script, including one that waits for fonts: this
        # callback is registered last, so it runs last.
        js = (f"document.fonts.ready.then(() => {json.dumps(drop)}"
              ".forEach(id => document.getElementById(id)?.remove()));")
        note = (f"<!-- GENERATED from {src.name}: layer {lay}{'' if k == 0 else ' only, transparent'}."
                f" Do not edit; regenerate with python -m figlib.layers build. -->")
        variant = src.with_name(f"{src.stem}_{lay}.html")
        variant.write_text(f"{note}\n{text.rstrip()}\n<script>{js}</script>\n", encoding="utf-8")
        if export:
            svg = variant.with_suffix(".svg")
            export_svg.main([str(variant), str(svg)])      # exits with a message on failure
            variant.unlink()                               # intermediate; the HTML source is the record
            out.append(svg)
        else:
            out.append(variant)
    return out


def anim(html: Path, *, viewport: tuple[int, int] = (1640, 760), wait_ms: int = 700) -> Path:
    """Export an animated figure: per-layer PNGs, the manifest, and preview frames. Returns the manifest.
    Layer paths in the manifest are relative to the manifest's folder."""
    from playwright.sync_api import sync_playwright
    src = Path(html).resolve()
    prev_dir = src.with_name(f"{src.stem}_preview")
    prev_dir.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]}, device_scale_factor=3)
        fonts.use_in_browser(pg)
        pg.goto(src.as_uri())
        pg.wait_for_timeout(wait_ms)
        spec = pg.evaluate("window.ANIM")
        if not spec:
            raise ValueError(f"{src.name} defines no window.ANIM")
        svg = pg.query_selector("svg")
        layers = []
        for i, lid in enumerate(spec["layers"]):
            pg.evaluate("""([lid, keepBg]) => {
                for (const g of document.querySelectorAll('[data-layer]')) {
                    g.style.display = g.id === lid ? '' : 'none'; g.removeAttribute('transform'); }
                const bg = document.getElementById('bg'); if (bg) bg.style.display = keepBg ? '' : 'none';
                for (const el of [document.documentElement, document.body])
                    el.style.background = keepBg ? '#ffffff' : 'transparent';
            }""", [lid, i == 0])
            out = src.with_name(f"{src.stem}_{lid}.png")
            svg.screenshot(path=str(out), omit_background=i > 0)
            layers.append({"id": lid, "png": out.name})
        pg.evaluate("""() => { const bg = document.getElementById('bg'); if (bg) bg.style.display = '';
            for (const el of [document.documentElement, document.body]) el.style.background = '#ffffff'; }""")
        for k in range(len(spec["steps"]) + 1):
            pg.evaluate("k => window.ANIM_STATE(k)", k)
            svg.screenshot(path=str(prev_dir / f"{k}.png"))
        browser.close()
    man = src.with_name(f"{src.stem}_anim.json")
    man.write_text(json.dumps({"source": src.name, "canvas": spec["canvas"], "layers": layers,
                               "steps": spec["steps"]}, indent=1) + "\n")
    return man


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m figlib.layers", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="one SVG per click layer")
    b.add_argument("html", type=Path)
    b.add_argument("layers", nargs="+", help="layer ids, in click order (the first shows with the slide)")
    a = sub.add_parser("anim", help="layer PNGs + manifest for `animation:`")
    a.add_argument("html", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "build":
        for svg in build(args.html, args.layers):
            print("wrote", svg)
    else:
        man = anim(args.html)
        n = len(json.loads(man.read_text())["steps"])
        print(f"wrote {man} and its layers; previews 0..{n} in {args.html.stem}_preview/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

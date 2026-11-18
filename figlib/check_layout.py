#!/usr/bin/env python3
"""Layout linter for HTML+SVG figures. Run it before export_svg.

    python -m figlib.check_layout figure.html [--margin 60] [--min-pt 10]

Checks, in headless Chromium:
  OVERFLOW    text crosses the page margin or leaves the viewBox
  OVERLAP     two text elements intersect (loose tolerances; see OVERLAP_MIN_*)
  SMALL TYPE  text renders below --min-pt once the figure is fitted to a slide
  MISSING GLYPH  a character the deck font (Carlito/Calibri) can't draw
  FONT        a text style that doesn't render with Calibri/Carlito metrics, so the
              layout was measured in a face PowerPoint won't use (monospace stacks are skipped)

Text over shapes is not checked: most labels sit on a panel rect by design.
Exits 1 on any finding, so it can gate an export.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from figlib import fonts as _fonts

__version__ = "1.2.0"

# An intersection must be at least this many viewBox units in BOTH axes, and
# cover at least this fraction of the smaller box, before it counts. Loose on
# purpose, so tightly set paragraph lines pass.
OVERLAP_MIN_UNITS = 3.0
OVERLAP_MIN_FRAC = 0.10

# Text authored exactly at the margin measures a fraction of a unit outside it.
EPS = 0.5

#: How many SMALL TYPE rows to print before collapsing to a count.
SHOW_SMALL = 8

# getBBox() is in the element's own user space, not the root viewBox, so text in
# a transformed <g> comes back in the wrong coordinates. Each box goes through
# root.getScreenCTM().inverse() * el.getScreenCTM() (element -> root), and font
# size is scaled by sqrt(|det|) so scaled type is measured as rendered.
PROBE = """() => {
  const svg = document.querySelector('svg');
  const vb = svg.viewBox.baseVal;
  const rootInv = svg.getScreenCTM().inverse();
  const out = [];
  svg.querySelectorAll('text').forEach((t, i) => {
    if (t.querySelector('text')) return;             // outer of a nested pair
    const s = (t.textContent || '').trim();
    if (!s) return;
    const b = t.getBBox();
    if (!b.width || !b.height) return;
    const own = t.getScreenCTM();
    if (!own) return;                                // not rendered
    const m = rootInv.multiply(own);
    const xs = [], ys = [];
    for (const [cx, cy] of [[b.x, b.y], [b.x + b.width, b.y],
                            [b.x, b.y + b.height], [b.x + b.width, b.y + b.height]]) {
      const p = svg.createSVGPoint(); p.x = cx; p.y = cy;
      const q = p.matrixTransform(m); xs.push(q.x); ys.push(q.y);
    }
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const y0 = Math.min(...ys), y1 = Math.max(...ys);
    const scale = Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)) || 1;
    out.push({i, text: s.slice(0, 60),
              x: x0, y: y0, w: x1 - x0, h: y1 - y0,
              px: parseFloat(getComputedStyle(t).fontSize) * scale});
  });
  return {vbw: vb.width, vbh: vb.height, texts: out};
}"""


def probe(html: Path, wait_ms: int) -> dict:
    url = html.resolve().as_uri()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1700, "height": 1000})
        _fonts.use_in_browser(page)   # Carlito as 'Calibri', before the figure's script runs
        page.goto(url)
        page.wait_for_timeout(wait_ms)
        data = page.evaluate(PROBE)
        data["font"] = _fonts.font_mismatches(page)
        browser.close()
    return data


def overlap(a: dict, b: dict) -> tuple[float, float, float] | None:
    iw = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    ih = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    if iw <= 0 or ih <= 0:
        return None
    area = iw * ih
    frac = area / min(a["w"] * a["h"], b["w"] * b["h"])
    if iw < OVERLAP_MIN_UNITS or ih < OVERLAP_MIN_UNITS or frac < OVERLAP_MIN_FRAC:
        return None
    return iw, ih, frac


#: Carlito has Calibri's metrics and the same coverage gaps, so its cmap stands in
#: for what the audience's Calibri can draw.
FONT_CHECK = Path(__file__).resolve().parent / "fonts" / "Carlito-Regular.ttf"


def glyph_gaps(texts):
    """Characters used in the figure that the deck's font cannot draw.

    Returns (char, codepoint, sample-context) triples; [] if fontTools or the font
    is unavailable, so a missing optional dependency never blocks an export.
    """
    try:
        from fontTools.ttLib import TTFont
    except ImportError:                                    # pragma: no cover
        return []
    if not FONT_CHECK.exists():                            # pragma: no cover
        return []
    cmap = set(TTFont(str(FONT_CHECK)).getBestCmap())
    seen, out = {}, []
    for t in texts:
        for ch in t.get("text", ""):
            code = ord(ch)
            if code > 0x7F and code not in cmap and ch not in seen:
                seen[ch] = t["text"][:44]
    for ch, where in seen.items():
        out.append((ch, ord(ch), where))
    return sorted(out, key=lambda r: r[1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("html", type=Path)
    ap.add_argument("--margin", type=float, default=40.0,
                    help="page margin in viewBox units (default 40); set it to "
                         "whatever your deck uses")
    ap.add_argument("--slide", default="13.333x7.5",
                    help="target slide size in inches (default 13.333x7.5)")
    ap.add_argument("--min-pt", type=float, default=9.0,
                    help="minimum rendered point size (default 9; aim for 11 "
                         "on body text)")
    ap.add_argument("--wait", type=int, default=500,
                    help="ms to wait for the page's own layout script")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if not a.html.exists():
        print(f"no such file: {a.html}", file=sys.stderr)
        return 2

    sw, sh = (float(v) for v in a.slide.lower().split("x"))
    d = probe(a.html, a.wait)
    vbw, vbh, texts = d["vbw"], d["vbh"], d["texts"]
    scale = min(sw * 72 / vbw, sh * 72 / vbh)     # fit to slide, preserve aspect

    fails: list[dict] = []

    for t in texts:
        right, bottom = t["x"] + t["w"], t["y"] + t["h"]
        if t["x"] < a.margin - EPS or right > vbw - a.margin + EPS:
            fails.append({"kind": "OVERFLOW", "text": t["text"],
                          "detail": f"x {t['x']:.0f}..{right:.0f} outside "
                                    f"[{a.margin:.0f}, {vbw - a.margin:.0f}]"})
        elif bottom > vbh + EPS or t["y"] < -EPS:
            fails.append({"kind": "OVERFLOW", "text": t["text"],
                          "detail": f"y {t['y']:.0f}..{bottom:.0f} outside "
                                    f"[0, {vbh:.0f}]"})

    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            ov = overlap(texts[i], texts[j])
            if ov:
                iw, ih, frac = ov
                fails.append({"kind": "OVERLAP",
                              "text": f"{texts[i]['text'][:34]!r} x {texts[j]['text'][:34]!r}",
                              "detail": f"{iw:.0f}x{ih:.0f} units, "
                                        f"{100 * frac:.0f}% of the smaller box"})

    small = sorted((t for t in texts if t["px"] * scale < a.min_pt),
                   key=lambda t: t["px"])
    for t in small[:SHOW_SMALL]:
        fails.append({"kind": "SMALL TYPE", "text": t["text"],
                      "detail": f"{t['px']:.0f}px renders at "
                                f"{t['px'] * scale:.1f}pt (floor {a.min_pt:g})"})
    if len(small) > SHOW_SMALL:
        fails.append({"kind": "SMALL TYPE",
                      "text": f"... and {len(small) - SHOW_SMALL} more",
                      "detail": f"{len(small)} of {len(texts)} text elements are "
                                f"below {a.min_pt:g}pt"})

    # --- MISSING GLYPH -------------------------------------------------------
    # A fallback font can render a glyph Calibri lacks (e.g. U+2713 check marks),
    # so check the deck font's cmap rather than trusting the render.
    missing = glyph_gaps(texts)
    for ch, code, where in missing:
        fails.append({"kind": "MISSING GLYPH", "text": f"{ch}  (U+{code:04X})",
                      "detail": f"not in {FONT_CHECK.name}; appears in: {where}"})

    # --- FONT ------------------------------------------------------------------
    # Everything above was measured in whatever face Chromium used; if that isn't
    # Carlito/Calibri, the measurements don't describe the slide.
    for r in d["font"]:
        fails.append({"kind": "FONT", "text": f"{r['family']} ({r['weight']}, {r['style']})",
                      "detail": f"renders {100 * (r['ratio'] - 1):+.0f}% vs Calibri/Carlito, "
                                f"e.g. {r['sample']!r}; declare figlib.fonts.STACK"})

    if a.json:
        print(json.dumps({"file": str(a.html), "viewBox": [vbw, vbh],
                          "scale_pt_per_unit": scale, "n_text": len(texts),
                          "fails": fails}, indent=2))
        return 1 if fails else 0

    fit = "width" if sw * 72 / vbw <= sh * 72 / vbh else "HEIGHT"
    print(f"{a.html.name}: viewBox {vbw:.0f}x{vbh:.0f}, {len(texts)} text elements, "
          f"fits slide {fit} at {scale:.3f} pt/unit")
    if fit == "HEIGHT":
        print("  NOTE: taller than the slide, so it is sized to height. Raising "
              "font sizes here can make the viewBox taller and rendered type "
              "SMALLER; cut content or split the figure instead.")
    if not fails:
        print(f"  clean — no overflow, no text collisions, nothing below "
              f"{a.min_pt:g}pt, every glyph in the font, measured in Carlito")
        return 0
    for kind in ("OVERFLOW", "OVERLAP", "SMALL TYPE", "MISSING GLYPH", "FONT"):
        rows = [f for f in fails if f["kind"] == kind]
        if not rows:
            continue
        print(f"\n  {kind}  ({len(rows)})")
        for r in rows:
            print(f"    {r['text']}")
            print(f"      {r['detail']}")
    print(f"\n{len(fails)} issue(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())

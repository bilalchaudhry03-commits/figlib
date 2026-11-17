#!/usr/bin/env python3
"""CANONICAL COPY -- moved into the repo 2026-08-27 alongside export_svg, for the
same reason: a build tool for a repo artifact belongs under version control.

Run as:  python3 -m figlib.check_layout figure.html

Layout linter for the HTML+SVG schematics. Run it BEFORE export_svg.py.

WHY THIS EXISTS
---------------
Measured on 2026-08-05 while building three figures in one session: 13 render
iterations were spent on the loop "render -> look at the PNG -> spot a collision
-> patch". Every collision found that way was machine-detectable. Mid-session an
ad-hoc getBBox() overflow check was written inline, immediately caught two
overflows that had survived visual review of a scaled-down screenshot, and was
then thrown away -- which is exactly the failure mode karyoPPI/lib/palette.py's
docstring describes about its CVD validator being hand-ported twice and
discarded both times.

So this is the same fix applied to the same class of problem: write the check
once, ship it next to the tool it guards.

WHAT IT CHECKS
--------------
  OVERFLOW    a text element's bbox crosses the page margin, or falls outside
              the viewBox vertically. This is the one that survives visual
              review most often, because a figure previewed scaled-to-fit hides
              a few units of overhang at the right edge.

  OVERLAP     two text elements' bboxes intersect. Tolerances are deliberately
              loose (see OVERLAP_MIN_*) because adjacent lines of a manually
              laid-out paragraph legitimately sit close, and a linter that
              cries wolf gets ignored.

  SMALL TYPE  a text element renders below --min-pt once the figure is fitted
              to a slide. The skill's two formulas (960/viewBox-width for wide
              figures, 540/viewBox-height for tall ones) are the two branches of
              one calculation -- fit-preserving-aspect -- so this computes the
              fit directly and works for any aspect without a special case.

WHAT IT DELIBERATELY DOES NOT CHECK
-----------------------------------
Text-over-shape overlap. Almost every label in these figures sits on a panel
rect by design, so the check would be nearly all false positives. Text-vs-text
is the signal worth having.

Exits 1 if anything fails, so it can gate an export.

Usage:
    source /Genomics/wuehrlab/People/Bilal/envs/analysis/bin/activate
    python3 ~/.claude/skills/scientific-figure-design/scripts/check_layout.py figure.html
    python3 ... check_layout.py figure.html --margin 60 --min-pt 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys

__version__ = "1.1.0"
from pathlib import Path

from playwright.sync_api import sync_playwright

# Importing figlib.fonts registers the vendored Carlito with matplotlib and
# symlinks it where fontconfig will find it, so headless Chromium measures
# the face the deck actually declares instead of a fallback 20% wider.
from figlib import fonts as _fonts  # noqa: F401


# An intersection must be at least this many viewBox units in BOTH axes, and
# cover at least this fraction of the smaller box, before it counts. Tuned so
# the 2026-08-05 deck's manually laid-out paragraph blocks pass clean.
OVERLAP_MIN_UNITS = 3.0
OVERLAP_MIN_FRAC = 0.10

# Text authored AT the margin measures a fraction of a unit outside it. Without
# this every left-aligned title in the deck reports as an overflow.
EPS = 0.5

#: How many SMALL TYPE rows to print before collapsing to a count.
SHOW_SMALL = 8

# getBBox() reports the element's OWN user space, NOT the root viewBox space, so
# anything inside a transformed <g> comes back in the wrong coordinate system.
# Caught 2026-08-05 by running this across 22 deck figures: the ones built with
# group transforms reported labels at negative x and produced both false
# overflows and false overlaps. Every box is therefore pushed through
# root.getScreenCTM().inverse() * el.getScreenCTM(), which is the element-to-root
# user-space matrix, and font size is scaled by sqrt(|det|) so a scaled group's
# type is measured as rendered rather than as authored.
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
        page.goto(url)
        page.wait_for_timeout(wait_ms)
        data = page.evaluate(PROBE)
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



#: The face the deliverable is actually rendered in. Carlito is metric-compatible
#: with Calibri AND has the same coverage gaps, so checking against it is checking
#: against what the audience's Calibri will do.
FONT_CHECK = Path(__file__).resolve().parent / "fonts" / "Carlito-Regular.ttf"


def glyph_gaps(texts):
    """Characters used in the figure that the deck's font cannot draw.

    Returns (char, codepoint, sample-context) triples. Silent no-op if fontTools
    or the font is unavailable -- a missing linter dependency should not block an
    export.
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
                    help="page margin in viewBox units (default 40). This is a "
                         "house convention, not a property of the file — set it "
                         "to whatever the deck actually uses. Any value above "
                         "~20 catches the failure this exists for: a title that "
                         "runs off the right edge of a wide viewBox.")
    ap.add_argument("--slide", default="13.333x7.5",
                    help="target slide size in inches (default 13.333x7.5)")
    ap.add_argument("--min-pt", type=float, default=9.0,
                    help="minimum rendered point size (default 9; the skill "
                         "recommends aiming for 11 on body text)")
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
    # A font substitution hides a missing glyph as readily as it hides a metric
    # error. Slide 28 shipped four tofu boxes because U+2713/U+2717 are absent
    # from Calibri -- they live in Segoe UI Symbol on Windows -- and DejaVu was
    # standing in on the build machine, so they rendered here and would not have
    # rendered for the audience. Checking the declared font's cmap catches that
    # with no render at all.
    missing = glyph_gaps(texts)
    for ch, code, where in missing:
        fails.append({"kind": "MISSING GLYPH", "text": f"{ch}  (U+{code:04X})",
                      "detail": f"not in {FONT_CHECK.name}; appears in: {where}"})

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
              "font sizes here can make rendered type SMALLER (see SKILL.md); "
              "cut content or split the figure instead.")
    if not fails:
        print(f"  clean — no overflow, no text collisions, nothing below "
              f"{a.min_pt:g}pt, every glyph in the font")
        return 0
    for kind in ("OVERFLOW", "OVERLAP", "SMALL TYPE", "MISSING GLYPH"):
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

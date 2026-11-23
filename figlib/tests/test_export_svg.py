"""Tests for export_svg's style baking: each element pins a class-set property (fill:none,
stroke-width, dasharray, ...) that the standalone SVG must carry without the page's stylesheet.

Needs headless Chromium, so the export runs once per module.
"""

from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

pytest.importorskip("playwright")

from figlib import export_svg  # noqa: E402

SVGNS = "{http://www.w3.org/2000/svg}"

FIXTURE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  :root { --ink: #333333; }
  body { background: #ffffff; margin: 0; }
  svg { width: 400px; }
  .bg       { fill: #ffffff; }
  .blob     { fill: #4477aa; }
  .outline  { fill: none; stroke: var(--ink); stroke-width: 1.6; }
  .thick    { fill: #cccccc; stroke: #333333; stroke-width: 3; }
  .dash     { fill: none; stroke: #333333; stroke-width: 1.2;
              stroke-dasharray: 4 3; stroke-linecap: round; }
  .nostroke { stroke: none; }
  .override { fill: none; }
  .half     { opacity: 0.5; }
  .muted    { fill: #5b6672; font-size: 10px; }
</style></head><body>
<svg viewBox="0 0 200 100">
  <rect class="bg" x="0" y="0" width="200" height="100"/>
  <!-- outline-only circle: the exact Fig 5A failure -->
  <circle id="outline" class="outline" cx="20" cy="20" r="12"/>
  <rect id="thick" class="thick" x="40" y="10" width="20" height="20"/>
  <circle id="dash" class="dash" cx="80" cy="20" r="10"/>
  <!-- authored attributes only, no class: must NOT gain geometry attributes -->
  <circle id="plain" cx="110" cy="20" r="8" fill="#aabbcc"/>
  <!-- stroke:none / a default width must override what a parent attribute sets -->
  <g stroke="#000000" stroke-width="2">
    <line id="nostroke" class="nostroke" x1="0" y1="50" x2="40" y2="50"/>
    <line id="thin" style="stroke-width:1" x1="0" y1="60" x2="40" y2="60"/>
    <line id="inherits" x1="0" y1="70" x2="40" y2="70"/>
  </g>
  <!-- a class rule beats a presentation attribute in the browser -->
  <circle id="overridden" class="override" fill="#ff0000" stroke="#000000" cx="140" cy="20" r="8"/>
  <line id="attrwidth" class="thick" stroke-width="7" x1="60" y1="80" x2="100" y2="80"/>
  <text id="badge" class="muted" fill="#ffffff" x="120" y="90">1</text>
  <g id="halfg" class="half"><rect x="160" y="10" width="10" height="10" fill="#000000"/></g>
  <path id="inline" style="fill:none;stroke:#333333;stroke-dasharray:2,2" d="M60 60 L100 60"/>
  <!-- an inline custom-property colour: resolved AND dropped, or it outranks the baked attribute -->
  <circle id="inlinevar" style="fill:var(--ink); stroke-linecap:round" cx="150" cy="30" r="8"/>
  <!-- styles already written as attributes, with px units and commas -->
  <circle id="preset" class="dash" fill="none" stroke-width="1.2px"
          stroke-dasharray="4, 3" cx="180" cy="70" r="10"/>
</svg>
</body></html>
"""


def _nums(s):
    return [float(x) for x in s.replace(",", " ").replace("px", "").split()]


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    d = tmp_path_factory.mktemp("export_svg")
    html = d / "fixture.html"
    html.write_text(FIXTURE)
    out = d / "fixture.svg"
    r = subprocess.run([sys.executable, "-m", "figlib.export_svg", str(html), str(out)],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stderr or r.stdout
    root = ET.fromstring(out.read_text())
    by_id = {e.get("id"): e for e in root.iter() if e.get("id")}
    return out, root, by_id


def test_class_fill_none_is_baked(exported):
    _, _, el = exported
    assert el["outline"].get("fill") == "none"
    assert _nums(el["outline"].get("stroke-width")) == [1.6]
    assert el["outline"].get("stroke") == "rgb(51, 51, 51)"   # var() still resolved


def test_class_stroke_width_is_baked(exported):
    _, _, el = exported
    assert _nums(el["thick"].get("stroke-width")) == [3.0]


def test_class_dasharray_and_linecap_are_baked(exported):
    _, _, el = exported
    assert el["dash"].get("fill") == "none"
    assert _nums(el["dash"].get("stroke-dasharray")) == [4.0, 3.0]
    assert el["dash"].get("stroke-linecap") == "round"


def test_inline_style_values_are_baked(exported):
    _, _, el = exported
    assert el["inline"].get("fill") == "none"
    assert _nums(el["inline"].get("stroke-dasharray")) == [2.0, 2.0]


def test_values_override_an_inherited_attribute(exported):
    """stroke:none and stroke-width:1 are SVG defaults, but here a parent <g>
    attribute would otherwise supply black / 2 in the standalone file."""
    _, _, el = exported
    assert el["nostroke"].get("stroke") == "none"
    assert _nums(el["thin"].get("stroke-width")) == [1.0]
    # nothing to override: inherits 2 from the <g> attribute, no attribute needed
    assert el["inherits"].get("stroke-width") is None


def test_class_rule_beats_presentation_attribute(exported):
    _, _, el = exported
    assert el["overridden"].get("fill") == "none"


def test_class_stroke_width_beats_width_attribute(exported):
    _, _, el = exported
    assert _nums(el["attrwidth"].get("stroke-width")) == [3.0]


def test_authored_colour_recoloured_by_class_is_kept(exported):
    """An authored colour attribute is the intent when a class merely recolours it;
    only a class that turns the paint to `none` overrides it."""
    _, _, el = exported
    assert el["badge"].get("fill") == "#ffffff"


def test_group_opacity_is_baked(exported):
    _, _, el = exported
    assert float(el["halfg"].get("opacity")) == 0.5


def test_defaults_are_not_baked(exported):
    """Keep output small: a shape whose geometry is all SVG default gets nothing."""
    _, _, el = exported
    plain = el["plain"]
    for a in ("stroke-width", "stroke-dasharray", "stroke-linecap", "stroke-linejoin",
              "stroke-dashoffset", "fill-opacity", "stroke-opacity", "opacity"):
        assert plain.get(a) is None, a
    assert plain.get("stroke") is None


def test_styles_already_written_as_attributes_still_export(exported):
    _, _, el = exported
    w = el["preset"]
    assert w.get("fill") == "none"
    assert _nums(w.get("stroke-width")) == [1.2]
    assert _nums(w.get("stroke-dasharray")) == [4.0, 3.0]


def test_provenance_stamp_names_this_version(exported):
    out, _, _ = exported
    assert f"figlib.export_svg {export_svg.__version__};" in out.read_text()


def test_outline_circle_renders_hollow(exported, tmp_path):
    """Render the SVG without its page: the outline-only circle must be hollow, not black."""
    try:
        import cairosvg                    # OSError, not ImportError, when native cairo is missing
    except (ImportError, OSError):
        pytest.skip("cairosvg / native cairo not available")
    import io
    from PIL import Image
    out, _, _ = exported
    png = cairosvg.svg2png(url=str(out), output_width=400)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    # viewBox 200 wide -> 2 px per unit; outline circle centre is (20, 20)
    assert img.getpixel((40, 40)) == (255, 255, 255)


def test_provenance_stamp_names_the_exporter_and_the_figlib_build(exported):
    import figlib
    out, _, _ = exported
    stamp = re.search(r'<metadata id="figlib-provenance">(.*?)</metadata>', out.read_text()).group(1)
    assert f"figlib.export_svg {export_svg.__version__}" in stamp
    assert f"figlib {figlib.build_id()}" in stamp and "source=fixture.html" in stamp


def test_inline_var_declarations_are_resolved_and_dropped(exported):
    out, _, el = exported
    c = el["inlinevar"]
    assert c.get("fill") == "rgb(51, 51, 51)"
    assert "var(" not in (c.get("style") or "") and "stroke-linecap:round" in c.get("style")
    assert "var(" not in out.read_text()

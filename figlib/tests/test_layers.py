"""figlib.layers: per-click SVG layers and animation manifests from an HTML+SVG figure."""

import json

import pytest

pytest.importorskip("playwright")

from figlib import layers, outline, render  # noqa: E402

BUILD_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
text { font-family: Calibri, Arial, sans-serif; font-size: 40px; }</style></head><body>
<svg viewBox="0 0 800 400" xmlns="http://www.w3.org/2000/svg">
<rect id="bg" width="800" height="400" fill="#ffffff"/>
<g id="L1"><text x="40" y="100">one</text></g>
<g id="L2"><text x="40" y="200">two</text></g>
</svg></body></html>"""

ANIM_HTML = """<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0">
<svg viewBox="0 0 400 200" width="400" height="200" xmlns="http://www.w3.org/2000/svg">
<rect id="bg" width="400" height="200" fill="#ffffff"/>
<g id="base" data-layer="base"><rect x="10" y="10" width="60" height="60" fill="#2a78d6"/></g>
<g id="dot" data-layer="dot"><circle cx="100" cy="100" r="20" fill="#eb6834"/></g>
</svg><script>
window.ANIM = {canvas: [400, 200], layers: ["base", "dot"],
               steps: [[[["in", "dot", 300]]], [[["move", "dot", 500, 200, 0]]]]};
window.ANIM_STATE = k => {
  document.getElementById("dot").style.display = k >= 1 ? "" : "none";
  document.getElementById("dot").setAttribute("transform", k >= 2 ? "translate(200,0)" : "");
};
</script></body></html>"""


def test_variants_drop_the_other_layers(tmp_path):
    html = tmp_path / "f.html"
    html.write_text(BUILD_HTML, encoding="utf-8")
    v1, v2 = layers.build(html, ["L1", "L2"], export=False)
    assert '["L2"]' in v1.read_text() and '["L1", "bg"]' in v2.read_text()


def _launches():
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


needs_browser = pytest.mark.skipif(not _launches(), reason="Chromium not installed")


@needs_browser
def test_build_exports_transparent_later_layers(tmp_path):
    html = tmp_path / "f.html"
    html.write_text(BUILD_HTML, encoding="utf-8")
    s1, s2 = layers.build(html, ["L1", "L2"])
    a, b = s1.read_text(), s2.read_text()
    assert ">one<" in a and ">two<" not in a and 'id="bg"' in a
    assert ">two<" in b and ">one<" not in b and 'id="bg"' not in b
    assert not list(tmp_path.glob("f_L*.html"))              # intermediates removed


@needs_browser
def test_anim_manifest_builds_an_animated_slide(tmp_path):
    html = tmp_path / "figs" / "a.html"
    html.parent.mkdir()
    html.write_text(ANIM_HTML, encoding="utf-8")
    man = layers.anim(html)
    spec = json.loads(man.read_text())
    assert [la["png"] for la in spec["layers"]] == ["a_base.png", "a_dot.png"]
    assert len(list((tmp_path / "figs" / "a_preview").glob("*.png"))) == 3
    md = tmp_path / "talk.md"
    md.write_text("### S01 · Moves\nanimation: figs/a_anim.json\n", encoding="utf-8")
    r = outline.build(md)
    assert r.missing == []
    assert render.slide_flags(r.out)[0] == [1]

"""Tests for fonts and inputs."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from figlib import fonts  # noqa: E402
from figlib.inputs import MissingInput, require  # noqa: E402


# --------------------------------------------------------------------- fonts

def test_carlito_is_vendored_with_its_licence():
    """The OFL requires the licence travel with the font."""
    ttfs = fonts.ttf_files()
    assert len(ttfs) == 4, [p.name for p in ttfs]
    assert (fonts.FONT_DIR / "OFL.txt").exists()


def test_declared_stack_names_calibri_first():
    """Calibri leads so the real face wins where installed; Carlito is the stand-in."""
    assert fonts.STACK.startswith("Calibri")
    assert fonts.STACK_LIST[0] == "Calibri"
    assert "Carlito" in fonts.STACK_LIST


def test_register_is_idempotent_and_finds_carlito():
    first = fonts.register()
    second = fonts.register()
    assert first == second
    assert any("Carlito" in n for n in first), "Carlito not registered with matplotlib"


def test_ensure_visible_points_at_the_repo_copy_not_a_duplicate():
    """One copy of the fonts, in the package: a symlink, not a copy."""
    link = Path(fonts.ensure_visible())
    assert link.exists()
    assert link.is_symlink(), f"{link} should be a symlink, not a real directory"
    assert link.resolve() == fonts.FONT_DIR.resolve()


def test_ensure_visible_links_inside_an_existing_fonts_dir(tmp_path, monkeypatch):
    """A labmate's real ~/.fonts must not be replaced: link inside it instead."""
    home = tmp_path / ".fonts"
    home.mkdir()
    monkeypatch.setattr(fonts, "LINK", home)
    link = Path(fonts.ensure_visible())
    assert link == home / "figlib-carlito" and link.is_symlink()
    assert link.resolve() == fonts.FONT_DIR.resolve()
    assert fonts.ensure_visible() == str(link)          # idempotent


def test_ensure_visible_refuses_a_dangling_link(tmp_path, monkeypatch):
    dangling = tmp_path / ".fonts"
    dangling.symlink_to(tmp_path / "gone")
    monkeypatch.setattr(fonts, "LINK", dangling)
    with pytest.raises(FileNotFoundError, match="dangling"):
        fonts.ensure_visible()

# -------------------------------------------------------------------- inputs

def test_require_returns_paths_when_present(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("x\n")
    assert require(f, exit_code=None) == [f]


def test_require_reports_every_missing_input_not_just_the_first(tmp_path):
    """The whole point over a bare open(): one line naming all of them."""
    present = tmp_path / "here.csv"
    present.write_text("x\n")
    with pytest.raises(MissingInput) as exc:
        require(present, tmp_path / "gone_a.csv", tmp_path / "gone_b.csv",
                why="demo", exit_code=None)
    msg = str(exc.value)
    assert "gone_a.csv" in msg and "gone_b.csv" in msg
    assert "missing 2 of 3" in msg
    assert "demo" in msg


def test_missing_input_is_catchable_as_filenotfounderror(tmp_path):
    """Existing `except FileNotFoundError` handlers must keep working."""
    with pytest.raises(FileNotFoundError):
        require(tmp_path / "nope.csv", exit_code=None)


# ---------------------------------------------------------------- export_svg

def _export(tmp_path, body, *flags):
    src = tmp_path / "f.html"
    src.write_text(
        '<div class="stage"><svg id="fig" viewBox="0 0 1600 900" '
        'xmlns="http://www.w3.org/2000/svg">' + body + "</svg></div>")
    dst = tmp_path / "f.svg"
    r = subprocess.run([sys.executable, "-m", "figlib.export_svg", *flags,
                        str(src), str(dst)], capture_output=True, text=True, cwd=REPO)
    return r, dst


def test_export_stamps_its_version(tmp_path):
    """Provenance: an SVG says which exporter version made it."""
    r, dst = _export(tmp_path, '<text x="10" y="40" font-size="40">hi</text>')
    assert r.returncode == 0, r.stderr
    stamp = re.search(r'<metadata id="figlib-provenance">([^<]*)</metadata>', dst.read_text())
    assert stamp, dst.read_text()[:400]
    assert "figlib.export_svg" in stamp.group(1)


def test_markers_are_baked_into_geometry(tmp_path):
    """Markers become rotated geometry: SVG 1.1 consumers ignore auto-start-reverse."""
    body = ('<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            '<path d="M0,0 L10,5 L0,10 z" fill="#000"/></marker></defs>'
            '<line x1="100" y1="100" x2="500" y2="100" stroke="#000" '
            'stroke-width="4" marker-end="url(#a)"/>')
    r, dst = _export(tmp_path, body)
    assert r.returncode == 0, r.stderr
    out = dst.read_text()
    assert "marker-end=" not in out, "marker reference survived the bake"
    assert "<marker" not in out, "dead marker def left behind"
    assert "rotate(" in out, "no rotated arrowhead was emitted"


# -------------------------------------------------------------- check_layout

def test_glyph_gap_check_finds_characters_the_deck_font_lacks():
    """U+2713/U+2717 are in neither Calibri nor Carlito, though fallback fonts render them."""
    from figlib.check_layout import glyph_gaps
    gaps = glyph_gaps([{"text": "correct ✓"}, {"text": "wrong ✗"}, {"text": "fine →"}])
    codes = {c for _, c, _ in gaps}
    assert 0x2713 in codes and 0x2717 in codes
    assert 0x2192 not in codes, "→ IS in Carlito and must not be flagged"


def test_glyph_gap_check_passes_plain_text():
    from figlib.check_layout import glyph_gaps
    assert glyph_gaps([{"text": "Cytoplasm"}, {"text": "carried in"}]) == []


# ------------------------------------------------- fonts inside headless Chromium

FIG = """<!doctype html><svg viewBox="0 0 1600 900" xmlns="http://www.w3.org/2000/svg">
<text x="200" y="300" style="font-family: {family}; font-size: 40px">Cytoplasm to nucleus</text>
</svg><script>window.early = document.querySelector('text').getComputedTextLength();</script>"""


def _check_layout(tmp_path, family):
    pytest.importorskip("playwright")
    html = tmp_path / "fig.html"
    html.write_text(FIG.format(family=family))
    home = tmp_path / "home"            # no ~/.fonts: the tool must bring its own font
    home.mkdir()
    env = {**__import__("os").environ, "HOME": str(home)}
    return subprocess.run([sys.executable, "-m", "figlib.check_layout", str(html)],
                          capture_output=True, text=True, cwd=REPO, env=env)


def test_check_layout_measures_in_carlito_without_a_fonts_dir(tmp_path):
    r = _check_layout(tmp_path, fonts.STACK)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "measured in Carlito" in r.stdout


def test_check_layout_flags_a_figure_laid_out_in_another_face(tmp_path):
    r = _check_layout(tmp_path, "'DejaVu Sans'")
    assert r.returncode == 1 and "FONT" in r.stdout, r.stdout + r.stderr


def test_faces_exist_before_the_figure_script_measures_text(tmp_path):
    """A figure's own layout script runs during parsing; it must already see Carlito."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    html = tmp_path / "fig.html"
    html.write_text(FIG.format(family=fonts.STACK))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        fonts.use_in_browser(page)
        page.goto(html.as_uri())
        early = page.evaluate("window.early")
        carlito = page.evaluate("""() => { const t = document.querySelector('text');
            t.style.fontFamily = 'Carlito'; return t.getComputedTextLength(); }""")
        assert fonts.font_mismatches(page) == []
        browser.close()
    assert early == pytest.approx(carlito, rel=1e-3)

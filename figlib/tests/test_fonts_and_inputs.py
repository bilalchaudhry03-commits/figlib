"""Tests for the figure-build modules added 2026-08-27.

Each test pins a behaviour that was got WRONG first, on the principle the rest
of this repo's tests follow: a test that only restates the happy path would not
have caught any of these.
"""

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
    """Calibri leads because the PRESENTING machine has it; Carlito is the
    stand-in for machines that do not. Reversing them would ship a deck that
    renders in the substitute even where the real face is installed."""
    assert fonts.STACK.startswith("Calibri")
    assert fonts.STACK_LIST[0] == "Calibri"
    assert "Carlito" in fonts.STACK_LIST


def test_register_is_idempotent_and_finds_carlito():
    first = fonts.register()
    second = fonts.register()
    assert first == second
    assert any("Carlito" in n for n in first), "Carlito not registered with matplotlib"


def test_ensure_visible_points_at_the_repo_copy_not_a_duplicate():
    """One copy of the fonts, in the repo. The first attempt COPIED them to a
    repo-root .local/share/fonts, which duplicated 2.7 MB and left two
    directories to keep in step."""
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
    """Provenance. Without it, "did the exporter change or did the figure?"
    is unanswerable, which is what moving these tools into the repo was for."""
    r, dst = _export(tmp_path, '<text x="10" y="40" font-size="40">hi</text>')
    assert r.returncode == 0, r.stderr
    stamp = re.search(r'<metadata id="figlib-provenance">([^<]*)</metadata>', dst.read_text())
    assert stamp, dst.read_text()[:400]
    assert "figlib.export_svg" in stamp.group(1)


def test_markers_are_baked_into_geometry(tmp_path):
    """orient="auto-start-reverse" is SVG 2. Illustrator and PowerPoint are
    SVG 1.1 and fall back to NO rotation, so an arrowhead arrives as a bare
    unrotated triangle -- the defect this replaced."""
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
    """U+2713/U+2717 are absent from Calibri AND Carlito -- they live in Segoe UI
    Symbol on Windows. Slide 28 shipped four of them as tofu because the build
    machine was falling back to DejaVu, which has them. This check is what turns
    that from a render-and-squint into a lint."""
    from figlib.check_layout import glyph_gaps
    gaps = glyph_gaps([{"text": "correct ✓"}, {"text": "wrong ✗"}, {"text": "fine →"}])
    codes = {c for _, c, _ in gaps}
    assert 0x2713 in codes and 0x2717 in codes
    assert 0x2192 not in codes, "→ IS in Carlito and must not be flagged"


def test_glyph_gap_check_passes_plain_text():
    from figlib.check_layout import glyph_gaps
    assert glyph_gaps([{"text": "Cytoplasm"}, {"text": "carried in"}]) == []

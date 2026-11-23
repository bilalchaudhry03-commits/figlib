"""figlib.render: finding LibreOffice, slide flags, the font check, and (where installed) a real render."""

import os

import pytest

from figlib import outline, render

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
       '<rect width="200" height="100" fill="#2a78d6"/></svg>')
OUTLINE = """### S01 · A static slide
- one bullet

### S02 · A slide that builds
figure: f.svg
build: f.svg
"""


def _deck(tmp_path):
    (tmp_path / "f.svg").write_text(SVG, encoding="utf-8")
    (tmp_path / "talk.md").write_text(OUTLINE, encoding="utf-8")
    return outline.build(tmp_path / "talk.md").out


def test_find_soffice_prefers_env_and_explains_when_missing(monkeypatch):
    monkeypatch.setenv("FIGLIB_SOFFICE", "/x/soffice")
    assert render.find_soffice() == ["/x/soffice"]
    assert render.find_soffice("/y/soffice") == ["/y/soffice"]
    monkeypatch.delenv("FIGLIB_SOFFICE")
    monkeypatch.setenv("FIGLIB_LIBREOFFICE_SIF", "/x/lo.sif")
    assert render.find_soffice() == ["apptainer", "exec", "/x/lo.sif", "soffice"]
    monkeypatch.delenv("FIGLIB_LIBREOFFICE_SIF")
    monkeypatch.setattr(render.shutil, "which", lambda name: None)
    monkeypatch.setattr(render, "MAC_SOFFICE", "/nonexistent")
    monkeypatch.setattr(render, "WIN_SOFFICE", [])
    with pytest.raises(FileNotFoundError, match="LibreOffice"):
        render.find_soffice()


def test_slide_flags_mark_builds_not_static(tmp_path):
    stacked, movies = render.slide_flags(_deck(tmp_path))
    assert stacked == [2] and movies == []


def test_declared_fonts_and_substitution():
    used = ["Carlito", "Carlito-Bold", "DejaVuSans"]
    assert render._substituted(used, {"Calibri"}) == ["DejaVuSans"]
    assert render._substituted(["ArialMT", "Arial-BoldMT"], {"Arial"}) == []


def test_declared_fonts_are_the_slides_not_the_themes_script_lists(tmp_path):
    # The default theme lists Arial, Times New Roman, ... for other scripts; counting them would
    # let a Calibri -> Arial fallback pass. Found 2026-11-23, after 0.2.6.
    assert render.declared_fonts(_deck(tmp_path)) == {"Calibri"}


def test_pdf_fonts_are_the_fonts_that_draw_characters(tmp_path):
    pytest.importorskip("pypdfium2")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from figlib import fonts
    fonts.register()
    fig = plt.figure(figsize=(3, 1))
    fig.text(0.1, 0.5, "Carlito text", family="Carlito")
    with matplotlib.rc_context({"pdf.fonttype": 42}):
        fig.savefig(tmp_path / "x.pdf")
    plt.close(fig)
    used = render.pdf_fonts(tmp_path / "x.pdf")
    assert used and all(f.startswith("Carlito") for f in used), used


def test_contact_sheet(tmp_path):
    from PIL import Image
    pngs = []
    for i in range(5):
        p = tmp_path / f"s{i}.png"
        Image.new("RGB", (1600, 900), "white").save(p)
        pngs.append(p)
    out = render._contact(pngs, [str(i) for i in range(5)], tmp_path / "contact.png")
    w, h = Image.open(out).size
    assert w > 4 * render.THUMB_W and h > 2 * 270          # 4 columns, 2 rows


def _have_soffice():
    try:
        render.find_soffice()
    except FileNotFoundError:
        return False
    return not os.environ.get("FIGLIB_LIBREOFFICE_SIF")     # an image needs a compute node; skip


@pytest.mark.skipif(not _have_soffice(), reason="LibreOffice not installed")
def test_real_render(tmp_path):
    pytest.importorskip("pypdfium2")
    r = render.render(_deck(tmp_path))
    assert len(r.pngs) == 2 and r.contact.exists() and r.pdf.exists()
    assert r.stacked == [2]
    assert r.fonts and not r.substituted, r.fonts
    assert not list(r.contact.parent.glob(".work_*"))       # temp profile cleaned up

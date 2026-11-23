"""figlib.outline: front matter, the slide format, and an end-to-end build."""

import json

import pytest
from pptx import Presentation

from conftest import SVG
from figlib import outline

OUTLINE = """---
author: A. Presenter
root: assets
---
# My talk

Notes to self above the first slide are ignored.
### Not a slide: no id

### S01 · A title slide
section: title

### S02 · Import is faster than diffusion
figure: fig.svg
build: fig_L2.svg
notes:
Say the number.
- this dash line is a note, not a bullet

### S03 · Three things
- one
- two

### B01 · Backup with a missing figure
figure: nope.svg
notes:
[DRAFT] check this
"""


def _write(tmp_path, text=OUTLINE):
    (tmp_path / "assets").mkdir()
    for name in ("fig.svg", "fig_L2.svg"):
        (tmp_path / "assets" / name).write_text(SVG, encoding="utf-8")
    md = tmp_path / "talk.md"
    md.write_text(text, encoding="utf-8")
    return md


def test_front_matter_splits_and_rejects_unknown_keys():
    meta, body = outline.front_matter("---\nauthor: X\n---\n### S01 · T\n")
    assert meta == {"author": "X"} and body == "### S01 · T"
    assert outline.front_matter("### S01 · T") == ({}, "### S01 · T")
    with pytest.raises(ValueError, match="autor"):
        outline.front_matter("---\nautor: X\n---\n")
    with pytest.raises(ValueError, match="never closed"):
        outline.front_matter("---\nauthor: X\n")


def test_parse_needs_an_id_and_keeps_notes_verbatim():
    slides = outline.parse(outline.front_matter(OUTLINE)[1])
    assert [s["id"] for s in slides] == ["S01", "S02", "S03", "B01"]
    s02 = slides[1]
    assert s02["builds"] == [("fig", "fig_L2.svg")] and s02["bullets"] == []
    assert "- this dash line is a note, not a bullet" in s02["notes"]
    assert slides[2]["bullets"] == ["one", "two"]


def test_equation_after_figure_is_a_click_and_derivation_splits():
    s = outline.parse("### S01 · T\nfigure: f.svg\nequation: a = b @x=0.25\n"
                      "derivation: x >> = y\n")[0]
    assert s["equation"] == "a = b" and s["equation_x"] == 0.25
    assert s["builds"] == [("eq", "a = b"), ("deq", (0, 0)), ("deq", (0, 1))]
    with pytest.raises(ValueError, match="one `equation:`"):
        outline.parse("### S01 · T\nequation: a\nequation: b\n")


def test_build_end_to_end(tmp_path):
    r = outline.build(_write(tmp_path))
    assert r.out == tmp_path / "talk.pptx" and r.out.exists()
    assert (r.main, r.backup) == (3, 1)
    assert r.missing == [("B01", "nope.svg")] and r.drafts == ["B01"]
    prs = Presentation(r.out)
    assert len(prs.slides) == 4
    texts = [sh.text_frame.text for sh in prs.slides[0].shapes if sh.has_text_frame]
    assert "A. Presenter" in texts
    s02 = prs.slides[1]
    assert sum(sh.shape_type == 13 for sh in s02.shapes) == 2          # figure + one build layer
    assert s02.notes_slide.notes_text_frame.text.startswith("S02 — Import is faster than diffusion\n\nSay")


def test_cli_exits_1_on_missing_and_honours_out(tmp_path):
    md = _write(tmp_path)
    assert outline.main([str(md), "-o", str(tmp_path / "x.pptx")]) == 1
    assert (tmp_path / "x.pptx").exists()
    md.write_text(OUTLINE.split("### B01")[0], encoding="utf-8")
    assert outline.main([str(md)]) == 0


def test_starter_builds_clean_and_refuses_a_full_folder(tmp_path):
    md = outline.starter(tmp_path / "talk")
    r = outline.build(md)
    assert r.missing == [] and (r.main, r.backup) == (4, 1)
    with pytest.raises(FileExistsError):
        outline.starter(tmp_path / "talk")


def test_no_logo_means_no_slot_and_a_missing_logo_is_reported(tmp_path):
    md = _write(tmp_path, OUTLINE.split("### B01")[0])
    prs = Presentation(outline.build(md).out)
    assert not [sh for s in prs.slides for sh in s.shapes if sh.name.startswith("logo")]
    md.write_text(OUTLINE.replace("root: assets", "root: assets\nlogo: shield.png").split("### B01")[0], encoding="utf-8")
    assert outline.build(md).missing == [("logo", "shield.png")]


def test_handout_flattens_animations_to_their_final_frame(tmp_path):
    from PIL import Image
    for name in ("a_base.png", "a_dot.png", "a_final.png"):
        Image.new("RGBA", (400, 200), (42, 120, 214, 255)).save(tmp_path / name)
    man = {"canvas": [400, 200], "layers": [{"id": "base", "png": "a_base.png"}, {"id": "dot", "png": "a_dot.png"}],
           "steps": [[[["in", "dot", 300]]]], "final": "a_final.png"}
    (tmp_path / "a_anim.json").write_text(json.dumps(man), encoding="utf-8")
    md = tmp_path / "talk.md"
    md.write_text("### S01 · Moves\nanimation: a_anim.json\n", encoding="utf-8")
    live = Presentation(outline.build(md).out).slides[0]
    r = outline.build(md, handout=True)
    assert r.out.name == "talk_handout.pptx" and r.stacked == []
    flat = Presentation(r.out).slides[0]
    pics = lambda s: [sh for sh in s.shapes if sh.shape_type == 13]
    assert len(pics(live)) == 2 and len(pics(flat)) == 1
    assert "<p:anim" not in flat._element.xml and "<p:set" not in flat._element.xml
    del man["final"]                                             # an older manifest: no final frame
    (tmp_path / "a_anim.json").write_text(json.dumps(man), encoding="utf-8")
    assert outline.build(md, handout=True).stacked == ["S01"]


def test_build_reports_near_wrap_titles(tmp_path):
    from figlib import deck
    title = "Import is faster than diffusion for every cargo we measured"
    width_in = deck._measure(True)(title + " x", 30) / 0.996 / 72
    md = tmp_path / "talk.md"
    md.write_text(f"### S01 · {title} x\ntitle_width: {width_in:.4f}\n- one\n\n### S02 · Fine\n- two\n",
                  encoding="utf-8")
    r = outline.build(md)
    assert [sid for sid, _, _ in r.near_wrap] == ["S01"]

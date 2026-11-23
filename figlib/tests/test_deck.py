"""figlib.deck: geometry, SVG embedding, movies, and the no-secondary-text linter."""

import zipfile

import pytest
from PIL import Image
from pptx.util import Inches, Pt

from figlib import deck

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
       '<rect width="200" height="100" fill="#2a78d6"/></svg>')


def _deck_with_content(theme):
    prs = deck.new_presentation()
    deck.title_slide(prs, theme, "A title", "A. Presenter")
    s, box = deck.content_slide(prs, theme, "Content", "Aim 1 · 2")
    deck.bullets(s, box, ["one", "two"], theme)
    return prs, s, box


def test_slide_is_exact_16x9():
    prs = deck.new_presentation()
    assert (prs.slide_width, prs.slide_height) == (12192000, 6858000)
    assert "type" not in prs._element.find(deck.qn("p:sldSz")).attrib


def test_svg_rides_on_png_blip(tmp_path):
    svg = tmp_path / "f.svg"
    svg.write_text(SVG)
    prs, s, box = _deck_with_content(deck.Theme())
    pic = deck.add_figure(s, svg, box, tmp_path / "cache")
    assert pic.width / pic.height == pytest.approx(2.0, rel=0.01)
    out = tmp_path / "d.pptx"
    prs.save(out)
    names = zipfile.ZipFile(out).namelist()
    assert any(n.endswith(".svg") for n in names)
    assert any(n.endswith(".png") for n in names)


def test_movie_embeds_with_poster(tmp_path):
    poster = tmp_path / "p.png"
    Image.new("RGB", (160, 90), "white").save(poster)
    mp4 = tmp_path / "m.mp4"
    mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42")  # content is not parsed by python-pptx
    prs, s, box = _deck_with_content(deck.Theme())
    deck.add_movie(s, mp4, poster, box)
    out = tmp_path / "d.pptx"
    prs.save(out)
    assert any(n.endswith(".mp4") for n in zipfile.ZipFile(out).namelist())


def test_every_theme_lints_clean():
    for rule in ("bottom", "band", "title"):
        for logo_on in ("all", "title"):
            prs, *_ = _deck_with_content(deck.Theme(rule=rule, logo_on=logo_on))
            assert deck.lint_deck(prs) == [], (rule, logo_on)


def test_lint_catches_grey_subtitle_and_small_caption():
    theme = deck.Theme()
    prs, s, box = _deck_with_content(theme)
    deck._text(s, (Inches(1), Inches(6), Inches(5), Inches(0.4)), "n = 96 frames",
               pt=12, color="000000")
    deck._text(s, (Inches(1), Inches(2), Inches(5), Inches(0.4)), "a subtitle",
               pt=20, color=deck.MUTED)
    errs = deck.lint_deck(prs)
    assert any("12pt" in e for e in errs)
    assert any("grey" in e for e in errs)


def test_footer_is_exempt_by_name_not_position():
    prs, s, _ = _deck_with_content(deck.Theme())
    tb = deck._text(s, (Inches(1), Inches(7), Inches(5), Inches(0.3)), "caption", pt=11,
                    color=deck.MUTED)
    assert deck.lint_deck(prs), "a low-sitting caption must not pass as a footer"
    tb.name = deck.FOOTER_NAME
    assert deck.lint_deck(prs) == []


def test_bullets_have_no_levels():
    prs, s, box = _deck_with_content(deck.Theme())
    tb = deck.bullets(s, box, ["a", "b"], deck.Theme())
    assert all(p.level == 0 for p in tb.text_frame.paragraphs)
    assert all(r.font.size >= Pt(deck.MIN_BODY_PT) for p in tb.text_frame.paragraphs
               for r in p.runs)


def test_anim_writes_playable_outputs(tmp_path):
    import numpy as np

    from figlib import anim
    frames = (np.full((91, 161, 3), i * 20, np.uint8) for i in range(10))  # odd dims
    out = anim.write(frames, tmp_path / "clip", fps=10, gif_width=80, contact_n=4)
    assert out.n_frames == 10
    for p in (out.mp4, out.gif, out.poster, out.contact):
        assert p.exists() and p.stat().st_size > 0
    # thumbnail() never upscales, so 4 columns of the 161x91 frame, one row
    assert Image.open(out.contact).size == (4 * 161, 91)


def test_anim_long_dark_clip_skips_gif_and_is_not_clipped(tmp_path):
    import numpy as np

    from figlib import anim
    dark = (14, 17, 22)
    frames = (np.full((40, 64, 3), dark, np.uint8) for _ in range(50))   # 25 s at 2 fps
    out = anim.write(frames, tmp_path / "dark", fps=2, contact_n=3, bg=dark)
    assert out.gif is None                       # > GIF_MAX_S, not asked for
    assert out.clipped == ()                     # a uniform dark frame matches bg=dark
    assert Image.open(out.contact).size == (4 * 64, 40)   # 4 columns, one row of 3 thumbs


def test_anim_poster_defaults_to_middle_and_delivery_copy(tmp_path):
    import numpy as np

    from figlib import anim
    frames = (np.full((40, 64, 3), 0 if i < 5 else 200, np.uint8) for i in range(10))
    out = anim.write(frames, tmp_path / "fade", fps=10, gif=False, contact_n=0)
    assert np.asarray(Image.open(out.poster).convert("L")).mean() > 150   # not the black frame 0
    small = anim.delivery_copy(out.mp4, height=20)
    assert small.name == "fade_send.mp4" and small.stat().st_size > 0


def test_touches_edge_flags_content_on_border():
    import numpy as np

    from figlib import anim
    a = np.full((20, 30, 3), 255, np.uint8)
    a[5:10, 5:10] = 0
    assert not anim.touches_edge(a)
    a[0, 12] = (213, 94, 0)
    assert anim.touches_edge(a)


def test_calibri_first_fixes_carlito_only_mathtext():
    svg = (b'<svg><text style="font-size: 9px; font-family: \'Carlito\'">k</text>'
           b'<text style="font-family: \'Calibri\', \'Carlito\'; fill: #000">a</text>'
           b'<text font-family="Arial, sans-serif">b</text></svg>')
    out = deck.calibri_first(svg).decode()
    assert "font-family: 'Calibri', 'Carlito'\"" in out
    assert out.count("Calibri") == 3          # the already-correct one is untouched
    assert 'font-family="Calibri, Arial, sans-serif"' in out


def test_build_on_click_fades_each_layer_in_order(tmp_path):
    svg = tmp_path / "f.svg"
    svg.write_text(SVG)
    prs, s, box = _deck_with_content(deck.Theme())
    pics = [deck.add_figure(s, svg, box, tmp_path / "cache") for _ in range(3)]
    deck.build_on_click(s, pics[1:], dur_ms=100)
    out = tmp_path / "d.pptx"
    prs.save(out)
    from pptx import Presentation
    sld = Presentation(out).slides[1]._element
    timing = sld.find(deck.qn("p:timing"))
    assert timing is not None and sld[-1] is timing          # after cSld/clrMapOvr
    effects = timing.findall(".//" + deck.qn("p:animEffect"))
    assert [e.get("filter") for e in effects] == ["fade", "fade"]
    targets = [t.get("spid") for t in timing.findall(".//" + deck.qn("p:spTgt"))]
    want = [str(p.shape_id) for p in pics[1:]]
    assert targets == [want[0], want[0], want[1], want[1]]   # set + fade per layer
    ids = [int(c.get("id")) for c in timing.iter(deck.qn("p:cTn"))]
    assert len(ids) == len(set(ids))
    assert {c.find(deck.qn("p:cBhvr")).find(deck.qn("p:cTn")).get("dur") for c in effects} == {"100"}


def test_animate_moves_accumulate_and_phases_chain(tmp_path):
    svg = tmp_path / "f.svg"
    svg.write_text(SVG)
    prs, s, box = _deck_with_content(deck.Theme())
    a, b = (deck.add_figure(s, svg, box, tmp_path / "cache") for _ in range(2))
    W, H = prs.slide_width, prs.slide_height
    deck.animate(s, [[[("in", a, 300)]],
                     [[("move", a, 1000, W // 4, 0)], [("in", b, 300), ("out", a, 300)]],
                     [[("move", a, 500, 0, H // 2)]]], slide_w=W, slide_h=H)
    out = tmp_path / "d.pptx"
    prs.save(out)
    from pptx import Presentation
    sld = Presentation(out).slides[1]._element
    t = sld.find(deck.qn("p:timing"))
    seq = t.find(".//" + deck.qn("p:cTn") + "[@nodeType='mainSeq']").find(deck.qn("p:childTnLst"))
    assert len(seq) == 3                                                  # one par per click
    paths = [m.get("path") for m in t.iter(deck.qn("p:animMotion"))]
    assert paths == ["M 0.00000 0.00000 L 0.25000 0.00000 E",            # second move starts where
                     "M 0.25000 0.00000 L 0.25000 0.50000 E"]            # the first one ended
    nodes = [c.get("nodeType") for c in t.iter(deck.qn("p:cTn")) if c.get("presetClass")]
    assert nodes == ["clickEffect", "clickEffect", "afterEffect", "withEffect", "clickEffect"]
    click2 = seq[1].find(".//" + deck.qn("p:childTnLst"))
    delays = [ph.find(deck.qn("p:cTn")).find(".//" + deck.qn("p:cond")).get("delay") for ph in click2]
    assert delays == ["0", "1000"]                                        # phase 2 waits for the move
    classes = [c.get("presetClass") for c in t.iter(deck.qn("p:cTn")) if c.get("presetClass")]
    assert classes == ["entr", "path", "entr", "exit", "path"]
    ids = [int(c.get("id")) for c in t.iter(deck.qn("p:cTn"))]
    assert len(ids) == len(set(ids))


def test_animate_plays_movies_auto_and_on_click(tmp_path):
    """A looping background movie starts with the slide; a click swaps it for a second movie."""
    from PIL import Image
    poster = tmp_path / "p.png"
    Image.new("RGB", (160, 69), "white").save(poster)
    mp4 = tmp_path / "m.mp4"
    mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42")          # python-pptx embeds the bytes as given
    prs, s, box = _deck_with_content(deck.Theme())
    bgm, split = deck.add_movie(s, mp4, poster, box), deck.add_movie(s, mp4, poster, box)
    W, H = prs.slide_width, prs.slide_height
    deck.animate(s, [[[("out", bgm, 300), ("in", split, 300), ("play", split, 2600)]]],
                 slide_w=W, slide_h=H, auto=[[("play", bgm, 16000)]], loop=[bgm])
    out = tmp_path / "d.pptx"
    prs.save(out)
    from pptx import Presentation
    t = Presentation(out).slides[1]._element.find(deck.qn("p:timing"))
    seq = t.find(".//" + deck.qn("p:cTn") + "[@nodeType='mainSeq']").find(deck.qn("p:childTnLst"))
    assert len(seq) == 2                                                  # the auto start + one click
    begin = seq[0].find(deck.qn("p:cTn")).find(deck.qn("p:stCondLst"))
    assert [c.get("evt") for c in begin] == [None, "onBegin"]             # starts with the slide
    cmds = [(c.get("cmd"), c.find(".//" + deck.qn("p:spTgt")).get("spid")) for c in t.iter(deck.qn("p:cmd"))]
    assert cmds == [("playFrom(0.0)", str(bgm.shape_id)), ("playFrom(0.0)", str(split.shape_id))]
    nodes = {n.find(".//" + deck.qn("p:spTgt")).get("spid"): n.find(deck.qn("p:cTn")).get("repeatCount")
             for n in t.iter(deck.qn("p:cMediaNode"))}
    assert nodes == {str(bgm.shape_id): "indefinite", str(split.shape_id): None}   # one node per movie
    classes = [c.get("presetClass") for c in t.iter(deck.qn("p:cTn")) if c.get("presetClass")]
    assert classes == ["mediacall", "exit", "entr", "mediacall"]
    ids = [int(c.get("id")) for c in t.iter(deck.qn("p:cTn"))]
    assert len(ids) == len(set(ids))


def test_animate_refuses_a_loop_that_never_plays(tmp_path):
    from PIL import Image
    poster = tmp_path / "p.png"
    Image.new("RGB", (160, 69), "white").save(poster)
    mp4 = tmp_path / "m.mp4"
    mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    prs, s, box = _deck_with_content(deck.Theme())
    m = deck.add_movie(s, mp4, poster, box)
    with pytest.raises(ValueError, match="no play effect"):
        deck.animate(s, [], slide_w=prs.slide_width, slide_h=prs.slide_height, loop=[m])


def test_equation_sits_above_figure_at_natural_size(tmp_path):
    prs, s, box = _deck_with_content(deck.Theme())
    pic, rest = deck.add_equation(s, r"R = \frac{k_{\mathrm{pas}}}{k_{\mathrm{pas}} + k_{\mathrm{deg}} V_n}",
                                  box, tmp_path / "cache")
    svg, png, w_in, h_in = deck.render_equation(
        r"R = \frac{k_{\mathrm{pas}}}{k_{\mathrm{pas}} + k_{\mathrm{deg}} V_n}", tmp_path / "cache")
    assert abs(pic.width - Inches(w_in)) <= 1 and abs(pic.height - Inches(h_in)) <= 1   # never scaled
    assert pic.top == box[1] and rest[1] >= pic.top + pic.height                        # figure below it
    assert rest[1] + rest[3] == box[1] + box[3]                                          # same bottom
    blip = pic._element.blipFill.find(deck.qn("a:blip"))
    assert blip.find(".//{%s}svgBlip" % deck.NS_ASVG) is not None                       # vector rides along
    assert "<text" not in svg.read_text() and "<path" in svg.read_text()             # glyphs as outlines


def test_equation_refuses_small_type_and_overwide(tmp_path):
    prs, s, box = _deck_with_content(deck.Theme())
    with pytest.raises(ValueError, match="slide floor"):
        deck.add_equation(s, "x", box, tmp_path, pt=deck.MIN_BODY_PT - 1)
    with pytest.raises(ValueError, match="wide"):
        deck.add_equation(s, "x" * 400, box, tmp_path)


def test_equation_column_stacks_in_box_without_overlap(tmp_path):
    prs, s, box = _deck_with_content(deck.Theme())
    texs = [r"a = b", r"\dfrac{c}{d} = e", r"f(r) = \dfrac{g}{r}\,\exp[-h]"]
    pics = [line[0] for line in deck.add_equation_column(s, texs, box, tmp_path / "cache")]
    assert len(pics) == 3 and all(p.left == box[0] for p in pics)                # left-aligned
    for a, b in zip(pics, pics[1:]):
        assert a.top + a.height <= b.top                                          # top-down, no overlap
    assert pics[0].top >= box[1] and pics[-1].top + pics[-1].height <= box[1] + box[3]
    with pytest.raises(ValueError, match="tall"):
        deck.add_equation_column(s, texs * 6, box, tmp_path / "cache")


def test_equation_parts_share_a_baseline(tmp_path):
    """A line revealed in pieces: same height and top, so baselines and fraction bars line up."""
    prs, s, box = _deck_with_content(deck.Theme())
    parts = [r"\tau = \dfrac{1}{k\,(1/V_c + 1/V_n)}", r"\approx \dfrac{V_n}{k}"]
    (line,) = deck.add_equation_column(s, [parts], box, tmp_path / "cache")
    a, b = line
    assert a.top == b.top and a.height == b.height
    assert b.left > a.left + a.width                                             # side by side
    r = deck.render_equation_parts(parts, tmp_path / "cache")
    assert len({round(h, 6) for *_, h in r}) == 1
    assert r"\cdot" not in "" and "<text" not in r[1][0].read_text()


def test_fallback_png_without_native_cairo_uses_chromium(tmp_path, monkeypatch):
    # Windows has no libcairo, so cairosvg can't even be imported there (os-check, 2026-11-23).
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception:
        pytest.skip("Chromium not installed")
    monkeypatch.setattr(deck, "_cairosvg", lambda: None)
    svg = tmp_path / "f.svg"
    svg.write_text(SVG)
    png = deck.fallback_png(svg, tmp_path / "cache")
    im = Image.open(png).convert("RGB")
    assert im.size == (deck.FALLBACK_PX_WIDTH, deck.FALLBACK_PX_WIDTH // 2)
    assert im.getpixel((im.width // 2, im.height // 2)) == (0x2a, 0x78, 0xd6)
    assert not list((tmp_path / "cache").glob("*.html"))

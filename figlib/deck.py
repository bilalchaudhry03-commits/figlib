"""Build .pptx decks: SVG figures with PNG fallback, equations, MP4 movies, a house template, and a linter.

Each talk keeps its own content and a short build script; this holds the reusable parts.
Slides are title + main content only: there is no subtitle or caption parameter, and
`require_clean(prs)` fails the build on non-footer text that is grey or under 18 pt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import cairosvg
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, PP_PLACEHOLDER
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import Part
from pptx.oxml import parse_xml
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

SVG_EXT_URI = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"
NS_ASVG = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"

# Exact EMU, not Inches(13.333): the decimal is 305 EMU short of a true 13-1/3 in.
SLIDE_W, SLIDE_H = Emu(12192000), Emu(6858000)
FALLBACK_PX_WIDTH = 2400

FOOTER_NAME = "figlib-footer"   # the one shape lint_deck lets be small and grey; matched by
                                # name, not position, so a caption can't pass by sitting low
MIN_BODY_PT = 18                # slide text floor; figures have their own (9pt) via figcheck

INK = "1A242E"
MUTED = "5A6673"                # footer only
# Sampled from the official shield file (PU_mark.svg).
PRINCETON_ORANGE = "F58025"


# --------------------------------------------------------------------------- template

@dataclass(frozen=True)
class Theme:
    """Slide chrome. Everything a template varies lives here; slides never set colour.

    `rule`: where the orange line goes -- "bottom" (thin full-width rule above the
    footer), "band" (thick bottom band with the footer reversed out in white), or
    "title" (short accent under each title, thin rule at the bottom).
    `logo`: path to the shield image, or None to leave the slot empty.
    `title_logo`: a wider lockup (shield + wordmark) for the title slide only, top-left;
    None falls back to `logo` in the top-right slot.
    `logo_on`: "all" | "title" -- whether content slides carry the shield.
    """
    name: str = "A"
    rule: str = "bottom"
    accent: str = PRINCETON_ORANGE
    ink: str = INK
    font: str = "Calibri"
    title_pt: int = 30
    body_pt: int = 22
    logo: Path | None = None
    title_logo: Path | None = None
    logo_on: str = "all"


def _rgb(h: str) -> RGBColor:
    return RGBColor.from_string(h)


def new_presentation() -> Presentation:
    """A blank 16:9 deck at PowerPoint's own 13.333 x 7.5 in."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H
    # The default template's stale type="screen4x3" makes PowerPoint report 4:3 in
    # Page Setup while rendering 16:9.
    prs._element.find(qn("p:sldSz")).attrib.pop("type", None)
    return prs


def _blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _rect(slide, x, y, w, h, color):
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    shp.fill.solid()
    shp.fill.fore_color.rgb = _rgb(color)
    shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def _text(slide, box, text, *, pt, color, bold=False, font="Calibri",
          align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, name=None):
    tb = slide.shapes.add_textbox(*box)
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = 0
    lines = text if isinstance(text, list) else [text]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.size, r.font.bold, r.font.name = Pt(pt), bold, font
        r.font.color.rgb = _rgb(color)
    return tb


def _logo(slide, theme: Theme, x, y, h, *, path=None, align="right"):
    """Place the shield (or `path`), or an outlined placeholder box when there is no file.
    `x` is the right edge for align="right", the left edge for align="left"."""
    path = path or theme.logo
    if path and Path(path).exists():
        pic = slide.shapes.add_picture(str(path), x, y, height=h)
        if align == "right":
            pic.left = x - pic.width
        pic.name = "logo"
        return
    w = int(h * 0.82)
    box = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x - w, y, w, h)
    box.fill.background()
    box.line.color.rgb = _rgb("B0B0B0")
    box.line.dash_style = 4
    box.name = "logo-slot"


def _chrome(slide, theme: Theme, footer: str, *, is_title: bool):
    """Orange rule/band, footer, shield. Returns the bottom of the usable area (EMU)."""
    W, H = SLIDE_W, SLIDE_H
    m = Inches(0.5)
    show_logo = theme.logo_on == "all" or is_title
    if theme.rule == "band":
        band_h = Inches(0.42)
        _rect(slide, 0, H - band_h, W, band_h, theme.accent)
        if footer:
            _text(slide, (m, H - band_h, Inches(8), band_h), footer, pt=11,
                  color="FFFFFF", font=theme.font, anchor=MSO_ANCHOR.MIDDLE, name=FOOTER_NAME)
        if show_logo:  # inside the band, so it never competes with the figure area
            _logo(slide, theme, W - m, H - band_h + Inches(0.05), band_h - Inches(0.1))
        return H - band_h - Inches(0.15)
    rule_y = H - Inches(0.5)
    _rect(slide, 0 if theme.rule == "bottom" else m, rule_y,
          W if theme.rule == "bottom" else W - 2 * m, Pt(3 if theme.rule == "bottom" else 1.5),
          theme.accent)
    if footer:
        _text(slide, (m, rule_y + Inches(0.1), Inches(8), Inches(0.3)), footer, pt=11,
              color=MUTED, font=theme.font, name=FOOTER_NAME)
    if show_logo:
        _logo(slide, theme, W - m, rule_y + Inches(0.06), Inches(0.38))
    return rule_y - Inches(0.1)


def title_slide(prs, theme: Theme, title: str, author: str, *, name: str = "Title"):
    """Title + presenter. Deliberately no subtitle, date or affiliation line: those are
    the grey secondary text the house rule forbids -- say them, or put them in notes."""
    s = _blank(prs)
    W, H = SLIDE_W, SLIDE_H
    m = Inches(0.9)
    if theme.rule == "title":
        _rect(s, m, Inches(2.45), Inches(1.6), Pt(5), theme.accent)
    elif theme.rule == "band":
        _rect(s, 0, H - Inches(0.42), W, Inches(0.42), theme.accent)
    else:
        _rect(s, 0, H - Inches(0.5), W, Pt(3), theme.accent)
    _text(s, (m, Inches(2.6), W - 2 * m - Inches(2), Inches(2.2)), title, pt=40, bold=True,
          color=theme.ink, font=theme.font, anchor=MSO_ANCHOR.TOP)
    _text(s, (m, Inches(4.9), W - 2 * m, Inches(0.5)), author, pt=24,
          color=theme.ink, font=theme.font)
    if theme.title_logo and Path(theme.title_logo).exists():
        _logo(s, theme, m, Inches(0.75), Inches(0.95), path=theme.title_logo, align="left")
    else:
        _logo(s, theme, W - m, Inches(0.7), Inches(1.6))
    set_slide_name(s, name)
    return s


def content_slide(prs, theme: Theme, title: str, footer: str = "", *, name: str | None = None):
    """Title + chrome; returns (slide, box) where box is the free area below the title."""
    s = _blank(prs)
    W = SLIDE_W
    m = Inches(0.5)
    # Sized for a two-line title at title_pt, since assertion titles often wrap.
    _text(s, (m, Inches(0.3), W - 2 * m - Inches(0.6), Inches(1.1)), title, pt=theme.title_pt,
          bold=True, color=theme.ink, font=theme.font, anchor=MSO_ANCHOR.MIDDLE)
    top = Inches(1.6)
    if theme.rule == "title":
        _rect(s, m, Inches(1.47), Inches(1.2), Pt(3), theme.accent)
        top = Inches(1.7)
    bottom = _chrome(s, theme, footer, is_title=False)
    set_slide_name(s, name or title)
    return s, (m, top, W - 2 * m, bottom - top)


def bullets(slide, box, items: list[str], theme: Theme):
    """Top-level bullets only. No `level` argument: sub-bullets are secondary text."""
    tb = _text(slide, box, [f"•  {b}" for b in items], pt=theme.body_pt,
               color=theme.ink, font=theme.font)
    for p in tb.text_frame.paragraphs:
        p.space_after = Pt(10)
    return tb


# --------------------------------------------------------------------------- pictures

def fallback_png(svg: Path, cache_dir: Path) -> Path:
    """Rasterise `svg` into `cache_dir`, reusing an up-to-date render.

    Rendered with Carlito standing in for Calibri, so judge the figure by its SVG, not this.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    png = cache_dir / (svg.stem + ".png")
    if not png.exists() or png.stat().st_mtime < svg.stat().st_mtime:
        cairosvg.svg2png(bytestring=calibri_first(svg.read_bytes()), url=str(svg),
                         write_to=str(png), output_width=FALLBACK_PX_WIDTH)
    return png


_CSS_FAMILY = re.compile(r"(font-family:\s*)([^;\"]+)")
_ATTR_FAMILY = re.compile(r'(font-family=")([^"]+)(")')


def calibri_first(svg: bytes) -> bytes:
    """Put Calibri at the head of every font-family list that lacks it.

    Figure scripts lay out mathtext in Carlito, and matplotlib then writes
    `font-family: 'Carlito'` alone. Presenting machines don't have Carlito, so PowerPoint
    would substitute its default face. Carlito is metric-identical to Calibri, so naming
    Calibri first changes no layout, and fontconfig still resolves it to Carlito here.
    """
    def css(m):
        v = m.group(2)
        return m.group(0) if "calibri" in v.lower() else f"{m.group(1)}'Calibri', {v}"

    def attr(m):
        v = m.group(2)
        return m.group(0) if "calibri" in v.lower() else f"{m.group(1)}Calibri, {v}{m.group(3)}"

    text = svg.decode("utf-8")
    return _ATTR_FAMILY.sub(attr, _CSS_FAMILY.sub(css, text)).encode("utf-8")


def _fit(pic, box):
    left, top, width, height = box
    scale = min(width / pic.width, height / pic.height)
    pic.width, pic.height = Emu(int(pic.width * scale)), Emu(int(pic.height * scale))
    pic.left = Emu(int(left + (width - pic.width) / 2))
    pic.top = Emu(int(top + (height - pic.height) / 2))
    return pic


def add_svg_picture(slide, svg: Path, png: Path, box):
    """Place `png` fitted inside `box`, then attach `svg` as the vector authority."""
    pic = _fit(slide.shapes.add_picture(str(png), box[0], box[1]), box)
    return _attach_svg(slide, pic, svg)


def _attach_svg(slide, pic, svg: Path):
    """Carry `svg` on `pic`'s raster blip as the asvg:svgBlip extension.

    OOXML requires a picture's primary blip to be raster; vector rides along as this
    extension. PowerPoint 2019/365 renders the SVG (and "Convert to Shape" works on it);
    older versions show the PNG. python-pptx has no API for it, hence the raw XML.
    """
    package = slide.part.package
    part = Part(package.next_partname("/ppt/media/image%d.svg"), "image/svg+xml",
                package, calibri_first(svg.read_bytes()))
    rid = slide.part.relate_to(part, RT.IMAGE)
    blip = pic._element.blipFill.find(qn("a:blip"))
    blip.append(parse_xml(
        f'<a:extLst xmlns:a="{NS_A}">'
        f'<a:ext uri="{SVG_EXT_URI}">'
        f'<asvg:svgBlip xmlns:asvg="{NS_ASVG}" xmlns:r="{NS_R}" r:embed="{rid}"/>'
        f"</a:ext></a:extLst>"
    ))
    return pic


def add_raster_picture(slide, png: Path, box):
    return _fit(slide.shapes.add_picture(str(png), box[0], box[1]), box)


def add_figure(slide, fig: Path, box, cache_dir: Path):
    """SVG -> vector with fallback; anything else -> raster."""
    if fig.suffix == ".svg":
        return add_svg_picture(slide, fig, fallback_png(fig, cache_dir), box)
    return add_raster_picture(slide, fig, box)


# --------------------------------------------------------------------------- equations

EQUATION_PT = 26        # = Theme.body_pt; never below MIN_BODY_PT
EQUATION_GAP = Inches(0.15)


def render_equation_parts(texs: list[str], cache_dir: Path, *, pt: int = EQUATION_PT,
                          color: str = INK) -> list[tuple[Path, Path, float, float]]:
    """Typeset pieces of ONE equation line (mathtext, no $) that will sit side by side on a slide.

    Each piece is drawn on an identical canvas at the same baseline and all are cropped to the
    same vertical extent, so placed at one `top` their baselines and fraction bars line up (e.g.
    to reveal "≈ simpler form" after the full form). Horizontally each is cropped to its own ink.
    Returns, per piece, (svg, png, width_in, height_in) at natural size; `pt` is the slide size.

    Glyphs are written as paths, not text: a glyph Carlito lacks (e.g. \\cdot) would otherwise
    fall back to another face, and PowerPoint draws it blank.
    """
    import hashlib
    import logging
    import matplotlib
    matplotlib.use("Agg")
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)   # stack walk noise
    import matplotlib.pyplot as plt
    import numpy as np
    from PIL import Image
    from figlib import fonts

    if pt < MIN_BODY_PT:
        raise ValueError(f"equation at {pt}pt is below the {MIN_BODY_PT}pt slide floor")
    fonts.register()
    cache_dir.mkdir(parents=True, exist_ok=True)
    DPI, W_IN, H_IN, X0_IN, BASE_IN = 300, 16.0, 3.0, 0.1, 1.5          # one canvas for every piece
    rc = {"mathtext.fontset": "custom", "mathtext.rm": "Carlito", "mathtext.it": "Carlito:italic",
          "mathtext.bf": "Carlito:bold", "svg.fonttype": "path", "font.family": fonts.STACK_LIST}
    raw = []
    for tex in texs:
        key = hashlib.sha1(f"v2|{tex}|{pt}|{color}".encode()).hexdigest()[:12]
        svg_full, png_full = cache_dir / f"eqfull_{key}.svg", cache_dir / f"eqfull_{key}.png"
        if not (svg_full.exists() and png_full.exists()):
            with plt.rc_context(rc):
                fig = plt.figure(figsize=(W_IN, H_IN))
                fig.text(X0_IN / W_IN, BASE_IN / H_IN, f"${tex}$", fontsize=pt, color=f"#{color}",
                         va="baseline", ha="left")
                fig.savefig(svg_full, transparent=True)
                fig.savefig(png_full, dpi=DPI, transparent=True)
                plt.close(fig)
        alpha = np.asarray(Image.open(png_full).convert("RGBA"))[:, :, 3]
        ys, xs = np.nonzero(alpha)
        if not len(xs):
            raise ValueError(f"equation drew nothing: {tex}")
        if xs.max() >= alpha.shape[1] - 2 or ys.min() <= 1 or ys.max() >= alpha.shape[0] - 2:
            raise ValueError(f"equation is too wide or tall for its {W_IN}x{H_IN} in canvas: {tex}")
        raw.append((key, svg_full, png_full, xs.min(), xs.max(), ys.min(), ys.max()))
    pad = int(0.04 * DPI)
    top = min(r[5] for r in raw) - pad
    bot = max(r[6] for r in raw) + pad
    out = []
    for key, svg_full, png_full, x0, x1, _, _ in raw:
        l, r = x0 - pad, x1 + pad
        png = cache_dir / f"eq_{key}_{top}_{bot}.png"
        svg = png.with_suffix(".svg")
        Image.open(png_full).crop((l, top, r, bot)).save(png)
        # same crop on the SVG: matplotlib's user space is points (72/in), origin top-left
        k = 72 / DPI
        vb = f"{l * k:.3f} {top * k:.3f} {(r - l) * k:.3f} {(bot - top) * k:.3f}"
        t = svg_full.read_text()
        t = re.sub(r'width="[^"]*pt"', f'width="{(r - l) * k:.3f}pt"', t, count=1)
        t = re.sub(r'height="[^"]*pt"', f'height="{(bot - top) * k:.3f}pt"', t, count=1)
        t = re.sub(r'viewBox="[^"]*"', f'viewBox="{vb}"', t, count=1)
        svg.write_text(t)
        out.append((svg, png, (r - l) / DPI, (bot - top) / DPI))
    return out


def render_equation(tex: str, cache_dir: Path, *, pt: int = EQUATION_PT,
                    color: str = INK) -> tuple[Path, Path, float, float]:
    """One equation, as SVG (glyph outlines) + 300 dpi PNG; see `render_equation_parts`.

    `lint_deck` can't see type inside a picture, so the size floor is enforced here: `pt` is
    the size on the slide, because `add_equation` never scales it.
    """
    return render_equation_parts([tex], cache_dir, pt=pt, color=color)[0]


def add_equation(slide, tex: str, box, cache_dir: Path, *, pt: int = EQUATION_PT):
    """Place `tex` at natural size, centred, at the top of `box`; return (picture, box left over).

    The figure that shares the slide goes in the returned box, so the two never overlap and
    the equation is never shrunk to fit. Too wide for the box is an error, not a rescale.
    """
    svg, png, w_in, h_in = render_equation(tex, cache_dir, pt=pt)
    left, top, width, height = box
    w, h = Inches(w_in), Inches(h_in)
    if w > width:
        raise ValueError(f"equation is {w_in:.2f} in wide; the box is {Emu(width).inches:.2f} in")
    pic = slide.shapes.add_picture(str(png), Emu(int(left + (width - w) / 2)), top, w, h)
    _attach_svg(slide, pic, svg)
    rest = top + h + EQUATION_GAP
    return pic, (left, rest, width, top + height - rest)


def add_equation_column(slide, lines: list, box, cache_dir: Path, *, pt: int = EQUATION_PT):
    """Stack equation lines top-down, left-aligned, in `box` (a derivation); return pictures per line.

    A line is a string, or a list of pieces placed side by side on a shared baseline (so a later
    click can reveal the rest of a line). Natural size, never scaled: a line too wide or a stack
    too tall is an error. Spare height becomes equal gaps (at most one line height), and the
    stack is centred vertically.
    """
    left, top, width, height = box
    lines = [[ln] if isinstance(ln, str) else list(ln) for ln in lines]
    part_gap = Inches(0.28 * pt / 72)                     # ~ a relation's space in mathtext
    rendered = [render_equation_parts(ln, cache_dir, pt=pt) for ln in lines]
    for ln, parts in zip(lines, rendered):
        w = sum(Inches(p[2]) for p in parts) + part_gap * (len(parts) - 1)
        if w > width:
            raise ValueError(f"equation line is {Emu(w).inches:.2f} in wide; the column is "
                             f"{Emu(width).inches:.2f} in: {' '.join(ln)}")
    hs = [Inches(parts[0][3]) for parts in rendered]
    spare = height - sum(hs)
    if spare < 0:
        raise ValueError(f"{len(lines)} equations need {Emu(sum(hs)).inches:.2f} in; the box is "
                         f"{Emu(height).inches:.2f} in tall")
    gap = min(spare // max(len(lines), 1), max(hs))
    y = top + (spare - gap * (len(lines) - 1)) // 2
    out = []
    for parts, h in zip(rendered, hs):
        x, pics = left, []
        for svg, png, w_in, _ in parts:
            pic = slide.shapes.add_picture(str(png), Emu(int(x)), Emu(int(y)), Inches(w_in), h)
            _attach_svg(slide, pic, svg)
            pics.append(pic)
            x += Inches(w_in) + part_gap
        out.append(pics)
        y += h + gap
    return out


def add_movie(slide, mp4: Path, poster: Path, box):
    """Embed an MP4 fitted to `box`, with `poster` as the frame shown when not playing.

    MP4 rather than GIF: a GIF is 256 colours, large, and loops with no pause. LibreOffice/PDF
    renders show only the poster; review the motion with `figlib.anim`'s contact sheet.
    """
    probe = slide.shapes.add_picture(str(poster), 0, 0)
    w0, h0 = probe.width, probe.height
    probe._element.getparent().remove(probe._element)
    left, top, width, height = box
    scale = min(width / w0, height / h0)
    w, h = int(w0 * scale), int(h0 * scale)
    return slide.shapes.add_movie(str(mp4), Emu(int(left + (width - w) / 2)),
                                  Emu(int(top + (height - h) / 2)), Emu(w), Emu(h),
                                  poster_frame_image=str(poster), mime_type="video/mp4")


def build_on_click(slide, shapes, *, dur_ms: int = 100) -> None:
    """Fade `shapes` in one per click, in order (PowerPoint entrance effect "Fade", preset 10).

    For panel-by-panel builds, export one transparent SVG per layer into the same box. python-pptx
    has no animation API, so this writes `p:timing` by hand. LibreOffice/PDF renders show every
    layer at once; check the build in PowerPoint.
    """
    if not shapes:
        return
    ids = iter(range(3, 10_000))
    clicks = []
    for shp in shapes:
        sp = shp.shape_id
        a, b, c, d, e = (next(ids) for _ in range(5))
        clicks.append(
            f'<p:par><p:cTn id="{a}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/>'
            f'</p:stCondLst><p:childTnLst><p:par><p:cTn id="{b}" fill="hold"><p:stCondLst>'
            f'<p:cond delay="0"/></p:stCondLst><p:childTnLst><p:par><p:cTn id="{c}" '
            f'presetID="10" presetClass="entr" presetSubtype="0" fill="hold" '
            f'nodeType="clickEffect"><p:stCondLst><p:cond delay="0"/></p:stCondLst>'
            f'<p:childTnLst><p:set><p:cBhvr><p:cTn id="{d}" dur="1" fill="hold"><p:stCondLst>'
            f'<p:cond delay="0"/></p:stCondLst></p:cTn><p:tgtEl><p:spTgt spid="{sp}"/>'
            f'</p:tgtEl><p:attrNameLst><p:attrName>style.visibility</p:attrName>'
            f'</p:attrNameLst></p:cBhvr><p:to><p:strVal val="visible"/></p:to></p:set>'
            f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{e}" '
            f'dur="{dur_ms}"/><p:tgtEl><p:spTgt spid="{sp}"/></p:tgtEl></p:cBhvr>'
            f'</p:animEffect></p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>'
            f'</p:childTnLst></p:cTn></p:par>'
        )
    _set_timing(slide, clicks)


def _set_timing(slide, clicks: list[str]) -> None:
    """Write one main click sequence (`clicks`, one <p:par> per click) as the slide's p:timing."""
    timing = parse_xml(
        f'<p:timing xmlns:p="{NS_P}"><p:tnLst><p:par><p:cTn id="1" dur="indefinite" '
        f'restart="never" nodeType="tmRoot"><p:childTnLst><p:seq concurrent="1" '
        f'nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
        + "".join(clicks) +
        '</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl>'
        '<p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst><p:nextCondLst><p:cond '
        'evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst>'
        '</p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>'
    )
    sld = slide._element
    old = sld.find(qn("p:timing"))
    if old is not None:
        sld.remove(old)
    # schema order in p:sld: cSld, clrMapOvr, transition, timing, extLst
    ext = sld.find(qn("p:extLst"))
    if ext is not None:
        ext.addprevious(timing)
    else:
        sld.append(timing)


def animate(slide, steps, *, slide_w: int, slide_h: int) -> None:
    """Click-driven animation with fades in and out and motion paths.

    `steps` is one entry per click; each click is a list of PHASES that play one after
    another without a further click; each phase is a list of effects that play together:

        ("in", shape, ms) | ("out", shape, ms) | ("move", shape, ms, dx_emu, dy_emu)

    A shape with an "in" effect starts hidden (PowerPoint hides an entrance-effect target until it
    plays). Motion paths are written relative to the shape's LAYOUT position (origin="layout"), so a
    shape that moves twice gets a path from its accumulated offset to the new one, tracked here --
    pass each move as the step it takes, not as an absolute position. Paths are in fractions of the
    slide, hence slide_w/slide_h. LibreOffice/PDF renders show every shape at its start position; the
    animation can only be checked in PowerPoint.
    """
    ids = iter(range(3, 100_000))
    at: dict[int, tuple[float, float]] = {}
    clicks = []

    def tgt(sp):
        return f'<p:tgtEl><p:spTgt spid="{sp}"/></p:tgtEl>'

    def effect(kind, shp, ms, node, dx=0, dy=0):
        sp, c = shp.shape_id, next(ids)
        head = (f'<p:par><p:cTn id="{c}" presetID="{{pid}}" presetClass="{{cls}}" presetSubtype="0" '
                f'fill="hold" nodeType="{node}"{{extra}}><p:stCondLst><p:cond delay="0"/></p:stCondLst>'
                f'<p:childTnLst>')
        tail = '</p:childTnLst></p:cTn></p:par>'
        if kind == "in":
            body = (f'<p:set><p:cBhvr><p:cTn id="{next(ids)}" dur="1" fill="hold"><p:stCondLst>'
                    f'<p:cond delay="0"/></p:stCondLst></p:cTn>{tgt(sp)}<p:attrNameLst>'
                    f'<p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr><p:to>'
                    f'<p:strVal val="visible"/></p:to></p:set><p:animEffect transition="in" '
                    f'filter="fade"><p:cBhvr><p:cTn id="{next(ids)}" dur="{ms}"/>{tgt(sp)}</p:cBhvr>'
                    f'</p:animEffect>')
            return head.format(pid=10, cls="entr", extra="") + body + tail
        if kind == "out":
            body = (f'<p:animEffect transition="out" filter="fade"><p:cBhvr><p:cTn id="{next(ids)}" '
                    f'dur="{ms}"/>{tgt(sp)}</p:cBhvr></p:animEffect><p:set><p:cBhvr><p:cTn '
                    f'id="{next(ids)}" dur="1" fill="hold"><p:stCondLst><p:cond delay="{max(ms - 1, 0)}"/>'
                    f'</p:stCondLst></p:cTn>{tgt(sp)}<p:attrNameLst><p:attrName>style.visibility'
                    f'</p:attrName></p:attrNameLst></p:cBhvr><p:to><p:strVal val="hidden"/></p:to></p:set>')
            return head.format(pid=10, cls="exit", extra="") + body + tail
        if kind == "move":
            x0, y0 = at.get(sp, (0.0, 0.0))
            x1, y1 = x0 + dx / slide_w, y0 + dy / slide_h
            at[sp] = (x1, y1)
            body = (f'<p:animMotion origin="layout" path="M {x0:.5f} {y0:.5f} L {x1:.5f} {y1:.5f} E" '
                    f'pathEditMode="relative" ptsTypes="AA"><p:cBhvr><p:cTn id="{next(ids)}" dur="{ms}" '
                    f'fill="hold"/>{tgt(sp)}<p:attrNameLst><p:attrName>ppt_x</p:attrName>'
                    f'<p:attrName>ppt_y</p:attrName></p:attrNameLst></p:cBhvr></p:animMotion>')
            return head.format(pid=0, cls="path", extra=' accel="50000" decel="50000"') + body + tail
        raise ValueError(f"unknown effect {kind!r}")

    for click in steps:
        outer, phases, delay = next(ids), [], 0
        for k, phase in enumerate(click):
            nodes = [("clickEffect" if k == 0 else "afterEffect") if j == 0 else "withEffect"
                     for j in range(len(phase))]
            body = "".join(effect(e[0], e[1], e[2], n, *e[3:]) for e, n in zip(phase, nodes))
            phases.append(f'<p:par><p:cTn id="{next(ids)}" fill="hold"><p:stCondLst><p:cond '
                          f'delay="{delay}"/></p:stCondLst><p:childTnLst>{body}</p:childTnLst>'
                          f'</p:cTn></p:par>')
            delay += max(e[2] for e in phase)
        clicks.append(f'<p:par><p:cTn id="{outer}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/>'
                      f'</p:stCondLst><p:childTnLst>{"".join(phases)}</p:childTnLst></p:cTn></p:par>')
    _set_timing(slide, clicks)


# --------------------------------------------------------------------------- notes / naming

def set_slide_name(slide, name: str) -> None:
    """Name the slide for PowerPoint's navigation without printing it on the slide."""
    slide.shapes._spTree.getparent().set("name", name[:120])  # spTree's parent IS p:cSld


def set_notes(slide, text: str) -> None:
    slide.notes_slide.notes_text_frame.text = text


def md_to_notes(text: str) -> str:
    """Markdown -> plain text for the notes pane. Structure kept, syntax dropped."""
    out = []
    for line in text.splitlines():
        line = re.sub(r"^>\s?", "", line)
        line = line.replace("**", "").replace("`", "")
        line = re.sub(r"\*\[(.*?)\]\*", r"[\1]", line)
        line = re.sub(r"(?<!\*)\*(?!\s)([^*]+?)(?<!\s)\*(?!\*)", r"\1", line)
        out.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


# --------------------------------------------------------------------------- lint

def _is_grey(rgb: str) -> bool:
    """Low-saturation and neither near-black ink nor white. White is allowed because the
    band template reverses its footer out; anything mid-grey is secondary text."""
    r, g, b = (int(rgb[i:i + 2], 16) for i in (0, 2, 4))
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return max(r, g, b) - min(r, g, b) < 40 and 0.25 < lum < 0.95


def lint_deck(prs, *, min_pt: int = MIN_BODY_PT) -> list[str]:
    """Return one line per violation of the title-plus-content rule. Empty = clean.

    Checks every text run outside the footer: grey colour, explicit size below
    `min_pt`, and any SUBTITLE placeholder at all. Text inside pictures/SVGs is the
    figure linters' job (`figcheck` / `check_layout`), not this one's.
    """
    errs = []
    for i, slide in enumerate(prs.slides, 1):
        for shp in slide.shapes:
            if shp.name == FOOTER_NAME:
                continue
            if shp.is_placeholder and shp.placeholder_format.type == PP_PLACEHOLDER.SUBTITLE \
                    and shp.has_text_frame and shp.text_frame.text.strip():
                errs.append(f"slide {i}: subtitle placeholder {shp.text_frame.text[:40]!r}")
            if not shp.has_text_frame:
                continue
            for p in shp.text_frame.paragraphs:
                for r in p.runs:
                    if not r.text.strip():
                        continue
                    sz = r.font.size or p.font.size
                    if sz is not None and sz.pt < min_pt and shp.name != "logo-slot":
                        # Titles are bigger; the title slide's author line is 24.
                        errs.append(f"slide {i}: {sz.pt:g}pt < {min_pt}pt  {r.text[:40]!r}")
                    try:
                        col = str(r.font.color.rgb)
                    except AttributeError:
                        col = None
                    if col and _is_grey(col):
                        errs.append(f"slide {i}: grey text #{col}  {r.text[:40]!r}")
    return errs


def require_clean(prs, **kw) -> None:
    errs = lint_deck(prs, **kw)
    if errs:
        raise SystemExit("deck lint FAILED:\n  " + "\n  ".join(errs))

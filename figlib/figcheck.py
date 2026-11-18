"""Layout linter for matplotlib figures. Runs in-process on the live Figure, before savefig.

    from figlib import figcheck
    figcheck.check(fig)      # returns findings, prints nothing
    figcheck.report(fig)     # prints them, returns the count
    figcheck.require(fig)    # raises if anything is wrong

    python -m figlib.figcheck path/to/plotting_script.py   # audit a script unmodified

Checks:
  OVERLAP    text overlaps text (or crosses it at right angles)
  OUTSIDE    text runs past the canvas, where savefig silently crops it
  SMALL      type falls below `min_pt` once the figure is scaled onto a slide
  LEGEND     the legend covers data points
  OVERDATA   in-axes text sits on markers or bars (an opaque text bbox counts as fixed)
  OVERLINE   in-axes text sits on a plotted line
  EXPANDED   bbox_inches="tight" grows the canvas, shrinking every label on the slide
  CLIPPED    data falls outside the axes limits and is never drawn -- the one check
             visual review can't replace. Opt out per axes with `ax.set_gid(CLIP_OK_GID)`.
  COLORROLE  opt-in: one legend colour means two different things across panels
"""
from __future__ import annotations

# stdlib + matplotlib only (no module-level numpy), so it imports from lighter envs too.
import runpy
import sys
from dataclasses import dataclass

import matplotlib
from matplotlib.lines import Line2D
from matplotlib.text import Text
from matplotlib.transforms import BlendedGenericTransform

#: An intersection must be at least this many display pixels in BOTH axes and
#: cover this fraction of the smaller box before it counts. Loose enough that
#: deliberately tight stat blocks pass clean.
OVERLAP_MIN_PX = 3.0
OVERLAP_MIN_FRAC = 0.15

#: Second acceptance rule for OVERLAP. The area rule under-reports a long thin
#: box crossing a short wide one (a rotated panel label through a title covers
#: the title's full height but ~7% of the label's area). A crossing -- the
#: intersection spans most of one box's width AND the other's height -- is
#: distinct from two stacked lines grazing, which the area rule is meant to allow.
OVERLAP_CROSS_FRAC = 0.8

#: Points of slack before a box counts as off-canvas. savefig crops at exactly
#: the canvas edge, so anything past it really is lost.
EDGE_SLACK_PX = 1.0

#: Data points inside the legend box before it is worth reporting.
LEGEND_MIN_POINTS = 20

#: OVERDATA thresholds. The point count is a CAP, not the trigger: the check
#: fires when a text box covers OVERDATA_MIN_FRAC of the axes' own marks, so it
#: works on a 40-point panel and a 4,000-point scatter alike. Floored so a small
#: panel does not fire on one grazed marker.
OVERDATA_MIN_POINTS = 20
OVERDATA_MIN_FRAC = 0.05
OVERDATA_MIN_POINTS_FLOOR = 4

#: A text bbox at least this opaque counts as fixed. Below 1.0 on purpose: a
#: semi-opaque backing keeps the marks visible around the label.
OVERDATA_BBOX_ALPHA = 0.75

#: Bars are judged by the fraction of the text box they cover, not by count:
#: two bars under a label is a collision, two scatter points is not.
OVERDATA_MIN_COVER = 0.35

#: CLIPPED fires when at least this many marks, AND this fraction of the axes'
#: marks, fall outside the limits. Both, so a curve's endpoint leaving the view
#: is silent and a dropped tail is not.
CLIPPED_MIN_POINTS = 3
CLIPPED_MIN_FRAC = 0.02

#: Per-AXES opt-out for CLIPPED, via `ax.set_gid(CLIP_OK_GID)`. Finer than
#: `check_clipped=False`: one panel can be a deliberate zoom while its neighbour
#: is still checked, and the gid is a greppable declaration in the script.
CLIP_OK_GID = "figcheck:clip-ok"

#: OVERLINE fires when a text box crosses a plotted LINE for at least this many
#: display pixels. OVERDATA only counts markers and patches, so a label sitting
#: on a plain `ax.plot` curve needs its own check. Small, like OVERLAP_MIN_PX:
#: rejects a corner graze, catches a real crossing.
OVERLINE_MIN_PX = 3.0

#: COLORROLE (one legend colour backing two different labels across panels) is
#: opt-in: a deliberately shared colour, e.g. "control" in every panel, is common
#: and correct, so this check would cry wolf if it ran by default.
CHECK_COLOR_ROLES_DEFAULT = False

#: A patch spanning at least this fraction of the axes is background shading
#: (axhspan/axvspan/fill_between), not a data mark, so labels on it are fine.
#: Extent alone can't tell an axvspan from a tall bar; see `_is_background_patch`.
BACKGROUND_PATCH_FRAC = 0.9

#: EXPANDED fires when `bbox_inches="tight"` grows the canvas at least this
#: much past the declared `figsize`. A tight save always grows a little (tick
#: padding), so this sits above that noise; a single overhanging `fig.text` is
#: typically 1.08x or more.
EXPAND_MIN_FRAC = 1.05

#: Default target slide, inches (16:9 widescreen).
SLIDE_IN = (13.333, 7.5)

#: Below this, projected text is unreadable from the back of a room. Aim for
#: 11pt body text; 7 is the floor at which it is simply broken.
MIN_PT = 7.0

SHOW_PER_KIND = 8


@dataclass
class Finding:
    kind: str
    what: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind:<10} {self.what}\n           {self.detail}"


def _live_ticklabels(axis):
    """Tick labels the axis will actually DRAW.

    `get_xticklabels()` includes ticks outside the view limits. They aren't
    drawn but still report a window extent off the end of the axis, which shows
    up as phantom OUTSIDE/OVERLAP findings. Filter on the view interval, as the
    draw pass does.
    """
    lo, hi = sorted(axis.get_view_interval())
    pad = (hi - lo) * 1e-6
    out = []
    for tick in list(axis.get_major_ticks()) + list(axis.get_minor_ticks()):
        loc = getattr(tick, "get_loc", lambda: None)()
        if loc is None or not (lo - pad <= loc <= hi + pad):
            continue
        for lab in (tick.label1, tick.label2):
            if lab is not None and lab.get_visible():
                out.append(lab)
    return out


def _collect(fig):
    """Every Text artist that is actually drawn, from the documented accessors.

    NOT `fig.findobj(Text)`: matplotlib pools `Tick` objects per axis, and the
    unused ones keep stale label text and still report visible, which produces
    collisions with ticks that aren't on the figure. Enumerate from the
    accessors, which return only the current set.
    """
    out = list(fig.texts)
    for leg in getattr(fig, "legends", []):
        out += list(leg.get_texts())
        if leg.get_title() is not None:
            out.append(leg.get_title())
    for ax in fig.get_axes():
        if not ax.get_visible():        # hidden axes draw nothing (explainer scenes swap panels)
            continue
        out.append(ax.title)
        for attr in ("_left_title", "_right_title"):
            t = getattr(ax, attr, None)
            if t is not None:
                out.append(t)
        for axis in (ax.xaxis, ax.yaxis):
            out.append(axis.label)
            out.append(axis.get_offset_text())
            out += _live_ticklabels(axis)
        out += list(ax.texts)
        leg = ax.get_legend()
        if leg is not None and leg.get_visible():
            out += list(leg.get_texts())
            if leg.get_title() is not None:
                out.append(leg.get_title())
    return out


def _text_only_extent(t: Text, renderer):
    """The text's own ink -- excludes an `annotate(..., arrowprops=...)` arrow.

    `Annotation.get_window_extent()` unions in the arrow's bbox, and an arrow
    reaches right up to the data it labels, so every check here would see the
    label as sitting on the data. The base `Text.get_window_extent`, called on
    an `Annotation`, returns the text alone.
    """
    if getattr(t, "arrow_patch", None) is not None:
        return Text.get_window_extent(t, renderer)
    return t.get_window_extent(renderer)


def _texts(fig):
    """Every visible, non-empty drawn Text artist, with its display-space box."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    out, seen = [], set()
    for t in _collect(fig):
        if t is None or id(t) in seen:
            continue
        seen.add(id(t))
        try:
            if not t.get_visible() or not t.get_text().strip():
                continue
            if t.get_alpha() == 0:      # faded out (an animation frame): not drawn
                continue
            bb = _text_only_extent(t, renderer)
            if bb.width <= 0 or bb.height <= 0:
                continue
        except Exception:                                    # noqa: BLE001
            continue                                         # unrenderable
        out.append((t, bb))
    return out


def _label(t: Text, limit: int = 46) -> str:
    s = " ".join(t.get_text().split())
    return s[:limit] + ("…" if len(s) > limit else "")


def _crosses(iw, ih, a, b):
    """Does the intersection pierce one box across the other? See OVERLAP_CROSS_FRAC."""
    f = OVERLAP_CROSS_FRAC
    return ((iw >= f * a.width and ih >= f * b.height)
            or (iw >= f * b.width and ih >= f * a.height))


def _overlap(a, b):
    iw = min(a.x1, b.x1) - max(a.x0, b.x0)
    ih = min(a.y1, b.y1) - max(a.y0, b.y0)
    if iw <= 0 or ih <= 0:
        return None
    if iw < OVERLAP_MIN_PX or ih < OVERLAP_MIN_PX:
        return None
    frac = (iw * ih) / min(a.width * a.height, b.width * b.height)
    if frac < OVERLAP_MIN_FRAC and not _crosses(iw, ih, a, b):
        return None
    return iw, ih, frac


def _segment_clip_len(x0, y0, x1, y1, box):
    """Pixels of segment (x0,y0)-(x1,y1) inside `box` (Liang-Barsky clip); 0.0 on a miss."""
    dx, dy = x1 - x0, y1 - y0
    p = (-dx, dx, -dy, dy)
    q = (x0 - box.x0, box.x1 - x0, y0 - box.y0, box.y1 - y0)
    u0, u1 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return 0.0                    # parallel to this edge, outside it
            continue
        t = qi / pi
        if pi < 0:
            if t > u1:
                return 0.0
            u0 = max(u0, t)
        else:
            if t < u0:
                return 0.0
            u1 = min(u1, t)
    if u0 > u1:
        return 0.0
    return (u1 - u0) * (dx * dx + dy * dy) ** 0.5


def _line_hits_text(xy_disp, box):
    """Total pixels of a polyline (display coords) that fall inside `box`."""
    total = 0.0
    for i in range(len(xy_disp) - 1):
        (x0, y0), (x1, y1) = xy_disp[i], xy_disp[i + 1]
        total += _segment_clip_len(x0, y0, x1, y1, box)
    return total


def _is_full_span_reference_line(line) -> bool:
    """True for `axhline`/`axvline`: a full-panel reference marker, not data.

    Exempt from OVERLINE because it spans the whole axes by construction, so any
    caption near that value would trip it. Both helpers pin their free axis to
    [0, 1] in axes fraction via a blended transform, so this reads matplotlib's
    own construction rather than guessing from geometry.
    """
    if not isinstance(line.get_transform(), BlendedGenericTransform):
        return False
    xd, yd = line.get_xdata(), line.get_ydata()
    return ((len(xd) == 2 and tuple(xd) == (0, 1))
            or (len(yd) == 2 and tuple(yd) == (0, 1)))


def _drawn_lines(ax):
    """(transform, xy) for every Line2D in `ax` that renders an actual LINE
    (as opposed to markers-without-a-line, which `_scatter_like` already
    covers, a full-span `axhline`/`axvline` reference marker, or an
    invisible/legend-only artist)."""
    out = []
    skip = _errorbar_decoration(ax)
    for line in getattr(ax, "lines", []):
        if id(line) in skip or not line.get_visible():
            continue
        ls = line.get_linestyle()
        if ls in ("None", "none", " ", ""):
            continue
        if _is_full_span_reference_line(line):
            continue
        try:
            xy = line.get_xydata()
        except Exception:                                    # noqa: BLE001
            continue
        if xy is not None and len(xy) >= 2:
            out.append((line.get_transform(), xy))
    return out


#: How close an `annotate(..., xy=...)` anchor must sit to a line for that line
#: to count as the thing the label names, which exempts it from OVERLINE for that
#: label only. Roughly a default marker's radius plus slack.
ANCHOR_TOL_PX = 14.0


def _anchor_disp(t, ax):
    """Display-space position of an `Annotation`'s OWN `xy`, or None.

    Only data coordinates are handled -- the pattern this exists for is a value
    written at a point on a line, `ax.annotate(f"{v:.1f}", xy=(x, y), xytext=...,
    textcoords="offset points")`. Anything else returns None, and the text is
    checked against every line with no exemption.
    """
    xy = getattr(t, "xy", None)
    xycoords = getattr(t, "xycoords", "data")
    if xy is None or xycoords not in (None, "data"):
        return None
    try:
        return ax.transData.transform(xy)
    except Exception:                                        # noqa: BLE001
        return None


def _point_to_segment_dist2(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return (px - x0) ** 2 + (py - y0) ** 2
    frac = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length2))
    cx, cy = x0 + frac * dx, y0 + frac * dy
    return (px - cx) ** 2 + (py - cy) ** 2


def _point_near_polyline(pt, xy_disp, tol) -> bool:
    px, py = pt
    tol2 = tol * tol
    for i in range(len(xy_disp) - 1):
        (x0, y0), (x1, y1) = xy_disp[i], xy_disp[i + 1]
        if _point_to_segment_dist2(px, py, x0, y0, x1, y1) <= tol2:
            return True
    return False


def _data_points_in(ax, box, renderer):
    """Count data points landing inside `box`. Best-effort per artist type."""
    n = 0
    for line in getattr(ax, "lines", []):
        try:
            xy = line.get_xydata()
            if xy is None or not len(xy):
                continue
            for px, py in ax.transData.transform(xy):
                if box.x0 <= px <= box.x1 and box.y0 <= py <= box.y1:
                    n += 1
        except Exception:                                    # noqa: BLE001
            pass
    for coll in getattr(ax, "collections", []):
        try:
            off = coll.get_offsets()
            if off is None or not len(off):
                continue
            for px, py in coll.get_offset_transform().transform(off):
                if box.x0 <= px <= box.x1 and box.y0 <= py <= box.y1:
                    n += 1
        except Exception:                                    # noqa: BLE001
            pass
    for patch in getattr(ax, "patches", []):
        try:
            pb = patch.get_window_extent(renderer)
            if pb.overlaps(box):
                n += 1
        except Exception:                                    # noqa: BLE001
            pass
    return n


def _is_background_patch(patch, pb, ax_w, ax_h):
    """Is this patch a shaded band rather than a data mark?

    Geometry alone cannot tell them apart: `ax.bar` with bars reaching the top of
    the axes renders exactly like an `axvspan`, and both are `Rectangle` with a
    composite transform, so neither type nor extent discriminates.

    What does: an `axhspan`/`axvspan` is pinned to the AXES in its spanning
    direction, so its own untransformed bbox runs 0..1 there (axes fraction),
    while a bar's comes from the data and runs 0..height:

        axvspan  Bbox(x0=2.0, y0=0.0, x1=3.0, y1=1.0)     <- y pinned
        bar      Bbox(x0=1.6, y0=0.0, x1=2.4, y1=3.0)     <- y is data

    Both the pinning AND a full-extent render are required, so a data patch that
    happens to sit in 0..1 is not exempted unless it also spans the axes.

    Edge case: a bar of height exactly 1.0 on ylim (0, 1) is treated as
    background. Harmless -- the point rule still applies.
    """
    if ax_w > 0 and pb.width >= BACKGROUND_PATCH_FRAC * ax_w:
        return True                      # axhspan, or any full-width band
    try:
        own = patch.get_bbox()
    except Exception:                                        # noqa: BLE001
        return False
    tol = 1e-9
    y_pinned = abs(own.y0) < tol and abs(own.y1 - 1.0) < tol
    x_pinned = abs(own.x0) < tol and abs(own.x1 - 1.0) < tol
    if y_pinned and ax_h > 0 and pb.height >= BACKGROUND_PATCH_FRAC * ax_h:
        return True                      # axvspan
    if x_pinned and ax_w > 0 and pb.width >= BACKGROUND_PATCH_FRAC * ax_w:
        return True
    return False


def _patch_cover(ax, box, renderer):
    """Fraction of `box` covered by non-background patches (bars, boxes, wedges).

    Background bands (see `_is_background_patch`) are skipped.
    """
    if box.width <= 0 or box.height <= 0:
        return 0.0
    try:
        ax_box = ax.get_window_extent(renderer)
        ax_w, ax_h = ax_box.width, ax_box.height
    except Exception:                                        # noqa: BLE001
        return 0.0
    covered = 0.0
    for patch in getattr(ax, "patches", []):
        try:
            pb = patch.get_window_extent(renderer)
            if _is_background_patch(patch, pb, ax_w, ax_h):
                continue                                     # background band
            iw = min(pb.x1, box.x1) - max(pb.x0, box.x0)
            ih = min(pb.y1, box.y1) - max(pb.y0, box.y0)
            if iw > 0 and ih > 0:
                covered += iw * ih
        except Exception:                                    # noqa: BLE001
            pass
    return min(1.0, covered / (box.width * box.height))


def _errorbar_decoration(ax):
    """ids of artists that are error-bar decoration, not data marks.

    An `errorbar` call adds cap Line2Ds (markers-only, so `_scatter_like` would
    count them) and LineCollections whose default offsets are a single [0, 0]
    (a phantom mark at the origin, often CLIPPED). Excluding them keeps the
    reported counts matching what a reader can count.
    """
    from matplotlib.container import ErrorbarContainer

    skip = set()
    for cont in getattr(ax, "containers", []):
        if not isinstance(cont, ErrorbarContainer):
            continue
        try:
            _dataline, caps, bars = cont.lines
        except (ValueError, TypeError):                      # noqa: PERF203
            continue
        for group in (caps or (), bars or ()):
            for art in group:
                skip.add(id(art))
    return skip


def _scatter_like(ax):
    """Artists whose marks are individually meaningful, as (transform, points).

    Line2D is included ONLY when it is markers-without-a-line, i.e. a scatter
    drawn through `ax.plot(x, y, "o")`. A real line's vertices are not marks: a
    model curve running off the axes is normal, and counting it would make
    CLIPPED fire on almost every figure.
    """
    skip = _errorbar_decoration(ax)
    out = []
    for line in getattr(ax, "lines", []):
        if id(line) in skip:
            continue
        ls = line.get_linestyle()
        mk = line.get_marker()
        if ls in ("None", "none", " ", "") and mk not in (None, "None", "", " "):
            xy = line.get_xydata()
            if xy is not None and len(xy):
                out.append((ax.transData, xy))
    for coll in getattr(ax, "collections", []):
        if id(coll) in skip:
            continue
        try:
            off = coll.get_offsets()
        except Exception:                                    # noqa: BLE001
            continue
        if off is not None and len(off):
            out.append((coll.get_offset_transform(), off))
    return out


def _axes_mark_count(ax):
    """How many individual data marks this axes holds. Denominator for the
    relative OVERDATA and CLIPPED thresholds."""
    return sum(len(pts) for _tr, pts in _scatter_like(ax))


def _overdata_threshold(n_marks):
    """Marks-under-text at which OVERDATA fires, given the axes' own density.

    Relative with a floor and a cap: a flat count can't fire on a typical
    ~200-point panel, where a text box covers fewer than 20 marks wherever it sits.
    """
    if n_marks <= 0:
        return OVERDATA_MIN_POINTS
    rel = max(OVERDATA_MIN_POINTS_FLOOR, round(OVERDATA_MIN_FRAC * n_marks))
    return int(min(OVERDATA_MIN_POINTS, rel))


def _has_opaque_bbox(t: Text) -> bool:
    """True if this text carries a backing patch opaque enough to count as fixed
    (the remedy OVERDATA/OVERLINE suggest)."""
    patch = t.get_bbox_patch()
    if patch is None:
        return False
    try:
        alpha = patch.get_alpha()
        if alpha is None:
            fc = patch.get_facecolor()
            alpha = fc[3] if fc is not None and len(fc) == 4 else 0.0
        return float(alpha) >= OVERDATA_BBOX_ALPHA
    except Exception:                                        # noqa: BLE001
        return False


def _clipped_marks(ax):
    """(n_outside, n_total) for data marks outside this axes' current limits.

    Uses the limits rather than the rendered bbox: a mark outside x/ylim is not
    drawn at all, which is the failure worth catching. Inverted axes are handled
    by sorting the limits.
    """
    x0, x1 = sorted(ax.get_xlim())
    y0, y1 = sorted(ax.get_ylim())
    n_out = n_tot = 0
    for _tr, pts in _scatter_like(ax):
        for px, py in pts:
            if px != px or py != py:                         # NaN placeholder
                continue
            n_tot += 1
            if px < x0 or px > x1 or py < y0 or py > y1:
                n_out += 1
    return n_out, n_tot


def _in_axes_texts(fig):
    """(ax, text) for every visible in-axes annotation, excluding legend text.

    Titles, axis labels and tick labels are excluded because they live outside
    the data area by construction -- including them would report nothing and
    cost a transform per artist. Legend text has its own dedicated check.
    """
    out = []
    for ax in fig.get_axes():
        leg = ax.get_legend()
        skip = set()
        if leg is not None:
            skip = {id(t) for t in leg.get_texts()}
            if leg.get_title() is not None:
                skip.add(id(leg.get_title()))
        for t in getattr(ax, "texts", []):
            if id(t) not in skip and t.get_visible() and t.get_text().strip():
                out.append((ax, t))
    return out


def _hex(rgba) -> str:
    r, g, b, _a = rgba
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def _artist_color(handle):
    """The one colour a legend swatch reads as, or None if it has none/varies.

    A marker-only Line2D (e.g. a scatter legend proxy,
    `Line2D([], [], marker="o", ls="", mfc=colour)`) draws no line, so its
    `get_color()` is the unset "C0" placeholder, not what's visible. Read the
    marker colour instead, using the same marker-only test as `_scatter_like`.
    """
    try:
        if isinstance(handle, Line2D):
            ls = handle.get_linestyle()
            if ls in ("None", "none", " ", ""):
                c = handle.get_markerfacecolor()
                if c in (None, "none", "None"):
                    c = handle.get_markeredgecolor()
            else:
                c = handle.get_color()
        elif hasattr(handle, "get_facecolor"):
            c = handle.get_facecolor()
        else:
            return None
        return tuple(round(v, 3) for v in matplotlib.colors.to_rgba(c))
    except (ValueError, TypeError):
        return None                                          # e.g. an Nx4 array


def _legend_color_labels(fig):
    """(colour, label, axes-index) for every legend swatch in the figure."""
    out = []
    for i, ax in enumerate(fig.get_axes()):
        leg = ax.get_legend()
        if leg is None or not leg.get_visible():
            continue
        handles = getattr(leg, "legend_handles", None)
        if handles is None:
            handles = getattr(leg, "legendHandles", [])       # matplotlib < 3.7
        for h, t in zip(handles, leg.get_texts()):
            color = _artist_color(h)
            label = t.get_text().strip()
            if color is not None and label:
                out.append((color, label, i))
    return out


def check(fig, min_pt: float = MIN_PT, slide=SLIDE_IN,
          check_legend: bool = True, crops: bool = True,
          check_overdata: bool = True, check_clipped: bool = True,
          check_overline: bool = True,
          check_color_roles: bool = CHECK_COLOR_ROLES_DEFAULT) -> list[Finding]:
    """Return layout findings for `fig`. Prints nothing, raises nothing.

    `crops=False` when the figure is saved with `bbox_inches="tight"`: savefig
    then EXPANDS the output to include overhanging text instead of cutting it,
    so OUTSIDE is not a defect and reporting it is a false positive. `install()`
    detects this from savefig's own kwargs; a script calling `check`/`report`
    directly has to say so. The tight bbox is also the real output size, so it
    is used for the slide scale when available.
    """
    found: list[Finding] = []
    items = _texts(fig)
    canvas = fig.bbox

    for t, bb in (items if crops else []):
        if (bb.x0 < canvas.x0 - EDGE_SLACK_PX or bb.x1 > canvas.x1 + EDGE_SLACK_PX
                or bb.y0 < canvas.y0 - EDGE_SLACK_PX
                or bb.y1 > canvas.y1 + EDGE_SLACK_PX):
            found.append(Finding(
                "OUTSIDE", _label(t),
                f"box x {bb.x0:.0f}..{bb.x1:.0f} y {bb.y0:.0f}..{bb.y1:.0f} "
                f"vs canvas {canvas.x1:.0f}x{canvas.y1:.0f} — savefig will crop it"))

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            ov = _overlap(items[i][1], items[j][1])
            if ov:
                iw, ih, frac = ov
                found.append(Finding(
                    "OVERLAP", f"{_label(items[i][0], 30)!r} × {_label(items[j][0], 30)!r}",
                    f"{iw:.0f}×{ih:.0f} px, {100 * frac:.0f}% of the smaller box"))

    w_in, h_in = fig.get_size_inches()
    if not crops:                       # tight save: the OUTPUT is what scales
        declared_w, declared_h = w_in, h_in
        try:
            tb = fig.get_tightbbox(fig.canvas.get_renderer())
        except Exception:                                    # noqa: BLE001
            tb = None
        if tb is not None:
            w_in, h_in = max(w_in, tb.width), max(h_in, tb.height)
            grow = max(w_in / declared_w if declared_w else 1.0,
                       h_in / declared_h if declared_h else 1.0)
            if grow >= EXPAND_MIN_FRAC:
                overhang = sorted(
                    (t for t, bb in items
                     if bb.x0 < canvas.x0 - EDGE_SLACK_PX
                     or bb.x1 > canvas.x1 + EDGE_SLACK_PX
                     or bb.y0 < canvas.y0 - EDGE_SLACK_PX
                     or bb.y1 > canvas.y1 + EDGE_SLACK_PX),
                    key=lambda t: -t.get_fontsize())
                cause = f" — likely cause: {_label(overhang[0])!r}" if overhang else ""
                found.append(Finding(
                    "EXPANDED",
                    f"tight bbox grew the canvas {grow:.2f}× past the declared figsize",
                    f"declared {declared_w:.1f}×{declared_h:.1f}in, tight bbox needs "
                    f"{w_in:.1f}×{h_in:.1f}in{cause} — this is why SMALL fires below: "
                    f"overhanging text expands bbox_inches=\"tight\" instead of being "
                    f"cropped, which shrinks the slide scale for every label. Wrap or "
                    f"shorten the text rather than letting the canvas absorb it"))
    scale = min(slide[0] / w_in, slide[1] / h_in)
    small = sorted(((t, bb) for t, bb in items
                    if t.get_fontsize() * scale < min_pt),
                   key=lambda p: p[0].get_fontsize())
    for t, _ in small[:SHOW_PER_KIND]:
        found.append(Finding(
            "SMALL", _label(t),
            f"{t.get_fontsize():.0f}pt × {scale:.2f} slide scale = "
            f"{t.get_fontsize() * scale:.1f}pt (floor {min_pt:g})"))
    if len(small) > SHOW_PER_KIND:
        found.append(Finding("SMALL", f"… and {len(small) - SHOW_PER_KIND} more",
                             f"{len(small)} of {len(items)} text artists"))

    if check_legend:
        renderer = fig.canvas.get_renderer()
        for ax in fig.get_axes():
            leg = ax.get_legend()
            if leg is None or not leg.get_visible():
                continue
            try:
                box = leg.get_window_extent(renderer)
            except Exception:                                # noqa: BLE001
                continue
            n = _data_points_in(ax, box, renderer)
            if n >= LEGEND_MIN_POINTS:
                found.append(Finding(
                    "LEGEND", f"legend on {ax.get_title() or 'axes'!r}"[:60],
                    f"{n} data points fall inside the legend box — move it, or "
                    f"use loc='best' / bbox_to_anchor"))

    if check_overdata:
        renderer = fig.canvas.get_renderer()
        for ax, t in _in_axes_texts(fig):
            try:
                box = _text_only_extent(t, renderer)
            except Exception:                                # noqa: BLE001
                continue
            if box.width <= 0 or box.height <= 0:
                continue
            if _has_opaque_bbox(t):
                continue                                     # already remediated
            n = _data_points_in(ax, box, renderer)
            cover = _patch_cover(ax, box, renderer)
            limit = _overdata_threshold(_axes_mark_count(ax))
            if n >= limit:
                found.append(Finding(
                    "OVERDATA", _label(t),
                    f"{n} data marks fall under this text (fires at {limit} for "
                    f"an axes with {_axes_mark_count(ax)} marks) — move it, or "
                    f"give it a bbox at least {OVERDATA_BBOX_ALPHA:g} opaque"))
            elif cover >= OVERDATA_MIN_COVER:
                found.append(Finding(
                    "OVERDATA", _label(t),
                    f"{100 * cover:.0f}% of this text's box is covered by bars — "
                    f"move it, or give it an opaque bbox"))

    if check_overline:
        renderer = fig.canvas.get_renderer()
        for ax, t in _in_axes_texts(fig):
            try:
                box = _text_only_extent(t, renderer)
            except Exception:                                # noqa: BLE001
                continue
            if box.width <= 0 or box.height <= 0 or _has_opaque_bbox(t):
                continue                                     # remediated
            anchor = _anchor_disp(t, ax)
            worst = 0.0
            for transform, xy in _drawn_lines(ax):
                try:
                    xy_disp = transform.transform(xy)
                except Exception:                             # noqa: BLE001
                    continue
                if anchor is not None and _point_near_polyline(anchor, xy_disp, ANCHOR_TOL_PX):
                    continue                # labelling THIS line at its own xy, not a collision
                worst = max(worst, _line_hits_text(xy_disp, box))
            if worst >= OVERLINE_MIN_PX:
                found.append(Finding(
                    "OVERLINE", _label(t),
                    f"a plotted line runs under this text for {worst:.0f}px — "
                    f"move the label off the curve, or give it an opaque bbox "
                    f"(OVERDATA does not see plain lines, only markers and bars)"))

    if check_clipped:
        for ax in fig.get_axes():
            if ax.get_gid() == CLIP_OK_GID:
                continue                     # declared deliberate, see CLIP_OK_GID
            n_out, n_tot = _clipped_marks(ax)
            if not n_tot or n_out < CLIPPED_MIN_POINTS:
                continue
            if n_out / n_tot < CLIPPED_MIN_FRAC:
                continue
            found.append(Finding(
                "CLIPPED", (ax.get_title() or ax.get_ylabel() or "axes")[:46],
                f"{n_out} of {n_tot} data marks fall OUTSIDE the axes limits and "
                f"are not drawn — widen the limits, draw them at the edge as "
                f"bounds, or pass check_clipped=False if the zoom is deliberate"))

    if check_color_roles:
        by_color: dict = {}
        for color, label, _ax_i in _legend_color_labels(fig):
            by_color.setdefault(color, set()).add(label)
        for color, labels in by_color.items():
            if len(labels) > 1:
                found.append(Finding(
                    "COLORROLE", f"{_hex(color)} means {len(labels)} different things",
                    f"used for: {', '.join(sorted(labels))} — one colour, one role "
                    f"per figure, or the reader has to relearn the legend per panel"))
    return found


def report(fig, prefix: str = "", **kw) -> int:
    """Print findings. Returns how many there were (0 == clean)."""
    found = check(fig, **kw)
    w_in, h_in = fig.get_size_inches()
    head = f"{prefix}figure {w_in:.1f}×{h_in:.1f}in"
    if not found:
        print(f"{head}: layout clean")
        return 0
    print(f"{head}: {len(found)} issue(s)")
    # CLIPPED first: it is the only kind that reports MISSING data. Every kind
    # must be listed here, or its findings count toward the total but never print.
    for kind in ("CLIPPED", "OUTSIDE", "OVERLAP", "OVERLINE", "EXPANDED", "SMALL",
                 "LEGEND", "OVERDATA", "COLORROLE"):
        for f in (f for f in found if f.kind == kind):
            print(f"  {f}")
    return len(found)


def require(fig, **kw) -> None:
    """Raise if the layout is broken. For scripts that should not ship a bad
    figure -- the analogue of check_layout.py's non-zero exit."""
    found = check(fig, **kw)
    if found:
        raise AssertionError(
            f"{len(found)} layout issue(s):\n"
            + "\n".join(f"  {f}" for f in found))


def install(**kw) -> None:
    """Monkeypatch `Figure.savefig` to report before every save.

    For auditing scripts without editing them. Deliberately reports rather than
    raises: a sweep over existing figures should surface everything, not stop at
    the first one.

    Also records every filename actually saved, on `Figure.savefig._saves` --
    see `_main`'s stale-output warning below.
    """
    from matplotlib.figure import Figure
    if getattr(Figure.savefig, "_figcheck", False):
        return
    orig = Figure.savefig
    saves: list = []

    def patched(self, fname, *a, **k):
        bbox = k.get("bbox_inches", matplotlib.rcParams.get("savefig.bbox"))
        try:
            report(self, prefix=f"[{getattr(fname, 'name', fname)}] ",
                   crops=(bbox != "tight"), **kw)
        except Exception as e:                               # noqa: BLE001
            print(f"[figcheck] skipped: {e}")
        result = orig(self, fname, *a, **k)
        saves.append(fname)
        return result

    patched._figcheck = True
    patched._saves = saves
    Figure.savefig = patched


def _main(argv) -> int:
    """Run `script` under the savefig hook, then warn if it never saved.

    A script that dies before its first `savefig` leaves the previous run's
    output on disk looking fresh, so the absence of a save is made explicit.
    """
    if len(argv) < 2:
        print(__doc__.strip())
        return 2
    matplotlib.use("Agg")
    install()
    from matplotlib.figure import Figure
    saves = Figure.savefig._saves
    script, sys.argv = argv[1], argv[1:]
    try:
        runpy.run_path(script, run_name="__main__")
    finally:
        if not saves:
            print(f"[figcheck] WARNING: {script} exited without calling savefig -- "
                  f"any existing PNG/SVG for this script is STALE, left over from a "
                  f"previous successful run, not this one.")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))

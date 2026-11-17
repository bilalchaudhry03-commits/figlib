"""Layout linter for matplotlib figures. The chart-side counterpart to
`~/.claude/skills/scientific-figure-design/scripts/check_layout.py`.

WHY THIS EXISTS
---------------
Measured 2026-08-05: three figures in one session cost 13 render-look-patch
iterations, and 7 of those were matplotlib -- legend sitting on the data,
clipped subtitles, a footnote overrunning the axis labels, a y-label off the
canvas. Every one was detectable from the figure object. The HTML schematics got
a linter the same day; this is the half that was still missing.

WHY IT IS A LIBRARY AND NOT A CLI OVER FILES
--------------------------------------------
An HTML figure is a file you can load and measure. A matplotlib figure exists
only while its script is running -- once it is a PNG the text positions are
gone, and no amount of looking at the image recovers them. So the check has to
run IN-PROCESS, against the live `Figure`, before `savefig`. Two ways in:

    from figlib import figcheck
    figcheck.check(fig)                     # returns findings, prints nothing
    figcheck.report(fig)                    # prints them, returns the count
    figcheck.require(fig)                   # raises if anything is wrong

and, for auditing scripts you do not want to edit:

    python3 -m figlib.figcheck path/to/plotting_script.py

which installs a `savefig` hook and runs the script unmodified.

WHAT IT CHECKS
--------------
  OVERLAP     two text artists' boxes intersect. Catches crowded tick labels,
              a title running into a subtitle, an annotation landing on a
              label. Tolerances are loose on purpose (see OVERLAP_MIN_*) --
              a linter that cries wolf gets ignored. Two acceptance rules, and
              the second exists because the first has a blind spot: an
              intersection counts if it covers OVERLAP_MIN_FRAC of the smaller
              box, OR if it is a perpendicular CROSSING (see OVERLAP_CROSS_FRAC).

  OUTSIDE     a text box extends past the figure canvas. This is the one that
              survives review, because `savefig` silently crops it and the
              missing words are invisible in the PNG unless you knew to look.

  SMALL TYPE  a font that renders below `min_pt` ONCE THE FIGURE IS PLACED ON A
              SLIDE. This is the check with teeth: matplotlib sizes are real
              points, so an 8pt annotation looks fine -- but an 18.4in-wide
              figure dropped on a 13.333in slide is scaled by 0.72x and that
              annotation lands at 5.8pt. Wide multi-panel figures are exactly
              where this bites and exactly where nobody thinks to check.

  LEGEND      data points falling inside the legend's box. Conservative: it
              flags only when a real number of points are covered, because a
              legend clipping one marker is usually fine and a legend sitting
              on the distribution is not.

  OVERDATA    an in-axes text artist sitting on real data marks. ON by default
              since 2026-08-17 -- see below, the threshold used to make it
              unable to fire on a normal-sized panel.

  OVERLINE    an in-axes text artist sitting on a plotted LINE (a curve, not
              markers). OVERDATA's mark-counting is blind to this: a plain
              `ax.plot` line has no markers to count and is not a patch, so a
              label parked directly on a curve linted clean. Added 2026-09-09
              after three such misses in one session -- a MOR-curve label, a
              staircase decomposition label, and a third caption -- all
              visibly on top of their line and all reported clean. Tests each
              text box against the line's own path in display coordinates
              (Liang-Barsky segment clipping); ON by default since the miss
              rate today was 3-for-3, not a rare edge case.

              **Exempts a label from the very thing it names.** A repo-wide
              sweep the same day found this house pattern dominates the hit
              count: `ax.annotate(f"{v:.1f}", xy=(x, y), xytext=(dx, dy),
              textcoords="offset points")`, writing a value at the exact point
              on a bracket/rung/threshold line it is reporting -- by
              construction as close to that line as a label can get, and nothing
              like the accidental case OVERLINE exists for. `_anchor_disp` reads
              the annotation's own `xy`; if it sits within `ANCHOR_TOL_PX` of a
              given line, that line is exempted for THAT text only -- a
              collision with any OTHER, unrelated line still fires.

              **Also exempts `axhline`/`axvline`.** The same sweep found a
              second dominant pattern: a full-panel threshold or context
              marker, drawn once and captioned nearby, trips OVERLINE on every
              label anywhere near that value -- it spans the whole axes by
              construction, not because a real measurement runs there. Both
              helpers pin their one free axis to axes-fraction [0, 1] via a
              blended transform, so `_is_full_span_reference_line` detects them
              exactly rather than by guessing from geometry (mirrors
              `_is_background_patch`'s treatment of `axhspan`/`axvspan` for
              OVERDATA).

  EXPANDED    a `bbox_inches="tight"` save grows the canvas past the declared
              `figsize` (see SMALL above: the slide scale is `slide_width /
              canvas_width`, so a bigger canvas silently shrinks every label).
              Added 2026-09-09 after the same mistake landed twice in one
              session -- SMALL reported the *symptom* (small type) both times
              and the cause (an overhanging `fig.text` expanding the tight
              bbox) had to be rediscovered from scratch. `figcheck` already
              computed `get_tightbbox` for the slide-scale math; this just
              keeps the comparison to the declared size instead of discarding
              it.

  CLIPPED     DATA MARKS drawn outside the axes' own limits, i.e. points that
              are simply not in the figure. **This is the only check here that
              visual review cannot replace**: every other finding is something
              you could see by looking at a zoomed crop, and this one is the
              absence of something. Added 2026-08-17 after a figure passed clean
              while silently dropping 27 of 179 points off the bottom of a log
              axis -- and they were the largest proteins in the set, i.e. exactly
              the data the panel existed to discuss.

  COLORROLE   OPT-IN (`check_color_roles=True`), unlike everything else here.
              Warns when one legend colour backs two different labels across
              the figure's axes -- caught by hand 2026-09-09 after shipping a
              figure where green and blue each meant different things in two
              panels. `palette.py` validates CVD separation, not semantics, so
              nothing else checks this. Off by default because a genuinely
              shared role (e.g. one colour always means "control") is common
              and correct, so this check will cry wolf more than the others;
              turn it on for a specific figure rather than globally.

AN ANNOTATION ARROW IS NOT PART OF THE LABEL, FOUND 2026-09-09
----------------------------------------------------------------
Cross-cutting, not one check: `Annotation.get_window_extent()` -- matplotlib's
own method, called by every check above through `_texts()`/`_in_axes_texts()`
-- UNIONS the arrow patch's bbox into whatever it returns, because that keeps
`bbox_inches="tight"` from clipping the arrow. An annotation arrow is DESIGNED
to reach from its caption to the data point it names, so that union makes an
`ax.annotate(..., arrowprops=...)` label's reported footprint include its
entire reach toward the data -- exactly the region OVERLINE and OVERDATA exist
to compare it against.

Found chasing an OVERLINE hit a screenshot could not confirm: a two-line
callout on `20260909_fig_caliper_staircase_v2.py` sat well clear of the curve
it was near, on-screen, but its `get_window_extent()` ran all the way up to
the curve because the box also covered the leader line pointing at it, not
the caption itself. `_text_only_extent()` fixes it at the source -- one place,
`_texts()`, used by everything else -- via the un-overridden base method
`Text.get_window_extent(t, renderer)`, which excludes `arrow_patch` if that
Text happens to be an `Annotation` carrying one. Since this can only SHRINK a
box that was previously too generous, it strictly removes false positives; it
cannot introduce new findings anywhere in the file.

TEXT OVER DATA: OPT-IN 2026-08-13, ON BY DEFAULT 2026-08-17
-----------------------------------------------------------
The opt-in version could not fire on this repo's figures, and that was measured
rather than argued. `OVERDATA_MIN_POINTS` was an ABSOLUTE count of 20 marks,
calibrated for dense scatter. On a 179-point panel a text box covers at most ~18
marks no matter where you put it:

    the label that shipped over the cloud, 2026-08-17     17 marks   silent
    a label parked in the DENSEST part of the same panel  18 marks   silent

So the check was not merely off by default, it was inapplicable to figures of
the size this repo actually draws. Two changes make it usable, and they had to
land together:

  * the threshold is now RELATIVE -- `OVERDATA_MIN_FRAC` of the axes' own marks,
    floored at `OVERDATA_MIN_POINTS_FLOOR` and capped at the old absolute
    `OVERDATA_MIN_POINTS`. A 179-point panel fires at 9; a 5,000-point scatter
    still fires at 20.
  * the check now HONOURS ITS OWN ADVICE. Its message said "move it, or give it
    an opaque bbox" while nothing inspected whether you had, so lowering the
    threshold alone would have flagged every correctly-backed label as a fault.
    A text whose bbox patch is at least `OVERDATA_BBOX_ALPHA` opaque is now
    treated as remediated.

Patch COVERAGE (a bar chart's bars covering `OVERDATA_MIN_COVER` of the box) is
unchanged. Full-width patches are background shading and ignored, so an
`axhspan` with a label in it stays silent.

Pure stdlib + matplotlib. No numpy import at module level, so it stays usable
from `envs/geometric` as well as `envs/analysis`.
"""
from __future__ import annotations

import runpy
import sys
from dataclasses import dataclass

import matplotlib
from matplotlib.lines import Line2D
from matplotlib.text import Text
from matplotlib.transforms import BlendedGenericTransform

#: An intersection must be at least this many display pixels in BOTH axes and
#: cover this fraction of the smaller box before it counts. Tuned so the
#: 2026-08-05 figures' deliberately-tight stat blocks pass clean.
OVERLAP_MIN_PX = 3.0
OVERLAP_MIN_FRAC = 0.15

#: Second acceptance rule for OVERLAP, added 2026-08-13 to close a real blind
#: spot in the first. `OVERLAP_MIN_FRAC` divides the intersection by the SMALLER
#: BOX'S AREA, which systematically under-reports a long thin box crossing a
#: short wide one: a rotated 90° panel label piercing a panel title covers 100%
#: of the title's HEIGHT and only ~7% of the label's area, so it passed clean
#: while being plainly wrong on screen (found on
#: `passive_diffusion/figures/20260813_nls_vs_deviation.png`, where the linter
#: said "layout clean" and visual review did not).
#:
#: A crossing is the case where the intersection spans essentially the full
#: width of one box AND the full height of the other -- a plus-shape. That is
#: geometrically distinct from the tight-adjacency case the area rule was tuned
#: to allow, where two stacked lines of a stat block graze by a pixel: there the
#: intersection spans one box's width but nothing like either box's height.
OVERLAP_CROSS_FRAC = 0.8

#: Points of slack before a box counts as off-canvas. savefig crops at exactly
#: the canvas edge, so anything past it really is lost.
EDGE_SLACK_PX = 1.0

#: Data points inside the legend box before it is worth reporting.
LEGEND_MIN_POINTS = 20

#: OVERDATA thresholds (opt-in check; see the module docstring). Points reuses
#: the LEGEND figure because it is the same measurement on the same units and
#: that threshold is already trusted. Coverage is the bar-chart route: patch
#: count is not comparable to point count (two bars under a label is a real
#: collision; two points is not), so patches are judged by the fraction of the
#: text box they cover instead.
OVERDATA_MIN_POINTS = 20

#: The relative rule, added 2026-08-17. The absolute count above is a CAP, not
#: the trigger: a text box covering this fraction of an axes' own marks is a
#: collision whether that axes holds 40 points or 4,000. Floored so a 12-point
#: panel does not fire on one grazed marker.
OVERDATA_MIN_FRAC = 0.05
OVERDATA_MIN_POINTS_FLOOR = 4

#: A text bbox at least this opaque counts as the documented remedy rather than
#: as a fault. Set below 1.0 on purpose: 0.8-0.9 white backing is the honest fix
#: for a label over a faint background layer -- the marks stay visible around the
#: text -- and demanding full opacity would push authors toward hiding data.
OVERDATA_BBOX_ALPHA = 0.75

OVERDATA_MIN_COVER = 0.35

#: CLIPPED fires when at least this many marks, AND this fraction of the axes'
#: marks, fall outside the limits. Both, so a curve's endpoint leaving the view
#: is silent and a dropped tail is not.
CLIPPED_MIN_POINTS = 3
CLIPPED_MIN_FRAC = 0.02

#: Per-AXES opt-out for CLIPPED, via `ax.set_gid(CLIP_OK_GID)`.
#:
#: `check_clipped=False` is the whole-figure switch and it is too blunt for the
#: common honest case: a multi-panel figure where one panel is a deliberate
#: window and its neighbour carries the full range
#: (`20260805_relaxation_time_vs_radius` panel A is linear 0-14 h, panel B is log
#: 5e-3 to 2e5). Switching the figure off would also stop the check on the panel
#: that is not zoomed. A gid on the specific axes is a DECLARATION in the script,
#: greppable and reviewable, rather than a silence.
CLIP_OK_GID = "figcheck:clip-ok"

#: OVERLINE fires when a text box crosses a plotted LINE (not a marker, not a
#: patch) for at least this many display pixels. Added 2026-09-09: a plain
#: `ax.plot(x, y)` curve is invisible to OVERDATA, which only counts markers
#: (`_scatter_like` deliberately excludes marker-less lines, since a model
#: curve's own vertices running off-axes is normal) and to patch coverage. A
#: label sitting directly on a curve therefore linted clean while being
#: visibly wrong -- three times in one session (a MOR-curve label, a staircase
#: decomposition label, a "other three fixes" label). Small on purpose, the
#: same reasoning as OVERLAP_MIN_PX: big enough to reject a corner graze,
#: small enough to catch a real crossing.
OVERLINE_MIN_PX = 3.0

#: COLORROLE is opt-in (`check_color_roles=True`), unlike every other check
#: here. It compares legend swatch colours across axes in one figure and warns
#: when the same colour backs two different labels -- caught 2026-09-09 after
#: shipping a figure with green/blue meaning different things in two panels.
#: Left off by default: `palette.py` validates CVD separation rigorously and
#: says nothing about SEMANTICS, and a genuinely reused colour (e.g. a shared
#: "control" role across panels) is often correct, not a bug -- this is the
#: one check here likely to cry wolf, so it stays a deliberate opt-in rather
#: than something that has to be silenced per figure.
CHECK_COLOR_ROLES_DEFAULT = False

#: A patch spanning at least this fraction of the axes is background shading
#: (axhspan/axvspan/fill_between), not a data mark. Labelling a shaded band is
#: normal and must not be reported.
#:
#: `axvspan` was missed until 2026-08-17: this rule tested WIDTH only, so a
#: full-height vertical band -- narrow by construction -- scored as a bar, and
#: six labels inside one `axvspan` were reported as covered "by bars" the first
#: time OVERDATA ran by default. Widening it to "either direction" then exempted
#: real bar charts whose bars reach the top of the axes, which is why the rule
#: below also asks HOW the patch is pinned. See `_is_background_patch`.
BACKGROUND_PATCH_FRAC = 0.9

#: EXPANDED fires when `bbox_inches="tight"` grows the canvas at least this
#: much past the declared `figsize`. A tight save always differs a little (axis
#: labels, tick padding), so this is set above that noise floor and tuned to
#: the actual measured cases: 14.6->19.98in (1.37x) and 14.6->15.7in (1.08x),
#: both driven by one overhanging `fig.text` call. See EXPANDED below.
EXPAND_MIN_FRAC = 1.05

#: Default target slide, inches (16:9 widescreen).
SLIDE_IN = (13.333, 7.5)

#: Below this, projected text is not readable from the back of a room. The
#: house skill asks for 11pt body; 7 is the floor at which it is simply broken.
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

    `get_xticklabels()` returns a label for every locator tick, including ticks
    outside the current view limits. Those are culled at draw time but still
    report a `get_window_extent()`, placed off the end of the axis -- which is
    how a y-tick at 1.2 on an axis limited to (0.38, 1.02) was reported both as
    running off the canvas and as colliding with a real x-tick 15 times over.
    Filter on the view interval, which is what the draw pass uses.
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

    NOT `fig.findobj(Text)`. matplotlib keeps a POOL of `Tick` objects per axis
    and reuses it across formatter changes; the unused ones keep stale label
    text and still report `get_visible() == True`. On the 08-05 gate matrix that
    produced 15 confident OVERLAP reports between a real '0.0' x-tick and a
    '1.2' y-tick that does not exist on the figure at all -- a linter reporting
    collisions between phantom artists is worse than no linter. `get_xticklabels
    ()` and friends return only the current set, so enumerate from those.
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

    `Annotation.get_window_extent()` UNIONS the arrow patch's bbox into its
    return value (so `bbox_inches="tight"` does not clip the arrow). Every
    check here wants where the READABLE TEXT sits, not the arrow: an
    annotation arrow is designed to reach right up to the data point it is
    labelling, so leaving the union in makes the label's reported footprint
    include that entire reach. Found 2026-09-09 chasing an OVERLINE hit a
    screenshot could not confirm -- a callout's two-line caption sat well
    clear of a plotted curve, but its `get_window_extent()` ran all the way
    up to the curve because the box also covered the leader line pointing at
    it. `Text.get_window_extent` (the un-overridden base method) is the fix:
    called on an `Annotation` instance it returns the text alone.
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
    """Does the intersection pierce one box across the other's full extent?

    See OVERLAP_CROSS_FRAC. True when the intersection spans essentially all of
    one box's width and all of the other's height -- the rotated-label-through-
    a-title case, which the area rule cannot see.
    """
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
    """Liang-Barsky clip: how many pixels of segment (x0,y0)-(x1,y1) fall
    inside `box`, or 0.0 if it misses entirely. Standard parametric clip --
    walk the four half-plane tests and narrow the surviving `t` range."""
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
    """True for `axhline`/`axvline` (and anything built the same way): a
    full-PANEL threshold or context marker, not data.

    Same reasoning as `_is_background_patch` for `axhspan`/`axvspan`, and the
    test is exactly as mechanical: both matplotlib helpers hard-code their one
    free axis to the placeholder range [0, 1] in AXES-FRACTION coordinates via
    a blended transform (one axis `transAxes`, the other `transData`), so this
    reads matplotlib's own construction rather than guessing from geometry.
    Found 2026-09-09 sweeping the repo for OVERLINE hits: an `axhline`
    reference threshold spans the whole axes by construction, so ANY caption
    placed near that value reads as "a curve runs under this text" when what
    actually ran under it was a context marker, never a measurement.
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


#: How close an `annotate(..., xy=...)` anchor must sit to a line before that
#: line counts as "the thing this label names" rather than an accidental
#: collision -- see `_anchor_disp` and OVERLINE below. Set to roughly a
#: default marker's radius plus a little slack.
ANCHOR_TOL_PX = 14.0


def _anchor_disp(t, ax):
    """Display-space position of an `Annotation`'s OWN `xy`, or None.

    Only handles the default case (`xycoords` unset or `"data"`) -- the common
    house pattern this exists for is `ax.annotate(f"{value:.1f}", xy=(x, y),
    xytext=(dx, dy), textcoords="offset points")`, i.e. a value written at a
    specific point with a small pixel nudge. Anything else (axes-fraction
    coords, a second annotation as the anchor) returns None and the caller
    checks that text against every line with no exemption -- conservative,
    since a real collision wrongly let through costs more than one wrongly
    kept.
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
    while a bar's comes from the data and runs 0..height. Verified against
    matplotlib's own output rather than assumed:

        axvspan  Bbox(x0=2.0, y0=0.0, x1=3.0, y1=1.0)     <- y pinned
        bar      Bbox(x0=1.6, y0=0.0, x1=2.4, y1=3.0)     <- y is data

    Both the pinning AND a full-extent render are required, so a data patch that
    happens to sit in 0..1 is not exempted unless it also spans the axes.

    KNOWN EDGE CASE: a bar of height exactly 1.0 on an axes with ylim (0, 1) is
    indistinguishable this way and would be treated as background. Harmless --
    patch coverage is the weaker of the two OVERDATA rules and the point rule
    still applies.
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

    Patch COUNT is not comparable to point count -- two bars under a label is a
    real collision and two scatter points is not -- so bar-like data is judged
    by area instead. Full-width patches are background shading and are skipped;
    labelling an `axhspan` is normal.
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

    An `errorbar` call adds two cap Line2Ds (markers-only, so `_scatter_like`
    would count them) and a LineCollection per bar direction (whose default
    `get_offsets()` is a single [0, 0], which would count as a mark AT THE ORIGIN
    and therefore usually as CLIPPED). Left in, a 23-point literature figure
    reported "10 of 57 data marks" outside its limits when the honest answer was
    2 of 23 -- the ratio survived but the numbers did not, and a check whose
    counts do not match what a reader can count by hand will be distrusted and
    switched off.
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
    model curve running off the top of the axes is normal and intentional
    (`20260817_probe_ladder` draws one deliberately), and counting its vertices
    as clipped data would make the CLIPPED check fire on almost every figure
    here -- the fastest way to get a check switched back off.
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

    Relative with a floor and a cap: see the module docstring's measured table
    for why the old flat 20 could not fire on a 179-point panel.
    """
    if n_marks <= 0:
        return OVERDATA_MIN_POINTS
    rel = max(OVERDATA_MIN_POINTS_FLOOR, round(OVERDATA_MIN_FRAC * n_marks))
    return int(min(OVERDATA_MIN_POINTS, rel))


def _has_opaque_bbox(t: Text) -> bool:
    """True if this text carries a backing patch opaque enough to count as fixed.

    The check's own message has always said "move it, or give it an opaque
    bbox"; until 2026-08-17 nothing verified the second half, so the remedy did
    not silence the finding.
    """
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

    REGRESSION, 2026-09-09: a Line2D used as a marker-only legend PROXY (the
    house pattern for a scatter legend --
    `Line2D([], [], marker="o", ls="", mfc=colour, mec="white")`) has NO drawn
    line, so `get_color()` -- checked first, and always present on a Line2D --
    returns the LINE colour's unset placeholder (`"C0"`), not the marker face
    colour that is actually visible. On
    `20260826_probe_ladder_revised.py` this read all four legend entries
    (dye/PEG/protein/overlap-set, visibly orange/green/blue/white on screen)
    as the identical resolved colour of `"C0"`, manufacturing a COLORROLE
    finding out of nothing. Same marker-only test `_scatter_like` already uses
    elsewhere in this file (`ls in ("None", "none", " ", "")`) decides which
    colour attribute is the one actually drawn.
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
    # CLIPPED first: it is the only kind that reports MISSING data, so it
    # outranks anything about placement. OVERDATA was absent from this tuple
    # until 2026-08-17, so an OVERDATA finding counted toward the total and then
    # printed nothing -- the one failure mode worse than not checking.
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
    """Run `script` under the savefig hook, then flag a stale-output crash.

    WHY: a script that raises before its first `savefig` leaves the PREVIOUS
    run's PNG/SVG on disk, looking exactly like a fresh one -- there is no
    exception in the figure file itself. Found 2026-09-09 when an undefined
    name killed a script mid-run and the old output was the only thing
    reviewed; the only tell was that the `[figcheck] ... wrote ...`-style save
    line was missing from the console output, which is easy to miss and
    impossible to grep for after the fact. Checking `Figure.savefig._saves`
    after the run makes that absence an explicit warning instead of something
    you have to notice.
    """
    if len(argv) < 2:
        print(__doc__.split("WHY THIS EXISTS")[0].strip())
        print("usage: python3 -m figlib.figcheck <plotting_script.py> [args...]")
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

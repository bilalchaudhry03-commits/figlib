"""Tests for figcheck: each detector fires on a figure broken for it, and a clean figure
reports nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from figlib import figcheck  # noqa: E402


@pytest.fixture
def fig():
    f = plt.figure(figsize=(8, 5))
    yield f
    plt.close(f)


def kinds(findings):
    return {f.kind for f in findings}


# --------------------------------------------------------------- does it fire
def test_overlapping_text_is_reported(fig):
    ax = fig.add_subplot()
    ax.text(0.5, 0.5, "SOME OVERLAPPING TEXT", transform=ax.transAxes,
            ha="center", fontsize=20)
    ax.text(0.5, 0.505, "SOME OVERLAPPING TEXT", transform=ax.transAxes,
            ha="center", fontsize=20)
    assert "OVERLAP" in kinds(figcheck.check(fig))


def test_text_off_the_canvas_is_reported(fig):
    fig.add_subplot()
    fig.text(1.4, 0.5, "this runs off the right edge", fontsize=14)
    found = figcheck.check(fig)
    assert "OUTSIDE" in kinds(found)
    assert any("crop" in f.detail for f in found if f.kind == "OUTSIDE")


def test_small_type_uses_the_slide_scale_not_the_raw_point_size(fig):
    """The check with teeth: 9pt is fine on its own and not fine on an 18in
    figure scaled onto a 13.333in slide."""
    wide = plt.figure(figsize=(20, 6))
    wide.add_subplot().set_title("nine point", fontsize=9)
    try:
        assert "SMALL" in kinds(figcheck.check(wide, min_pt=7.0))
        # same point size, a figure that does not have to shrink -> silent
        fig.add_subplot().set_title("nine point", fontsize=9)
        assert "SMALL" not in kinds(figcheck.check(fig, min_pt=7.0))
    finally:
        plt.close(wide)


def test_legend_sitting_on_the_data_is_reported(fig):
    ax = fig.add_subplot()
    grid = [(i, j) for i in range(60) for j in range(60)]      # deterministic
    ax.scatter([p[0] for p in grid], [p[1] for p in grid], s=4)
    ax.legend(["dense cloud"], loc="center")
    assert "LEGEND" in kinds(figcheck.check(fig))


def test_legend_check_is_deliberately_conservative(fig):
    """A legend clipping a handful of markers is normal and must stay silent;
    only a legend sitting ON the distribution is worth a report. A 200-point
    diagonal through a centred legend covers 14 points, under the threshold."""
    ax = fig.add_subplot()
    ax.plot(range(200), range(200), "o")
    ax.legend(["sparse line"], loc="center")
    assert "LEGEND" not in kinds(figcheck.check(fig))


def test_require_raises_and_check_does_not(fig):
    fig.text(1.4, 0.5, "off canvas", fontsize=14)
    figcheck.check(fig)                       # must not raise
    with pytest.raises(AssertionError):
        figcheck.require(fig)


def test_a_rotated_label_crossing_a_title_is_reported(fig):
    """REGRESSION, 2026-08-13. The area rule alone could not see this.

    `OVERLAP_MIN_FRAC` divides the intersection by the SMALLER BOX'S AREA. A
    90°-rotated label piercing a horizontal title covers 100% of the title's
    height and only a few percent of the tall label's area, so it scored under
    the threshold and the linter printed "layout clean" on a figure where the
    two were plainly on top of each other
    (`passive_diffusion/figures/20260813_nls_vs_deviation.png`). Visual review
    caught it; that is the gap `_crosses` closes.
    """
    ax = fig.add_subplot()
    ax.set_title("D  a panel title wide enough to be crossed", fontsize=11)
    # 0.85 up, so the label runs off the top of the axes and through the title
    # exactly the way a staggered per-point annotation does.
    ax.text(0.5, 0.85, "a tall rotated label", transform=ax.transAxes,
            rotation=90, ha="center", va="bottom", fontsize=9)
    found = [f for f in figcheck.check(fig) if f.kind == "OVERLAP"]
    assert found, "a rotated label piercing the title must be reported"
    # and the point of the new rule: the area fraction alone would have passed
    assert all(float(f.detail.split("%")[0].split()[-1]) < 100 * figcheck.OVERLAP_MIN_FRAC
               for f in found)


def test_overdata_fires_on_dense_scatter_and_can_be_switched_off(fig):
    """Was `test_overdata_is_opt_in_...` until 2026-08-17.

    It asserted the opposite default, on the reasoning that in-axes annotations
    sit on the plot area by design so a default-on check would cry wolf. What
    changed is not the taste, it is a measurement: with the old flat threshold
    the check could not fire on a normal-sized panel at all (17 and 18 marks
    under two real faults, against a trigger of 20), so "off by default" meant
    "unavailable". The threshold is relative now and the remedy silences it, so
    the wolf-crying objection is handled by the bbox rule instead of by the
    default. Off is still one keyword away.
    """
    ax = fig.add_subplot()
    grid = [(i, j) for i in range(60) for j in range(60)]
    ax.scatter([p[0] for p in grid], [p[1] for p in grid], s=4)
    ax.text(30, 30, "buried in the cloud", ha="center", fontsize=12)
    assert "OVERDATA" in kinds(figcheck.check(fig))
    assert "OVERDATA" not in kinds(figcheck.check(fig, check_overdata=False))


def test_overdata_sees_bars_by_area_not_by_count(fig):
    """Two bars under a label is a real collision; two scatter points is not.
    Patch count and point count are not the same units, so bars are judged by
    the fraction of the text box they cover."""
    ax = fig.add_subplot()
    ax.bar(range(10), [10] * 10)
    ax.text(4.5, 5, "sitting on the bars", ha="center", fontsize=12)
    assert "OVERDATA" in kinds(figcheck.check(fig, check_overdata=True))


def test_overdata_ignores_background_shading(fig):
    """Labelling an axhspan is normal. A full-width patch is background, not a
    data mark, and must not be reported."""
    ax = fig.add_subplot()
    ax.plot([0, 1], [0, 1])
    ax.axhspan(0.3, 0.7, color="0.9")
    ax.text(0.5, 0.5, "labelled band", ha="center", fontsize=12)
    assert "OVERDATA" not in kinds(figcheck.check(fig, check_overdata=True))


# ------------------------------------------------------------ does it shut up
def test_the_crossing_rule_does_not_fire_on_grazing_stat_block_lines(fig):
    """REGRESSION GUARD for the rule above. The area rule's tolerances were
    tuned so a deliberately-tight stat block passes clean; the crossing rule
    must not undo that. Two stacked lines that graze span one box's width but
    nothing like either box's height, so they are not a crossing."""
    ax = fig.add_subplot()
    ax.text(0.03, 0.97, "rho +0.02 (p 0.78)", transform=ax.transAxes,
            va="top", fontsize=9)
    ax.text(0.03, 0.92, "partial rho -0.06", transform=ax.transAxes,
            va="top", fontsize=9)
    assert "OVERLAP" not in kinds(figcheck.check(fig))


def test_a_clean_figure_reports_nothing(fig):
    ax = fig.add_subplot()
    ax.plot([0, 1], [0, 1])
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_title("a title")
    assert figcheck.check(fig) == []


def test_ticks_outside_the_view_limits_are_ignored(fig):
    """REGRESSION. A locator tick beyond the view limits is culled at draw time
    but still reports a window extent, off the end of the axis. Reporting those
    produced 15 phantom OVERLAPs on the 08-05 gate matrix."""
    ax = fig.add_subplot()
    ax.plot([0, 1], [0, 1])
    ax.set_ylim(0.38, 1.02)                   # locator still offers 1.2
    labels = [t.get_text() for t, _ in figcheck._texts(fig)]
    assert not any(lbl.strip() in {"1.2", "1.4"} for lbl in labels)
    assert figcheck.check(fig) == []


def test_stale_tick_pool_entries_are_ignored(fig):
    """REGRESSION. matplotlib reuses Tick objects; ones dropped by a new
    formatter keep their old text and stay `visible`. `fig.findobj(Text)` sees
    them, the documented accessors do not."""
    ax = fig.add_subplot()
    ax.plot([0, 1], [0, 1])
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    fig.canvas.draw()
    ax.set_xticks([0, 1])                     # shrink the tick set
    live = {t.get_text().strip() for t, _ in figcheck._texts(fig)}
    assert "0.25" not in live and "0.75" not in live


def test_tight_bbox_means_overhang_is_not_a_defect(fig):
    """bbox_inches="tight" EXPANDS the saved output rather than cropping, so
    OUTSIDE would be a false positive. Caught on
    20260803_confidence_stratified_figures.py, which saves tight."""
    fig.add_subplot()
    fig.text(1.05, 0.5, "overhangs, but tight-save keeps it", fontsize=14)
    assert "OUTSIDE" in kinds(figcheck.check(fig, crops=True))
    assert "OUTSIDE" not in kinds(figcheck.check(fig, crops=False))


def test_expanded_reports_tight_bbox_growth_and_its_likely_cause(fig):
    """Added 2026-09-09, after the same canvas-expansion mistake landed twice in
    one session: SMALL reported the symptom (small type) both times, and the
    cause -- an overhanging `fig.text` growing the tight bbox past the declared
    figsize, which shrinks the slide scale for every label -- had to be
    rediscovered from scratch each time. EXPANDED should name the growth ratio
    and point at the offending text."""
    fig.add_subplot()
    fig.text(1.6, 0.5, "a long overhanging caption pushing the tight bbox way out",
             fontsize=14)
    found = figcheck.check(fig, crops=False)
    assert "EXPANDED" in kinds(found)
    exp = next(f for f in found if f.kind == "EXPANDED")
    assert "overhanging caption" in exp.detail


def test_expanded_stays_quiet_on_a_normal_tight_save(fig):
    """A tight save ordinarily grows a little from axis-label padding alone;
    only real overhang past EXPAND_MIN_FRAC should fire."""
    ax = fig.add_subplot()
    ax.plot([0, 1], [0, 1])
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    assert "EXPANDED" not in kinds(figcheck.check(fig, crops=False))


def test_install_is_idempotent_and_honours_tight(fig, capsys, tmp_path):
    """rc_context is load-bearing, not tidiness. Four scripts under
    scripts/plotting/ set `savefig.bbox: "tight"` in a module-level
    rcParams.update, and importing any of them leaks it into the whole pytest
    session -- which made this test pass alone and fail in the full suite. The
    tool was right; the test was not controlling its environment."""
    from matplotlib.figure import Figure
    original = Figure.savefig
    with matplotlib.rc_context({"savefig.bbox": None}):
        try:
            figcheck.install()
            figcheck.install()                # second call must be a no-op
            fig.add_subplot()
            fig.text(1.05, 0.5, "overhang", fontsize=14)
            fig.savefig(tmp_path / "a.png", bbox_inches="tight")
            assert "OUTSIDE" not in capsys.readouterr().out
            fig.savefig(tmp_path / "b.png")
            assert "OUTSIDE" in capsys.readouterr().out
        finally:
            Figure.savefig = original


def test_install_honours_a_tight_default_from_rcparams(fig, capsys, tmp_path):
    """A script that sets `savefig.bbox: "tight"` in rcParams and then calls a
    bare `fig.savefig(path)` is still saving tight, so OUTSIDE must stay quiet
    even though the call site says nothing about bbox."""
    from matplotlib.figure import Figure
    original = Figure.savefig
    with matplotlib.rc_context({"savefig.bbox": "tight"}):
        try:
            figcheck.install()
            fig.add_subplot()
            fig.text(1.05, 0.5, "overhang", fontsize=14)
            fig.savefig(tmp_path / "c.png")
            assert "OUTSIDE" not in capsys.readouterr().out
        finally:
            Figure.savefig = original


def test_stale_output_warning_fires_when_the_script_crashes_before_saving(tmp_path, capsys):
    """Added 2026-09-09. A crashed script leaves the PREVIOUS run's PNG/SVG on
    disk looking exactly like a fresh one -- there is no exception recorded in
    the figure file itself. Reproduces the actual incident: an undefined name
    kills the script before its first savefig."""
    script = tmp_path / "broken.py"
    script.write_text("raise NameError('CONTEXT is not defined')\n")
    from matplotlib.figure import Figure
    original = Figure.savefig
    try:
        with pytest.raises(NameError):
            figcheck._main(["figcheck", str(script)])
        out = capsys.readouterr().out
        assert "WARNING" in out and "STALE" in out
    finally:
        Figure.savefig = original


def test_stale_output_warning_is_silent_when_a_save_happened(tmp_path, capsys):
    script = tmp_path / "ok.py"
    out_png = tmp_path / "out.png"
    script.write_text(
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "fig = plt.figure()\n"
        f"fig.savefig(r'{out_png}')\n"
    )
    from matplotlib.figure import Figure
    original = Figure.savefig
    try:
        figcheck._main(["figcheck", str(script)])
        assert "STALE" not in capsys.readouterr().out
    finally:
        Figure.savefig = original


# ------------------------------------------------- CLIPPED (added 2026-08-17)
#
# Built from the figure that shipped the fault: `20260817_size_coverage` panel A
# drew a signal/noise ratio spanning 11 decades on an axis floored at 2e-3, and
# 27 of its 179 points fell below the floor. The linter said "layout clean". The
# 27 were the LARGEST proteins in the set -- the panel's own subject -- and no
# amount of looking at the PNG could reveal them, because the failure is the
# absence of a mark. That asymmetry is why this check is on by default.
def test_scatter_points_outside_the_limits_are_reported(fig):
    ax = fig.add_subplot()
    ax.scatter([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [1, 1, 1, 1, 1, 1, 1, 9, 9, 9])
    ax.set_ylim(0, 2)                       # drops the last three
    found = figcheck.check(fig)
    assert "CLIPPED" in kinds(found)
    assert "3 of 10" in next(f.detail for f in found if f.kind == "CLIPPED")


def test_the_size_coverage_fault_reproduces(fig):
    """The real shape: a log axis whose floor silently eats the tail."""
    ax = fig.add_subplot()
    inside = [1.0] * 152
    below = [1e-6] * 27                     # the 27 that vanished
    ax.scatter(list(range(179)), inside + below)
    ax.set_yscale("log")
    ax.set_ylim(2e-3, 60)
    found = figcheck.check(fig)
    assert "CLIPPED" in kinds(found)
    assert "27 of 179" in next(f.detail for f in found if f.kind == "CLIPPED")


def test_a_curve_running_off_the_axes_is_NOT_clipped_data(fig):
    """A model curve leaving the view is normal and intentional -- the probe
    ladder draws one on purpose. Only individually meaningful marks count, so a
    Line2D with a linestyle is never CLIPPED data."""
    ax = fig.add_subplot()
    ax.plot([1, 2, 3, 4, 5], [1, 10, 100, 1000, 10000])
    ax.set_ylim(0, 50)
    assert "CLIPPED" not in kinds(figcheck.check(fig))


def test_markers_drawn_through_plot_do_count(fig):
    """`ax.plot(x, y, "o")` is a scatter wearing a Line2D, and its marks are
    individually meaningful, so it must not escape the check on a technicality."""
    ax = fig.add_subplot()
    ax.plot([1, 2, 3, 4, 5, 6, 7, 8], [1, 1, 1, 1, 1, 9, 9, 9], "o")
    ax.set_ylim(0, 2)
    assert "CLIPPED" in kinds(figcheck.check(fig))


def test_one_stray_point_does_not_fire(fig):
    """Both thresholds must be met. A single mark off the edge is the kind of
    thing that gets a linter switched off."""
    ax = fig.add_subplot()
    ax.scatter(list(range(100)), [1] * 99 + [99])
    ax.set_ylim(0, 2)
    assert "CLIPPED" not in kinds(figcheck.check(fig))


def test_clipped_can_be_switched_off_for_a_deliberate_zoom(fig):
    ax = fig.add_subplot()
    ax.scatter([1, 2, 3, 4, 5], [1, 1, 1, 9, 9])
    ax.set_ylim(0, 2)
    assert "CLIPPED" not in kinds(figcheck.check(fig, check_clipped=False))


# ------------------------------------------ OVERDATA: relative and bbox-aware
#
# The measured failure this replaces: with the old flat OVERDATA_MIN_POINTS = 20,
# a label parked in the DENSEST part of a 179-point panel put 18 marks under
# itself and stayed silent, because a text box simply cannot cover 20 of 179
# points. The check existed, was opt-in, and could not fire on the figures this
# repo draws.
def test_overdata_threshold_is_relative_to_the_axes_density():
    assert figcheck._overdata_threshold(179) == 9
    assert figcheck._overdata_threshold(5000) == figcheck.OVERDATA_MIN_POINTS
    assert figcheck._overdata_threshold(12) == figcheck.OVERDATA_MIN_POINTS_FLOOR


def test_label_on_a_sparse_cloud_now_fires(fig):
    """~15 marks under a label on a 179-point panel: silent before, caught now."""
    ax = fig.add_subplot()
    xs = [i / 100 for i in range(179)]
    ax.scatter(xs, [0.5] * 179)
    ax.text(0.5, 0.5, "a label parked on the data", fontsize=14,
            ha="left", va="center")
    found = figcheck.check(fig)
    assert "OVERDATA" in kinds(found)


def test_an_opaque_bbox_silences_overdata(fig):
    """The check's own remedy has to work, or lowering the threshold just
    generates noise for correctly-backed labels."""
    ax = fig.add_subplot()
    xs = [i / 100 for i in range(179)]
    ax.scatter(xs, [0.5] * 179)
    t = ax.text(0.5, 0.5, "a label parked on the data", fontsize=14,
                ha="left", va="center")
    assert "OVERDATA" in kinds(figcheck.check(fig))
    t.set_bbox(dict(facecolor="white", edgecolor="none", alpha=1.0))
    assert "OVERDATA" not in kinds(figcheck.check(fig))


def test_a_translucent_bbox_does_not_count_as_remediated(fig):
    ax = fig.add_subplot()
    xs = [i / 100 for i in range(179)]
    ax.scatter(xs, [0.5] * 179)
    t = ax.text(0.5, 0.5, "a label parked on the data", fontsize=14,
                ha="left", va="center")
    t.set_bbox(dict(facecolor="white", edgecolor="none", alpha=0.2))
    assert "OVERDATA" in kinds(figcheck.check(fig))


def test_report_prints_every_kind_it_counts(fig, capsys):
    """OVERDATA was missing from report()'s kind tuple until 2026-08-17, so it
    was counted in the total and then never printed -- a finding you cannot read
    is worse than no finding."""
    ax = fig.add_subplot()
    xs = [i / 100 for i in range(179)]
    ax.scatter(xs, [0.5] * 179)
    ax.text(0.5, 0.5, "a label parked on the data", fontsize=14,
            ha="left", va="center")
    n = figcheck.report(fig, crops=False)
    out = capsys.readouterr().out
    assert n >= 1
    assert out.count("  ") >= n            # every counted finding has a line
    assert "OVERDATA" in out


def test_a_label_inside_a_vertical_shaded_band_is_not_a_bar(fig):
    """`axvspan` is background shading, same as `axhspan`.

    BACKGROUND_PATCH_FRAC's comment named axvspan from the start but the code
    tested width only, so a full-height band -- narrow by construction -- scored
    as a bar covering 100% of any label inside it. Found 2026-08-17 the first
    time OVERDATA ran by default: six annotations inside one shaded window on
    `20260817_size_coverage` were all reported as covered "by bars".
    """
    ax = fig.add_subplot()
    ax.scatter([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
    ax.axvspan(2, 3, color="blue", alpha=0.1)
    ax.text(2.5, 4, "labelling the band", ha="center", fontsize=11)
    assert "OVERDATA" not in kinds(figcheck.check(fig))


def test_a_horizontal_band_is_still_exempt(fig):
    """The case that already worked must keep working."""
    ax = fig.add_subplot()
    ax.scatter([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
    ax.axhspan(2, 3, color="blue", alpha=0.1)
    ax.text(3, 2.5, "labelling the band", ha="center", fontsize=11)
    assert "OVERDATA" not in kinds(figcheck.check(fig))


def test_full_height_bars_are_still_judged_as_bars(fig):
    """The counter-case to the axvspan fix, and why `_is_background_patch` asks
    how the patch is pinned rather than only how big it is: bars reaching the top
    of the axes render exactly like a vertical band, and exempting them would
    have silently undone `test_overdata_sees_bars_by_area_not_by_count`."""
    ax = fig.add_subplot()
    ax.bar(range(10), [10] * 10)            # every bar spans the full height
    ax.text(4.5, 5, "sitting on the bars", ha="center", fontsize=12)
    assert "OVERDATA" in kinds(figcheck.check(fig))


def test_a_panel_can_declare_its_zoom_deliberate(fig):
    """Per-axes opt-out, because the whole-figure switch is too blunt: a linear
    detail panel beside a log full-range panel is the honest reason to clip, and
    silencing the figure would also silence the panel that is not zoomed."""
    axA = fig.add_subplot(121)
    axB = fig.add_subplot(122)
    for ax in (axA, axB):
        ax.scatter([1, 2, 3, 4, 5, 6], [1, 1, 1, 9, 9, 9])   # 3 out, meets the floor
        ax.set_ylim(0, 2)
    axA.set_gid(figcheck.CLIP_OK_GID)
    found = [f for f in figcheck.check(fig) if f.kind == "CLIPPED"]
    assert len(found) == 1, "only the undeclared panel should report"


def test_errorbar_caps_are_not_counted_as_data_marks(fig):
    """An errorbar's caps and bar collections are decoration of one mark, not
    marks. Counting them made a 23-point literature figure report "10 of 57"
    when the honest count was 2 of 23 -- and the LineCollection's default
    offset of [0, 0] reads as a mark at the origin, usually outside the limits."""
    ax = fig.add_subplot()
    ax.errorbar([1, 2, 3], [1, 1, 1], yerr=[0.1, 0.1, 0.1], fmt="o", capsize=3)
    ax.set_xlim(0.5, 3.5)
    ax.set_ylim(0.5, 1.5)
    assert figcheck._axes_mark_count(ax) == 3
    assert "CLIPPED" not in kinds(figcheck.check(fig))


# ------------------------------------------------- OVERLINE (added 2026-09-09)
def test_a_label_sitting_directly_on_a_plain_line_is_reported(fig):
    """The exact miss from today: a plain `ax.plot` curve has no markers for
    OVERDATA to count and is not a patch, so a label placed on top of it must
    be caught by a dedicated check instead."""
    ax = fig.add_subplot()
    ax.plot([0, 1, 2, 3, 4], [0, 1, 2, 3, 4])
    ax.text(2, 2, "sitting right on the curve", ha="center", va="center",
            fontsize=12)
    assert "OVERLINE" in kinds(figcheck.check(fig))
    assert "OVERDATA" not in kinds(figcheck.check(fig))       # confirms the gap


def test_overdata_alone_would_have_missed_it(fig):
    """REGRESSION GUARD documenting the actual failure mode: a marker-less line
    contributes zero marks, so `_axes_mark_count` -- and therefore OVERDATA's
    every threshold -- sees this axes as empty."""
    ax = fig.add_subplot()
    ax.plot([0, 1, 2, 3, 4], [0, 1, 2, 3, 4])
    assert figcheck._axes_mark_count(ax) == 0


def test_a_label_clear_of_the_line_is_silent(fig):
    ax = fig.add_subplot()
    ax.plot([0, 1, 2, 3, 4], [0, 1, 2, 3, 4])
    ax.text(0.5, 3.5, "well above the curve", ha="center", fontsize=12)
    assert "OVERLINE" not in kinds(figcheck.check(fig))


def test_overline_can_be_switched_off(fig):
    ax = fig.add_subplot()
    ax.plot([0, 1, 2, 3, 4], [0, 1, 2, 3, 4])
    ax.text(2, 2, "on the curve", ha="center", va="center", fontsize=12)
    assert "OVERLINE" not in kinds(figcheck.check(fig, check_overline=False))


def test_an_opaque_bbox_silences_overline_too(fig):
    """Same remedy as OVERDATA: an opaque backing patch is the documented fix,
    and the check must honour it instead of flagging the correctly-backed
    label as a fault."""
    ax = fig.add_subplot()
    ax.plot([0, 1, 2, 3, 4], [0, 1, 2, 3, 4])
    ax.text(2, 2, "backed label", ha="center", va="center", fontsize=12,
            bbox=dict(facecolor="white", alpha=0.9, edgecolor="none"))
    assert "OVERLINE" not in kinds(figcheck.check(fig))


def test_overline_ignores_an_annotation_arrows_reach_toward_the_curve(fig):
    """REGRESSION, found 2026-09-09 auditing a real figure.

    `Annotation.get_window_extent()` unions the arrow patch's bbox into the
    text's reported extent (so a tight save does not clip the arrow). An
    annotation arrow is designed to reach from its caption to the data point
    it names, so leaving that union in makes the label's footprint include
    its own reach toward the data -- a callout can sit nowhere near a curve on
    screen and still "collide" with it because its arrow tip touches the
    curve, which is the entire point of drawing the arrow there.
    """
    ax = fig.add_subplot()
    ax.plot([0, 1, 2, 3, 4], [0, 1, 2, 1, 1])
    ax.annotate("callout text, well clear of the curve", xy=(2, 2), xytext=(2, -1),
                va="center", ha="center", arrowprops=dict(arrowstyle="-"))
    assert "OVERLINE" not in kinds(figcheck.check(fig))


def test_overline_exempts_a_value_labelling_its_own_point_on_the_line(fig):
    """The dominant house pattern found sweeping the repo 2026-09-09: a value
    written at the exact point on a bracket/rung/threshold line it reports,
    via `ax.annotate(f"{v:.1f}", xy=(x, y), xytext=(dx, dy),
    textcoords="offset points")`. That `xy` sits AS CLOSE to the line as a
    label can get by construction, which is not the accidental case OVERLINE
    exists for and would otherwise dominate its false-positive rate."""
    ax = fig.add_subplot()
    ax.plot([0, 1, 2], [1.1, 1.1, 1.1], lw=4.5, solid_capstyle="butt")
    ax.annotate("1.1", xy=(0, 1.1), xytext=(0, -6), textcoords="offset points",
                ha="center", va="top", fontsize=9)
    assert "OVERLINE" not in kinds(figcheck.check(fig))


def test_overline_still_fires_when_the_collision_is_with_an_unrelated_line(fig):
    """The exemption is per-LINE, not per-text: a label anchored on the bar it
    names must still be reported if it also crosses a DIFFERENT, unrelated
    line it is not labelling."""
    ax = fig.add_subplot()
    ax.plot([0, 1, 2], [1.1, 1.1, 1.1], lw=4.5, solid_capstyle="butt")
    ax.plot([0, 1, 2], [0.85, 0.85, 0.85], lw=2)     # unrelated context line
    # xy anchors on the FIRST line (exempted); the caption itself is placed,
    # in data coords, directly on top of the SECOND, unrelated line.
    ax.annotate("1.1", xy=(0, 1.1), xytext=(1, 0.85), ha="center", va="center",
                fontsize=9)
    assert "OVERLINE" in kinds(figcheck.check(fig))


def test_overline_ignores_an_axhline_reference_threshold(fig):
    """Second dominant house pattern found in the same sweep: a full-panel
    `axhline`/`axvline` threshold marker spans the whole axes by construction,
    so a caption placed anywhere near that value would otherwise always
    collide with it -- that is not the same failure as a caption sitting on a
    real measurement curve."""
    ax = fig.add_subplot()
    ax.plot([0, 1, 2], [0, 1, 2])
    ax.axhline(1.0, color="black")
    ax.text(0.5, 1.02, "reference threshold", ha="center", va="bottom", fontsize=11)
    assert "OVERLINE" not in kinds(figcheck.check(fig))


def test_overline_ignores_an_axvline_reference_threshold(fig):
    ax = fig.add_subplot()
    ax.plot([0, 1, 2], [0, 1, 2])
    ax.axvline(1.0, color="black")
    ax.text(1.02, 0.5, "threshold", ha="left", va="center", fontsize=11)
    assert "OVERLINE" not in kinds(figcheck.check(fig))


def test_overline_still_fires_on_a_real_curve_near_an_axhline(fig):
    """REGRESSION GUARD: the axhline exemption must not blanket-exempt the
    whole axes -- a real curve sitting under a label must still be reported
    even when an unrelated axhline is also present."""
    ax = fig.add_subplot()
    ax.plot([0, 1, 2, 3, 4], [0, 1, 2, 1, 1])
    ax.axhline(-5.0, color="black")           # far away, should not matter
    ax.text(2, 2, "sitting right on the curve", ha="center", va="center",
            fontsize=12)
    assert "OVERLINE" in kinds(figcheck.check(fig))


def test_a_curve_running_under_a_title_or_tick_label_is_not_reported(fig):
    """OVERLINE only looks at in-axes annotations (`_in_axes_texts`), same scope
    as OVERDATA -- titles and tick labels live outside the data area by
    construction and a curve reaching the axes edge under them is normal."""
    ax = fig.add_subplot()
    ax.plot([0, 1], [0, 1])
    ax.set_title("a title near the top-right corner of the axes")
    assert "OVERLINE" not in kinds(figcheck.check(fig))


# ------------------------------------------------ COLORROLE (added 2026-09-09)
def test_color_role_reuse_across_axes_is_reported_when_enabled(fig):
    """The actual incident: green meant one thing in one panel and a different
    thing in another. Opt-in, so it must be silent unless asked for."""
    axA = fig.add_subplot(121)
    axA.plot([0, 1], [0, 1], color="green", label="raw")
    axA.legend()
    axB = fig.add_subplot(122)
    axB.plot([0, 1], [1, 0], color="green", label="corrected")
    axB.legend()
    assert "COLORROLE" not in kinds(figcheck.check(fig))
    found = figcheck.check(fig, check_color_roles=True)
    assert "COLORROLE" in kinds(found)
    detail = next(f.detail for f in found if f.kind == "COLORROLE")
    assert "raw" in detail and "corrected" in detail


def test_color_role_reuse_is_fine_when_the_label_is_the_same(fig):
    """A colour meaning the SAME thing in every panel is the common, correct
    case (e.g. a shared "control" role) and must stay silent."""
    axA = fig.add_subplot(121)
    axA.plot([0, 1], [0, 1], color="green", label="control")
    axA.legend()
    axB = fig.add_subplot(122)
    axB.plot([0, 1], [1, 0], color="green", label="control")
    axB.legend()
    assert "COLORROLE" not in kinds(figcheck.check(fig, check_color_roles=True))


def test_color_role_reads_marker_only_legend_proxies_correctly(fig):
    """REGRESSION, found sweeping the repo 2026-09-09 on
    `20260826_probe_ladder_revised.py`. That figure's legend is built from
    marker-only Line2D proxies (`Line2D([], [], marker="o", ls="", mfc=colour,
    mec="white")`, the house pattern for a scatter legend). `get_color()` is
    always present on a Line2D and was checked first, so it read the LINE
    colour's unset placeholder ("C0") instead of the marker face colour that
    is actually visible -- manufacturing a COLORROLE finding across four
    entries that were visibly orange/green/blue/white on screen."""
    from matplotlib.lines import Line2D
    ax = fig.add_subplot()
    ax.plot([0], [0])                                         # give the axes data
    handles = [
        Line2D([], [], marker="o", ls="", mfc="orange", mec="white", label="dye"),
        Line2D([], [], marker="o", ls="", mfc="green", mec="white", label="PEG"),
        Line2D([], [], marker="o", ls="", mfc="blue", mec="white", label="protein"),
    ]
    ax.legend(handles=handles)
    assert "COLORROLE" not in kinds(figcheck.check(fig, check_color_roles=True))


def test_hidden_axes_and_transparent_text_are_not_checked():
    """Explainer frames hide whole panels and fade text to alpha 0; neither is drawn."""
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(6, 4))
    a1 = fig.add_axes([0.15, 0.15, 0.7, 0.7]); a1.set_xlabel("shown")
    a2 = fig.add_axes([0.15, 0.15, 0.7, 0.7]); a2.set_xlabel("hidden"); a2.set_visible(False)
    fig.text(0.5, 0.95, "ghost", alpha=0); fig.text(0.5, 0.95, "real")
    kinds = [f.kind for f in figcheck.check(fig)]
    assert "OVERLAP" not in kinds
    plt.close(fig)

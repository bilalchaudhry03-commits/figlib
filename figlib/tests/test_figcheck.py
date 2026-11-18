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
    """A rotated label piercing a title scores under the area rule; `_crosses` catches it."""
    # Pinned to matplotlib's bundled font: the area fraction depends on glyph metrics,
    # and the default family resolves differently from machine to machine.
    with plt.rc_context({"font.family": "DejaVu Sans"}):
        ax = fig.add_subplot()
        ax.set_title("D  a panel title wide enough to be crossed", fontsize=11)
        # 0.85 up, so the label runs off the top of the axes and through the title
        # exactly the way a staggered per-point annotation does.
        ax.text(0.5, 0.85, "a tall rotated label", transform=ax.transAxes,
                rotation=90, ha="center", va="bottom", fontsize=9)
        found = [f for f in figcheck.check(fig) if f.kind == "OVERLAP"]
    assert found, "a rotated label piercing the title must be reported"
    # the area fraction alone would have passed
    assert all(float(f.detail.split("%")[0].split()[-1]) < 100 * figcheck.OVERLAP_MIN_FRAC
               for f in found)


def test_overdata_fires_on_dense_scatter_and_can_be_switched_off(fig):
    """OVERDATA is on by default and `check_overdata=False` turns it off."""
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
    """Two stacked lines that graze span one box's width but not either box's
    height, so the crossing rule must not fire on a tight stat block."""
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
    """A locator tick beyond the view limits isn't drawn but still reports a
    window extent; it must not produce phantom findings."""
    ax = fig.add_subplot()
    ax.plot([0, 1], [0, 1])
    ax.set_ylim(0.38, 1.02)                   # locator still offers 1.2
    labels = [t.get_text() for t, _ in figcheck._texts(fig)]
    assert not any(lbl.strip() in {"1.2", "1.4"} for lbl in labels)
    assert figcheck.check(fig) == []


def test_stale_tick_pool_entries_are_ignored(fig):
    """matplotlib reuses Tick objects; ones dropped by a new
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
    OUTSIDE would be a false positive."""
    fig.add_subplot()
    fig.text(1.05, 0.5, "overhangs, but tight-save keeps it", fontsize=14)
    assert "OUTSIDE" in kinds(figcheck.check(fig, crops=True))
    assert "OUTSIDE" not in kinds(figcheck.check(fig, crops=False))


def test_expanded_reports_tight_bbox_growth_and_its_likely_cause(fig):
    """An overhanging `fig.text` grows the tight bbox and shrinks every label on
    the slide; EXPANDED names the growth ratio and the offending text."""
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
    """rc_context pins `savefig.bbox`, which other code in the same pytest
    process may have set globally."""
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
    """A script that dies before its first savefig leaves the previous run's
    output looking fresh, so the CLI must warn."""
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


# ----------------------------------------------------------------- CLIPPED
# Marks outside the limits are never drawn, so no amount of looking at the PNG
# reveals them. That is why this check is on by default.
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
    """A model curve leaving the view is normal. Only individually meaningful
    marks count, so a Line2D with a linestyle is never CLIPPED data."""
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
# A text box can't cover 20 of 179 points, so a flat threshold of 20 never fires
# on a typical panel; the threshold scales with the axes' mark count.
def test_overdata_threshold_is_relative_to_the_axes_density():
    assert figcheck._overdata_threshold(179) == 9
    assert figcheck._overdata_threshold(5000) == figcheck.OVERDATA_MIN_POINTS
    assert figcheck._overdata_threshold(12) == figcheck.OVERDATA_MIN_POINTS_FLOOR


def test_label_on_a_sparse_cloud_now_fires(fig):
    """~15 marks under a label on a 179-point panel is reported."""
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
    """Every kind check() can return is printed by report(), not just counted."""
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
    """`axvspan` is background shading, same as `axhspan`, even though a
    full-height band is narrow."""
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
    """Counter-case to the axvspan test: bars reaching the top of the axes look
    like a vertical band, which is why `_is_background_patch` checks how the
    patch is pinned, not just its size."""
    ax = fig.add_subplot()
    ax.bar(range(10), [10] * 10)            # every bar spans the full height
    ax.text(4.5, 5, "sitting on the bars", ha="center", fontsize=12)
    assert "OVERDATA" in kinds(figcheck.check(fig))


def test_a_panel_can_declare_its_zoom_deliberate(fig):
    """CLIP_OK_GID silences one zoomed panel while its neighbour is still checked."""
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
    marks (and the collection's default [0, 0] offset would read as a mark at
    the origin)."""
    ax = fig.add_subplot()
    ax.errorbar([1, 2, 3], [1, 1, 1], yerr=[0.1, 0.1, 0.1], fmt="o", capsize=3)
    ax.set_xlim(0.5, 3.5)
    ax.set_ylim(0.5, 1.5)
    assert figcheck._axes_mark_count(ax) == 3
    assert "CLIPPED" not in kinds(figcheck.check(fig))


# ---------------------------------------------------------------- OVERLINE
def test_a_label_sitting_directly_on_a_plain_line_is_reported(fig):
    """A plain `ax.plot` curve has no markers for OVERDATA to count, so a label
    on top of it is caught by OVERLINE."""
    ax = fig.add_subplot()
    ax.plot([0, 1, 2, 3, 4], [0, 1, 2, 3, 4])
    ax.text(2, 2, "sitting right on the curve", ha="center", va="center",
            fontsize=12)
    assert "OVERLINE" in kinds(figcheck.check(fig))
    assert "OVERDATA" not in kinds(figcheck.check(fig))       # confirms the gap


def test_overdata_alone_would_have_missed_it(fig):
    """A marker-less line contributes zero marks, so OVERDATA sees this axes as empty."""
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
    """Same remedy as OVERDATA: an opaque backing patch counts as fixed."""
    ax = fig.add_subplot()
    ax.plot([0, 1, 2, 3, 4], [0, 1, 2, 3, 4])
    ax.text(2, 2, "backed label", ha="center", va="center", fontsize=12,
            bbox=dict(facecolor="white", alpha=0.9, edgecolor="none"))
    assert "OVERLINE" not in kinds(figcheck.check(fig))


def test_overline_ignores_an_annotation_arrows_reach_toward_the_curve(fig):
    """`Annotation.get_window_extent()` includes the arrow, which reaches the
    data by design; only the caption's own box is checked."""
    ax = fig.add_subplot()
    ax.plot([0, 1, 2, 3, 4], [0, 1, 2, 1, 1])
    ax.annotate("callout text, well clear of the curve", xy=(2, 2), xytext=(2, -1),
                va="center", ha="center", arrowprops=dict(arrowstyle="-"))
    assert "OVERLINE" not in kinds(figcheck.check(fig))


def test_overline_exempts_a_value_labelling_its_own_point_on_the_line(fig):
    """A value annotated at its own point on a line (`ax.annotate(f"{v:.1f}",
    xy=(x, y), xytext=..., textcoords="offset points")`) is not a collision."""
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
    """A full-panel `axhline`/`axvline` reference spans the whole axes, so a
    caption near it is not a collision."""
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
    """The axhline exemption is per line: a real curve under the label still fires."""
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


# --------------------------------------------------------------- COLORROLE
def test_color_role_reuse_across_axes_is_reported_when_enabled(fig):
    """Green means one thing in one panel and another thing in the next.
    Opt-in, so it must be silent unless asked for."""
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
    """Marker-only legend proxies (`Line2D([], [], marker="o", ls="", mfc=c)`)
    are read by marker colour, not the unset line colour "C0"."""
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

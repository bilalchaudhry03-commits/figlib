"""figlib.scene: cues, captions, the equation row, and the storyboard/frame drivers."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pytest

from figlib import scene


def test_cue_is_clamped_and_monotone():
    c = scene.Cue(1.0, 2.0)
    vals = [c(t) for t in np.linspace(-5, 10, 301)]
    assert min(vals) == 0.0 and max(vals) == 1.0
    assert all(b >= a for a, b in zip(vals, vals[1:]))
    assert c(0.0) == 0.0 and c(3.0) == 1.0 and c(2.0) == pytest.approx(0.5)


def test_zero_length_cue_is_a_step():
    c = scene.Cue(1.0, 0.0)
    assert (c(0.999), c(1.0)) == (0.0, 1.0)


def test_timeline_window_fades_in_then_out():
    tl = scene.Timeline().at("in", 0, 1).at("out", 3, 1)
    assert tl.window("in", "out", 0) == 0
    assert tl.window("in", "out", 2) == 1
    assert tl.window("in", "out", 5) == 0


def test_caption_timing_from_word_count():
    caps = scene.caption_track(["one two", " ".join(["w"] * 10)], start=1.0)
    assert caps[0].end - caps[0].start == scene.MIN_CAPTION_S       # 2 words -> floor
    assert caps[1].end - caps[1].start == pytest.approx(10 / scene.WPS)
    assert caps[1].start == pytest.approx(caps[0].end + scene.CAPTION_GAP_S)


def test_caption_at_fades_and_gaps():
    caps = scene.caption_track(["a b c d e"], start=0.0)
    assert scene.caption_at(caps, caps[0].start)[1] == 0.0
    mid = (caps[0].start + caps[0].end) / 2
    assert scene.caption_at(caps, mid) == ("a b c d e", 1.0)
    assert scene.caption_at(caps, caps[0].end + 0.1) == ("", 0.0)


def test_srt_format(tmp_path):
    p = scene.write_srt(tmp_path / "x.srt", [scene.Caption(61.5, 3723.25, "hi")])
    assert p.read_text() == "1\n00:01:01,500 --> 01:02:03,250\nhi\n\n"


def test_global_captions_offset_by_scene():
    caps = [scene.Caption(0.5, 1.0, "x")]
    s1 = scene.Scene("a", 2.0, lambda t: None, caps)
    s2 = scene.Scene("b", 3.0, lambda t: None, caps)
    g = scene.global_captions([s1, s2])
    assert [c.start for c in g] == [0.5, 2.5]


def test_eqrow_pieces_do_not_overlap_and_brackets_sit_under_their_piece():
    fig = plt.figure(figsize=(8, 4.5), dpi=100)
    row = scene.EqRow(fig, [r"$a+b$", r"$=$", r"$\dfrac{c}{d}$"], 0.1, 0.6).layout()
    row.bracket(2, "fraction", "red")
    xs = [(b.x0, b.x1) for b in row.boxes]
    assert all(a[1] <= b[0] + 1e-9 for a, b in zip(xs, xs[1:]))
    ln, tx = row.brackets[2]
    assert row.boxes[2].x0 <= min(ln.get_xdata()) and max(ln.get_xdata()) <= row.boxes[2].x1
    assert max(ln.get_ydata()) <= min(b.y0 for b in row.boxes)
    plt.close(fig)


def test_frames_count_and_draw_is_called_with_local_time():
    fig = plt.figure(figsize=(2, 1), dpi=50)
    seen = []
    s = scene.Scene("a", 1.0, seen.append)
    out = list(scene.frames(fig, [s, s], fps=10))
    assert len(out) == 20 and out[0].shape[2] == 3
    assert seen[:3] == [0.0, 0.1, 0.2] and seen[10] == 0.0
    plt.close(fig)


def test_failing_model_check_stops_before_any_frame(tmp_path):
    fig = plt.figure(figsize=(2, 1), dpi=50)
    drawn = []

    def bad():
        raise AssertionError("tau_nuc off")

    s = scene.Scene("a", 1.0, drawn.append)
    with pytest.raises(AssertionError, match="tau_nuc"):
        scene.render(fig, [s], "storyboard", tmp_path / "v", checks=[bad])
    assert drawn == []
    plt.close(fig)


def test_storyboard_one_still_per_caption(tmp_path):
    fig = plt.figure(figsize=(4, 2.25), dpi=50)
    cap = fig.text(0.5, 0.1, "", ha="center")
    caps = scene.caption_track(["one", "two", "three"])
    times = []
    s = scene.Scene("a", caps[-1].end, times.append, caps)
    png, notes = scene.storyboard(fig, [s], tmp_path / "v", caption=cap, purity=False)
    assert png.exists() and len(times) == 3
    assert isinstance(notes, list)
    times.clear()
    scene.render(fig, [s], "storyboard", tmp_path / "v", caption=cap)
    assert len(times) == 9                       # purity: each still redrawn after a perturbing draw
    plt.close(fig)


def _leaky_scenes(fig, reset: bool):
    """Scene A writes a label that changes with t; scene B clears it only when `reset`.
    Without the reset, B shows whichever A still came last: order-dependent, so detectable."""
    lab = fig.text(0.5, 0.5, "", ha="center", va="center", fontsize=40)
    caps = scene.caption_track(["one two three", "four five six"])

    def a(t):
        lab.set_text(f"A {t:.1f}")

    def b(t):
        if reset:
            lab.set_text("")

    return [scene.Scene("a", caps[-1].end, a, caps), scene.Scene("b", caps[-1].end, b, caps)]


def test_storyboard_flags_a_scene_that_leaks_into_the_next(tmp_path):
    fig = plt.figure(figsize=(4, 2.25), dpi=50)
    _, notes = scene.storyboard(fig, _leaky_scenes(fig, reset=False), tmp_path / "v")
    impure = [n for n in notes if "IMPURE" in n]
    assert impure and all(n.startswith("b ") for n in impure)
    plt.close(fig)


def test_storyboard_purity_clean_when_every_scene_resets(tmp_path):
    fig = plt.figure(figsize=(4, 2.25), dpi=50)
    _, notes = scene.storyboard(fig, _leaky_scenes(fig, reset=True), tmp_path / "v")
    assert not [n for n in notes if "IMPURE" in n]
    plt.close(fig)


def test_eqrow_rejects_unsupported_mathtext_at_construction():
    fig = plt.figure(figsize=(8, 4.5), dpi=100)
    with pytest.raises(ValueError, match=r"\\big"):
        scene.EqRow(fig, [r"$a\big/b$"], 0.1, 0.5)
    scene.EqRow(fig, [r"$\dfrac{a}{b}$", "plain text"], 0.1, 0.5)      # valid pieces pass
    plt.close(fig)


def test_eqrow_layout_refuses_to_run_off_the_figure():
    fig = plt.figure(figsize=(8, 4.5), dpi=100)
    row = scene.EqRow(fig, [r"$a+b+c+d+e+f+g+h$"] * 3, 0.6, 0.5, size=40)
    fig.canvas.draw()
    with pytest.raises(ValueError, match="max_x"):
        row.layout()
    plt.close(fig)


def test_unknown_mode_rejected(tmp_path):
    fig = plt.figure()
    with pytest.raises(ValueError):
        scene.render(fig, [], "preview", tmp_path / "v")
    plt.close(fig)

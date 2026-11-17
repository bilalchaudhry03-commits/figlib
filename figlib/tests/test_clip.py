"""figlib.clip: pre-rendered clips as scenes (reading frames, the overlay, purity, missing clips)."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pytest

from figlib import anim, clip, scene

COLORS = [(200, 30, 30), (30, 200, 30), (30, 30, 200)]     # one colour per second


@pytest.fixture
def mp4(tmp_path):
    frames = [np.full((90, 160, 3), COLORS[k // 10], np.uint8) for k in range(30)]
    out = anim.write(iter(frames), tmp_path / "c", fps=10, gif=False, bg=(0, 0, 0))
    return out.mp4


def _near(a, rgb, tol=25):
    return np.abs(a.reshape(-1, 3).mean(0) - np.array(rgb)).max() < tol


def test_clip_metadata_and_frames_by_time(mp4):
    c = clip.Clip(mp4)
    assert c.exists and c.size == (160, 90) and abs(c.fps - 10) < 1e-6
    assert abs(c.duration - 3.0) < 0.15
    assert _near(c.frame(0.5), COLORS[0]) and _near(c.frame(1.5), COLORS[1])
    assert _near(c.frame(0.2), COLORS[0])          # backwards seek reopens
    assert _near(c.frame(99), COLORS[2])           # holds the last frame


def test_clip_scene_overlays_then_hides(mp4):
    fig = plt.figure(figsize=(3.2, 1.8), dpi=50)
    fig.patch.set_facecolor("white")
    clip_s = scene.Scene("clip", 3.0, lambda t: None, clip=clip.Clip(mp4))
    plain = scene.Scene("plain", 1.0, lambda t: None)
    frames = list(scene.frames(fig, [clip_s, plain], fps=2))
    assert _near(frames[0], COLORS[0]) and _near(frames[3], COLORS[1])
    assert _near(frames[-1], (255, 255, 255))      # the clip layer is hidden again
    plt.close(fig)


def test_storyboard_with_clip_is_pure(mp4, tmp_path):
    fig = plt.figure(figsize=(3.2, 1.8), dpi=50)
    caps = scene.caption_track(["one two", "three four"])
    lab = fig.text(0.5, 0.5, "", fontsize=20)

    def plain(t):
        lab.set_text("plain")

    def morph(t):
        lab.set_text("")

    scenes = [scene.Scene("plain", caps[-1].end, plain, caps),
              scene.Scene("morph", 3.0, morph, caps, clip=clip.Clip(mp4))]
    _, notes = scene.storyboard(fig, scenes, tmp_path / "v")
    assert not [n for n in notes if "IMPURE" in n]
    plt.close(fig)


def test_missing_clip_placeholder_in_storyboard_and_refused_in_draft(tmp_path):
    fig = plt.figure(figsize=(3.2, 1.8), dpi=50)
    s = scene.Scene("morph", 1.0, lambda t: None, clip=clip.Clip(tmp_path / "nope.mp4"))
    _, notes = scene.storyboard(fig, [s], tmp_path / "v")
    assert any("MISSING CLIP" in n for n in notes)
    with pytest.raises(FileNotFoundError, match="nope.mp4"):
        scene.render(fig, [s], "draft", tmp_path / "v")
    plt.close(fig)


def test_manim_command_binds_repo_and_sets_quality(tmp_path):
    cmd = clip.manim_command(tmp_path / "m.py", "Morph", tmp_path / "out", "draft")
    assert cmd[:2] == ["apptainer", "exec"] and str(clip.SIF) in cmd
    assert "960,540" in cmd and "15" in cmd and cmd[-1] == "Morph"
    assert any(str(clip.ROOT) in a for a in cmd)

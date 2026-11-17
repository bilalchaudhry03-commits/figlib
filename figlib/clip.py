"""Pre-rendered video clips (Manim equation morphs) as scenes in a figlib.scene explainer.

Added 2026-11-13 ("option 1"): Manim renders only the short clips where an equation's terms
morph into another equation; matplotlib (figlib.scene) keeps drawing everything else, so the
model checks, the storyboard (figcheck + purity) and draft/final modes all still apply. A
clip is a build artifact: the explainer's sbatch renders it with Manim inside
`envs/manim/manim.sif` BEFORE the matplotlib script runs, and the script shows it frame by
frame as a `Scene(..., clip=Clip(mp4))`. Captions stay matplotlib's, drawn over the clip.

    from figlib import clip, scene
    morph = clip.Clip(HERE / "clips" / "Substitute.mp4")
    s = scene.Scene("substitute", morph.duration + 0.5, draw=lambda t: blank(), captions=caps,
                    clip=morph)

Render the Manim scenes (compute node only; the image is not usable on head nodes):

    print(" ".join(clip.manim_command(HERE / "morphs.py", "Substitute", HERE / "clips")))

The storyboard works without the clips (a placeholder frame and a `MISSING CLIP` note), so
layout review never needs the container; draft and final refuse to run without them.
Manim scene files may import `figlib.palette` (stdlib only): the command binds the repo root
and puts it on PYTHONPATH inside the container.
"""
from __future__ import annotations

from pathlib import Path

import imageio_ffmpeg
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SIF = ROOT / "envs/manim/manim.sif"
QUALITY = {"draft": ("960,540", 15), "final": ("1920,1080", 30)}


class Clip:
    """Frames of an MP4 by time. Sequential reads stream; a backwards seek reopens the file."""

    def __init__(self, mp4: Path | str):
        self.path = Path(mp4)
        self.exists = self.path.exists()
        self.fps, self.size, self.n_frames = 30.0, (1920, 1080), 1
        self._gen, self._k, self._frame = None, -1, None
        if self.exists:
            meta = self._open()
            self.fps = float(meta["fps"])
            self.size = tuple(meta["size"])
            self.n_frames = max(1, int(round(float(meta["duration"]) * self.fps)))
            self._gen, self._k = None, -1

    @property
    def duration(self) -> float:
        return self.n_frames / self.fps

    def _open(self) -> dict:
        self._gen = imageio_ffmpeg.read_frames(str(self.path))
        self._k = -1
        return next(self._gen)

    def frame(self, t: float) -> np.ndarray:
        """RGB uint8 frame shown at clip time t; holds the last frame past the end."""
        if not self.exists:
            raise FileNotFoundError(self.path)
        k = min(max(int(t * self.fps + 1e-9), 0), self.n_frames - 1)
        if self._gen is None or k < self._k:
            self._open()
        while self._k < k:
            try:
                raw = next(self._gen)
            except StopIteration:          # metadata duration overestimated the frame count
                self.n_frames = self._k + 1
                break
            self._k += 1
            w, h = self.size
            self._frame = np.frombuffer(raw, np.uint8).reshape(h, w, 3)
        return self._frame


def render_manim(scene_file: Path | str, scene_names, out_dir: Path | str, mode: str = "final") -> list[Path]:
    """Render each Manim scene and move its MP4 to `<out_dir>/<name>.mp4`. Compute node only."""
    import shutil
    import subprocess
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outs = []
    for name in scene_names:
        subprocess.run(manim_command(scene_file, name, out_dir, mode), check=True)
        made = sorted((out_dir / "_manim" / "videos").rglob(f"{name}.mp4"), key=lambda p: p.stat().st_mtime)
        if not made:
            raise FileNotFoundError(f"manim wrote no {name}.mp4 under {out_dir / '_manim'}")
        dest = out_dir / f"{name}.mp4"
        shutil.move(str(made[-1]), dest)
        outs.append(dest)
    shutil.rmtree(out_dir / "_manim", ignore_errors=True)
    return outs


def manim_command(scene_file: Path | str, scene_name: str, out_dir: Path | str,
                  mode: str = "final", sif: Path = SIF) -> list[str]:
    """argv that renders `scene_name` from `scene_file` to `<out_dir>/<scene_name>.mp4`."""
    res, fps = QUALITY[mode]
    scene_file, out_dir = Path(scene_file).resolve(), Path(out_dir).resolve()
    work = out_dir / "_manim"
    return ["apptainer", "exec", "--bind", f"{ROOT},{out_dir}",
            "--env", f"PYTHONPATH={ROOT},TEXMFVAR={work}/texmf-var",
            str(sif), "manim", "--resolution", res, "--frame_rate", str(fps),
            "--media_dir", str(work), "-o", f"{scene_name}.mp4",
            str(scene_file), scene_name]

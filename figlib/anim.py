"""Frames -> MP4 (for slides) + GIF (for Slack) + poster PNG + contact sheet.

Added 2026-10-30. Source-agnostic: pass any iterable of RGB frames (PIL images or
HxWx3 uint8 arrays) -- matplotlib canvases, Playwright screenshots, PyMOL PNGs.

    from figlib import anim
    out = anim.write(frames, Path("figs/ensemble"), fps=24)
    # out.mp4, out.gif, out.poster, out.contact

Why it is shaped like this:

* **Frames stream into ffmpeg's stdin**, never through a directory of PNGs. A 10 s clip
  at 24 fps is 240 files per take, and the cluster rules call many-small-files a design
  smell. The one exception is a renderer that can only write files (PyMOL): give it a
  per-job scratch folder and delete it after, as `pymol_frames` does.
* **ffmpeg is the one bundled with `imageio-ffmpeg`** in `envs/analysis` (7.0.2, libx264 +
  gif). No system ffmpeg on Argo, nothing to install.
* **MP4 is H.264 / yuv420p / +faststart with even dimensions**: the combination PowerPoint
  on Windows and macOS both play without a codec pack. yuv420p requires even width and
  height, so odd frames are padded by one pixel rather than failing in the encoder.
* **The GIF is made from the MP4 with a two-pass palette** (palettegen -> paletteuse).
  A one-pass GIF uses ffmpeg's generic 256-colour palette and bands every gradient.
* **The contact sheet is the QA artifact for motion.** The LibreOffice -> PDF deck check
  shows a video slide as its poster only, so this is the only way to review the frames
  without opening PowerPoint. Thumbnails are kept at a stride that doubles as the clip
  grows: keeping every one cost ~170 KB a frame, ~0.8 GB for a 2.7 min explainer.
* **`bg` is the frame's background**, used for the edge check and the encoder's pad.
  Hard-coded white flagged every frame of a dark explainer as clipped (2026-11-02).
* **The poster defaults to the middle frame**, pulled back out of the MP4: frame 0 of a video
  that fades in from black is a blank poster (2026-11-02).
* **`delivery_copy` makes a <30 MiB copy** for sending: a 2 min 1080p final at crf 18 is
  ~42 MB, over SendUserFile's limit.
* **The GIF is skipped above 20 s unless asked for.** A minutes-long GIF is tens of MB,
  loops with no pause, and nobody watches it in Slack.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


@dataclass(frozen=True)
class Outputs:
    mp4: Path
    gif: Path | None
    poster: Path
    contact: Path | None
    n_frames: int
    clipped: tuple[int, ...] = ()   # frames with content touching the edge (see `touches_edge`)


def _rgb(frame) -> np.ndarray:
    if isinstance(frame, Image.Image):
        frame = np.asarray(frame.convert("RGB"))
    a = np.ascontiguousarray(frame[..., :3], dtype=np.uint8)
    if a.ndim != 3:
        raise ValueError(f"frame must be HxWx3, got shape {a.shape}")
    return a


def touches_edge(a: np.ndarray, bg=(255, 255, 255), tol: int = 24) -> bool:
    """True if any non-background pixel sits on the frame border.

    The animation analogue of figcheck's CLIPPED: a molecule cut off by the camera is
    invisible in review -- you cannot see the part that was never drawn -- so count it.
    """
    edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]).astype(int)
    return bool((np.abs(edge - np.array(bg)).max(axis=1) > tol).any())


GIF_MAX_S = 20     # gif=None writes a GIF only for clips up to this long


def write(frames, stem: Path, *, fps: int = 24, crf: int = 18, gif: bool | None = None,
          gif_width: int = 720, gif_fps: int = 12, poster_index: int | None = None,
          contact_n: int = 12, contact_width: int = 320, bg=(255, 255, 255)) -> Outputs:
    """Encode `frames` to `<stem>.mp4` (+ `.gif`, `_poster.png`, `_contact.png`).

    `gif=None` writes the GIF only if the clip is <= GIF_MAX_S long; pass True/False to force.
    `poster_index=None` takes the middle frame.
    """
    stem = Path(stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    mp4 = stem.with_suffix(".mp4")
    poster = stem.parent / f"{stem.name}_poster.png"

    proc, size, thumbs, n, clipped = None, None, [], 0, []
    stride, keep = 1, max(4 * contact_n, 1)   # thumbs holds every `stride`-th frame, <= keep
    pad = "0x{:02x}{:02x}{:02x}".format(*bg)
    try:
        for frame in frames:
            a = _rgb(frame)
            if proc is None:
                size = a.shape[1], a.shape[0]
                proc = subprocess.Popen(
                    [FFMPEG, "-y", "-loglevel", "error",
                     "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}",
                     "-r", str(fps), "-i", "-",
                     "-vf", f"pad=ceil(iw/2)*2:ceil(ih/2)*2:color={pad}",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(crf),
                     "-preset", "slow", "-movflags", "+faststart", str(mp4)],
                    stdin=subprocess.PIPE)
            elif (a.shape[1], a.shape[0]) != size:
                raise ValueError(f"frame {n} is {a.shape[1]}x{a.shape[0]}, first was {size}")
            proc.stdin.write(a.tobytes())
            if touches_edge(a, bg):
                clipped.append(n)
            if poster_index is not None and n == poster_index:
                Image.fromarray(a).save(poster)
            if contact_n and n % stride == 0:
                t = Image.fromarray(a)
                t.thumbnail((contact_width, contact_width * 4))
                thumbs.append(t)
                if len(thumbs) > keep:
                    thumbs, stride = thumbs[::2], stride * 2
            n += 1
    finally:
        if proc is not None:
            proc.stdin.close()
            if proc.wait() != 0:
                raise RuntimeError(f"ffmpeg failed writing {mp4}")
    if n == 0:
        raise ValueError("no frames")

    if poster_index is None:
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", f"{(n // 2) / fps:.4f}",
                        "-i", str(mp4), "-frames:v", "1", str(poster)], check=True)

    gif_path = None
    if gif or (gif is None and n / fps <= GIF_MAX_S):
        gif_path = stem.with_suffix(".gif")
        flt = f"fps={gif_fps},scale={gif_width}:-1:flags=lanczos"
        subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error", "-i", str(mp4), "-filter_complex",
             f"[0:v]{flt},split[a][b];[a]palettegen=stats_mode=diff[p];"
             f"[b][p]paletteuse=dither=sierra2_4a", str(gif_path)],
            check=True)

    contact = None
    if contact_n:
        idx = np.linspace(0, len(thumbs) - 1, min(contact_n, len(thumbs))).round().astype(int)
        picks = [thumbs[i] for i in idx]
        cols = 4
        rows = -(-len(picks) // cols)
        tw, th = picks[0].size
        sheet = Image.new("RGB", (cols * tw, rows * th), "white")
        for k, t in enumerate(picks):
            sheet.paste(t, ((k % cols) * tw, (k // cols) * th))
        contact = stem.parent / f"{stem.name}_contact.png"
        sheet.save(contact)

    return Outputs(mp4, gif_path, poster, contact, n, tuple(clipped))


def delivery_copy(mp4: Path, *, height: int = 720, crf: int = 26) -> Path:
    """Re-encode `mp4` smaller, to `<stem>_send.mp4`, for channels with a size cap."""
    mp4 = Path(mp4)
    out = mp4.with_name(f"{mp4.stem}_send.mp4")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(mp4),
                    "-vf", f"scale=-2:{height}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", str(crf), "-preset", "slow", "-movflags", "+faststart", str(out)],
                   check=True)
    return out


def png_frames(paths):
    """Yield frames from PNG files in order (for renderers that can only write files)."""
    for p in paths:
        with Image.open(p) as im:
            yield im.convert("RGB")

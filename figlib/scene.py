"""Explainer videos: scenes on a cue timeline, rendered as storyboard, draft or final.

Added 2026-11-02 after the first explainer (`explainers/20261102_flux_model/`) cost three
cluster renders to get right. Each failure maps to a rule here:

* **A scene is `draw(t)`: a pure function of its local time.** The 11-02 script was one
  generator chain, so seeing scene 6 meant simulating scenes 1-5, nothing could be
  previewed, and a scene-3 bug cost a job. A pure `draw(t)` can be called at any t, in
  any order, which is what makes the storyboard possible.
* **`draw` never advances a model.** Simulate first, into arrays indexed by frame, then
  draw from them. In the 11-02 script the on-screen transit of a copy also froze its model
  state, and tau_nuc read 2.3 h against 1.0 true: a bias that hides inside a drawing loop.
  `render(checks=...)` runs the video's model checks BEFORE any frame, and a failing check
  fails the run.
* **Every fade is a `Cue`, clamped to [0, 1].** Hand-written `ramp(i - 300)` offsets went
  negative and crashed matplotlib (job 13308168).
* **Captions are timed from word count** (2.5 words/s, 1.5 s minimum: slower than reading
  speed because the viewer is also watching motion) and written as `.srt` beside the
  video, so a narration can replace them later.
* **Three modes.** `storyboard`: one still per caption, each run through `figcheck`, one
  contact PNG, on the head node in seconds. `draft`: 960x540 at 15 fps. `final`: 1920x1080
  at 30 fps. Draft halves the figure dpi, so the layout is identical, only smaller.
* **The storyboard tests purity, not just layout (2026-11-13).** Every still is drawn twice,
  once in scene order and once straight after a still from far away in the list, and any
  still whose pixels change is reported `IMPURE`. A `draw(t)` that reads state another scene
  left behind looks right in scene order, which is the only order a contact sheet shows.

    from figlib import scene
    tl = scene.Timeline().at("eq", 1.0, 0.5)
    caps = scene.caption_track(["First point.", "Second point."], start=0.5)
    s = scene.Scene("intro", caps[-1].end + 0.5, draw=lambda t: eq.set_alpha(tl("eq", t)),
                    captions=caps)
    scene.render(fig, [s], "storyboard", stem, caption=cap_artist, checks=[my_check])

`EqRow` is the bracketed-equation primitive: a row of mathtext pieces laid out left to
right from their measured extents, with a labelled bracket under any piece. It fails at
construction on a piece mathtext cannot parse (`\\big` crashed the 11-13 storyboard mid-draw
instead), and at `layout()` when the row runs past `max_x` of the figure.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
from matplotlib.lines import Line2D
from matplotlib.mathtext import MathTextParser
from PIL import Image, ImageDraw

from figlib import anim, figcheck

MODES = {"storyboard": (None, 1.0), "draft": (15, 0.5), "final": (30, 1.0)}   # fps, dpi scale
WPS, MIN_CAPTION_S, CAPTION_GAP_S = 2.5, 1.5, 0.3


# ------------------------------------------------------------------ cues
def smooth(x: float) -> float:
    return x * x * (3 - 2 * x)


EASE = {"smooth": smooth, "linear": lambda x: x}


@dataclass(frozen=True)
class Cue:
    """0 before `start`, 1 after `start + dur`, eased in between. Never outside [0, 1]."""
    start: float
    dur: float = 0.5
    ease: str = "smooth"

    def __call__(self, t: float) -> float:
        if self.dur <= 0:
            return float(t >= self.start)
        x = min(1.0, max(0.0, (t - self.start) / self.dur))
        return float(EASE[self.ease](x))


class Timeline:
    """Named cues for one scene, in that scene's local seconds."""

    def __init__(self):
        self.cues: dict[str, Cue] = {}

    def at(self, name: str, start: float, dur: float = 0.5, ease: str = "smooth") -> "Timeline":
        self.cues[name] = Cue(start, dur, ease)
        return self

    def __call__(self, name: str, t: float) -> float:
        return self.cues[name](t)

    def window(self, name_in: str, name_out: str, t: float) -> float:
        """Fades in on `name_in`, out on `name_out`."""
        return self(name_in, t) * (1 - self(name_out, t))


# ------------------------------------------------------------------ captions
@dataclass(frozen=True)
class Caption:
    start: float
    end: float
    text: str


def caption_seconds(text: str, wps: float = WPS, min_s: float = MIN_CAPTION_S) -> float:
    return max(min_s, len(text.split()) / wps)


def caption_track(texts: Sequence[str], start: float = 0.0, wps: float = WPS,
                  min_s: float = MIN_CAPTION_S, gap: float = CAPTION_GAP_S) -> list[Caption]:
    """Back-to-back captions, each on screen for as long as it takes to read."""
    out, t = [], start
    for text in texts:
        d = caption_seconds(text, wps, min_s)
        out.append(Caption(t, t + d, text))
        t += d + gap
    return out


def caption_at(track: Sequence[Caption], t: float, fade: float = 0.3) -> tuple[str, float]:
    """(text, alpha) of the caption on screen at t; ('', 0) between captions."""
    for c in track:
        if c.start <= t < c.end:
            return c.text, min(Cue(c.start, fade)(t), 1 - Cue(c.end - fade, fade)(t))
    return "", 0.0


def _stamp(s: float) -> str:
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def write_srt(path: Path, captions: Sequence[Caption]) -> Path:
    path = Path(path)
    path.write_text("".join(f"{k}\n{_stamp(c.start)} --> {_stamp(c.end)}\n{c.text}\n\n"
                            for k, c in enumerate(captions, 1)))
    return path


# ------------------------------------------------------------------ equations
class EqRow:
    """Mathtext pieces laid out left to right; `bracket(i, ...)` labels piece i from below.

    Layout is measured from the rendered extents, so call `layout()` once after the
    figure exists (and after any change to the pieces' size). Positions are figure
    fractions, so a draft render at half dpi keeps the same layout.
    """

    _PARSER = MathTextParser("path")

    def __init__(self, fig, parts: Sequence[str], x: float, y: float, size: float = 36,
                 color: str = "white", gap: float = 0.006, max_x: float = 0.99):
        for p in parts:
            if p.count("$") >= 2:
                try:
                    self._PARSER.parse(p)
                except ValueError as e:
                    why = [ln for ln in str(e).strip().splitlines() if ln.strip()][-1]
                    raise ValueError(f"EqRow piece {p!r} is not valid mathtext: {why}") from None
        self.fig, self.x, self.y, self.gap, self.max_x = fig, x, y, gap, max_x
        self.texts = [fig.text(x, y, p, fontsize=size, color=color, va="baseline", alpha=0)
                      for p in parts]
        self.brackets: dict[int, tuple[Line2D, object]] = {}
        self.boxes = []

    def layout(self) -> "EqRow":
        r = self.fig.canvas.get_renderer()
        inv = self.fig.transFigure.inverted()
        x = self.x
        for t in self.texts:
            t.set_x(x)
            x += t.get_window_extent(r).transformed(inv).width + self.gap
        self.boxes = [t.get_window_extent(r).transformed(inv) for t in self.texts]
        right = max(b.x1 for b in self.boxes)
        if right > self.max_x:
            raise ValueError(f"EqRow {''.join(t.get_text() for t in self.texts)!r} reaches x = {right:.3f} "
                             f"of the figure (max_x {self.max_x}); shrink `size` or move `x` left")
        return self

    def bracket(self, i: int, label: str, color: str, drop: float = 0.012,
                size: float = 22) -> "EqRow":
        if not self.boxes:
            self.layout()
        bb = self.boxes[i]
        y = min(b.y0 for b in self.boxes) - drop
        x0, x1 = bb.x0 + 0.003, bb.x1 - 0.003
        ln = Line2D([x0, x0, x1, x1], [y + 0.012, y, y, y + 0.012],
                    transform=self.fig.transFigure, color=color, lw=3, alpha=0,
                    solid_capstyle="butt")
        self.fig.add_artist(ln)
        tx = self.fig.text((x0 + x1) / 2, y - 0.008, label, ha="center", va="top",
                           fontsize=size, color=color, alpha=0, multialignment="center")
        self.brackets[i] = (ln, tx)
        return self

    def set_alpha(self, a: float) -> None:
        for t in self.texts:
            t.set_alpha(a)

    def set_bracket(self, i: int, a: float, glow: float = 0.0) -> None:
        """Show bracket i at alpha a; glow in [0, 1] thickens it (e.g. on an event)."""
        ln, tx = self.brackets[i]
        ln.set_alpha(a); tx.set_alpha(a)
        ln.set_linewidth(3 + 5 * glow * a)

    def hide(self) -> None:
        self.set_alpha(0)
        for i in self.brackets:
            self.set_bracket(i, 0)

    def shift(self, dy: float) -> None:
        """Move the row and its brackets by dy (figure fraction) from the laid-out position."""
        for t in self.texts:
            t.set_y(self.y + dy)
        for i, (ln, tx) in self.brackets.items():
            base = getattr(ln, "_scene_y", None)
            if base is None:
                ln._scene_y, tx._scene_y = list(ln.get_ydata()), tx.get_position()[1]
            ln.set_ydata([v + dy for v in ln._scene_y]); tx.set_y(tx._scene_y + dy)


# ------------------------------------------------------------------ scenes and rendering
@dataclass
class Scene:
    """`draw(t)` sets every artist the scene uses for local time t in [0, duration).

    It must be a pure function of t: no model stepping, no state carried between calls.
    `captions` are in local seconds; `keyframes` adds storyboard stills. `clip` (a
    `figlib.clip.Clip`) shows a pre-rendered video full-frame over everything but the caption,
    frame by frame at local time t; `_show` hides it again for every scene without one.
    """
    name: str
    duration: float
    draw: Callable[[float], None]
    captions: Sequence[Caption] = ()
    keyframes: Sequence[float] = field(default_factory=tuple)
    clip: object = None

    def storyboard_times(self) -> list[float]:
        ts = [c.start + 0.75 * (c.end - c.start) for c in self.captions] + list(self.keyframes)
        return sorted(ts) or [self.duration / 2]


def grab(fig) -> np.ndarray:
    fig.canvas.draw()
    return np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()


def global_captions(scenes: Sequence[Scene]) -> list[Caption]:
    out, t0 = [], 0.0
    for s in scenes:
        out += [Caption(t0 + c.start, t0 + c.end, c.text) for c in s.captions]
        t0 += s.duration
    return out


CLIP_Z = 1000


def _clip_layer(fig):
    """The full-figure axes clips are shown in, created on first use, one per figure."""
    ax = getattr(fig, "_scene_clip_ax", None)
    if ax is None:
        ax = fig.add_axes([0, 0, 1, 1], zorder=CLIP_Z)
        ax.axis("off")
        ax.set_gid("figlib-scene-clip")
        im = ax.imshow(np.zeros((9, 16, 3), np.uint8), aspect="auto", interpolation="antialiased")
        fig._scene_clip_ax, fig._scene_clip_im = ax, im
    return ax, fig._scene_clip_im


def _placeholder(clip) -> np.ndarray:
    w, h = 480, 270
    im = Image.new("RGB", (w, h), (40, 40, 38))
    ImageDraw.Draw(im).text((12, h // 2 - 8), f"MISSING CLIP: {Path(clip.path).name}", fill=(255, 210, 0))
    return np.asarray(im)


def _show(fig, s: Scene, t: float, caption) -> None:
    s.draw(t)
    if s.clip is not None:
        ax, im = _clip_layer(fig)
        im.set_data(s.clip.frame(t) if s.clip.exists else _placeholder(s.clip))
        ax.set_visible(True)
        if caption is not None:
            caption.set_zorder(CLIP_Z + 1)
    elif getattr(fig, "_scene_clip_ax", None) is not None:
        fig._scene_clip_ax.set_visible(False)
    if caption is not None:
        text, a = caption_at(s.captions, t)
        caption.set_text(text); caption.set_alpha(a)


def frames(fig, scenes: Sequence[Scene], fps: int, caption=None):
    """Yield every frame of the video at `fps`."""
    for s in scenes:
        for k in range(int(round(s.duration * fps))):
            _show(fig, s, k / fps, caption)
            yield grab(fig)


def run_checks(checks: Sequence[Callable[[], None]]) -> None:
    """Model checks run before any frame is drawn; any exception fails the render."""
    for c in checks:
        c()


LABEL_H = 16           # storyboard: label strip above each still, so it never covers a caption
IMPURE_FRAC = 1e-4     # share of thumbnail pixels allowed to differ between the two passes


def _thumb(fig, width: int) -> Image.Image:
    im = Image.fromarray(grab(fig))
    im.thumbnail((width, width))
    return im


def storyboard(fig, scenes: Sequence[Scene], stem: Path, caption=None, cols: int = 4,
               width: int = 480, purity: bool = True) -> tuple[Path, list[str]]:
    """One still per caption (+ keyframes), checked by figcheck, tiled into one PNG.

    With `purity`, every still is drawn a second time straight after a still from far away in
    the list and compared with the first: a still that changes depends on what was drawn before
    it (`IMPURE`). What reordering cannot see is an artist set once and never reset by anyone:
    it looks the same in every order, so it shows on the sheet itself, in scene order.
    """
    stills = [(s, t) for s in scenes for t in s.storyboard_times()]
    thumbs, notes = [], []
    for s in scenes:
        if s.clip is not None and not s.clip.exists:
            notes.append(f"{s.name}  MISSING CLIP: {s.clip.path} (placeholder shown; render it with "
                         f"figlib.clip.render_manim on a compute node before draft/final)")
    for s, t in stills:
        _show(fig, s, t, caption)
        for f in figcheck.check(fig):
            notes.append(f"{s.name} t={t:.1f}s  {f.kind}: {f.what}  ({f.detail})")
        thumbs.append(_thumb(fig, width))
    if purity and len(stills) > 1:
        n = len(stills)
        for k in range(n):
            s, t = stills[k]
            other = stills[(k + max(1, n // 2)) % n]          # a still far away, usually another scene
            _show(fig, *other, caption)                       # sets artists only; no canvas render
            _show(fig, s, t, caption)
            a, b = np.asarray(thumbs[k], int), np.asarray(_thumb(fig, width), int)
            frac = float((np.abs(a - b).max(axis=2) > 8).mean()) if a.shape == b.shape else 1.0
            if frac > IMPURE_FRAC:
                notes.append(f"{s.name} t={t:.1f}s  IMPURE: draw(t) depends on what was drawn before  "
                             f"({frac:.2%} of pixels change when drawn after another still; reset every "
                             f"artist this scene uses, and hide every artist other scenes use)")
    tw, th = thumbs[0].size
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (cols * tw, rows * (th + LABEL_H)), "black")
    for k, ((s, t), im) in enumerate(zip(stills, thumbs)):
        x, y = (k % cols) * tw, (k // cols) * (th + LABEL_H)
        sheet.paste(im, (x, y + LABEL_H))
        ImageDraw.Draw(sheet).text((x + 4, y + 2), f"{s.name}  {t:.1f}s", fill=(255, 210, 0))
    out = Path(stem).parent / f"{Path(stem).name}_storyboard.png"
    sheet.save(out)
    return out, notes


def render(fig, scenes: Sequence[Scene], mode: str, stem: Path, *, caption=None,
           checks: Sequence[Callable[[], None]] = (), bg=(255, 255, 255), **write_kw):
    """Run the model checks, then render `scenes` in `mode` (storyboard | draft | final).

    storyboard returns (contact PNG, figcheck notes). draft/final write `<stem>[_draft].mp4`
    via `anim.write` plus a `.srt` of the captions, and return anim's Outputs.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {sorted(MODES)}, got {mode!r}")
    run_checks(checks)
    stem = Path(stem)
    missing = [str(s.clip.path) for s in scenes if s.clip is not None and not s.clip.exists]
    if missing and mode != "storyboard":
        raise FileNotFoundError(f"{mode} needs every clip rendered first; missing: {missing}")
    if mode == "storyboard":
        return storyboard(fig, scenes, stem, caption)
    fps, scale = MODES[mode]
    dpi0 = fig.dpi
    fig.set_dpi(dpi0 * scale)
    try:
        if mode == "draft":
            stem = stem.parent / f"{stem.name}_draft"
        write_srt(stem.with_suffix(".srt"), global_captions(scenes))
        return anim.write(frames(fig, scenes, fps, caption), stem, fps=fps, bg=bg, **write_kw)
    finally:
        fig.set_dpi(dpi0)

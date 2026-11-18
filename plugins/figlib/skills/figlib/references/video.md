# Animations and explainer videos

Needs the `video` extra (imageio-ffmpeg; no system ffmpeg required).

## Frames → MP4 / GIF / poster / contact sheet

```python
from figlib import anim
out = anim.write(frames, Path("figs/ensemble"), fps=24, bg=(255, 255, 255))
# out.mp4, out.gif (only if <= 20 s unless gif=True), out.poster (middle frame), out.contact, out.clipped
small = anim.delivery_copy(out.mp4)     # 720p copy for chat/email size limits
```

- `frames` is any iterable of RGB frames (PIL images or HxWx3 uint8 arrays). Stream them from a
  generator; don't write a folder of PNGs. Only a renderer that can only write files (e.g. PyMOL)
  should use `anim.png_frames(paths)`, with the PNGs in a temp folder.
- Set `bg` to the real background colour, or every frame of a dark video reports as clipped.
- **Review `out.contact`** (a tiled sheet of frames) to check the motion, and **check `out.clipped`**:
  frames where content touches the edge, i.e. something was cut off by the camera.

## Explainer videos (figlib.scene)

A video is a list of `Scene`s. Each scene's `draw(t)` sets every artist it uses for local time `t`.

```python
from figlib import scene
tl = scene.Timeline().at("eq", 1.0, 0.5)                   # named fades: start s, duration s
caps = scene.caption_track(["First point.", "Second point."], start=0.5)   # timed from word count
s = scene.Scene("intro", caps[-1].end + 0.5,
                draw=lambda t: eq.set_alpha(tl("eq", t)), captions=caps)
scene.render(fig, [s], "storyboard", stem, caption=cap_artist, checks=[model_check])
```

Rules:
- **`draw(t)` must be a pure function of `t`.** Simulate the model first, into arrays indexed by
  frame, then draw from them. Never step a model inside `draw`. Reset every artist the scene uses
  and hide the ones other scenes use.
- Use `Timeline` / `Cue` for fades (values are clamped to [0, 1]); don't hand-write ramps.
- Pass model sanity checks as `checks=[...]`; they run before any frame and fail the render.

Work in this order:
1. `storyboard`: one still per caption, each run through figcheck, tiled into one PNG, in seconds.
   It also redraws every still out of order and reports `IMPURE` if its pixels change — fix
   those before rendering. Look at the storyboard PNG.
2. `draft`: 960×540 at 15 fps, same layout.
3. `final`: 1920×1080 at 30 fps. Captions are also written as `.srt`.

`scene.EqRow(fig, parts, x, y)` lays out mathtext pieces in a row with `bracket(i, label, color)`
labels underneath; call `.layout()` after the figure exists. It raises on invalid mathtext or a row
wider than the figure.

## Manim clips (figlib.clip)

For equation morphs only: render with Manim, then show the MP4 as a scene with
`Scene(..., clip=clip.Clip(mp4))`; captions are still drawn by matplotlib on top.
`clip.render_manim(scene_file, ["SceneName"], out_dir)` runs Manim inside an Apptainer image: set
`FIGLIB_MANIM_SIF` to the image's path, or pass `sif=` (it raises if neither is set). The storyboard shows a placeholder for a missing clip;
draft and final refuse to run without it.

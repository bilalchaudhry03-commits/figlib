---
name: explainer-video
description: Make a short standalone explainer video (MP4) that teaches a model, equation set or mechanism, e.g. a stochastic simulation drawn alongside the equations it obeys, using figlib.scene and figlib.anim. Use when asked for an explainer, animation, teaching video or "show me how this works" walkthrough of a concept. Not for slide figures (see scientific-figure-design) or a simple movie of frames for a deck (figlib.anim alone).
---

# Explainer videos

Standalone videos watched at a desk, so they can carry captions. Built on `figlib.scene` (scenes,
cue timeline, captions, storyboard) and `figlib.anim` (encoding and QA). The API, with examples, is
in the figlib skill's `references/video.md` and `figlib/scene.py`'s docstring. This file covers the
workflow and why each gate exists.

## Layout

One folder per video: the script, the job script if it renders on a cluster, and the outputs beside
them. Commit the scripts; don't commit `.mp4 .gif .png .npz .srt`. Model code that belongs to a
project is imported from that project, not copied into the video script.

## The order, and why each gate exists

1. **Model check first, before any drawing.** Simulate once, seeded, into arrays indexed by frame.
   Assert that the simulation recovers what the equations say (e.g. measured mean residence time = τ
   within tolerance), and pass those assertions as `scene.render(checks=[...])` so they run before
   frame 0 in every mode.
   *Why:* in the first explainer, molecules drawn crossing a pore were also frozen in the model, and
   the nuclear residence time read 2.3 h against a true 1.0 h. The picture looked right; only a
   measured check could see it.
   **Measure the way the video displays it.** A check that averaged only *completed* stays dropped
   the long recent ones (3.29 h vs 3.60), and the same bias was on screen.
   Rendering never advances the model.
2. **Storyboard** (seconds, no cluster needed): one still per caption on one sheet, each run through
   `figcheck`, plus the purity check, which redraws stills out of order and reports `IMPURE` if pixels
   change. Look at it, and show the user if the structure is new, before rendering anything.
   *Why:* the first explainer was one generator chain, and a bug in scene 3 cost a full render.
3. **Draft** (960×540, 15 fps): watch for pacing and motion, which stills can't show.
4. **Final** (1920×1080, 30 fps). Pass `bg=` if the background isn't white, or every frame is
   reported clipped. Check `out.clipped` and the contact sheet.

Draft and final are long CPU jobs. On a shared cluster, submit them as batch jobs.

## Content rules

- **One idea per scene.** Captions ≤ ~15 words, timed from word count (`scene.caption_track`).
- **Equations appear as the thing they describe happens,** with the active term highlighted on its
  event. That coupling is the point of the format.
- **Same numbers as the documents.** Parameters come from the derivation or the project's code, and
  the script's header cites where. A video that teaches a different model than the paper or proposal
  is worse than none.
- Units on every axis and every clock; say when time is in model units.
- **Each `draw(t)` states its whole frame.** Start it by resetting every artist the scene owns and
  hiding the ones other scenes use, so a still at any `t` is correct without the scenes before it.
  `figcheck` skips hidden axes and fully transparent text, so faded artists are not linted.
- Colours from `figlib.palette`; Carlito/Calibri; text ≥ 24 px at 1080p.
- No GIF unless asked (`anim.write` skips it above 20 s).

## Equation morphs (Manim)

Only for clips where an equation's terms morph into another equation. Render the clip with
`figlib.clip.render_manim(...)` inside the Manim Apptainer image (set `FIGLIB_MANIM_SIF` or pass
`sif=`; on clusters this usually means a compute node), then show it as
`Scene(..., clip=clip.Clip(mp4))`. Captions stay matplotlib's, drawn on top. Everything else stays
in matplotlib, so the model checks, storyboard and modes still apply. The storyboard shows a
placeholder for a missing clip; draft and final refuse to run without it.

## Delivering

Give the path to the final MP4. A 2-minute 1080p final is ~40 MB, so if it's going through a channel
with an upload cap, send `anim.delivery_copy(mp4)` (720p, written beside it as `_send.mp4`) and give
the full final's path. Say what the model check measured (e.g. "τ_nuc recovered 1.05 h vs 1.0") and
anything left unfixed.

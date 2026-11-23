---
name: talk
description: Build and iterate on a slide deck (talk, lab meeting, journal club, committee meeting, defense, conference talk) as a Markdown outline that figlib turns into a .pptx, rendering the slides to look at after every change. Use whenever someone asks for slides, a deck, a presentation or a talk, or to revise one made this way. Not for a single figure (see the figlib and scientific-figure-design skills).
---

# Talks as outlines

The outline (`talk.md`) is the source; the `.pptx` is generated from it and overwritten on every
build. You edit the outline, build, render, look at the slides, and edit again. That loop, done
many times, is what makes the deck good — so run it every time, not just at the end.

## Setup (once per session)

figlib must be installed: follow the setup block in the `figlib` skill. Then check LibreOffice,
which the render step uses:

```bash
python -c "from figlib import render; print(render.find_soffice())"
```

If it isn't found, ask the user to install it (libreoffice.org/download, or
`brew install --cask libreoffice` on a Mac, `winget install TheDocumentFoundation.LibreOffice` on
Windows) — about 1 GB, once. On a cluster without it, an Apptainer image can be named in
`FIGLIB_LIBREOFFICE_SIF` (run renders on a compute node). Without a render you are building blind:
say so rather than skipping it.

## Starting a talk

1. **Storyline first, before any figure.** Ask for (or draft and confirm) the talk's audience,
   length and the 5–15 claims it makes, one per slide. Each slide title is a claim the audience
   should walk away with ("Larger proteins enter the nucleus more slowly"), not a topic ("Results").
2. Scaffold: `python -m figlib.outline --starter <folder>` copies a five-slide starter (outline,
   a figcheck'd matplotlib script, a click-by-click schematic). Replace its slides with the storyline;
   keep the front matter (`author:`; `logo:` only if they have one).
3. Write each slide's speaker notes under `notes:` as you go: what to say, numbers, caveats.

## The format

```markdown
---
author: Your Name
---
### S01 · Talk title
section: title

### S02 · The claim this slide makes
figure: figs/panel.svg
notes:
What to say.

### B01 · A backup slide
- one-line bullet
```

`### S01 · …` main slides, `### B01 · …` backup; a heading without an id is ignored. Key lines:
`figure:`, `build:` (a layer per click), `equation:` (mathtext, no `$`; use `\dfrac`), `derivation:`
(equations revealed line by line), `movie: label | a.mp4 | poster.png`, `tag: Expected result`
(for illustrative data), `animation:`, `- bullet`, `notes:`. The full reference is
`python -m figlib.outline --help` plus the module docstring (`python -c "import figlib.outline as o; help(o)"`).
Paths are relative to the outline (or to `root:` in the front matter).

## The loop

```bash
python -m figlib.outline talk.md       # build; exits 1 and lists any MISSING figure
python -m figlib.render talk.pptx      # talk_render/contact.png + slide-NN.png
```

1. Build. A MISSING line is a figure you still owe; make it or remove the line.
2. Render, then **Read `talk_render/contact.png`** for the whole deck, and the full-size
   `slide-NN.png` of every slide you changed.
3. Critique each changed slide against the checklist below, fix the outline or the figure, repeat.
4. Tell the user what changed, by slide id ("S04: title shortened; S07: new panel B"), and which
   slides they should look at in PowerPoint.

**Read the render's warnings.** `layers stacked` slides have click builds or animations: the render
draws every layer at once, so overlapping layers there are expected — check the HTML layers or
`<stem>_preview/` frames instead, and tell the user to check those clicks in PowerPoint. A `FONT`
line (exit 1) means text was measured in the wrong typeface; the render's line breaks can't be
trusted until it's fixed.

## Checklist for every slide

- The title is one claim and fits on one line (two at most). If it wraps badly, shorten it.
- One idea per slide; the figure is the evidence for the title, legible from the back of the room.
- No secondary text: no subtitles, captions, footnotes or grey text. `deck.require_clean` fails the
  build on grey or sub-18 pt text; detail goes in `notes:`.
- Figures: made with figlib's checks (figcheck for matplotlib; check_layout + export_svg for
  schematics, via the `scientific-figure-design` skill). One colour per entity across the whole deck.
- Nothing overflows the slide or collides in the render.
- Illustrative (not real) data carries `tag: Expected result`.

## Figures and builds

- Keep each figure's source next to it in `figs/` (script or HTML) and regenerate rather than
  hand-editing an SVG.
- Specific proteins or complexes: real silhouettes from structures, not screenshots or made-up blobs:
  `python -m figlib.silhouette <UniProt IDs or cofold.cif> --svg figs/x.svg` (details in the
  `scientific-figure-design` skill). Offer this whenever a slide shows proteins.
- Panel-by-panel builds: group the HTML figure into `<g id="L1">`, `L2`, … with a `<rect id="bg">`,
  then `python -m figlib.layers build figs/fig.html L1 L2 L3`, and in the outline
  `figure: figs/fig_L1.svg` followed by `build:` lines for L2, L3.
- Motion: `python -m figlib.layers anim figs/fig.html` (the figure defines `window.ANIM` and
  `window.ANIM_STATE`; see `python -c "import figlib.layers as m; help(m)"`), then `animation:` in the
  outline. Look at `figs/<stem>_preview/` to check each click.

## Rules

- Never edit the `.pptx`. If the user has edited the .pptx by hand, ask before rebuilding (it will
  overwrite their edits) and carry their changes into the outline first.
- Don't renumber slide ids when reordering; they are labels, and the footer numbers come from order.
- Keep the deck building at every step; a build that exits 1 is not a deck to hand over.
- When handing over: the .pptx path, the contact sheet, slides with clicks/animations to check in
  PowerPoint, and anything still MISSING or marked `[DRAFT]` in notes.

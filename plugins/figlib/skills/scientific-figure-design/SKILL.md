---
name: scientific-figure-design
description: Design clear, accurate scientific diagrams and schematics (pipelines, mechanisms, structural cartoons, model architectures, method comparisons) for talks, lab meetings and papers, built as HTML+SVG and exported with figlib for PowerPoint or Illustrator. Use when asked to draw or redesign a schematic, diagram, cartoon or slide figure. Covers layout choice, colour roles, type sizing for projection, and the export traps. For the figlib API itself see the figlib skill; for charts of quantitative data use matplotlib with figcheck, not this.
---

# Scientific figure design

The audience sees the figure once, projected, for about 30 seconds. Its job is to be understood
correctly and quickly, not to have a visual identity. If a stylistic choice (gradient, shadow,
clever layout) competes with the content, cut it. The reader should forget the figure was designed.

## Diagram or chart?

- **Diagram** (pipeline, mechanism, spatial cartoon, architecture, annotated concept): HTML+SVG,
  following this skill.
- **Chart** (anything plotting numbers: curves, bars, histograms, scatter): matplotlib, linted with
  `figcheck` (see the figlib skill).
- A slide that needs both gets two figures made with two tools. Don't force one into the other.

If a figure script reads data, declare it up front with `figlib.inputs.require(path, why=...)`, so a
missing input fails in one line before any work is done.

## Before drawing anything

Name the figure's one job. That decides the layout primitive:

| job | primitive |
|---|---|
| ordered steps (pipeline, workflow) | left-to-right flow |
| spatial relationship (chain layout, compartments) | spatial / radial |
| data flow through components (model architecture) | layered blocks |
| before/after, method A vs B | small multiples, aligned |

Don't default to boxes-and-arrows if the content isn't actually sequential. Sketch the entities and
the one relationship in words before touching colour or fonts.

## Colour

Take colours from `figlib.palette`, not from memory: `print(pal.as_css_vars())` gives the CSS
variables to paste into the figure's `<style>`. Use `pal.SERIES` in order (the order is what keeps
it colour-blind safe), `pal.ROLE` greys for text and structure, and run `pal.validate(colors)` on
any custom set before using it.

Decide what each colour is *doing*, because there are two different jobs:

- **Identity:** *which object is this?* Fixed across the whole talk. If importin-β is blue on
  slide 3, it is blue on slide 9.
- **Argument:** *what does it mean here?* For example broken / fixed / held out. A different
  object takes the role on each slide, so drawing it in its identity colour would say the wrong
  thing.

Don't collapse the two. Beyond that: flat categorical fills, no gradients. Grey for de-emphasised
context, so colour is reserved for what matters. Keep a mapping that appeared in an earlier figure
of the same talk rather than inventing a new one.

**Grey is for shapes and strokes, not for text.** No grey sub-line under a label, no grey caption,
subtitle or "note" text in the figure: a projected audience can't read it and won't try. If a note is
worth showing, make it a real label in ink; otherwise it belongs in the speaker notes. Axis ticks and
labels on charts are the exception.

## Type: do the slide arithmetic

"Looks fine in the browser" is not the test. The figure fills the browser at any viewBox, so type
that reads comfortably on screen can land at 7 pt on the slide.

```
figure fitted to slide WIDTH:   rendered pt = font-size × 960 / viewBox-width
figure fitted to slide HEIGHT:  rendered pt = font-size × 540 / viewBox-height
```

- In a 1700-wide viewBox one unit is 0.565 pt, so 13 px text renders at 7.3 pt.
- Aim for ≥ 11 pt body and ≥ 16 pt headers. In a 1700-wide viewBox that means ≥ 20 px body text.
- **A figure taller than 16:9 is fitted to slide height, and there raising font sizes can make type
  smaller.** Bigger text reflows taller, the viewBox grows, and the ratio falls. One real case: an
  1880×1300 figure at 14 px rendered at 5.8 pt. A 1.43× font bump should have reached 8.3 pt, but the
  content grew to ~1560 tall and it landed at 6.9 pt. The fixes
  there are cutting content or splitting across slides. That is an editorial call, so raise it with
  the user rather than silently rescaling.
- **Measure headroom before rescaling.** Compare each label's `getBBox().width` with its container.
  Often one row of headers is the binding constraint, and splitting them onto two lines is the
  cheapest way to unlock a larger size.

One sans-serif family (declare `figlib.fonts.STACK`). Hierarchy by size and weight only. Sentence
case, short labels, labelled directly on the element instead of a legend when there are ≤ 5–6
categories.

## Structure

- Align everything to a grid: shared margins, equal gutters, common baselines.
- One stroke weight for structure, one thinner one for connectors. Don't vary weight for decoration.
- No shadows, gradients, rounded "card" chrome or bevels.
- Arrows only for real relationships (flow, sequence, causality), never to fill space.
- Separate groups with white space before reaching for a divider or box.

## Check with the linter, not by eye

Run `python -m figlib.check_layout fig.html` and fix everything it reports *before* looking at a
screenshot. It finds text overflow, text-on-text collisions, type below the projection floor and
missing glyphs. Screenshot review misses a few units of overhang at a scaled-down edge, and spending
render-look-patch rounds on collisions a script can find is the biggest waste in this workflow.

**Know what it does not check.** It compares text boxes with each other and with the canvas. It
does not see:

- text sitting on artwork (a label that slid onto a shape when the figure was scaled);
- text overflowing its own container (a label in a fixed-radius badge);
- a stylesheet class silently overriding a `font-size` you set in JS.

So any change that scales type needs a before/after crop of the densest region, looked at by eye.
Several "fixed" figures have linted clean while visibly broken. Raising type size means re-laying out:
moving labels off artwork, growing containers, opening line spacing. It is not a parameter to sweep.

Then look at the rendered figure and ask the question no linter can answer: could someone who missed
the spoken explanation read this correctly in 30 seconds?

## Authoring rules that survive export

`python -m figlib.export_svg fig.html fig.svg --group` turns the live page into a standalone SVG.
It handles script-computed geometry, CSS variables (in attributes, class rules and inline
`style=`), missing intrinsic size, SVG 2 arrowheads and XML-invalid `--` in comments for you, so
don't hand-patch the SVG for any of those; if an export looks wrong, fix the HTML or report it.

One authoring rule still matters on screen: set each property one way (an attribute or a class
rule, not both), because a class rule silently beats an attribute.

Read the line the exporter prints. It reports the size it emitted, and a figure sized to slide
*height* is telling you it is taller than 16:9 and its type will render small.

The HTML is the source of truth and the SVG is a build artefact. Re-export after every edit, never
hand-edit the SVG: the next re-export silently discards the hand edits. Text stays live
`<text>` (editable in Illustrator); outline it by hand only if font fidelity matters more than
editability. For PowerPoint, the SVG with a PNG fallback (`figlib.deck.add_figure`) is the safe
form.

## Process

1. Name the job, pick the primitive, write the entities and relationship in words.
2. Build it flat and in greyscale first; get layout and labels right.
3. Add colour by role (identity vs argument), from the palette.
4. `check_layout` until clean, then look at it at slide size and self-critique the 30-second read.
5. Export with `export_svg --group`, read the size line, hand over the SVG.

## Not frontend-design

Don't use product-UI design guidance (signature elements, aesthetic risk, motion for delight) for
these figures. That optimises for distinctiveness; here the goal is the opposite.

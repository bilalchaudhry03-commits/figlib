# Building a .pptx with figlib.deck

Needs the `deck` extra (python-pptx, cairosvg).

```python
from pathlib import Path
from figlib import deck

theme = deck.Theme()                      # house style; override fields (accent, font, logo, rule, ...)
prs = deck.new_presentation()             # 16:9
deck.title_slide(prs, theme, "Talk title", "Author")

slide, box = deck.content_slide(prs, theme, "One-sentence takeaway as the title", footer="Lab meeting")
deck.add_figure(slide, Path("figs/panel.svg"), box, cache_dir=Path("build/cache"))
deck.set_notes(slide, "Speaker notes.")

deck.require_clean(prs)                   # fails on grey or < 18 pt text outside the footer
prs.save("talk.pptx")
```

## Rules the API enforces

- **Title + main content only.** There are no subtitle, caption or sub-bullet parameters, and
  `require_clean` fails on non-footer text that is grey or under 18 pt. Put the takeaway in the title;
  put detail in speaker notes. Always call `require_clean` before saving.
- `content_slide` returns `(slide, box)`; place content inside `box`.
- `add_figure`: an `.svg` goes in as vector with a PNG fallback (PowerPoint 2019/365 shows the
  vector); anything else goes in as a raster. Prefer SVG from `export_svg` or `savefig(..., format="svg")`.
- `bullets(slide, box, items, theme)` is top-level only.

## Equations

```python
pic, rest = deck.add_equation(slide, r"\tau = \dfrac{V}{k\,A}", box, cache)   # mathtext, no $
deck.add_figure(slide, fig_svg, rest, cache)                                   # figure goes in what's left
deck.add_equation_column(slide, [line1, [piece_a, piece_b]], box, cache)       # a derivation
```

- Equations are placed at natural size and never scaled. Too wide for the box, or `pt` under 18, raises —
  shorten the equation or give it a wider box.
- Use `\dfrac`, not `\frac` (mathtext sets `\frac` small).
- A line given as a list of pieces lines up on one baseline, so later pieces can be revealed on click.

## Builds and animation

- `build_on_click(slide, shapes)`: fade shapes in one per click. For panel-by-panel builds, export one
  transparent SVG per layer into the same box.
- `animate(slide, steps, slide_w=prs.slide_width, slide_h=prs.slide_height)`: one entry per click; each
  click is a list of phases played in turn; each phase is a list of effects played together:
  `("in", shape, ms)`, `("out", shape, ms)`, `("move", shape, ms, dx_emu, dy_emu)`. Give each move as
  the step it takes; chained moves are tracked for you.
- LibreOffice/PDF renders show every layer at its start position, so builds and animations can only be
  checked in PowerPoint. Say so when handing a deck over.

## Movies

`deck.add_movie(slide, mp4, poster, box)` — make the MP4 and poster with `figlib.anim` (see video.md).
Use MP4 in decks; GIFs are 256 colours and loop with no pause.

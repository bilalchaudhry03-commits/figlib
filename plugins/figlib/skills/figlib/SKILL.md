---
name: figlib
description: Make slide- and paper-ready scientific figures with the figlib Python package. Use when creating, editing or checking matplotlib figures or HTML+SVG schematics, exporting a figure to SVG for PowerPoint or Illustrator, choosing figure colours, building a .pptx deck from Python, or rendering animations and explainer videos — in any project that has figlib installed or asks for it.
---

# figlib

figlib catches figure problems you can't see by looking: labels that overlap or run off the canvas,
type that becomes too small once the figure is shrunk onto a slide, and data an axis limit silently
dropped. Use its checks instead of eyeballing a PNG.

## Setup (check once per session)

```bash
python -c "import figlib"            # missing? pip install "figlib[all] @ git+ssh://git@github.com/bilalchaudhry03-commits/figlib.git"
python -m figlib.fonts               # once per machine, before any HTML tool (links Carlito for Chromium)
```

Extras: `html` (check_layout, export_svg; then `playwright install chromium`), `deck`, `video`.
Carlito is a free font with Calibri's exact letter widths, so a layout checked here holds in PowerPoint.
PNGs rendered here use Carlito; for HTML figures the exported SVG is the authority.

## matplotlib figures

Lint the live figure before saving. It only works in-process: once a PNG exists, the text positions are gone.

```python
from figlib import figcheck, palette as pal
from figlib.inputs import require

SRC = require(DATA / "table.csv", why="what it is and what produced it")[0]   # fail early, all at once
...
figcheck.require(fig)                # raises with every finding; use report(fig) to print instead
fig.savefig(out)
```

- Pass `crops=False` to `check`/`report`/`require` when saving with `bbox_inches="tight"`.
- `min_pt` (default 7) is checked *after* scaling the figure onto a 13.333 × 7.5 in slide; aim for
  ≥ 11 pt body text. A wide figure is shrunk, so its 8 pt labels may land at 6 pt.
- **CLIPPED means data is missing from the plot.** Fix the limits. If a window is deliberate, declare
  it on that axes with `ax.set_gid(figcheck.CLIP_OK_GID)` and say how many points are shown vs
  available — never pass `check_clipped=False` to silence it.
- For OVERDATA / OVERLINE / LEGEND, move the label or legend. An opaque text bbox
  (`bbox=dict(facecolor="white", alpha=0.85)`) also counts as fixed.
- `check_color_roles=True` (opt-in) warns when one colour means two things across panels.
- Audit someone's script without editing it: `python -m figlib.figcheck script.py`.
- Import figcheck normally; loading it by file path breaks its dataclass.

## HTML+SVG figures

```bash
python -m figlib.check_layout fig.html                  # exits 1 on overflow, overlap, small type, missing glyph
python -m figlib.export_svg fig.html fig.svg --group    # standalone SVG for PowerPoint/Illustrator
```

Run `check_layout` first and fix everything it reports before exporting. The exporter writes colours,
fonts and styles into the SVG, gives it a slide-fitted size, turns arrowheads into plain shapes,
and stamps its version in `<metadata id="figlib-provenance">`. Declare the font stack as
`Calibri, Arial, Helvetica, sans-serif` (`figlib.fonts.STACK`).

## Colour

```python
pal.validate(["#0072B2", "#D55E00", "#009E73"], pairs="all")   # dict: ok, fails, warns, worst_cvd
pal.SERIES                       # 8-colour categorical ramp; use in order, don't re-sort (the order is what keeps it colour-blind safe)
pal.ROLE["ink_2"]                # text/structure greys: ink, ink_2, ink_3, grid, surface
pal.sequential("density")        # matplotlib cmap names for continuous data
print(pal.as_css_vars())         # the same tokens as CSS variables for HTML figures
```

Use `pairs="all"` for scatter and small multiples, `"adjacent"` for bars and lines. Run `validate` on
any custom set before using it. `pal.entity(...)` / `pal.argument(...)` are one lab member's named
colours — use them only to match those figures.

## Before calling a figure done

1. `figcheck.require(fig)` or `check_layout` is clean (or each remaining finding is explained).
2. Look at the rendered output yourself, at slide size.
3. Report how many data points are plotted vs available if any axis limit was set by hand.

## More

- Designing a schematic or diagram (layout, colour roles, type sizing, export traps): use the
  `scientific-figure-design` skill.
- Making an explainer video (workflow, model checks, content rules): use the `explainer-video` skill.
- Building a `.pptx`: read [references/decks.md](references/decks.md).
- Animations, MP4/GIF, explainer videos: read [references/video.md](references/video.md).

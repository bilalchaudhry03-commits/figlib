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
python -c "import figlib, sys; print(figlib.__version__, sys.executable)"   # which figlib, in which Python
```

This skill matches figlib **0.2.4**. If figlib is missing, install it into the project's environment (its
venv or conda env). If the project has none, ask the user which to use; never install into the system
Python or with `--user`.

```bash
pip install "figlib[all] @ git+ssh://git@github.com/bilalchaudhry03-commits/figlib.git@v0.2.4"
python -m playwright install chromium     # once per machine, for check_layout / export_svg
```

If the installed version is older than 0.2.4, tell the user and offer to upgrade with the same line; some
calls in this skill may not exist in older versions. Extras, if they want less: `html`, `deck`, `video`.
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
python -m figlib.check_layout fig.html                  # exits 1 on overflow, overlap, small type, missing glyph, FONT
python -m figlib.export_svg fig.html fig.svg --group    # standalone SVG for PowerPoint/Illustrator
```

Run `check_layout` first and fix everything it reports before exporting. The exporter writes colours,
fonts and styles into the SVG, gives it a slide-fitted size, turns arrowheads into plain shapes,
and stamps its version in `<metadata id="figlib-provenance">`. Declare the font stack as
`Calibri, Arial, Helvetica, sans-serif` (`figlib.fonts.STACK`). Both tools load Carlito into the page
as 'Calibri' on any OS; a FONT finding means some text uses another face, so its measurements
don't describe the slide. For your own Playwright screenshots, call `fonts.use_in_browser(page)`
before `goto`.

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

- Starting a new figure: copy `examples/schematic_template.html` (HTML+SVG schematic) or
  `examples/figcheck_example.py` (matplotlib) from the figlib repo; both pass the checks as they are.

- Designing a schematic or diagram (layout, colour roles, type sizing, export traps): use the
  `scientific-figure-design` skill.
- Making an explainer video (workflow, model checks, content rules): use the `explainer-video` skill.
- Building a `.pptx`: read [references/decks.md](references/decks.md).
- Animations, MP4/GIF, explainer videos: read [references/video.md](references/video.md).

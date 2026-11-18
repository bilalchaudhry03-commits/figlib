# figlib

Tools for making figures that hold up on a projected slide. They were built for one person's
talks and papers in the Wühr lab and are shared here for the lab to try.

There are three parts:

- **Linters** that catch layout problems you can't see by looking at a figure:
  - labels that overlap or run off the edge;
  - type that will be too small once the figure is shrunk onto a slide;
  - data points that an axis limit silently left out.
- **An HTML → SVG exporter** whose output opens correctly in PowerPoint and Illustrator.
- **Slide-deck helpers** that build a `.pptx` from Python.

## Install

You need access to this private repo and an SSH key on GitHub.

```bash
pip install "figlib @ git+ssh://git@github.com/bilalchaudhry03-commits/figlib.git@v0.2.3"          # matplotlib linter + palette only
pip install "figlib[all] @ git+ssh://git@github.com/bilalchaudhry03-commits/figlib.git@v0.2.3"     # everything
```

The `@v0.2.3` pins a release, so your scripts don't change under you when `main` does. To upgrade, re-run
the line with the newer tag (listed under the repo's Tags). Drop the `@v…` to track `main` instead.

**Where it runs.** Tested on Linux (Argo). Since v0.2.0 the HTML tools load their font themselves and
`check_layout` reports text measured in any other font, so they should also work on a Mac or Windows. That
isn't tested yet; tell Bilal if anything breaks there. The matplotlib tools work anywhere.

The extras:
- `html` installs `check_layout` and `export_svg`. Run `playwright install chromium` once afterwards.
- `deck` installs the `.pptx` helpers.
- `video` installs the animation tools.

**Fonts.** figlib includes Carlito, a free font with exactly the same letter widths as Calibri. With it, a layout checked on Linux is the layout PowerPoint will show. matplotlib finds it automatically, and `check_layout`/`export_svg` load it into the browser themselves, under the name Calibri. Nothing to set up. `check_layout` also reports any text that isn't measured in Carlito/Calibri (a FONT finding), so a layout can't silently be checked in the wrong font.

For your own Playwright screenshot scripts, call `figlib.fonts.use_in_browser(page)` before `page.goto(...)`.

## Using it with Claude Code

This repo is also a Claude Code plugin with three skills:
- `figlib`: use figlib's checks (and rules like "never hide clipped data") whenever you ask for
  figures, SVG exports, decks or videos;
- `scientific-figure-design`: how to design a schematic or diagram that reads in 30 seconds on a slide;
- `explainer-video`: how to make a teaching video whose model is checked before anything is drawn.

```bash
claude plugin marketplace add bilalchaudhry03-commits/figlib
claude plugin install figlib@figlib
```

Or inside a session: `/plugin marketplace add bilalchaudhry03-commits/figlib`, then `/plugin install figlib@figlib`.
It uses your existing GitHub SSH key (loaded in ssh-agent) to read this private repo. Claude picks
the skills up automatically; you can also call one directly, e.g. `/figlib:figlib`. To get updates:
`claude plugin marketplace update figlib`, then `claude plugin update figlib@figlib`.

## Starting points

Copy one of these rather than starting from a blank file. Both pass figlib's checks as they are.

- [`examples/schematic_template.html`](examples/schematic_template.html): an HTML+SVG slide
  schematic (a three-step flow) already set up for a 16:9 slide: font stack, palette colours,
  text sized for projection, boxes sized to their labels by script, an arrowhead that exports
  correctly. Edit the `STEPS` list, then `check_layout` and `export_svg` it.
- [`examples/figcheck_example.py`](examples/figcheck_example.py): a matplotlib figure with the
  font stack, palette colours, a hand-set axis limit with the plotted-vs-available count printed,
  and `figcheck.require(fig)` before saving.

## The tools

### `figcheck`: lint a matplotlib figure before you save it

```python
from figlib import figcheck
figcheck.report(fig)     # prints problems, returns how many it found
figcheck.require(fig)    # raises if there are any, e.g. in a script you rerun often
```

To audit an existing script without editing it:

```bash
python -m figlib.figcheck my_figure_script.py
```

It reports:
- text off the canvas;
- text overlapping text;
- legends or labels sitting on data;
- type below 7 pt once the figure is fitted to a 16:9 slide (`min_pt=` to change it; `check_layout` uses 9 pt);
- **data points that fall outside the axis limits and were never drawn.**

If an axis limit deliberately cuts off data, mark that axes with `ax.set_gid(figcheck.CLIP_OK_GID)`.

### `check_layout` and `export_svg`: HTML+SVG figures

```bash
python -m figlib.check_layout figure.html            # overflow, overlaps, small type
python -m figlib.export_svg figure.html figure.svg   # standalone SVG for PowerPoint/Illustrator
```

`export_svg` works around six ways a browser SVG breaks when you import it:
- CSS colour variables are written in as plain colours;
- fonts are written onto each text element;
- the SVG is given a real size, sized to fit a slide;
- arrowheads are converted to plain shapes, because PowerPoint does not rotate SVG markers;
- double hyphens in comments are removed, because they make the file invalid XML;
- with `--group`, nearby elements are grouped so the file doesn't open as 100+ loose objects.

Every SVG it writes records which exporter version made it.

### `palette`: colours that stay distinguishable for colour-blind viewers

```python
from figlib import palette as pal
pal.validate(["#0072B2", "#D55E00", "#009E73"])["ok"]   # True if they stay distinct under colour-blindness simulation
print(pal.as_css_vars())                           # CSS variables to paste into an HTML figure
```

The named colours (`pal.entity("GNN")`, `pal.argument("broken")`, …) are the ones from Bilal's slides. Use them if you want your figures to match; otherwise use `validate` on your own colours.

`python -m figlib.palette drift scripts/ html/` lists hardcoded colours that disagree with the named ones, or HTML literals that should be CSS variables.

### `deck`: build a `.pptx` from Python

`deck` builds on python-pptx:
- SVG figures with a PNG fallback;
- equations typeset as images;
- speaker notes;
- MP4 movies;
- click-by-click builds and animations (`build_on_click`, `animate`);
- a final check (`require_clean`) that fails the build on grey text or text under 18 pt.

The house style is in the `Theme` class.

### Smaller pieces

- `inputs.require(path, why=...)`: declare a script's input files, so a missing one fails on line 1 with a clear message.
- `anim.write(frames, stem)`: frames → MP4, a poster frame and a contact sheet, using ffmpeg from `imageio-ffmpeg`.
- `scene`, `clip`: used for explainer videos.
  - `clip` renders Manim clips inside an Apptainer image. Set `FIGLIB_MANIM_SIF` to the image's path (on Argo, the lab's is `/Genomics/wuehrlab/People/Bilal/envs/manim/manim.sif`), or pass `sif=`.

## Tests

```bash
pip install "figlib[test] @ git+ssh://..."   # or, from a clone: pip install -e ".[test]"
pytest "$(python -c 'import figlib, pathlib; print(pathlib.Path(figlib.__file__).parent / "tests")')"
```

## Background

`figlib/CLAUDE.md` has notes for working on the code (Claude Code reads it automatically).

This repo started on 2026-11-17 as a copy of the `figlib/` folder in Bilal's lab repo. That folder's earlier history is still there.

figlib is under the MIT License (`LICENSE`). The bundled Carlito font is under the SIL Open Font License (`figlib/fonts/OFL.txt`).

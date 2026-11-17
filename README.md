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
pip install "figlib @ git+ssh://git@github.com/bilalchaudhry03-commits/figlib.git"          # matplotlib linter + palette only
pip install "figlib[all] @ git+ssh://git@github.com/bilalchaudhry03-commits/figlib.git"     # everything
```

The extras:
- `html` installs `check_layout` and `export_svg`. Run `playwright install chromium` once afterwards.
- `deck` installs the `.pptx` helpers.
- `video` installs the animation tools.

**Fonts.** figlib includes Carlito, a free font with exactly the same letter widths as Calibri. With it, a layout checked on Linux is the layout PowerPoint will show. matplotlib finds it automatically. For the HTML tools, run this once per machine:

```bash
python -m figlib.fonts     # links the font into ~/.fonts so Chromium can find it
```

`check_layout` and `export_svg` also do this themselves the first time they run.

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
- type below about 9 pt once the figure is fitted to a 16:9 slide;
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
pal.validate(["#0072B2", "#D55E00", "#009E73"])   # checks the colours stay distinct under colour-blindness simulation
print(pal.as_css_vars())                           # CSS variables to paste into an HTML figure
```

The named colours (`pal.entity("GNN")`, `pal.argument("broken")`, …) are the ones from Bilal's slides. Use them if you want your figures to match; otherwise use `validate` on your own colours.

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
  - `clip` renders Manim clips with the lab's Apptainer image on Argo.
  - To use a different image, set `FIGLIB_MANIM_SIF`.

## Tests

```bash
pip install "figlib[test] @ git+ssh://..."   # or, from a clone: pip install -e ".[test]"
pytest "$(python -c 'import figlib, pathlib; print(pathlib.Path(figlib.__file__).parent / "tests")')"
```

## Background

`figlib/CLAUDE.md` explains why each tool works the way it does, including the bugs that led to most of these checks. Claude Code reads it automatically when it works in this repo.

This repo started on 2026-11-17 as a copy of the `figlib/` folder in Bilal's lab repo. That folder's earlier history is still there.

The Carlito font is under the SIL Open Font License (`figlib/fonts/OFL.txt`).

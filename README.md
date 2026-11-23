# figlib

Tools for talks and figures that hold up on a projected slide, built in the Wühr lab. Use it on its
own, or through Claude Code, where "make me a lab-meeting talk on …" becomes a deck that Claude
builds, renders and checks slide by slide.

## Get started with Claude Code

1. If you don't have PowerPoint, install [LibreOffice](https://www.libreoffice.org/download/) once
   (`brew install --cask libreoffice` on a Mac, `winget install TheDocumentFoundation.LibreOffice` on
   Windows). It renders your slides to images so Claude can look at them.
   figlib uses PowerPoint if installed (tested on Windows; the Mac route is untested), else LibreOffice.
2. Install the plugin, in a Claude Code session:
   ```
   /plugin marketplace add bilalchaudhry03-commits/figlib
   /plugin install figlib@figlib
   ```
3. Ask for a talk or a figure. The first time, Claude installs figlib into your project's Python
   environment.

Updates: `/plugin marketplace update figlib`, then `/plugin update figlib@figlib`.

The plugin's skills: `talk` (outline → deck → render → critique, every change), `figlib` (the checks
below), `scientific-figure-design` (schematics that read in 30 seconds) and `explainer-video`.

## What's in it

| | what it's for | |
|---|---|---|
| `outline`, `render` | a talk written as a Markdown outline, built into a `.pptx`, rendered to slide images | `python -m figlib.outline talk.md` |
| `figcheck` | lint a matplotlib figure: overlapping or off-canvas text, type too small on a slide, **data an axis limit silently hid** | `figcheck.require(fig)` |
| `check_layout`, `export_svg` | the same checks for HTML+SVG schematics, and an SVG export that opens correctly in PowerPoint and Illustrator | `python -m figlib.export_svg fig.html fig.svg` |
| `silhouette` | protein outlines from structures (AlphaFold DB by UniProt ID, or your .cif) at true relative size; complexes as grouped shapes, rings with open channels | `python -m figlib.silhouette P52292 --svg x.svg` |
| `layers` | click-by-click builds and animations from an HTML figure | `python -m figlib.layers build fig.html L1 L2` |
| `palette` | colours that stay distinct for colour-blind viewers, and a validator for your own | `palette.validate([...])` |
| `deck` | the `.pptx` building blocks the outline uses (SVG figures, equations, movies, animation) | |
| `anim`, `scene`, `clip` | movies and explainer videos | |

Each module's docstring is its manual: `python -c "import figlib.silhouette as m; help(m)"`.

**Fonts.** figlib ships Carlito, which has exactly Calibri's letter widths, so a layout checked on
any machine is the one PowerPoint shows. Every check measures in it and says so when it can't.

## Making a talk by hand

```bash
python -m figlib.outline --starter mytalk     # a five-slide starter: outline, a figure script, a schematic
python -m figlib.outline mytalk/talk.md       # build mytalk/talk.pptx
python -m figlib.render mytalk/talk.pptx      # mytalk/talk_render/contact.png: every slide on one page
```

Each slide is a block in `talk.md`:

```markdown
### S02 · Larger proteins enter the nucleus more slowly
figure: figs/rate_vs_size.svg
notes:
What to say over this slide.
```

**Edit `talk.md`, never the `.pptx`**: every build overwrites it. The title is the claim, the figure
is the evidence, everything else goes in the notes. Builds, equations, movies and animations: see the
format at the top of [`figlib/outline.py`](figlib/outline.py). The build fails on grey or small text
and on any missing figure. In the render, slides with clicks or animations show every layer at once
(marked on the contact sheet): check those in PowerPoint. For a PDF to send, build
`python -m figlib.outline talk.md --handout` and render `talk_handout.pptx`: animated slides show their
final frame.

To start a single figure instead, copy [`examples/figcheck_example.py`](examples/figcheck_example.py)
(matplotlib) or [`examples/schematic_template.html`](examples/schematic_template.html) (HTML+SVG
schematic); both pass the checks as they are.

## Installing without Claude

Python 3.10+ and git:

```bash
pip install "figlib[all] @ git+https://github.com/bilalchaudhry03-commits/figlib.git@v0.5.0"     # everything
pip install "figlib @ git+https://github.com/bilalchaudhry03-commits/figlib.git@v0.5.0"          # matplotlib linter + palette only
python -m playwright install chromium                                                           # once, for the HTML tools
```

The `@v…` pins a release so your scripts don't change under you. Extras, if you want less than
`all`: `html` (Chromium tools), `deck` (outline, render), `video`, `structure` (silhouette).
LibreOffice is found in its standard install location, at `FIGLIB_SOFFICE`, or inside an Apptainer
image at `FIGLIB_LIBREOFFICE_SIF`.

Tested on Linux, macOS and Windows. On Windows, deck PNG fallbacks are drawn by Chromium (no native
cairo). Tell Bilal if anything breaks.

## Development

```bash
pip install -e ".[test]" && python -m playwright install chromium && pytest figlib/tests
```

Notes for working on the code, and how to release: [`figlib/CLAUDE.md`](figlib/CLAUDE.md).
MIT License; the bundled Carlito font is under the SIL Open Font License (`figlib/fonts/OFL.txt`).

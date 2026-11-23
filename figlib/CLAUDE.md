# figlib — notes for working on the code

`README.md` is for people using figlib; the skills in `plugins/figlib/skills/` are what Claude reads
when using it. This file is for changing it. The package is `figlib`, not `lib`, so it can't collide
with a project's own `lib/`; modules carry no date prefix because they are imported, not run once.

## Modules

| module | what it does |
|---|---|
| `figcheck` | matplotlib layout linter, in-process on the live `Figure` |
| `check_layout` | the same checks for HTML+SVG, in headless Chromium |
| `export_svg` | HTML → standalone SVG for PowerPoint/Illustrator |
| `palette` | colour registry (series / roles / named entities) + colour-blindness validator; stdlib only |
| `fonts` | vendored Carlito (Calibri's metrics): matplotlib registration, browser injection |
| `inputs` | `require(path, why=…)`: declare a script's data inputs |
| `deck` | .pptx building blocks: `Theme`, SVG figures with PNG fallback, equations, movies, `animate`, `require_clean` |
| `outline` | Markdown outline → .pptx through `deck`; the format is its docstring; `--handout` flattens `animation:` slides to the manifest's `final` frame; `starter/` is the package-data talk `--starter` copies |
| `render` | .pptx → PDF (PowerPoint if installed, else headless LibreOffice) → slide PNGs + contact sheet via pypdfium2, with a font check |
| `layers` | HTML figure → per-click SVG layers (`build`) or moving layers + manifest (`anim`) for an outline |
| `silhouette` | structure (file or UniProt ID via AlphaFold DB) → flat outlines at a shared Å scale; same label = one shape, `ring` view, `keep_holes`, `--js` for HTML figures |
| `anim`, `scene`, `clip` | movies and explainer videos; `clip` renders Manim in Apptainer (`FIGLIB_MANIM_SIF`) |

## Releasing

`figlib/tests/test_release.py` fails unless these agree: `figlib.__version__`, `version` in
`plugins/figlib/.claude-plugin/plugin.json`, and the `@vX.Y.Z` pins in `README.md` and the figlib
skill's setup block (plus the not-installed eval's grader). Bump all, commit, `git tag -a vX.Y.Z`,
push the tag. Installed plugins update only on a version change.

Before a release that touches render, outline, layers, deck or the HTML tools, run the manual
`mac + windows check` workflow (`gh workflow run os-check.yml`); Argo can't test those paths.

The skills are what labmates' Claude knows about figlib: **update them when a public API or a usage
rule changes.** Keep detail in module docstrings and point to them, rather than copying it into
the README and skills (the outline format lives only in `outline.py`).

## Things that aren't obvious from the code

**Fonts**
- Calibri is proprietary; Carlito has identical metrics. Layout checked in any other face is wrong
  (DejaVu is ~25% wider), so every tool measures in Carlito and says so when it can't.
- Browser tools call `fonts.use_in_browser(page)` before `goto`: an init script registers the TTFs as
  'Calibri' and 'Carlito' from bytes, so they exist before the figure's own script measures text, on
  any OS. A stylesheet added after load is too late; `~/.fonts` only works where Chromium uses fontconfig.
- `check_layout` reports FONT when a text style's width differs from Carlito's by > 0.5%; monospace
  stacks are skipped (code labels are deliberate).
- `render` copies (not links) the TTFs into a throwaway LibreOffice profile: a link out of the work
  dir dangles inside an Apptainer image. Its font check reads the font of each visible character:
  LibreOffice embeds a default serif for empty text bodies that draws nothing, and the theme's
  per-script font lists (Arial, Times…) are not "declared" fonts.
- With PowerPoint installed, `render` uses it (COM on Windows, osascript on Mac) and LibreOffice
  is only the fallback; Argo has no PowerPoint, so the cluster keeps the LibreOffice/Apptainer path.
  Calibration (2026-11-23, PowerPoint 16 vs LibreOffice 26.8 on Windows and 24.2 + Carlito on Linux):
  same line breaks except in a band ~0.6-0.8% past the box width, where LibreOffice keeps on one line
  what PowerPoint wraps (its lines run ~0.1-0.2% narrower: ff/ti/fl/tt ligatures plus ~1 pt per line);
  LibreOffice text also sits ~1.5 pt lower. So a LibreOffice render can miss a wrap, never invent one.
  `deck.near_wraps` (reported by the outline build as NEAR-WRAP) flags every wrap decision within 1%
  of the box edge, measured in Carlito: renderer-independent, 1 of 62 paragraphs in the generals deck.
  An automatically chosen PowerPoint that fails falls back to LibreOffice (`Report.fallback`); a forced
  one fails. The macOS route (osascript through PowerPoint's container) has never been run.
- One copy of the TTFs, in `figlib/fonts/`. Don't vendor them elsewhere.

**figcheck**
- Import it; never load it by path (`spec_from_file_location`): its `@dataclass` needs the module in
  `sys.modules`.
- A deliberate axis window is declared per axes with `ax.set_gid(figcheck.CLIP_OK_GID)`, never by
  disabling `CLIPPED`.

**SVG export**
- Every SVG carries `<metadata id="figlib-provenance">` with the exporter version.
- Arrowheads are baked to paths (PowerPoint/Illustrator ignore SVG 2 marker orientation).
- Computed styles are baked as attributes, `none` included (`fill` defaults to black). A class rule
  that only recolours an authored colour attribute is *not* baked: authored white numerals stay white.

**Decks**
- No secondary text, enforced in code: no subtitle/caption parameters, and `require_clean` fails on
  non-footer text that is grey or < 18 pt (the footer is exempt by shape name, `FOOTER_NAME`).
- Equations are pictures, never scaled: too small or too wide raises. `\dfrac`, not `\frac`. Glyphs
  are outlines because PowerPoint draws blanks for glyphs Carlito lacks.
- `animate` writes its own `<p:video>` node for every played movie (setting the timing replaces
  python-pptx's); a movie never played gets none.
- PNG fallbacks: cairosvg where native cairo loads (imported lazily: at module top it made `deck`
  unimportable on Windows), else headless Chromium, a browser per call so later `sync_playwright()`
  users in the process still work.
- LibreOffice/PDF renders show every layer at once and movies as posters: check motion in PowerPoint.

**Structures**
- `silhouette` filters pLDDT only for predicted models (no resolution, no experimental method):
  experimental B-factors are not confidence. EBI returns 403 to a bare `figlib` User-Agent; keep the
  version in it.
- Rings are outer pieces (>= 10% of the largest) then holes (inside an outer piece, >= 200 Å², only
  with `keep_holes`): consumers must draw with fill-rule evenodd. The `ring` axis comes from the
  individual chains' centres, so subunits merged into one label still find it.

**Video**
- Frames stream into ffmpeg's stdin; `anim.write` skips the GIF above 20 s unless `gif=True`.

## Tests

```bash
pip install -e ".[test]" && python -m playwright install chromium && pytest figlib/tests
```

`tests/conftest.py` holds the shared SVG and the `chromium` / `soffice` / `powerpoint` skip
fixtures: use them rather than probing per file. CI has no Office, so the real PowerPoint render
only runs on a machine with it. Set `FIGLIB_SOFFICE` to a wrapper script to test render through an
Apptainer image.

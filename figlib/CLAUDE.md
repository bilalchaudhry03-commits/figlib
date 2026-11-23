# figlib — the figure toolchain

Importable package for figure work: `from figlib import palette, figcheck, ...`. Named `figlib`, not
`lib`, so it can't collide with the per-project `lib/` packages on `sys.path`; modules have no date
prefix because they're library code, not run artifacts. `README.md` is the user-facing doc (written
for labmates); this file is for working on the code.

## Repo setup — read before committing

- figlib is its own private repo, `bilalchaudhry03-commits/figlib`, shared with the Wühr lab. The
  checkout is `/Genomics/wuehrlab/People/Bilal/pkgs/figlib`; wuhrlab's `Bilal/figlib` is a symlink to
  `pkgs/figlib/figlib`, so existing imports, `python3 -m figlib.x`, `~/.fonts` and the
  Manim bind all resolve without an install.
- **Commit and push in `pkgs/figlib`.** wuhrlab doesn't track these files, so an edit made through
  the symlink won't show in wuhrlab's `git status`.
- No install is needed in the wuhrlab envs; the symlink covers it.
- Della has its own clone at `pkgs/figlib`, pulled by hand.
- History before 2026-11-17 is in wuhrlab (`git log -- figlib`).
- Lab-specific defaults are intentional: the palette's named entities and `deck.Theme`. The Manim
  image is not a default: export `FIGLIB_MANIM_SIF=/Genomics/wuehrlab/People/Bilal/envs/manim/manim.sif`
  (envs' activate scripts or the explainer sbatch), or pass `sif=`. Nothing in the package reads the wuhrlab tree; checks of
  wuhrlab's own scripts (entity-colour drift, known divergences) belong in wuhrlab's tests, using
  `palette.drift_report(dir)`.

## Modules

| module | what it does |
|---|---|
| `palette` | colour registry (entity / role / series) + CVD validator; stdlib only |
| `figcheck` | matplotlib layout linter; in-process on the live `Figure` |
| `check_layout` | the same for HTML+SVG — `python3 -m figlib.check_layout fig.html` |
| `export_svg` | HTML → standalone SVG — `python3 -m figlib.export_svg fig.html fig.svg` |
| `fonts` | vendored Carlito; registers with matplotlib, links for Chromium |
| `inputs` | `require(path, why=…)` — declare a script's data inputs |
| `deck` | .pptx assembly: `Theme`, SVG-with-PNG-fallback figures, equations, movies, `animate`, `lint_deck` |
| `outline` | Markdown outline → .pptx via `deck` (format in its docstring); ported 2026-11-23 from the generals builder, which it reproduces byte for byte apart from equation-SVG `<dc:date>` stamps |
| `anim` | frames → MP4 + GIF + poster + contact sheet; `.clipped` lists frames touching the edge |
| `scene`, `clip` | explainer videos; Manim clips rendered in Apptainer |

## Claude Code plugin

`.claude-plugin/marketplace.json` + `plugins/figlib/` make this repo a plugin marketplace with three
skills under `plugins/figlib/skills/`: `figlib` (the API and checks; `references/decks.md`,
`references/video.md`), `scientific-figure-design` (how to design a schematic: layout, colour roles,
type arithmetic, export traps) and `explainer-video` (workflow and gates). The last two are the
de-labbed versions of Bilal's personal `scientific-figure-design` and wuhrlab's `explainer-video`
skills, which were retired on 2026-11-18 once the plugin was installed on Argo (the originals are in
wuhrlab `archive/claude_skills/` and git history). They are what labmates' Claude knows about figlib, so **update them when a
public API or a usage rule changes**. `plugin.json` carries a `version`, so installed plugins update only on a release, in step with the
package. Check with `claude plugin validate .`.

**Releasing** (`figlib/tests/test_release.py` fails if these disagree): bump `figlib.__version__`, the
`version` in `plugins/figlib/.claude-plugin/plugin.json`, the `@vX.Y.Z` pins in `README.md` and in the
figlib skill's setup block; commit; `git tag -a vX.Y.Z`; push the tag.

## Things that aren't obvious from the code

**Using figcheck**
- Import it; never load it by path (`spec_from_file_location`) — its `@dataclass` needs the module in
  `sys.modules`.
- A deliberate axis window is declared per axes with `ax.set_gid(figcheck.CLIP_OK_GID)`, never by
  disabling `CLIPPED`. Still check plotted vs available point counts.

**Fonts**
- Calibri isn't on the cluster; DejaVu (the fallback) is ~25% wider, so layouts checked against it
  don't hold. Carlito is metric-compatible and fontconfig maps Calibri → Carlito, so declared stacks
  stay as they are. PNGs rendered here use Carlito; the SVG is the authority.
- `check_layout`/`export_svg` call `fonts.use_in_browser(page)` before `goto`: an init script registers
  the TTFs via the FontFace API from in-memory bytes as 'Calibri' and 'Carlito', so they exist before the
  figure's own script measures text (tested: parse-time width = Carlito width) and it works on any OS.
  A stylesheet added after load is too late; ~/.fonts only works where Chromium uses fontconfig. Since
  2026-11-18 (exporter 1.3.0, check_layout 1.2.0); before that the tools symlinked ~/.fonts, which
  would have crashed on Windows and been ignored on macOS. `check_layout` then measures each distinct
  text style against Carlito and reports FONT if any differs by > 0.5% (monospace stacks skipped: code
  labels in Consolas are deliberate; 0.2.0-0.2.3 failed 6 lab figures for them).
- `python -m figlib.fonts` (the ~/.fonts link) is now optional, for other Chromium use on Linux.
  Importing `figlib.fonts` only registers with matplotlib.
- Don't copy the TTFs anywhere. One copy, in the repo.

**SVG export**
- Every SVG carries `<metadata id="figlib-provenance">` with the exporter version. Run the tools as
  `python -m figlib.<tool>`; don't keep copies of them anywhere else (the old skill shims are gone).
- Arrowheads are baked to paths (Illustrator/PowerPoint don't honour SVG 2 marker orientation).
  `--group` clusters loose siblings into `<g>`.
- Computed styles are baked as attributes, `none` included (`fill`'s initial value is black). A class
  rule that only recolours an authored colour attribute is *not* baked — some figures author white
  numerals that a class greys on screen, and the white is intended.
- Rebuild everything and report drift:
  ```bash
  python3 scripts/20260827_rebuild_figures.py            # re-export all, report drift, exit 1
  python3 scripts/20260827_rebuild_figures.py --write    # install the regenerated SVGs
  python3 scripts/20260827_rebuild_figures.py --status   # figure inventory vs the manifest
  ```
  A CHANGED line means "look", not "regression" — fixes show up as changes too. Never auto-accept.

**Decks**
- No secondary text, enforced in code: no subtitle/caption parameters, and `require_clean(prs)` fails
  on non-footer text that is grey or < 18 pt. The footer is exempt by shape name (`FOOTER_NAME`).
- Equations are pictures (`render_equation`, `add_equation`, `add_equation_column`), never scaled; `pt`
  below `MIN_BODY_PT` or an equation wider than its box raises. Use `\dfrac`, not `\frac` (mathtext
  sets `\frac` small). Glyphs are written as outlines because PowerPoint draws blanks for glyphs
  Carlito lacks. `render_equation_parts` crops pieces to a shared height so they line up.
- `animate(slide, steps, ...)`: one entry per click, phases in turn, effects together —
  `("in"|"out", shape, ms)`, `("move", shape, ms, dx, dy)` or `("play", movie, ms)`. Motion paths are
  relative to the layout position; `animate` tracks chained moves. `auto=` phases run when the slide
  opens; `loop=` movies repeat. Writing the timing replaces python-pptx's media node for each movie, so
  `animate` writes its own `<p:video>` node for every played movie (`repeatCount="indefinite"` when
  looped); a movie that is never played gets none. Added 2026-11-19 for the generals S02 opener.
- LibreOffice/PDF shows every layer at its start position and video slides as their poster, so
  animations can only be checked in PowerPoint; QA motion from `anim.write(...).contact`.
  QA render: `sbatch scripts/20261030_render_pptx_argo.sbatch <deck.pptx> <out_dir>`.
- Movies are MP4 in the deck, GIF for Slack.

**Animation / video**
- Frames stream into ffmpeg's stdin; only file-only renderers (PyMOL) get a frame directory, in scratch.
- `anim.write`: `bg=` sets the edge-check and pad colour; the GIF is skipped above 20 s unless
  `gif=True`; the poster is the middle frame. `anim.delivery_copy(mp4)` makes a 720p copy under the
  30 MiB SendUserFile cap.
- Explainer workflow and gates: `plugins/figlib/skills/explainer-video/SKILL.md`; in wuhrlab, outputs
  go in `explainers/YYYYMMDD_topic/`.

## Tests

```bash
source envs/analysis/bin/activate && pytest figlib/tests
```

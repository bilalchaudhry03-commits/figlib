# figlib — the figure toolchain

Importable package for figure work: `from figlib import palette, figcheck, ...`. Named `figlib`, not
`lib`, so it can't collide with the per-project `lib/` packages on `sys.path`; modules have no date
prefix because they're library code, not run artifacts. `README.md` is the user-facing doc (written
for labmates); this file is for working on the code.

## Repo setup — read before committing

- figlib is its own private repo, `bilalchaudhry03-commits/figlib`, shared with the Wühr lab. The
  checkout is `/Genomics/wuehrlab/People/Bilal/pkgs/figlib`; wuhrlab's `Bilal/figlib` is a symlink to
  `pkgs/figlib/figlib`, so existing imports, `python3 -m figlib.x`, skill shims, `~/.fonts` and the
  Manim bind all resolve without an install.
- **Commit and push in `pkgs/figlib`.** wuhrlab doesn't track these files, so an edit made through
  the symlink won't show in wuhrlab's `git status`.
- **Don't `pip install -e` it into `envs/analysis`** — a second import route gives `palette._repo_root()`
  a different answer.
- Della has its own clone at `pkgs/figlib`, pulled by hand.
- History before 2026-11-17 is in wuhrlab (`git log -- figlib`).
- Lab-specific defaults are intentional: the palette's named entities, `deck.Theme`, `clip.SIF`
  (override with `FIGLIB_MANIM_SIF`), and `palette`'s drift-scan dirs (resolve only inside wuhrlab).
  Tests that need the wuhrlab tree skip outside it.

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
| `anim` | frames → MP4 + GIF + poster + contact sheet; `.clipped` lists frames touching the edge |
| `scene`, `clip` | explainer videos; Manim clips rendered in Apptainer |

## Claude Code plugin

`.claude-plugin/marketplace.json` + `plugins/figlib/` make this repo a plugin marketplace; the skill is
`plugins/figlib/skills/figlib/` (`SKILL.md`, plus `references/decks.md` and `references/video.md`).
It is what labmates' Claude knows about figlib, so **update it when a public API or a usage rule
changes**. No `version` is set, so installs track commits. Check with `claude plugin validate .`.

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
- A fresh machine needs `python -m figlib.fonts` once (or just run `check_layout`/`export_svg`).
  Importing `figlib.fonts` only registers with matplotlib — it never touches `~/.fonts`.
- Don't copy the TTFs anywhere. One copy, in the repo.

**SVG export**
- Every SVG carries `<metadata id="figlib-provenance">` with the exporter version. The skill's copies
  of the tools are shims that delegate here; keep them code-free so nothing drifts.
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
  `("in"|"out", shape, ms)` or `("move", shape, ms, dx, dy)`. Motion paths are relative to the
  layout position; `animate` tracks chained moves.
- LibreOffice/PDF shows every layer at its start position and video slides as their poster, so
  animations can only be checked in PowerPoint; QA motion from `anim.write(...).contact`.
  QA render: `sbatch scripts/20261030_render_pptx_argo.sbatch <deck.pptx> <out_dir>`.
- Movies are MP4 in the deck, GIF for Slack.

**Animation / video**
- Frames stream into ffmpeg's stdin; only file-only renderers (PyMOL) get a frame directory, in scratch.
- `anim.write`: `bg=` sets the edge-check and pad colour; the GIF is skipped above 20 s unless
  `gif=True`; the poster is the middle frame. `anim.delivery_copy(mp4)` makes a 720p copy under the
  30 MiB SendUserFile cap.
- Explainer workflow and gates: `.claude/skills/explainer-video/SKILL.md` (wuhrlab); outputs go in
  `explainers/YYYYMMDD_topic/`.

## Tests

```bash
source envs/analysis/bin/activate && pytest figlib/tests
```

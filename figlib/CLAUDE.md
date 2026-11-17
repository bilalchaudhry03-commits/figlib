# figlib — the figure toolchain

Split out of the root `CLAUDE.md`'s "Figure toolchain" section on 2026-09-21, once that
section had grown past what belonged inline in a repo-wide file. `figlib` is a real
cross-project importable package (`from figlib import palette, figcheck, ...`, repo root on
`sys.path`) — see root `CLAUDE.md`'s "File naming convention" for why it is `figlib`, not
`lib` (avoids the `sys.path`-order collision commit `d456f03` fixed) and why its modules carry
no date prefix (importable library code, not a run artifact).

`figlib/` is canonical, and it is versioned. Rebuilt 2026-08-27 — everything that makes a deck
figure now lives in the repo:

| module | what it does |
|---|---|
| `figlib/palette.py` | colour registry, three axes, self-validating for CVD |
| `figlib/figcheck.py` | matplotlib layout linter (overflow, collision, small type, CLIPPED, occlusion) |
| `figlib/check_layout.py` | the same for HTML+SVG — `python3 -m figlib.check_layout fig.html` |
| `figlib/export_svg.py` | HTML → standalone SVG — `python3 -m figlib.export_svg fig.html fig.svg` |
| `figlib/fonts.py` | vendored Carlito; registers with matplotlib, links for Chromium |
| `figlib/inputs.py` | `require(path, why=…)` — declare a script's data inputs |
| `figlib/deck.py` | .pptx assembly: house template (`Theme`), SVG-with-PNG-fallback figures, MP4 movies, notes, and `lint_deck` (no grey / sub-18pt text outside the footer) |
| `figlib/anim.py` | frames → MP4 + GIF + poster + contact sheet via the bundled ffmpeg; counts frames whose content touches the edge |

**⚠ The exporter and linter used to live in `~/.claude/skills/…/scripts/`, which is not a git
repository.** No SVG recorded which version made it, so when 13 of 19 deck SVGs failed to
reproduce from their HTML on 2026-08-27, separating "the exporter improved" from "the figure
drifted" took hours of rendering and diffing. **Every SVG now carries a
`<metadata id="figlib-provenance">` stamp** naming the tool version. The skill's copies are
shims that delegate here — deliberately carrying no code, because two copies of an exporter is
how they drift apart.

**⚠ Calibri is proprietary and has never been on Argo**, so every figure was laid out against
DejaVu — **~25% wider** (485 vs 389 px on the 08-27 test string; Carlito is ~20% *narrower*) — and then labelled "Calibri". The linters certified layouts the
deliverable would never use, which is the real reason behind the standing "the PNGs have
substituted fonts, the SVG is the authority" note. **`figlib/fonts/` now vendors Carlito**,
which is metric-compatible with Calibri under the OFL, and fontconfig maps one to the other, so
no figure's declared stack had to change. `figlib.fonts` symlinks `~/.fonts` → `figlib/fonts` on
import; **a fresh clone needs that once** (it is idempotent, and the tools call it themselves).
Do not copy the TTFs anywhere — one copy, in the repo, under version control.

**Regenerate and check with one command:**

```bash
python3 scripts/20260827_rebuild_figures.py            # re-export all, report drift, exit 1
python3 scripts/20260827_rebuild_figures.py --write    # install the regenerated SVGs
python3 scripts/20260827_rebuild_figures.py --status   # figure inventory vs the manifest
```

**⚠ It reports that an output CHANGED; it cannot tell you whether that is a repair or a
regression.** On 2026-08-27 a strict pixel-identity gate rejected six figures that were in fact
being fixed — their text colour had been missing since July. Treat a CHANGED line as a prompt to
look, never as a verdict, and never wire this to auto-accept.

**Arrowheads are baked, not `<marker>`s.** `orient="auto-start-reverse"` is SVG 2; Illustrator
and PowerPoint are SVG 1.1 and fall back to no rotation, so every arrowhead arrives as an
unrotated triangle. The exporter converts markers to positioned paths. **`--group`** additionally
clusters loose siblings into `<g>` so a figure does not open in Illustrator as 100+ top-level
objects; the rebuild script passes it, so a plain re-export will not silently strip it.

**Class/inline styles are baked as attributes, `none` included (exporter 1.2.0, 2026-10-19).**
The page's `<style>` does not travel with the SVG. Up to 1.1.0 only colours were baked and a
computed `none` was skipped — but `fill`'s initial value is *black*, so a `.outline{fill:none}`
circle imported solid black (generals Fig 5A), and class-set `stroke-width`/`stroke-dasharray`
reverted to 1/solid. Now fill/stroke `none`, stroke-width, -dasharray, -dashoffset, -linecap,
-linejoin, fill-/stroke-opacity (shapes and text) and `opacity` (also on `<g>`) are written
whenever the computed value differs from what the standalone file would inherit — defaults are
not written. A class rule that overrides an authored *geometry* attribute wins (as in the
browser); one that merely **recolours** an authored colour attribute does **not** — kept from
1.1.0 because three deck figures author white badge numerals that a `.tag{fill:muted}` rule
greys on screen, and the white is the intent. Re-exporting all 40 deck HTMLs with 1.2.0 was
byte-identical to 1.1.0, so this changes no installed figure. Tests: `figlib/tests/test_export_svg.py`.

## Decks and animations (`deck.py`, `anim.py`, added 2026-10-30)

**`deck.py` was lifted out of `admin/presentations/group_meetings/py/20260826_build_group_meeting_deck.py`**,
because `admin/` is gitignored and the builder was therefore unversioned (the exporter's old failure
mode, above). Each talk keeps its own content and a short build script under `admin/`; everything
reusable lives here. Tests: `figlib/tests/test_deck.py`.

- **The no-secondary-text rule is enforced in code, not prose.** The 08-26 builder wrote a grey
  18pt subtitle on its own title slide, against the 2026-10-20 rule. `deck.py` has no subtitle,
  caption or sub-bullet parameter, and `require_clean(prs)` fails the build on non-footer text that
  is grey or < 18pt. The footer is exempt **by shape name** (`FOOTER_NAME`), not by position.
- **Equations are pictures, sized by construction (2026-11-13).** `render_equation(tex, cache)`
  typesets matplotlib mathtext in Carlito as SVG + PNG; `add_equation(slide, tex, box, cache)` places it
  at natural size, centred at the top of `box`, and returns the box left for the figure;
  `add_equation_column(slide, lines, box, cache)` stacks a derivation. `lint_deck` cannot see type
  inside a picture, so the floor is enforced at render time instead: `pt` below `MIN_BODY_PT` raises,
  and so does an equation wider than its box (it is never scaled). Use `\dfrac`, not `\frac`:
  mathtext sets `\frac` in text style, which shrinks the fraction well below `pt`.
  - **Glyphs are written as outlines (`svg.fonttype: path`), not text.** With text, a glyph Carlito
    lacks (`\cdot`, U+22C5) fell back to another face; PowerPoint then looked it up in Calibri and drew
    a blank, so the multiplication dots vanished on the slide while the PNG render looked fine.
  - **A line can be revealed in pieces** (`render_equation_parts`): every piece is drawn on one
    canvas at one baseline and all are cropped to a shared height, so pieces placed at the same top
    line up as one equation (e.g. the full form, then "≈ the simple form" on the next click).
- **Motion, not just fades (2026-11-17): `animate(slide, steps, slide_w=, slide_h=)`.** One entry per
  click; each click is phases that play in turn; each phase is effects that play together:
  `("in"|"out", shape, ms)` or `("move", shape, ms, dx_emu, dy_emu)`. Motion paths are relative to the
  shape's *layout* position, so a second move on the same shape must start where the first ended;
  `animate` tracks that, so pass each move as a step. Shapes with an "in" start hidden. Full-canvas
  transparent layers make positioning trivial (the generals deck's S07 Ran cycle, exported by
  `admin/generals/slides/py/20261117_make_anim_layers.py`). **LibreOffice/PDF shows every layer at its
  start position, so the animation itself can only be checked in PowerPoint** — the exporter's
  per-click preview frames are the closest check off-Windows. **Verified in PowerPoint by the user on
  2026-11-17** (S07, 8 clicks of fades and chained moves: plays correctly, no repair prompt reported). `build_on_click` (fade-in only) is
  unchanged and shares `_set_timing` with it.
- **Movies are MP4 in the deck and GIF for Slack.** GIF is 256 colours and loops with no pause.
- **QA renders:** `sbatch scripts/20261030_render_pptx_argo.sbatch <deck.pptx> <out_dir>` (LibreOffice
  image, compute node). Video slides render as their poster only; the motion is QA'd from
  `anim.write(...).contact`, and `.clipped` lists frames with content touching the edge — the
  animation version of figcheck's CLIPPED, for the same reason (you cannot see what was never drawn).
- **Frames stream into ffmpeg's stdin.** Only a renderer that can only write files (PyMOL) gets a
  frame directory, and that goes in scratch.
- **`anim.write` changes, 2026-11-02 (from the first explainer video):** `bg=` sets the background
  for both the edge check and the encoder pad (hard-coded white flagged every frame of a dark
  video); `gif=None` (the new default) skips the GIF above `GIF_MAX_S` = 20 s; contact thumbnails
  are kept at a doubling stride, not one per frame (~0.8 GB for a 2.7 min clip). Callers that
  relied on the GIF for long clips must now pass `gif=True`. `poster_index=None` (the default)
  takes the middle frame, since frame 0 of a fade-in is black; `anim.delivery_copy(mp4)` writes a
  720p `_send.mp4` under SendUserFile's 30 MiB cap.
- **Explainer videos** use `scene.py` (scenes, cue timeline, captions, storyboard; owned by the
  session that built the flux explainer, 2026-11-02) on top of `anim.py`. Workflow and gates are
  in the project skill `.claude/skills/explainer-video/SKILL.md`; outputs go in
  `explainers/YYYYMMDD_topic/`.
- **The 08-26 builder was already failing before the move** ("slide 41 not found in the outline":
  the outline was edited after the deck was built). It was not fixed, only re-pointed at `deck.py`.

## Who imports this, and how

Every project that makes figures imports from here rather than keeping its own copy —
`from figlib import palette, figcheck` (and `check_layout`, `export_svg`, `fonts`, `inputs` as
needed), repo root on `sys.path`. `figlib/figcheck.py`'s matplotlib linter is in-process by
necessity: a matplotlib figure only exists while its script runs, so it checks the live
`Figure` before `savefig` (`figcheck.check(fig)` / `.report(fig)` / `.require(fig)`), or run
`python3 -m figlib.figcheck path/to/script.py` to audit a script without editing it (installs a
`savefig` hook). `figlib/check_layout.py` is the HTML+SVG equivalent, run as
`python3 -m figlib.check_layout fig.html`.

- **Never load `figcheck` by path** (`importlib.util.spec_from_file_location`): its `@dataclass`
  needs the module in `sys.modules`, so it raises `AttributeError` (job 12766597). Import it.
- **A deliberate axis window is declared per-axes** with `ax.set_gid(figcheck.CLIP_OK_GID)`,
  never by disabling `CLIPPED` — and still check plotted vs available counts (global CLAUDE.md).

Two known consumers, for context on how the package gets used day to day:
- **`karyoPPI/`** — `palette`/`figcheck` were originally `karyoPPI/lib/` modules, moved out
  2026-08-17 once other projects needed them; their tests moved with them to `figlib/tests/`.
  See `karyoPPI/CLAUDE.md`'s "Shared library (`lib/`) and test suite" section for that
  migration's detail.
- **`passive_diffusion/`** — imports `figcheck`/`palette` the same way; see the figure bullets
  under `passive_diffusion/CLAUDE.md`'s "Conventions" section.

Tests: `figlib/tests/` (moved from `karyoPPI/tests/` in the 2026-08-17 split). Run with
`source envs/analysis/bin/activate && pytest figlib/tests`.

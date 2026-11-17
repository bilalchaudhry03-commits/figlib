"""Figure tooling shared across projects: layout linting and colour.

WHY THIS IS AT THE REPO ROOT AND NOT IN `karyoPPI/lib/`
------------------------------------------------------
Both modules here started in `karyoPPI/lib/` because that is where the first
caller lived. They are not karyoPPI code: as of 2026-08-17 `figcheck` has 14
consumers in `passive_diffusion/scripts/` and 0 outside this repo, and
`passive_diffusion` was reusing `palette`'s hex values BY HAND, copied into each
script with a comment saying it did so deliberately to avoid importing across
projects. Copied colour values are the exact failure `palette` exists to
prevent, so the dependency was pointing the wrong way.

Moved 2026-08-17 (user decision), which also lifts the standing note in
`passive_diffusion/CLAUDE.md` that "both modules are candidates to move to a
shared top-level lib/".

WHY THE PACKAGE IS CALLED `figlib` AND NOT `lib`
-----------------------------------------------
Because a third package named `lib` would reintroduce a bug this repo has
already had. `karyoPPI/lib/` and `passive_diffusion/lib/` both exist, and commit
`d456f03` records what happened when a bare `from lib import x` was allowed to
resolve by sys.path order: each test suite passed alone and failed together,
with an error naming a module the test never asked for. A test that
importlib-loads a script runs that script's own `sys.path.insert` inside the
pytest process, so "scripts run one project per process" is not a defence.

`figlib` cannot collide with either: `lib` still resolves per project, `figlib`
resolves only here. Consumers put the REPO ROOT on `sys.path` and

    from figlib import figcheck, palette

The name is also honest about scope — both modules are figure tooling. A future
shared module that is not about figures belongs in a sibling package, not here.

CONTENTS
--------
    figcheck      matplotlib layout linter: text off-canvas, text-on-text, type
                  too small once projected, legend over data, text over data,
                  and data clipped outside the axes. `report(fig)` is the entry
                  point.
    palette       one source of truth for figure colour, plus the CVD validator
                  that checks any candidate set.

Added 2026-08-27, when the figure BUILD tools moved into the repo. They lived in
`~/.claude/skills/.../scripts/`, which is not a git repository, and nothing
recorded which version produced which SVG -- so when 13 of 19 deck figures
failed to reproduce from their HTML, telling "the exporter improved" from "the
figure drifted" took hours. Both now carry `__version__` and stamp it into their
output.

    check_layout  the same three checks as figcheck, for HTML+SVG figures, run
                  in headless Chromium. `python3 -m figlib.check_layout f.html`
    export_svg    HTML figure -> standalone SVG for Illustrator and PowerPoint:
                  bakes CSS-variable colours, inlines fonts, emits an intrinsic
                  size, converts <marker> arrowheads to plain geometry, and
                  optionally groups loose siblings. `python3 -m figlib.export_svg`
    fonts         vendors Carlito (metric-compatible with the deck's declared
                  Calibri, which is proprietary and has never been installable
                  here) and makes it visible to matplotlib and to Chromium.
                  `python -m figlib.fonts` once per machine for Chromium.
    inputs        `require(path, why=...)` -- declare a figure script's data
                  inputs so a missing one fails in one line at the top instead of
                  a pandas traceback halfway down.

Both use plain lowercase names, not the repo-wide `YYYYMMDD_` prefix, per the
importable-module exception in the root `CLAUDE.md`.
"""

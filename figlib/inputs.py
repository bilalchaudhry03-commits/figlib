"""Declare a figure script's data inputs, and fail readably when one is gone.

The failure this exists to prevent, observed 2026-08-27:

    FileNotFoundError: [Errno 2] No such file or directory:
    '/Genomics/.../massspec/diann_runs/20260615_exp2_oocyte_staging/output/report.stats.tsv'

That is a raw pandas traceback 200 lines into a script, after the imports and
the first half of the analysis have already run. It says what is missing but not
what the script was for, whether the file ever existed, or whether the figure it
feeds is still in the deck. A declared input list turns it into one line at the
top, before any work, naming every missing file at once rather than the first.

Usage -- declare beside the paths, check before doing anything:

    from figlib.inputs import require

    SRC = ROOT / "karyoPPI/data/import/20260804_abstention_gate_quadrants.csv"
    require(SRC, why="the 2x2 abstention quadrants; built by 20260804_abstention_gate.py")

Convention for new figure scripts: every path the script READS goes through
`require()` at module level. Paths it WRITES do not -- those are created.
"""

from __future__ import annotations

import sys
from pathlib import Path


class MissingInput(FileNotFoundError):
    """Raised when a declared input is absent. Subclasses FileNotFoundError so
    an existing `except FileNotFoundError` still catches it."""


def require(*paths, why: str = "", exit_code: int | None = 2) -> list[Path]:
    """Assert every path exists. Report ALL missing ones, not just the first.

    `why` is one line about what the data is and what produced it -- the thing
    a reader needs and a bare path never carries.

    With `exit_code` set (the default) this exits the process with a clean
    message rather than a traceback, because a missing input is an environment
    problem and a traceback buries that in stack frames. Pass `exit_code=None`
    to raise `MissingInput` instead, which is what tests want.
    """
    resolved = [Path(p) for p in paths]
    missing = [p for p in resolved if not p.exists()]
    if not missing:
        return resolved

    lines = [f"missing {len(missing)} of {len(resolved)} declared input(s):"]
    lines += [f"    {p}" for p in missing]
    if why:
        lines.append(f"  what it is: {why}")
    lines.append("  nothing was written. Restore the input, or retire the figure.")
    msg = "\n".join(lines)

    if exit_code is None:
        raise MissingInput(msg)
    sys.exit(msg)

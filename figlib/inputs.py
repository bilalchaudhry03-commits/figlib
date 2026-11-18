"""Declare a figure script's data inputs, and fail readably when one is missing.

    from figlib.inputs import require
    SRC = ROOT / "data/quadrants.csv"
    require(SRC, why="the 2x2 quadrants; built by make_quadrants.py")

Call it at module level for every path the script reads, so a missing file fails in one
line before any work runs, naming every missing input at once.
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

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
    """A declared input is absent. Still caught by `except FileNotFoundError`."""


def require(*paths, why: str = "", exit_code: int | None = 2) -> list[Path]:
    """Check every path exists, reporting all the missing ones, not just the first.

    `why` says what the data is and what produced it. By default a missing input
    exits with a clean message instead of a traceback; pass `exit_code=None` to
    raise `MissingInput` instead (e.g. in tests).
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

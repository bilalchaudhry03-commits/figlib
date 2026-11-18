"""Vendored Carlito, so layouts measured here match Calibri on the presenting machine.

Calibri is proprietary and can't be installed on the cluster; the fallback (DejaVu Sans) is
~25% wider, so layouts checked against it don't hold in the deck. Carlito has Calibri's
metrics, and fontconfig maps Calibri -> Carlito, so figures can keep declaring `STACK`.

    from figlib import fonts   # registers with matplotlib
    python -m figlib.fonts     # once per machine: makes Carlito visible to Chromium
"""

from __future__ import annotations

import os
from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent / "fonts"

#: The stack every figure in this deck should declare, in priority order.
STACK = "Calibri, Arial, Helvetica, sans-serif"

#: The same stack as a matplotlib `font.sans-serif` list.
STACK_LIST = ["Calibri", "Carlito", "Arial", "Helvetica", "DejaVu Sans"]

#: A directory fontconfig scans by default.
LINK = Path.home() / ".fonts"

_registered = False


def ttf_files() -> list[Path]:
    return sorted(FONT_DIR.glob("*.ttf"))


def register() -> list[str]:
    """Register the vendored TTFs with matplotlib. Idempotent.

    Returns the family names now available. Safe when matplotlib is absent --
    returns [] rather than raising, so importing figlib does not drag matplotlib
    in for a caller that only wants the palette.
    """
    global _registered
    try:
        from matplotlib import font_manager
    except ImportError:  # pragma: no cover - matplotlib not installed
        return []
    if not _registered:
        for ttf in ttf_files():
            font_manager.fontManager.addfont(str(ttf))
        _registered = True
    return sorted({f.name for f in font_manager.fontManager.ttflist})


def ensure_visible() -> str:
    """Make the vendored faces findable by headless Chromium. Idempotent.

    matplotlib is told about the TTFs directly by `register()`. Chromium is not
    -- it goes through fontconfig, which knows nothing about this repo. A
    symlink from a directory fontconfig already scans costs 44 bytes, keeps ONE
    real copy of the fonts (in the repo, where they are versioned), and needs no
    environment variable, so it works for every process on this machine.

    Two other approaches were tried on 2026-08-27; both are recorded so neither
    gets retried:

      * **Copy the TTFs** into a repo-root `.local/share/fonts`, which
        fontconfig scans via $XDG_DATA_HOME. Works, but duplicates 2.7 MB,
        leaves two directories to keep in step, and puts a `.local/` at the repo
        root that reads like an accident.
      * **FONTCONFIG_FILE pointing at a repo config.** Does NOT work. It
        replaces the entire configuration rather than adding to it, and a config
        that includes `/etc/fonts/fonts.conf` still fails, because that file's
        own includes are relative and resolve against the wrong directory. The
        symptom is misleading: system fonts still resolve, so it looks like the
        config is working and the vendored fonts are broken.

    A fresh install needs this once: `python -m figlib.fonts`, or let `check_layout` /
    `export_svg` do it, since both need Chromium to see Carlito. Since 2026-11-17 (figlib
    became its own repo, shared with the lab) importing `figlib.fonts` alone only registers
    with matplotlib and no longer touches the home directory.

    If ~/.fonts already exists as a real directory, or as a link to other fonts, the faces
    are linked INSIDE it as ~/.fonts/figlib-carlito instead; fontconfig scans recursively.
    """
    if LINK.is_symlink() and not LINK.exists():
        raise FileNotFoundError(f"{LINK} is a dangling symlink (-> {os.readlink(LINK)}); "
                                "remove it and run `python -m figlib.fonts` again")
    if not LINK.exists():
        LINK.symlink_to(FONT_DIR)
        return str(LINK)
    if LINK.resolve() == FONT_DIR:
        return str(LINK)
    inner = LINK / "figlib-carlito"
    if inner.is_symlink() and inner.resolve() != FONT_DIR:   # ours, from an older install
        inner.unlink()
    if not inner.exists():
        inner.symlink_to(FONT_DIR)
    return str(inner)


register()

if __name__ == "__main__":
    print("Carlito visible to fontconfig/Chromium via", ensure_visible())

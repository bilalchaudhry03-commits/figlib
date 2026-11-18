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

#: The font stack figures should declare, in priority order.
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

    Returns the family names now available, or [] when matplotlib is absent.
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

    Chromium finds fonts through fontconfig, so this symlinks ~/.fonts (which
    fontconfig scans) to the package's font directory: one copy of the fonts, no
    environment variable. If ~/.fonts already exists, the link goes inside it as
    ~/.fonts/figlib-carlito (fontconfig scans recursively).

    Called by check_layout and export_svg before they launch Chromium; never on import.

    Don't replace this with FONTCONFIG_FILE: it replaces the whole system config
    rather than adding to it, and system fonts still resolve, so it looks like the
    vendored fonts are what's broken.
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

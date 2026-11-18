"""Vendored Carlito, so layouts measured here match Calibri on the presenting machine.

Calibri is proprietary and can't be installed on the cluster; the fallback (DejaVu Sans) is
~25% wider, so layouts checked against it don't hold in the deck. Carlito has Calibri's
metrics, and fontconfig maps Calibri -> Carlito, so figures can keep declaring `STACK`.

    from figlib import fonts           # registers with matplotlib
    fonts.use_in_browser(page)         # Playwright page: Carlito as 'Calibri' (check_layout and
                                       # export_svg do this themselves, on any OS)
    python -m figlib.fonts             # optional, Linux: ~/.fonts link for other Chromium use
"""

from __future__ import annotations

import json
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

    Optional. figlib's own tools load the fonts into the page instead (`use_in_browser`),
    which works on every OS; this is for other Chromium/fontconfig use on Linux. Never on import.

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


#: The faces given to headless Chromium, as (file, CSS weight, CSS style).
BROWSER_FACES = (("Carlito-Regular.ttf", "400", "normal"), ("Carlito-Bold.ttf", "700", "normal"),
                 ("Carlito-Italic.ttf", "400", "italic"), ("Carlito-BoldItalic.ttf", "700", "italic"))

#: Registered under both names, so a figure declaring `STACK` gets Carlito's metrics on any OS.
BROWSER_FAMILIES = ("Calibri", "Carlito")

#: A figure text style whose test-string width differs from Carlito's by more than this
#: fraction is reported: its layout was measured in a face PowerPoint won't use.
FONT_TOL = 0.005

_INIT_JS = """(() => {
  const faces = %s, fams = %s;
  for (const [b64, weight, style] of faces) {
    const bin = atob(b64), buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    for (const fam of fams) document.fonts.add(new FontFace(fam, buf, {weight, style}));
  }
})();"""

_PROBE_JS = """async () => {
  await document.fonts.ready;
  const seen = new Map();
  for (const t of document.querySelectorAll('svg text, svg tspan')) {
    const s = (t.textContent || '').trim();
    if (!s) continue;
    const cs = getComputedStyle(t), key = [cs.fontStyle, cs.fontWeight, cs.fontFamily].join('|');
    if (!seen.has(key)) seen.set(key, s.slice(0, 40));
  }
  const c = document.createElement('canvas').getContext('2d'), S = 'Hamburgefontsiv 0123456789 (+=)';
  const width = f => { c.font = '100px serif'; c.font = f; return c.measureText(S).width; };
  return [...seen].map(([key, sample]) => {
    const [style, weight, family] = key.split('|');
    return {family, weight, style, sample,
            ratio: width(`${style} ${weight} 100px ${family}`) / width(`${style} ${weight} 100px Carlito`)};
  });
}"""


def use_in_browser(page) -> None:
    """Give a Playwright page the vendored faces as 'Calibri' and 'Carlito'. Call before `goto`.

    Registered with the FontFace API from in-memory bytes in an init script, so the faces exist
    before the figure's own layout script runs and measures text. A stylesheet added after
    load would be too late, and ~/.fonts only works where Chromium uses fontconfig (Linux).
    """
    import base64
    faces = [[base64.b64encode((FONT_DIR / f).read_bytes()).decode(), w, s] for f, w, s in BROWSER_FACES]
    page.add_init_script(_INIT_JS % (json.dumps(faces), json.dumps(list(BROWSER_FAMILIES))))


def font_mismatches(page, tol: float = FONT_TOL) -> list[dict]:
    """Text styles in the loaded figure that don't render with Carlito/Calibri metrics.

    One entry per distinct (style, weight, family) used by an SVG text element:
    {family, weight, style, sample, ratio}, where ratio is the test string's width in that
    style over its width in Carlito. Only entries with |ratio - 1| > tol are returned.
    """
    return [r for r in page.evaluate(_PROBE_JS) if abs(r["ratio"] - 1) > tol]


register()

if __name__ == "__main__":
    print("Carlito visible to fontconfig/Chromium via", ensure_visible())

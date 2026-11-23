"""Render a .pptx to per-slide PNGs and a contact sheet, so a deck can be looked at between edits.

    python -m figlib.render talk.pptx           # -> talk_render/slide-01.png ..., contact.png, talk.pdf

The deck is exported to PDF by PowerPoint if it is installed, else by headless LibreOffice, and
pypdfium2 rasterises the PDF. The engine used is printed (`Report.engine`). FIGLIB_RENDERER=powerpoint
or FIGLIB_RENDERER=libreoffice forces one; passing `soffice=` to `render()` means LibreOffice.

- PowerPoint: Windows drives it through COM (pywin32, installed with the `deck` extra): the deck is
  opened read-only with no window, saved as PDF, and PowerPoint quits unless you had other
  presentations open. macOS drives it through AppleScript (osascript). Office's sandbox limits
  where PowerPoint can read and write, so the deck goes through a folder inside PowerPoint's own
  container (~/Library/Containers/com.microsoft.Powerpoint/Data/figlib) and the PDF is copied out.
  The first run asks to allow automation of PowerPoint: allow it (System Settings > Privacy &
  Security > Automation, if it was refused).
- If PowerPoint was picked automatically but fails (e.g. a refused automation prompt) and LibreOffice
  is installed, LibreOffice renders instead and `Report.fallback` / the CLI say why. A forced
  FIGLIB_RENDERER=powerpoint fails instead. The macOS route is written but has not been run yet.
- LibreOffice: install once from libreoffice.org; it is found at FIGLIB_SOFFICE, inside an
  Apptainer image at FIGLIB_LIBREOFFICE_SIF (clusters without it), on PATH, or in its standard
  Mac/Windows install location.

What the render is and isn't:
- PowerPoint's own PDF is the slide. LibreOffice is close for layout: text runs in Carlito, which
  has Calibri's exact letter widths. Each LibreOffice run uses a fresh profile with figlib's Carlito
  in it. Either way the PDF's fonts are checked afterwards: a font the deck never asked for is a
  substitution (exit 1), because then the render's line breaks and overflows aren't the slide's.
- Click builds and animations show every layer at its start position, all at once, and movies
  show their poster. Those slides are listed (and marked on the contact sheet) so a stacked
  slide isn't mistaken for a broken one; check motion in PowerPoint.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from figlib import fonts

MAC_SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
WIN_SOFFICE = [r"C:\Program Files\LibreOffice\program\soffice.exe",
               r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"]
INSTALL_HINT = {
    "Darwin": "install LibreOffice from https://www.libreoffice.org/download/ (or `brew install --cask libreoffice`)",
    "Windows": "install LibreOffice from https://www.libreoffice.org/download/ (or `winget install TheDocumentFoundation.LibreOffice`)",
}
MAC_POWERPOINT = "/Applications/Microsoft PowerPoint.app"
MAC_PPT_DIR = Path.home() / "Library/Containers/com.microsoft.Powerpoint/Data/figlib"   # inside Office's sandbox
MAC_SCRIPT = """on run argv
    tell application "Microsoft PowerPoint"
        open (POSIX file (item 1 of argv))
        set p to active presentation
        save p in ((POSIX file (item 2 of argv)) as text) as save as PDF
        close p saving no
        if (count of presentations) is 0 then quit
    end tell
end run"""
TIMEOUT_S = 900
THUMB_W, COLS = 480, 4


@dataclass
class Report:
    pdf: Path
    pngs: list
    contact: Path
    engine: str                                       # "powerpoint" or "libreoffice"
    stacked: list = field(default_factory=list)       # slide numbers with click builds / animations
    movies: list = field(default_factory=list)        # slide numbers whose movies show as posters
    fonts: list = field(default_factory=list)         # fonts in the PDF
    substituted: list = field(default_factory=list)   # PDF fonts the deck never declared
    fallback: str = ""                                # why an automatic PowerPoint render fell back


def find_soffice(explicit: str | None = None) -> list[str]:
    """The command that runs LibreOffice: a path, or `apptainer exec <sif> soffice` (bind added later)."""
    if explicit:
        return [explicit]
    if os.environ.get("FIGLIB_SOFFICE"):
        return [os.environ["FIGLIB_SOFFICE"]]
    if os.environ.get("FIGLIB_LIBREOFFICE_SIF"):
        return ["apptainer", "exec", os.environ["FIGLIB_LIBREOFFICE_SIF"], "soffice"]
    for name in ("soffice", "libreoffice"):
        if shutil.which(name):
            return [shutil.which(name)]
    for p in [MAC_SOFFICE, *WIN_SOFFICE]:
        if Path(p).exists():
            return [p]
    hint = INSTALL_HINT.get(platform.system(), "install LibreOffice (package `libreoffice-impress`)")
    raise FileNotFoundError(f"LibreOffice not found: {hint}, or set FIGLIB_SOFFICE to its soffice.")


def has_powerpoint() -> bool:
    if sys.platform == "win32":
        import winreg
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"PowerPoint.Application\CLSID"))
            return True
        except OSError:
            return False
    return sys.platform == "darwin" and Path(MAC_POWERPOINT).exists()


def pick_engine(soffice: str | None = None) -> str:
    """"powerpoint" if installed, else "libreoffice"; FIGLIB_RENDERER forces one, `soffice` means LibreOffice."""
    forced = os.environ.get("FIGLIB_RENDERER", "")
    if forced not in ("", "powerpoint", "libreoffice"):
        raise ValueError(f"FIGLIB_RENDERER={forced!r}: use powerpoint or libreoffice")
    if forced == "powerpoint":
        if not has_powerpoint():
            raise FileNotFoundError("FIGLIB_RENDERER=powerpoint, but PowerPoint is not installed here")
        return "powerpoint"
    if not forced and soffice is None and has_powerpoint():
        return "powerpoint"
    try:
        find_soffice(soffice)
    except FileNotFoundError as e:
        if forced:
            raise
        raise FileNotFoundError(f"No renderer: PowerPoint is not installed, and {e}") from None
    return "libreoffice"


def slide_flags(pptx: Path) -> tuple[list, list]:
    """(slides with click builds/animations, slides with movies), 1-based, in deck order."""
    from pptx import Presentation
    stacked, movies = [], []
    for i, slide in enumerate(Presentation(pptx).slides, 1):
        xml = slide._element.xml
        if re.search(r"<p:(set|anim)", xml):      # appear/fade/motion effects; movie playback alone is <p:cmd>
            stacked.append(i)
        if "videoFile" in xml:
            movies.append(i)
    return stacked, movies


def declared_fonts(pptx: Path) -> set:
    """Latin typefaces the slides ask for: explicit faces in slide XML plus the theme's major/minor
    Latin fonts. Not the theme's per-script lists (Arial, Times New Roman, ... for other scripts):
    counting those would let a Calibri -> Arial fallback pass as declared."""
    names = set()
    with zipfile.ZipFile(pptx) as z:
        for n in z.namelist():
            xml = z.read(n).decode("utf-8", "replace") if n.endswith(".xml") else ""
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", n):
                names |= set(re.findall(r'<a:(?:latin|ea|cs|sym)\b[^>]*typeface="([^"+][^"]*)"', xml))
            elif re.fullmatch(r"ppt/theme/theme\d+\.xml", n):
                names |= set(re.findall(r'<a:latin\b[^>]*typeface="([^"+][^"]*)"', xml))
    return names


def pdf_fonts(pdf: Path) -> list:
    """Fonts that draw visible (non-whitespace) characters in the PDF, subset prefixes stripped.
    Per character, not the PDF's font list: newer LibreOffice embeds its default serif for empty
    text bodies, which draws nothing (os-check, 2026-11-23: Times New Roman on Windows, Liberation
    Serif on macOS, zero glyphs each)."""
    import ctypes
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c
    found = set()
    buf, flags = ctypes.create_string_buffer(256), ctypes.c_int()
    doc = pdfium.PdfDocument(pdf)
    try:
        for page in doc:
            tp = page.get_textpage()
            for i in range(tp.count_chars()):
                if tp.get_text_range(i, 1).isspace():
                    continue
                if pdfium_c.FPDFText_GetFontInfo(tp.raw, i, buf, len(buf), ctypes.byref(flags)):
                    found.add(re.sub(r"^[A-Z]{6}\+", "", buf.value.decode("utf-8", "replace")))
    finally:
        doc.close()
    return sorted(found)


def _substituted(used: list, declared: set) -> list:
    ok = {d.lower() for d in declared}
    if "calibri" in ok:
        ok.add("carlito")
    # PDF names carry the style: Carlito-Bold, Carlito,Bold, ArialMT ...
    return [f for f in used if not any(f.lower().replace(" ", "").startswith(d.replace(" ", "")) for d in ok)]


def _contact(pngs: list, labels: list, out: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    thumbs = []
    for p in pngs:
        im = Image.open(p).convert("RGB")
        thumbs.append(im.resize((THUMB_W, round(im.height * THUMB_W / im.width))))
    th = max(t.height for t in thumbs)
    lab_h, pad = 34, 12
    rows = -(-len(thumbs) // COLS)
    sheet = Image.new("RGB", (COLS * (THUMB_W + pad) + pad, rows * (th + lab_h + pad) + pad), "#d9d9d9")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(fonts.FONT_DIR / "Carlito-Bold.ttf"), 22)
    for k, (t, lab) in enumerate(zip(thumbs, labels)):
        x = pad + (k % COLS) * (THUMB_W + pad)
        y = pad + (k // COLS) * (th + lab_h + pad)
        draw.text((x, y + 4), lab, fill="#000000", font=font)
        sheet.paste(t, (x, y + lab_h))
    sheet.save(out)
    return out


def _pdf_libreoffice(deck: Path, soffice: str | None) -> Path:
    work = deck.parent
    cmd = find_soffice(soffice)
    font_dir = work / "profile" / "user" / "fonts"
    font_dir.mkdir(parents=True)
    for ttf in fonts.ttf_files():
        # Copies, not links: a link out of the work dir dangles inside an Apptainer image
        # (only the work dir is bound) and needs extra rights on Windows. ~1 MB, deleted on exit.
        shutil.copy(ttf, font_dir / ttf.name)
    if cmd[0] == "apptainer":
        cmd = [cmd[0], cmd[1], "--bind", str(work), *cmd[2:]]
    r = subprocess.run([*cmd, f"-env:UserInstallation={(work / 'profile').as_uri()}",
                        "--headless", "--convert-to", "pdf", "--outdir", str(work), str(deck)],
                       capture_output=True, text=True, timeout=TIMEOUT_S)
    made = deck.with_suffix(".pdf")
    if not made.exists():
        raise RuntimeError(f"LibreOffice made no PDF (exit {r.returncode}):\n{r.stdout}\n{r.stderr}")
    return made


def _powerpoint_com(deck: Path, pdf: Path) -> None:
    import win32com.client
    app = win32com.client.DispatchEx("PowerPoint.Application")
    pres = app.Presentations.Open(str(deck), True, False, False)       # read-only, no window
    try:
        pres.SaveAs(str(pdf), 32)                                        # 32 = ppSaveAsPDF
    finally:
        pres.Close()
        if app.Presentations.Count == 0:       # don't close a PowerPoint the user is working in
            app.Quit()


def _pdf_powerpoint(deck: Path) -> Path:
    made = deck.with_suffix(".pdf")
    if sys.platform == "win32":
        import pythoncom
        pythoncom.CoInitialize()
        try:
            _powerpoint_com(deck, made)     # its COM objects are released on return, before CoUninitialize
        finally:
            pythoncom.CoUninitialize()
    else:
        MAC_PPT_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=MAC_PPT_DIR) as box:
            src, dst = Path(box) / deck.name, Path(box) / made.name
            shutil.copy(deck, src)
            r = subprocess.run(["osascript", "-e", MAC_SCRIPT, str(src), str(dst)],
                               capture_output=True, text=True, timeout=TIMEOUT_S)
            if not dst.exists():
                raise RuntimeError(f"PowerPoint made no PDF at {dst} (osascript exit {r.returncode}): {r.stderr.strip()}"
                                   " -- if automation was refused, allow it in System Settings > Privacy & Security"
                                   " > Automation, or set FIGLIB_RENDERER=libreoffice")
            shutil.copy(dst, made)
    if not made.exists():
        raise RuntimeError("PowerPoint made no PDF")
    return made


def render(pptx: Path, out_dir: Path | None = None, *, dpi: int = 110,
           soffice: str | None = None) -> Report:
    import pypdfium2 as pdfium
    pptx = Path(pptx).resolve()
    out_dir = Path(out_dir).resolve() if out_dir else pptx.with_name(pptx.stem + "_render")
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = pick_engine(soffice)
    auto = engine == "powerpoint" and not os.environ.get("FIGLIB_RENDERER")
    fallback = ""
    # The work dir sits beside the output, not in the system temp dir: on a cluster that is the
    # shared volume, which an Apptainer image can be bound to.
    with tempfile.TemporaryDirectory(dir=out_dir, prefix=".work_") as tmp:
        work = Path(tmp)
        deck_copy = work / "deck.pptx"
        shutil.copy(pptx, deck_copy)
        if engine == "powerpoint":
            try:
                made = _pdf_powerpoint(deck_copy)
            except Exception as e:
                # Picked automatically (not forced) and LibreOffice is here: use it and say why.
                # A refused macOS automation prompt is the expected case.
                if not auto:
                    raise
                try:
                    find_soffice()
                except FileNotFoundError:
                    raise e from None
                fallback = f"PowerPoint failed ({type(e).__name__}: {str(e).splitlines()[0][:160]}); used LibreOffice"
                engine = "libreoffice"
                made = _pdf_libreoffice(deck_copy, None)
        else:
            made = _pdf_libreoffice(deck_copy, soffice)
        pdf = out_dir / (pptx.stem + ".pdf")
        shutil.copy(made, pdf)

    for old in out_dir.glob("slide-*.png"):
        old.unlink()
    doc = pdfium.PdfDocument(pdf)
    pngs = []
    for i in range(len(doc)):
        p = out_dir / f"slide-{i + 1:02d}.png"
        doc[i].render(scale=dpi / 72).to_pil().save(p)
        pngs.append(p)
    doc.close()

    stacked, movies = slide_flags(pptx)
    labels = [f"{i}" + ("  · layers stacked" if i in stacked else "") + ("  · movie poster" if i in movies else "")
              for i in range(1, len(pngs) + 1)]
    used = pdf_fonts(pdf)
    return Report(pdf=pdf, pngs=pngs, contact=_contact(pngs, labels, out_dir / "contact.png"),
                  engine=engine, fallback=fallback, stacked=stacked, movies=movies, fonts=used,
                  substituted=_substituted(used, declared_fonts(pptx)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m figlib.render", description=__doc__.split("\n")[0])
    ap.add_argument("pptx", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="output folder (default: <deck>_render/ beside the deck)")
    ap.add_argument("--dpi", type=int, default=110)
    a = ap.parse_args(argv)
    r = render(a.pptx, a.out, dpi=a.dpi)
    print(f"rendered {len(r.pngs)} slides with {r.engine} -> {r.contact.parent}  (contact sheet: {r.contact.name})")
    if r.fallback:
        print(f"  {r.fallback}")
    if r.stacked:
        print(f"  layers stacked (click builds/animations; check in PowerPoint): slides {', '.join(map(str, r.stacked))}")
    if r.movies:
        print(f"  movies shown as posters: slides {', '.join(map(str, r.movies))}")
    if not r.fonts:
        print("  FONT: could not read the PDF's fonts; text measurement is unverified")
    if r.substituted:
        print(f"  FONT: the render used fonts the deck never declared: {', '.join(r.substituted)}"
              " -- line breaks and overflows here may not match PowerPoint")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

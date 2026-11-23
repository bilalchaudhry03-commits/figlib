"""Build a .pptx from a Markdown outline: the outline is the source, the deck is generated.

    python -m figlib.outline talk.md            # writes talk.pptx beside it (or `out:`)
    python -m figlib.outline --starter mytalk   # a five-slide starter talk to edit
    python -m figlib.outline talk.md --handout  # talk_handout.pptx: animated slides as their final frame

Edit the outline, never the .pptx: a rebuild overwrites it. Ported from the generals-talk
builder (wuhrlab admin/generals/slides/py/20261030_build_generals_deck.py, 2026-11-23), which
reproduces byte for byte through `build()`.

FORMAT

Optional front matter, before anything else:

    ---
    author: Your Name          (title slide)
    out: talk.pptx             (default: the outline's name, .pptx)
    root: ..                   (folder that `figure:` etc. paths are relative to; default: the outline's)
    logo: assets/shield.png    (content slides, top right; relative to root)
    title_logo: assets/lockup.png
    ---

One block per slide, `### S01 · Title` (main deck) or `### B01 · Title` (backup). Any other
line before the first block is ignored, so the outline can carry its own notes. Titles are
assertions: what the audience should conclude. Key lines under the heading:

    section: title             this block is the title slide (other values are ignored)
    figure: figs/a.svg         the slide's picture, fitted to the content box
    build: figs/a_L2.svg       (repeatable) a same-size transparent layer over `figure:`, one per click;
                               make them with `python -m figlib.layers build a.html L1 L2 ...`
    equation: \\tau = \\dfrac{V}{kA}   mathtext, no $; above the figure. Before `figure:` it shows
                               with the slide, after it it fades in on a click; ` @x=0.25` centres
                               it over that fraction of the figure's width
    derivation: a = b >> = c   (repeatable) equations in a right-hand column, one click per line,
                               ` >> ` splits a line into pieces revealed one click at a time
    movie: label | a.mp4 | a_poster.png   (repeatable) movies side by side, label above each
    side: figs/b.svg           a figure in an extra column beside the movies
    tag: Expected result       a black-outlined label top right; the figure shrinks below it
    title_width: 12.67         widen this slide's title box (inches) to keep it on one line
    animation: a_anim.json     moving layers, from `python -m figlib.layers anim a.html`
    - a bullet                 top-level bullets, used only when the slide has no figure/movie
    notes:                     everything after this line is speaker notes, verbatim

The deck fails to build on grey or sub-18 pt text (`deck.require_clean`), and the CLI exits 1
on any missing figure or movie, so a placeholder never reaches the room silently. Notes that
contain `[DRAFT]` are listed after the build.

A PDF of a deck draws every animation layer at once. For a copy to send (a committee pre-read,
Slack), build with `--handout` and render that: each `animation:` slide shows its final frame (the
manifest's `final`, written by `figlib.layers anim`); click-by-click `build:` slides need nothing,
since all layers at once IS their last click. Slides with no final frame are listed.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pptx.util import Inches, Pt

from figlib import deck

FIG_FRAC = 0.46               # `derivation:` slides: the figure's share of the content width
DERIV_GAP = Inches(0.3)       # between the figure column and the equations
FRONT_KEYS = {"author", "out", "root", "logo", "title_logo"}
STARTER = Path(__file__).resolve().parent / "starter"


@dataclass
class Report:
    out: Path
    main: int
    backup: int
    missing: list = field(default_factory=list)     # (slide id, path)
    drafts: list = field(default_factory=list)      # slide ids with [DRAFT] in their notes
    stacked: list = field(default_factory=list)     # handout: animated slides with no final frame


def front_matter(text: str) -> tuple[dict, str]:
    """Split `---` front matter off the top of an outline. Unknown keys raise, so a typo
    can't silently fall back to a default."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta = {}
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return meta, "\n".join(lines[i + 1:])
        if line.strip():
            key, sep, val = line.partition(":")
            if not sep or key.strip() not in FRONT_KEYS:
                raise ValueError(f"front matter line {i + 1}: {line!r} (keys: {sorted(FRONT_KEYS)})")
            meta[key.strip()] = val.strip()
    raise ValueError("front matter opened with --- but never closed")


def parse(text: str) -> list[dict]:
    slides, cur, in_notes = [], None, False
    for line in text.splitlines():
        m = re.match(r"^### (S\d+|B\d+) · (.+)$", line)
        if m:
            cur = {"id": m.group(1), "title": m.group(2).strip(), "bullets": [], "notes": []}
            slides.append(cur)
            in_notes = False
            continue
        if cur is None:
            continue
        if in_notes:
            cur["notes"].append(line)
        elif line.strip() == "notes:":
            in_notes = True
        elif line.startswith("- "):
            cur["bullets"].append(line[2:].strip())
        elif (k := re.match(r"^build:\s*(.+)$", line)):
            cur.setdefault("builds", []).append(("fig", k.group(1).strip()))
        elif (k := re.match(r"^equation:\s*(.+?)(?:\s+@x=([0-9.]+))?\s*$", line)):
            if "equation" in cur:
                raise ValueError(f"{cur['id']}: one `equation:` per slide")
            cur["equation"] = k.group(1).strip()
            cur["equation_x"] = float(k.group(2)) if k.group(2) else None
            if "figure" in cur:
                cur.setdefault("builds", []).append(("eq", cur["equation"]))
        elif (k := re.match(r"^derivation:\s*(.+)$", line)):
            parts = [x.strip() for x in k.group(1).split(" >> ")]
            cur.setdefault("derivation", []).append(parts)
            li = len(cur["derivation"]) - 1
            for pi in range(len(parts)):
                cur.setdefault("builds", []).append(("deq", (li, pi)))
        elif (k := re.match(r"^movie:\s*(.+)$", line)):
            cur.setdefault("movies", []).append([x.strip() for x in k.group(1).split("|")])
        elif (k := re.match(r"^title_width:\s*([0-9.]+)$", line)):
            cur["title_width"] = float(k.group(1))
        elif (k := re.match(r"^animation:\s*(.+)$", line)):
            cur["animation"] = k.group(1).strip()
        elif (k := re.match(r"^tag:\s*(.+)$", line)):
            cur["tag"] = k.group(1).strip()
        elif (k := re.match(r"^(section|figure|side):\s*(.+)$", line)):
            cur[k.group(1)] = k.group(2).strip()
    return slides


def build(outline: Path, out: Path | None = None, *, theme: deck.Theme | None = None,
          author: str | None = None, root: Path | None = None,
          cache_dir: Path | None = None, handout: bool = False) -> Report:
    """Build `outline` into a .pptx and save it. Arguments override the front matter.
    Missing figures/movies are skipped and listed in `Report.missing`; check it. `handout`: animated
    slides as their final frame, written to <out>_handout.pptx unless `out` is given."""
    outline = Path(outline).resolve()
    explicit_out = out is not None
    meta, body = front_matter(outline.read_text(encoding="utf-8-sig"))   # -sig: Windows editors may add a BOM
    here = outline.parent
    root = Path(root) if root is not None else (here / meta["root"]).resolve() if "root" in meta else here
    out = Path(out) if out is not None else here / meta["out"] if "out" in meta else outline.with_suffix(".pptx")
    if handout and not explicit_out:
        out = out.with_name(out.stem + "_handout.pptx")
    cache = Path(cache_dir) if cache_dir is not None else out.parent / "_generated"
    author = author if author is not None else meta.get("author", "")
    missing, stacked = [], []
    if theme is None:
        logos = {k: root / meta[k] for k in ("logo", "title_logo") if k in meta}
        missing += [(k, meta[k]) for k, p in logos.items() if not p.exists()]   # slot shows; build fails
        theme = deck.Theme(**logos)

    slides = parse(body)
    prs = deck.new_presentation()
    for s in slides:
        notes = "\n".join(s["notes"]).strip()
        if s.get("section") == "title":
            slide = deck.title_slide(prs, theme, s["title"], author, name=s["id"])
        else:
            footer = str(len(prs.slides) + 1)
            slide, box = deck.content_slide(prs, theme, s["title"], footer,
                                            name=f"{s['id']} — {s['title']}")
            if "title_width" in s:
                next(sh for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text == s["title"]
                     ).width = Inches(s["title_width"])
            if "tag" in s:
                left, top, w, h = box
                tw, th = Inches(2.6), Inches(0.5)
                tb = deck._text(slide, (left + w - tw, top, tw, th), s["tag"], pt=18, color=theme.ink,
                                font=theme.font, align=deck.PP_ALIGN.CENTER, anchor=deck.MSO_ANCHOR.MIDDLE)
                tb.line.color.rgb, tb.line.width = deck._rgb(theme.ink), Pt(1.25)
                box = (left, top + th + Inches(0.1), w, h - th - Inches(0.1))
            if "movies" in s:
                # Equal columns, one per movie (+ one for `side:`); each label sits above its movie
                # in ink at body size: it names the condition compared, so it is content, not caption.
                left, top, w, h = box
                cols = s["movies"] + ([["", s["side"], None]] if "side" in s else [])
                gap = Inches(0.4)
                cw = int((w - gap * (len(cols) - 1)) / len(cols))
                lab_h = Inches(0.55)
                for j, (label, path, poster) in enumerate(cols):
                    x = left + j * (cw + gap)
                    if label:
                        deck._text(slide, (x, top, cw, lab_h), label, pt=theme.body_pt,
                                   bold=True, color=theme.ink, font=theme.font,
                                   align=deck.PP_ALIGN.CENTER)
                    cell = (x, top + lab_h, cw, h - lab_h)
                    src = root / path
                    if not src.exists() or (poster and not (root / poster).exists()):
                        missing.append((s["id"], path))
                    elif poster:
                        deck.add_movie(slide, src, root / poster, cell)
                    else:
                        deck.add_figure(slide, src, cell, cache)
            elif "animation" in s:
                man_path = root / s["animation"]
                man = json.loads(man_path.read_text())

                def at(p):
                    # root-relative (older manifests), else beside the manifest (figlib.layers anim)
                    return root / p if (root / p).exists() else man_path.parent / p
                final = at(man["final"]) if man.get("final") else None
                if handout and final is not None and final.exists():
                    deck.add_figure(slide, final, box, cache)       # the last click, flat
                    man = {"layers": []}
                elif handout:
                    stacked.append(s["id"])
                pics = {}
                for lay in man["layers"]:
                    # a layer is a PNG, or an MP4 with its poster; both fit `box` the same way
                    srcs = [lay["mp4"], lay["poster"]] if "mp4" in lay else [lay["png"]]
                    if not all(at(p).exists() for p in srcs):
                        missing.extend((s["id"], p) for p in srcs if not at(p).exists())
                    elif "mp4" in lay:
                        pics[lay["id"]] = deck.add_movie(slide, at(lay["mp4"]), at(lay["poster"]), box)
                    else:
                        pics[lay["id"]] = deck.add_figure(slide, at(lay["png"]), box, cache)
                if man["layers"] and len(pics) == len(man["layers"]):
                    emu = next(iter(pics.values())).width / man["canvas"][0]     # EMU per canvas unit

                    def conv(click):
                        return [[(e[0], pics[e[1]], e[2])
                                 + ((round(e[3] * emu), round(e[4] * emu)) if e[0] == "move" else ())
                                 for e in ph] for ph in click]
                    deck.animate(slide, [conv(c) for c in man["steps"]],
                                 slide_w=prs.slide_width, slide_h=prs.slide_height,
                                 auto=conv(man["auto"]) if man.get("auto") else None,
                                 loop=[pics[la["id"]] for la in man["layers"] if la.get("loop")])
            elif "figure" in s:
                eq, deqs = None, []
                if "equation" in s and "derivation" in s:
                    raise ValueError(f"{s['id']}: `equation:` and `derivation:` on one slide")
                if "equation" in s:
                    eq, box = deck.add_equation(slide, s["equation"], box, cache)
                if "derivation" in s:
                    left, top, w, h = box
                    fw = int(w * FIG_FRAC)
                    deqs = deck.add_equation_column(slide, s["derivation"],
                                                    (left + fw + DERIV_GAP, top, w - fw - DERIV_GAP, h),
                                                    cache)
                    box = (left, top, fw, h)
                eq_box = box if eq is None else (box[0], eq.top, box[2], box[1] + box[3] - eq.top)
                fig = root / s["figure"]
                if fig.exists():
                    figpic = deck.add_figure(slide, fig, box, cache)
                    if eq is not None and s.get("equation_x") is not None:
                        x = figpic.left + s["equation_x"] * figpic.width - eq.width / 2
                        eq.left = int(min(max(x, eq_box[0]), eq_box[0] + eq_box[2] - eq.width))
                else:
                    missing.append((s["id"], s["figure"]))
                layers = []
                for kind, b in s.get("builds", []):
                    if kind == "eq":
                        layers.append(eq)
                    elif kind == "deq":
                        layers.append(deqs[b[0]][b[1]])
                    elif (root / b).exists():
                        layers.append(deck.add_figure(slide, root / b, box, cache))
                    else:
                        missing.append((s["id"], b))
                deck.build_on_click(slide, layers, dur_ms=100)
            elif s["bullets"]:
                deck.bullets(slide, box, s["bullets"], theme)
        deck.set_notes(slide, f"{s['id']} — {s['title']}\n\n{notes}")

    deck.require_clean(prs)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(out)
    n_main = sum(s["id"].startswith("S") for s in slides)
    return Report(out=out, main=n_main, backup=len(slides) - n_main, missing=missing,
                  drafts=[s["id"] for s in slides if "[DRAFT]" in "\n".join(s["notes"])], stacked=stacked)


def starter(dest: Path) -> Path:
    """Copy the starter talk (outline, figure script, schematic, figures) into `dest`, a new or
    empty folder. Returns the outline's path."""
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"{dest} is not empty; give a new folder for the starter talk")
    shutil.copytree(STARTER, dest, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.png", "_generated", "*.pptx", "*_render"))
    return dest / "talk.md"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m figlib.outline", description=__doc__.split("\n")[0])
    ap.add_argument("outline", type=Path, nargs="?")
    ap.add_argument("-o", "--out", type=Path, help="output .pptx (overrides front matter `out:`)")
    ap.add_argument("--handout", action="store_true",
                    help="animated slides as their final frame, for a PDF to send (writes <name>_handout.pptx)")
    ap.add_argument("--starter", type=Path, metavar="DIR",
                    help="copy a five-slide starter talk into DIR (new or empty) instead of building")
    a = ap.parse_args(argv)
    if a.starter:
        print(f"wrote the starter talk: {starter(a.starter)}  (build it: python -m figlib.outline {a.starter / 'talk.md'})")
        return 0
    if a.outline is None:
        ap.error("give an outline to build, or --starter DIR")
    r = build(a.outline, a.out, handout=a.handout)
    print(f"wrote {r.out}: {r.main} main + {r.backup} backup slides")
    if r.drafts:
        print(f"  [DRAFT] flagged in notes: {', '.join(r.drafts)}")
    if r.stacked:
        print(f"  handout: no final frame for {', '.join(r.stacked)} -- these still show every layer at once"
              " (re-run python -m figlib.layers anim on their figures)")
    for sid, f in r.missing:
        print(f"  MISSING {sid}: {f}")
    return 1 if r.missing else 0


if __name__ == "__main__":
    sys.exit(main())

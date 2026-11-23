"""Flat protein silhouettes from structures, at one shared Angstrom scale, for slides.

    python -m figlib.silhouette P52292 --svg kpna2.svg                       # AlphaFold DB, by UniProt ID
    python -m figlib.silhouette P52292 Q14974 O14980 --svg baits.svg         # a row, true relative sizes
    python -m figlib.silhouette cofold.cif --chains A=XPO1,B=RanGTP,C=cargo --svg complex.svg
    python -m figlib.silhouette cofold.cif --views views.png                 # pick a view, then --view 3:270

A silhouette is computed from coordinates, not traced from a screenshot: CA atoms, minus residues
with pLDDT below 65 in predicted models (disordered tails would otherwise smear the shape),
projected onto the view plane, dilated to 4 A, hole-filled, smoothed and contoured. Chains are
drawn far to near; each gets a label anchor at the most interior point of its VISIBLE part.
Every silhouette is in Angstrom, so anything drawn together is at true relative size.

Views are `axis:degrees`: the view direction turns about principal axis 1, 2 or 3 of the CA
cloud. The default `2:90` looks along the smallest axis (the largest outline) with the longest
axis horizontal. `--views` writes a sheet of 24 views to choose from.

Sources: a .cif/.pdb file (AlphaFast, AlphaFold, PDB), or a UniProt accession, fetched once from
the AlphaFold Protein Structure Database (alphafold.ebi.ac.uk, CC BY 4.0: cite it) into a cache
($FIGLIB_CACHE, else the user cache dir, /figlib/afdb). pLDDT filtering applies only to predicted
models; an experimental structure (resolution or method declared) keeps every residue.

Outputs: SVG (fitted to a 16:9 slide, palette colours, Calibri labels; goes straight into an outline's
`figure:`) or JSON (`{w, h, chains: [{name, rings: [[[x, y], ...], ...], anchor: [x, y]}]}`, Angstrom,
y down) for HTML figures. Needs the `structure` extra (gemmi, scipy). Generalised 2026-11-23 from
the generals talk's cofold / opener / TurboID outline scripts and the 2026-11-04 bait panel.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from figlib import palette

PLDDT_MIN = 65.0     # predicted models: residues below this are left out of the outline
R_ATOM = 4.0         # A, disc each CA is dilated by
GRID = 1.0           # A per mask pixel
SMOOTH = 2.0         # px, Gaussian before contouring
PAD = 12.0           # A of mask margin around the projected CAs
FRAME = 6.0          # A between the outermost CA and the silhouette's frame
MIN_RING = 0.1       # keep separate pieces (e.g. domains split by a dropped linker) >= this x the largest
DEFAULT_VIEW = "2:90"
FONT = "Calibri, Arial, Helvetica, sans-serif"
UNIPROT = re.compile(r"^([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})$")
AFDB_API = "https://alphafold.ebi.ac.uk/api/prediction/{}"


@dataclass
class Chain:
    name: str
    rings: list                 # (N, 2) arrays, Angstrom, y down, in the silhouette's frame
    anchor: tuple               # most interior visible point
    depth: float                # mean distance along the view; larger = farther


@dataclass
class Silhouette:
    chains: list                # far to near: draw in this order
    w: float
    h: float
    source: str
    view: str
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"source": self.source, "view": self.view, "w": round(self.w, 1), "h": round(self.h, 1),
                "chains": [{"name": c.name, "rings": [np.round(r, 1).tolist() for r in c.rings],
                            "anchor": [round(float(v), 1) for v in c.anchor]} for c in self.chains]}


# --------------------------------------------------------------------------- sources

def cache_dir() -> Path:
    base = os.environ.get("FIGLIB_CACHE")
    if base:
        return Path(base) / "afdb"
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches"
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return root / "figlib" / "afdb"


def fetch(accession: str, cache: Path | None = None) -> tuple[Path, str]:
    """The AlphaFold DB model for a UniProt accession, downloaded once: (cif path, gene name)."""
    acc = accession.upper()
    cache = Path(cache) if cache else cache_dir()
    meta_path = cache / f"AF-{acc}.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if (cache / meta["file"]).exists():
            return cache / meta["file"], meta["gene"]
    cache.mkdir(parents=True, exist_ok=True)
    from figlib import __version__
    ua = {"User-Agent": f"figlib/{__version__}"}   # a bare "figlib" gets HTTP 403 from EBI
    req = urllib.request.Request(AFDB_API.format(acc), headers=ua)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            entries = json.load(r)
    except urllib.error.HTTPError as e:
        raise LookupError(f"AlphaFold DB has no model for {acc} (HTTP {e.code})") from None
    if not entries:
        raise LookupError(f"AlphaFold DB has no model for {acc}")
    entry = entries[0]                    # F1; very long proteins are split into fragments
    url = entry["cifUrl"]
    out = cache / url.rsplit("/", 1)[1]
    with urllib.request.urlopen(urllib.request.Request(url, headers=ua), timeout=60) as r:
        data = r.read()
    tmp = out.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(out)
    gene = entry.get("gene") or acc
    meta_path.write_text(json.dumps({"file": out.name, "gene": gene, "entry": entry.get("entryId"),
                                     "version": entry.get("latestVersion")}))
    return out, gene


def load(source, chains=None, plddt_min: float = PLDDT_MIN):
    """CA coordinates per chain: ({label: (N, 3) array}, default name, notes).

    `chains`: None (every chain with protein residues), a list of chain ids, or {id: label}."""
    import gemmi
    notes = []
    name = None
    src = str(source)
    if not Path(src).exists() and UNIPROT.match(src.upper()):
        path, name = fetch(src)
        notes.append(f"{src.upper()}: AlphaFold DB {path.name}")
    else:
        path = Path(src)
        if not path.exists():
            raise FileNotFoundError(f"{src}: no such file, and not a UniProt accession")
    st = gemmi.read_structure(str(path))
    predicted = st.resolution == 0 and not any(
        "PREDICT" not in (e.method or "").upper() and "THEORETICAL" not in (e.method or "").upper()
        for e in st.meta.experiments)
    if not predicted:
        plddt_min = None
        notes.append(f"{path.name}: experimental structure, all residues kept (B-factors are not pLDDT)")
    if chains is None:
        wanted = None
    elif isinstance(chains, dict):
        wanted = dict(chains)
    else:
        wanted = {c: c for c in chains}
    out = {}
    for ch in st[0]:
        if wanted is not None and ch.name not in wanted:
            continue
        ca = [a for r in ch for a in r if a.name == "CA" and a.element.name == "C"]
        kept = [a for a in ca if plddt_min is None or a.b_iso >= plddt_min]
        if not ca:
            continue                                   # ligand / ion / nucleic-acid chain
        if plddt_min is not None and len(kept) < len(ca):
            notes.append(f"chain {ch.name}: {len(ca) - len(kept)} of {len(ca)} residues below pLDDT {plddt_min:g} left out")
        if len(kept) < 3:
            notes.append(f"chain {ch.name}: fewer than 3 confident residues, skipped")
            continue
        label = wanted[ch.name] if wanted else ch.name
        out[label] = np.array([(a.pos.x, a.pos.y, a.pos.z) for a in kept])
    if wanted is not None:
        missing = [c for c in wanted if wanted[c] not in out]
        if missing:
            raise ValueError(f"{path.name}: chains {missing} not found or have no confident residues")
    if not out:
        raise ValueError(f"{path.name}: no protein chains")
    return out, name or path.stem, notes


# --------------------------------------------------------------------------- geometry

def _parse_view(view: str) -> tuple[int, float]:
    m = re.fullmatch(r"\s*([123])\s*:\s*(-?[0-9.]+)\s*", view or DEFAULT_VIEW)
    if not m:
        raise ValueError(f"view {view!r}: use axis:degrees, axis 1-3, e.g. 2:90")
    return int(m.group(1)) - 1, float(m.group(2))


def _mask(P, lo, shape):
    from scipy.ndimage import binary_dilation, binary_fill_holes, gaussian_filter
    g = np.zeros(shape, dtype=bool)
    ij = ((P - lo) / GRID).astype(int)
    g[ij[:, 1], ij[:, 0]] = True
    rr = int(np.ceil(R_ATOM / GRID))
    yy, xx = np.mgrid[-rr:rr + 1, -rr:rr + 1]
    g = binary_fill_holes(binary_dilation(g, structure=(xx ** 2 + yy ** 2) <= rr ** 2))
    return gaussian_filter(g.astype(float), SMOOTH)


def _area(v):
    return abs(np.sum(v[:-1, 0] * v[1:, 1] - v[1:, 0] * v[:-1, 1])) / 2


def _rings(g, lo):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    f = plt.figure()
    cs = plt.contour(np.arange(g.shape[1]) * GRID + lo[0], np.arange(g.shape[0]) * GRID + lo[1], g, levels=[0.5])
    plt.close(f)
    polys = [v for p in cs.get_paths() for v in p.to_polygons() if len(v) > 3]
    if not polys:
        return []
    big = max(_area(v) for v in polys)
    return sorted((v for v in polys if _area(v) >= MIN_RING * big), key=_area, reverse=True)


def project(coords: dict, view: str = DEFAULT_VIEW, source: str = "", notes=None) -> Silhouette:
    """Silhouette of the chains in `coords` ({label: (N, 3)}) seen from `view`."""
    from scipy.ndimage import distance_transform_edt
    ax_i, deg = _parse_view(view)
    allx = np.vstack(list(coords.values()))
    c = allx.mean(0)
    vt = np.linalg.svd(allx - c, full_matrices=False)[2]
    p, q = [i for i in range(3) if i != ax_i]
    up, t = vt[ax_i], np.deg2rad(deg)
    look = np.cos(t) * vt[p] + np.sin(t) * vt[q]
    hor = np.cross(up, look)
    proj = {n: np.c_[(x - c) @ hor, -((x - c) @ up)] for n, x in coords.items()}   # y down, as SVG
    depth = {n: float(((x - c) @ look).mean()) for n, x in coords.items()}
    order = sorted(coords, key=lambda n: -depth[n])                                  # far first
    allp = np.vstack(list(proj.values()))
    lo = allp.min(0) - PAD
    shape = tuple(np.ceil((allp.max(0) + PAD - lo) / GRID).astype(int)[::-1])
    masks = {n: _mask(proj[n], lo, shape) for n in order}
    x0 = allp.min(0) - FRAME
    notes = list(notes or [])
    chains = []
    for k, n in enumerate(order):
        visible = masks[n] > 0.5
        for nearer in order[k + 1:]:
            visible &= masks[nearer] <= 0.5
        if visible.sum() < 50:
            notes.append(f"{n}: almost entirely hidden behind nearer chains in view {view}; try --views")
            visible = masks[n] > 0.5
        d = distance_transform_edt(visible)
        iy, ix = np.unravel_index(np.argmax(d), d.shape)
        anchor = lo + np.array([ix, iy]) * GRID - x0
        rings = [r[::2] - x0 for r in _rings(masks[n], lo)]
        chains.append(Chain(name=n, rings=rings, anchor=(float(anchor[0]), float(anchor[1])), depth=depth[n]))
    ext = allp.max(0) - allp.min(0) + 2 * FRAME
    return Silhouette(chains=chains, w=float(ext[0]), h=float(ext[1]), source=source, view=view, notes=notes)


def silhouette(source, chains=None, view: str = DEFAULT_VIEW, plddt_min: float = PLDDT_MIN) -> Silhouette:
    """Load `source` (file or UniProt accession) and project it. A single-chain source is named
    after the protein (the gene name for an AlphaFold DB model) unless `chains` names it."""
    coords, name, notes = load(source, chains, plddt_min)
    if chains is None and len(coords) == 1:
        coords = {name: next(iter(coords.values()))}
    return project(coords, view, source=str(source), notes=notes)


# --------------------------------------------------------------------------- drawing

def _hex(rgb):
    return "#" + "".join(f"{int(round(v)):02x}" for v in rgb)


def _shade(color: str, k: float = 0.35) -> str:
    rgb = np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], float)
    return _hex(rgb * (1 - k))


def _ink_on(color: str) -> str:
    rgb = np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], float) / 255
    lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    return "#ffffff" if lum < 0.5 else palette.ROLE["ink"]


def _path(rings, dx, dy):
    return " ".join("M" + " L".join(f"{x + dx:.1f},{y + dy:.1f}" for x, y in r) + " Z" for r in rings)


def svg(sils, *, names=None, colors=None, labels: bool = True, gap: float = 30.0,
        slide=(13.333, 7.5)) -> str:
    """SVG of one silhouette, or several in a row (bottom-aligned, one shared Angstrom scale).

    Colours: palette.SERIES in order, per chain for a multi-chain silhouette, per silhouette for a
    row of single chains. Labels: chain names on multi-chain silhouettes (at each chain's anchor),
    the protein's name under each member of a row."""
    from figlib import __version__
    sils = list(sils) if isinstance(sils, (list, tuple)) else [sils]
    names = list(names) if names else [s.chains[0].name if len(s.chains) == 1 else Path(s.source).stem for s in sils]
    row_labels = labels and all(len(s.chains) == 1 for s in sils)
    H = max(s.h for s in sils)
    W = sum(s.w for s in sils) + gap * (len(sils) - 1)
    size = 0.027 * max(W, H * slide[0] / slide[1])        # ~24 pt once the SVG fills a slide
    stroke = size * 0.09
    lab_h = size * 1.6 if row_labels else 0.0
    total_h = H + lab_h
    singles = all(len(s.chains) == 1 for s in sils)
    cols = list(colors) if colors else palette.SERIES
    out, x = [], 0.0
    for i, s in enumerate(sils):
        dy = H - s.h
        for j, c in enumerate(s.chains):
            col = cols[(i if singles else j) % len(cols)]   # per protein in a row, per chain in a complex
            out.append(f'<path d="{_path(c.rings, x, dy)}" fill="{col}" stroke="{_shade(col)}" '
                       f'stroke-width="{stroke:.2f}" stroke-linejoin="round"><title>{c.name}</title></path>')
            if labels and len(s.chains) > 1:
                ax, ay = c.anchor
                out.append(f'<text x="{ax + x:.1f}" y="{ay + dy:.1f}" font-family="{FONT}" font-size="{size:.1f}" '
                           f'font-weight="700" fill="{_ink_on(col)}" text-anchor="middle" '
                           f'dominant-baseline="central">{c.name}</text>')
        if row_labels:
            out.append(f'<text x="{x + s.w / 2:.1f}" y="{H + size * 1.25:.1f}" font-family="{FONT}" '
                       f'font-size="{size:.1f}" fill="{palette.ROLE["ink"]}" text-anchor="middle">{names[i]}</text>')
        x += s.w + gap
    scale = min(slide[0] / W, slide[1] / total_h)
    meta = "; ".join(f"{s.source} view {s.view}" for s in sils)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.1f} {total_h:.1f}" '
            f'width="{W * scale:.3f}in" height="{total_h * scale:.3f}in">\n'
            f'<metadata id="figlib-provenance">figlib.silhouette {__version__}; {meta}; '
            f'pLDDT >= {PLDDT_MIN:g} (predicted models); Angstrom units</metadata>\n'
            + "\n".join(out) + "\n</svg>\n")


def views_sheet(coords: dict, out: Path, source: str = "") -> Path:
    """A 3 x 8 sheet of views (`axis:degrees`) to choose from."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from figlib import fonts
    fonts.register()
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": fonts.STACK_LIST})
    fig, axes = plt.subplots(3, 8, figsize=(16, 6.6))
    sils = {(a, deg): project(coords, f"{a + 1}:{deg}") for a in range(3) for deg in range(0, 360, 45)}
    mw, mh = max(s.w for s in sils.values()), max(s.h for s in sils.values())   # one scale for every panel
    for (a, deg), s in sils.items():
        ax = axes[a, deg // 45]
        for c in s.chains:
            col = palette.SERIES[list(coords).index(c.name) % len(palette.SERIES)]
            for r in c.rings:
                ax.fill(r[:, 0], r[:, 1], color=col, ec=_shade(col), lw=0.6)
        ax.set_xlim(s.w / 2 - mw / 2, s.w / 2 + mw / 2)
        ax.set_ylim(s.h / 2 + mh / 2, s.h / 2 - mh / 2)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title(f"{a + 1}:{deg}", fontsize=11)
    names = ", ".join(f"{n}" for n in coords)
    fig.suptitle(f"{Path(source).name or source}: {names}   (colours in palette order)", fontsize=12)
    fig.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return Path(out)


# --------------------------------------------------------------------------- CLI

def _chains_arg(text):
    """'A=XPO1,B=RanGTP,C' -> {'A': 'XPO1', 'B': 'RanGTP', 'C': 'C'}"""
    if not text:
        return None
    out = {}
    for item in text.split(","):
        cid, _, label = item.partition("=")
        out[cid.strip()] = label.strip() or cid.strip()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m figlib.silhouette", description=__doc__.split("\n")[0])
    ap.add_argument("sources", nargs="+", help=".cif/.pdb files or UniProt accessions")
    ap.add_argument("--chains", help="which chains and their labels: A=XPO1,B=RanGTP (default: every protein chain)")
    ap.add_argument("--names", help="comma-separated names for a row of proteins (default: gene names)")
    ap.add_argument("--view", default=DEFAULT_VIEW, help="axis:degrees (default 2:90, the largest outline)")
    ap.add_argument("--plddt", type=float, default=PLDDT_MIN, help="pLDDT floor for predicted models")
    ap.add_argument("--svg", type=Path, help="write an SVG (fits a 16:9 slide)")
    ap.add_argument("--json", type=Path, help="write outlines as JSON, for HTML figures")
    ap.add_argument("--views", type=Path, help="write a PNG sheet of 24 views (first source) to choose --view")
    ap.add_argument("--no-labels", action="store_true")
    a = ap.parse_args(argv)
    if not (a.svg or a.json or a.views):
        ap.error("give at least one of --svg, --json, --views")
    chains = _chains_arg(a.chains)
    if a.views:
        coords, name, notes = load(a.sources[0], chains, a.plddt)
        if chains is None and len(coords) == 1:
            coords = {name: next(iter(coords.values()))}
        print("\n".join(notes) or "", end="\n" if notes else "")
        print("wrote", views_sheet(coords, a.views, a.sources[0]))
    if a.svg or a.json:
        sils = [silhouette(s, chains, a.view, a.plddt) for s in a.sources]
        for s in sils:
            for n in s.notes:
                print(" ", n)
        if a.svg:
            names = [n.strip() for n in a.names.split(",")] if a.names else None
            a.svg.write_text(svg(sils, names=names, labels=not a.no_labels), encoding="utf-8")
            print("wrote", a.svg)
        if a.json:
            data = [s.to_dict() for s in sils]
            a.json.write_text(json.dumps(data[0] if len(data) == 1 else data, ensure_ascii=False), encoding="utf-8")
            print("wrote", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""One source of truth for figure colour, and the CVD validator that checks it.

    from figlib import palette as pal
    ax.plot(..., color=pal.entity("GNN"))      # one entity, one colour, in every figure
    ax.tick_params(colors=pal.ROLE["ink_2"])
    pal.validate(["#0072B2", "#D55E00"])       # contrast + colour-blindness checks
    print(pal.as_css_vars())                   # the same tokens for HTML+SVG figures

Find hardcoded colours that disagree with the registry, or should be tokens:

    python -m figlib.palette drift scripts/ figures/html/   # exits 1 on any disagreement
"""

# stdlib only, on purpose: Manim scene files and lighter envs import this.
import ast
import math
import os
import re

# The categorical ramp, in the dataviz reference ORDER -- the order is itself the
# CVD-safety mechanism, so don't resort it. Adjacent pairs clear CVD dE 9.1 / normal
# 19.6; only the first three also clear all-pairs (9.2 / 24.0), so only three are
# spent on model families.
SERIES = ["#2a78d6",  # 1 blue
          "#eb6834",  # 2 orange
          "#1baf7a",  # 3 aqua
          "#eda100",  # 4 yellow
          "#e87ba4",  # 5 magenta
          "#008300",  # 6 green
          "#4a3aa7",  # 7 violet
          "#e34948"]  # 8 red

SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500",
               "#d55181", "#008300", "#9085e9", "#e66767"]

# Text / structure tokens: five roles for every grey a figure needs.
ROLE = {
    "ink":      "#0b0b0b",   # primary text, reference lines
    "ink_2":    "#52514e",   # secondary text, axis labels, tick labels
    "ink_3":    "#8a8985",   # muted text, de-emphasis, spines
    "grid":     "#e4e3df",   # gridlines
    "surface":  "#fcfcfb",   # chart surface / marker knockout
}
ROLE_DARK = {
    "ink": "#ffffff", "ink_2": "#c3c2b7", "ink_3": "#8a8985",
    "grid": "#2e2e2c", "surface": "#1a1a19",
}

# ENTITY -- semantic name to colour. One entity, one colour, across every figure in
# a deck: "blue = GNN" on slide 6 must still be true on slide 11.
ENTITY = {
    # -- model families, on the first validated SERIES slots.
    "GNN":            SERIES[0],
    "RF":             SERIES[1],
    "blend":          SERIES[2],

    # -- what a model is measured against. ink_2, not ink_3: baselines are drawn as
    # marks beside model marks, so they must clear the separation floors, and ink_3
    # fails against `blend` (CVD dE 4.8 < 6.0, normal 14.4 < 15.0). ink_2 clears
    # both and still reads as de-emphasised. Figures that never draw `blend` may
    # keep ink_3 for baselines.
    "baseline_free":  ROLE["ink_2"],
    "pose":           SERIES[0],   # same slot as GNN; see SHARED_SLOTS

    # -- gene tiers on cargo-vs-background figures.
    "cargo":          "#08519C",   # confirmed / co-crystal-proven cargo
    "background":     "#BDBDBD",   # the proteome background
    "receptor_other": "#D55E00",   # a non-KPNA2 receptor (RCC1's KPNA4 case)

    # -- transport modes. Passive is the reference every active curve is read
    # against, so it takes ink and sits in CONTEXT. Import/export avoid blue/orange,
    # which already mean GNN/RF.
    "passive":        ROLE["ink"],
    "import":         SERIES[6],   # violet
    "export":         SERIES[7],   # red
}

# SCHEMATIC -- Okabe-Ito slots for HTML+SVG conceptual diagrams, not charts.
# Generic slots (chain_a/chain_b, ...), not fixed proteins: assign per figure and keep
# the assignment constant across a deck. Charts and schematics never share an axis,
# so the two sources can coexist; don't mix them within one figure.
SCHEMATIC = {
    "chain_a":   {"fill": "#009E73", "stroke": "#00543D"},
    "chain_b":   {"fill": "#CC79A7", "stroke": "#7A3F60"},
    "chain_c":   {"fill": "#E69F00", "stroke": "#8A5E00"},
    "chain_d":   {"fill": "#0072B2", "stroke": "#00436A"},
    "chain_e":   {"fill": "#D55E00", "stroke": "#7E3800"},
    "ink":       {"fill": "#1C2530", "stroke": "#1C2530"},  # deck's --ink
    "muted":     {"fill": "#5B6672", "stroke": "#5B6672"},  # deck's --muted
    "hairline":  {"fill": "#D3D9E0", "stroke": "#D3D9E0"},  # deck's --hairline
}

# ARGUMENT -- what a thing means in the figure's argument ("the thing that was
# broken" vs "the thing that fixed it"), a role a different entity can occupy on
# each slide. A separate axis from ENTITY; not in GROUPS, and checked by its own test.
#
# These colours collide with ENTITY (broken == receptor_other; fixed is dE 6.1 from
# GNN). That is safe only because ARGUMENT is for HTML+SVG schematics and ENTITY for
# matplotlib charts, and no figure uses both -- enforced by
# `test_argument_axis_is_schematic_only` and `test_no_figure_mixes_the_two_axes`.
# If a figure ever needs both, recolour ARGUMENT onto hues ENTITY doesn't use.
ARGUMENT = {
    "broken":  "#D55E00",   # vermilion -- the invalidated / discarded thing
    "fixed":   "#0072B2",   # blue      -- the corrected / retained thing
    "holdout": "#009E73",   # green     -- material held out of training
    "context": "#5B6672",   # the deck's --muted; never carries an argument
}

#: The three that carry meaning and can co-appear in one schematic. `context` is
#: deliberately excluded: it is a neutral doing de-emphasis work, exactly like
#: CONTEXT in the ENTITY checks.
ARGUMENT_CATEGORICAL = ("broken", "fixed", "holdout")


def argument(name):
    """ARGUMENT lookup that fails loudly on a typo. See `entity` for the why."""
    try:
        return ARGUMENT[name]
    except KeyError:
        raise KeyError(
            f"unknown argument role {name!r}. Known: {sorted(ARGUMENT)}. These "
            "are figure-argument roles (broken/fixed/holdout/context), NOT "
            "entities -- if you want a protein or model family, use entity()."
        ) from None


# SHARED_SLOTS -- entity pairs deliberately drawn in the same colour, safe only while
# no figure draws both; `test_no_file_draws_a_shared_slot_pair` keeps that true. If it
# fails, move the second member to a free SERIES slot.
SHARED_SLOTS = (("GNN", "pose"),)

# SEQUENTIAL -- matplotlib colormap names for density (hexbin, 2-D histograms). Not
# validated here (stdlib only); the tests check they are real colormaps.
#
# A density field and the categorical marks on top of it must not share a hue:
# `density` is Blues and SERIES[0] is blue, so use `density_warm` on any axis that
# also carries a blue categorical mark.
SEQUENTIAL = {
    "density":       "Blues",    # safe with no blue marks
    "density_warm":  "Oranges",  # when a blue categorical mark shares the axis
    "density_mono":  "Greys",    # when ANY hue would compete
    "diverging":     "RdBu_r",   # signed quantities, zero-centred
}


def sequential(name):
    """SEQUENTIAL lookup that fails loudly on a typo. See `entity` for the why."""
    try:
        return SEQUENTIAL[name]
    except KeyError:
        raise KeyError(
            f"unknown sequential ramp {name!r}. Known: {sorted(SEQUENTIAL)}. "
            "Add it here rather than hardcoding a cmap string in a figure."
        ) from None


# Entity class. The lightness-band and chroma-floor checks apply to marks doing
# identity work (CATEGORICAL), not to deliberately neutral context fills (CONTEXT),
# e.g. a light violin background. Separation and contrast apply to everything.
CATEGORICAL = {"GNN", "RF", "blend", "cargo", "pose", "receptor_other",
               "import", "export"}
CONTEXT = {"baseline_free", "background", "passive"}

#: Sets that are drawn in ONE figure and therefore must be mutually separable.
#: `validate_registry()` checks each; a new figure combining entities in a way
#: not listed here should add its combination rather than assume it is safe.
GROUPS = {
    "model families":            (["GNN", "RF", "blend"], "all"),
    "model families + baseline": (["GNN", "RF", "blend", "baseline_free"], "all"),
    "pose vs baseline":          (["pose", "baseline_free"], "all"),
    "cargo tiers":               (["cargo", "background", "receptor_other"], "all"),
    "transport modes":           (["passive", "import", "export"], "all"),
}


def validate_registry():
    """Validate every GROUP with the checks appropriate to each entity's class.

    Returns {group_name: report}. Unlike `validate()`, which treats every colour
    as categorical, this exempts CONTEXT fills from the band/chroma checks.
    """
    out = {}
    for label, (names, pairs) in GROUPS.items():
        cols = [entity(n) for n in names]
        rep = validate(cols, pairs=pairs)
        exempt = {entity(n) for n in names if n in CONTEXT}
        # Drop band/chroma complaints that belong to a context fill; keep every
        # separation and contrast finding, which apply regardless of class.
        rep["fails"] = [f for f in rep["fails"]
                        if not (f.startswith(("lightness band", "chroma floor"))
                                and any(h in f for h in exempt))]
        rep["ok"] = not rep["fails"]
        rep["entities"] = names
        out[label] = rep
    return out


def entity(name):
    """ENTITY lookup that fails loudly on a typo.

    `ENTITY.get("gnn")` returning None would silently draw a black line; this
    raises instead. Prefer it at call sites.
    """
    try:
        return ENTITY[name]
    except KeyError:
        raise KeyError(
            f"unknown entity {name!r}. Known: {sorted(ENTITY)}. Add it here "
            "rather than hardcoding a hex in a figure script -- that is the "
            "drift this module exists to stop.") from None


# The validator: a port of the dataviz skill's validate_palette.js -- same
# Machado-Oliveira-Fernandes (2009) severity-1.0 matrices, OKLab coefficients and
# thresholds. The CVD thresholds are calibrated to this simulation model, so don't
# swap the model without recalibrating. `validate_reference()` checks the port.
BAND = {"light": (0.43, 0.77), "dark": (0.48, 0.67)}   # OKLCH L
CHROMA_FLOOR = 0.10
CVD_TARGET, CVD_FLOOR = 8.0, 6.0
NORMAL_FLOOR = 15.0
CONTRAST_MIN = 3.0
DEFAULT_SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}

_MACHADO = {
    "protan": ((0.152286, 1.052583, -0.204868),
               (0.114503, 0.786281, 0.099216),
               (-0.003882, -0.048116, 1.051998)),
    "deutan": ((0.367322, 0.860646, -0.227968),
               (0.280085, 0.672501, 0.047413),
               (-0.011820, 0.042940, 0.968881)),
    "tritan": ((1.255528, -0.076749, -0.178779),
               (-0.078411, 0.930809, 0.147602),
               (0.004733, 0.691367, 0.303900)),
}

_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


def _lin(h):
    h = h.strip().lstrip("#")
    if not _HEX_RE.match(h):
        raise ValueError(f"not a 6-digit hex colour: {h!r}")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def _oklab(rgb):
    r, g, b = rgb
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def oklch(h):
    """(lightness, chroma) in OKLCH."""
    L, a, b = _oklab(_lin(h))
    return L, math.hypot(a, b)


def contrast(a, b):
    """WCAG contrast ratio between two hex colours."""
    def lum(h):
        r, g, bb = _lin(h)
        return 0.2126 * r + 0.7152 * g + 0.0722 * bb
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _simulate(h, kind):
    r, g, b = _lin(h)
    M = _MACHADO[kind]
    return [min(1.0, max(0.0, M[i][0] * r + M[i][1] * g + M[i][2] * b))
            for i in range(3)]


def delta_e(h1, h2, kind=None):
    """Euclidean OKLab distance x100. kind=None is unsimulated vision."""
    a = _oklab(_simulate(h1, kind) if kind else _lin(h1))
    b = _oklab(_simulate(h2, kind) if kind else _lin(h2))
    return 100 * math.dist(a, b)


def validate(colors, mode="light", surface=None, pairs="adjacent"):
    """The five computable checks. Returns a report dict; never raises on a
    failing palette -- the caller decides whether a FAIL is fatal.

    pairs="adjacent" is right for bars/lines/stacks (only neighbours are
    compared); pairs="all" for scatter/small-multiples, where any two marks can
    land side by side.
    """
    surface = surface or DEFAULT_SURFACE[mode]
    lo, hi = BAND[mode]
    fails, warns = [], []

    for h in colors:
        L, C = oklch(h)
        if not lo <= L <= hi:
            fails.append(f"lightness band: {h} L={L:.3f} outside [{lo}, {hi}]")
        if C < CHROMA_FLOOR:
            fails.append(f"chroma floor: {h} C={C:.3f} < {CHROMA_FLOOR}")
        c = contrast(h, surface)
        if c < CONTRAST_MIN:
            warns.append(f"contrast: {h} {c:.2f}:1 vs surface "
                         "(relief rule -- ship direct labels or a table view)")

    idx = ([(i, i + 1) for i in range(len(colors) - 1)] if pairs == "adjacent"
           else [(i, j) for i in range(len(colors))
                 for j in range(i + 1, len(colors))])

    worst_cvd = worst_norm = float("inf")
    worst_cvd_pair = worst_norm_pair = None
    for i, j in idx:
        a, b = colors[i], colors[j]
        cvd = min(delta_e(a, b, "protan"), delta_e(a, b, "deutan"))
        nrm = delta_e(a, b)
        if cvd < worst_cvd:
            worst_cvd, worst_cvd_pair = cvd, (a, b)
        if nrm < worst_norm:
            worst_norm, worst_norm_pair = nrm, (a, b)
        if cvd < CVD_FLOOR:
            fails.append(f"CVD: {a}/{b} dE={cvd:.1f} < floor {CVD_FLOOR}")
        elif cvd < CVD_TARGET:
            warns.append(f"CVD: {a}/{b} dE={cvd:.1f} in the "
                         f"{CVD_FLOOR}-{CVD_TARGET} band "
                         "(secondary encoding mandatory)")
        if nrm < NORMAL_FLOOR:
            fails.append(f"normal-vision: {a}/{b} dE={nrm:.1f} < {NORMAL_FLOOR}")

    return {"mode": mode, "surface": surface, "pairs": pairs, "n": len(colors),
            "worst_cvd": worst_cvd, "worst_cvd_pair": worst_cvd_pair,
            "worst_normal": worst_norm, "worst_normal_pair": worst_norm_pair,
            "fails": fails, "warns": warns, "ok": not fails}


# The four numbers palette.md documents for its own reference palette. Any port
# of this validator must reproduce them before its output is trusted.
REFERENCE_EXPECTED = {
    ("adjacent", 8): {"worst_cvd": 9.1, "worst_normal": 19.6},
    ("all", 3): {"worst_cvd": 9.2, "worst_normal": 24.0},
}


def validate_reference():
    """Self-test: reproduce palette.md's documented values. Returns (ok, lines).

    Run it after any edit to the conversion math.
    """
    lines, ok = [], True
    for (pairs, n), want in REFERENCE_EXPECTED.items():
        got = validate(SERIES[:n], mode="light", pairs=pairs)
        for key, expect in want.items():
            hit = abs(got[key] - expect) < 0.05
            ok &= hit
            lines.append(f"{'OK ' if hit else 'FAIL'} reference[{pairs},n={n}] "
                         f"{key}: {got[key]:.1f} (documented {expect})")
    return ok, lines


def as_css_vars(names=None, mode="light", indent="  "):
    """Emit the registry as CSS custom properties for HTML+SVG figures.

    Paste the output into the figure's <style> block, so a schematic and a chart of
    the same entity share one colour.
    """
    roles = ROLE_DARK if mode == "dark" else ROLE
    out = [":root {"]
    for k, v in roles.items():
        out.append(f"{indent}--{k.replace('_', '-')}: {v};")
    for k in (names if names is not None else sorted(ENTITY)):
        out.append(f"{indent}--{k.lower().replace('_', '-')}: {entity(k)};")
    for k, v in SCHEMATIC.items():
        out.append(f"{indent}--{k.replace('_', '-')}-fill: {v['fill']};")
        out.append(f"{indent}--{k.replace('_', '-')}-stroke: {v['stroke']};")
    # Prefixed: an unprefixed `--context` would read as a chrome token like --ink.
    for k, v in ARGUMENT.items():
        out.append(f"{indent}--arg-{k}: {v};")
    out.append("}")
    return "\n".join(out)


# Drift detection: find figure sources that hardcode a colour the registry names.
_ALIASES = {"gnn": "GNN", "rf": "RF", "blend": "blend",
            "cargo": "cargo", "pose": "pose"}


def _module_hex_constants(tree):
    """Module-level NAME = "#hex", including tuple unpacking.

    Scripts commonly write `BLUE, GREEN = "#0072B2", "#009E73"` and then use the
    name; without resolving these a static scan sees no colours at all.
    """
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str) \
                    and _HEX_RE.match(node.value.value):
                out[tgt.id] = node.value.value
            elif isinstance(tgt, ast.Tuple) and isinstance(node.value, ast.Tuple):
                for t, v in zip(tgt.elts, node.value.elts):
                    if isinstance(t, ast.Name) and isinstance(v, ast.Constant) \
                            and isinstance(v.value, str) and _HEX_RE.match(v.value):
                        out[t.id] = v.value
    return out


def _resolve(node, consts):
    """A hex literal, or a Name bound to one at module level."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str) \
            and _HEX_RE.match(node.value):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    return None


def scan_entity_mappings(path):
    """Every entity->hex a Python file assigns, via AST. Handles two forms:

      1. a dict literal, `FAM_COLOR = {"GNN": "#2a78d6", ...}`;
      2. a conditional, `return GREEN if m.startswith("GNN") else BLUE`.

    Only the entity named in the condition is recorded; the else-branch entity is
    implicit and not guessed.
    """
    with open(path) as fh:
        try:
            tree = ast.parse(fh.read())
        except SyntaxError:
            return {}
    consts = _module_hex_constants(tree)
    found = {}

    for node in ast.walk(tree):
        # form 1 -- dict literal
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                    continue
                name = _ALIASES.get(k.value.strip().lower())
                hexv = _resolve(v, consts)
                if name and hexv:
                    found[name] = hexv.strip().lower()
        # form 2 -- `A if <test mentioning an entity> else B`
        elif isinstance(node, ast.IfExp):
            names = {_ALIASES.get(c.value.strip().lower())
                     for c in ast.walk(node.test)
                     if isinstance(c, ast.Constant) and isinstance(c.value, str)}
            names.discard(None)
            hexv = _resolve(node.body, consts)
            if len(names) == 1 and hexv:
                found[names.pop()] = hexv.strip().lower()
    return found


def all_tokens():
    """{lowercase hex: [css token names]} across every axis in the registry."""
    out = {}
    def add(hexv, token):
        out.setdefault(hexv.lower(), []).append(token)
    for k, v in ROLE.items():
        add(v, f"--{k.replace('_', '-')}")
    for k in ENTITY:
        add(entity(k), f"--{k.lower().replace('_', '-')}")
    for k, v in ARGUMENT.items():
        add(v, f"--arg-{k}")
    for k, v in SCHEMATIC.items():
        add(v["fill"], f"--{k.replace('_', '-')}-fill")
        add(v["stroke"], f"--{k.replace('_', '-')}-stroke")
    return out


#: Below this OKLab chroma a colour is a neutral, and near-miss matching is skipped.
NEUTRAL_CHROMA = 0.02

_HTML_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")


def scan_schematic_literals(path, near_miss_de=3.0):
    """Literal hex colours in an HTML schematic that the registry already names.

    Returns [(hex, kind, token)] where kind is:
      "exact"     the hex IS a registered colour -- should be var(token)
      "near"      within `near_miss_de` of one but not equal: it reads as the same
                  colour and isn't, so a deck drifts into near-identical blues.
    """
    tokens = all_tokens()
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    rows, seen = [], set()
    for m in _HTML_HEX_RE.finditer(text):
        h = m.group(0).lower()
        if h in seen:
            continue
        seen.add(h)
        if h in tokens:
            # A hex can carry several names on different axes; report them all.
            rows.append((h, "exact", "/".join(tokens[h])))
            continue
        # Near-miss applies only to chromatic colours: neutrals sit close together
        # in OKLab, so a white page would "near-miss" the chart surface. Two nearly
        # identical dark oranges are real drift; #ffffff vs #fcfcfb is a choice.
        if oklch(h)[1] < NEUTRAL_CHROMA:
            continue
        best, best_de = None, near_miss_de
        for reg, names in tokens.items():
            if oklch(reg)[1] < NEUTRAL_CHROMA:
                continue
            de = delta_e(h, reg)
            if de < best_de:
                best, best_de = "/".join(names), de
        if best:
            rows.append((h, "near", best))
    return rows


def _files(dirs, ext):
    if not dirs:
        raise TypeError("pass at least one directory to scan")
    for d in dirs:
        if not os.path.isdir(d):
            raise FileNotFoundError(f"not a directory: {d}")
        for fn in sorted(os.listdir(d)):
            if fn.endswith(ext):
                yield os.path.join(d, fn)


def schematic_drift_report(*dirs):
    """[(path, hex, kind, token)] for hex literals in the .html files in `dirs` that are,
    or nearly are, registry colours (see `scan_schematic_literals`)."""
    return [(path, h, kind, tok)
            for path in _files(dirs, ".html")
            for h, kind, tok in scan_schematic_literals(path)]


def drift_report(*dirs):
    """[(path, entity, found_hex, registry_hex)] for every {entity: hex} in the .py files in
    `dirs` that disagrees with ENTITY.

    Sees only what `scan_entity_mappings` can resolve statically; colours reached through
    function calls or imports are invisible.
    """
    rows = []
    for path in _files(dirs, ".py"):
        for name, got in scan_entity_mappings(path).items():
            want = ENTITY.get(name, "").lower()
            if want and got != want:
                rows.append((path, name, got, want))
    return rows


def _print_drift(dirs):
    rows = drift_report(*dirs)
    print(f"=== {len(rows)} entity colour(s) that disagree with the registry ===")
    for path, name, got, want in rows:
        print(f"  {path}  {name}: {got} (registry {want}) -> use entity({name!r})")
    sch = schematic_drift_report(*dirs)
    exact = [r for r in sch if r[2] == "exact"]
    near = [r for r in sch if r[2] == "near"]
    print(f"\n=== HTML: {len(exact)} literal(s) that are registry colours, "
          f"{len(near)} near-miss(es) ===")
    for path, h, _kind, tok in near:
        print(f"  NEAR  {path}  {h} ~ {tok}")
    for path, h, _kind, tok in exact:
        print(f"  exact {path}  {h} -> use var({tok})")
    return len(rows) + len(near)


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["drift"]:
        if len(sys.argv) < 3:
            sys.exit("usage: python -m figlib.palette drift DIR [DIR ...]")
        sys.exit(1 if _print_drift(sys.argv[2:]) else 0)
    ok, lines = validate_reference()
    for l in lines:
        print(l)
    print(f"\nvalidator trusted: {ok}")

    print("\n=== registry, by co-appearing group ===")
    for label, rep in validate_registry().items():
        print(f"\n{label}  ({', '.join(rep['entities'])})")
        print(f"  worst CVD {rep['worst_cvd']:.1f}   "
              f"worst normal-vision {rep['worst_normal']:.1f}   ok={rep['ok']}")
        for f in rep["fails"]:
            print(f"    FAIL {f}")
        for w in rep["warns"]:
            print(f"    WARN {w}")

    sch = [v["fill"] for v in list(SCHEMATIC.values())[:5]]
    r = validate(sch, pairs="all")
    print("\nschematic chain slots (Okabe-Ito, separate medium)")
    print(f"  worst CVD {r['worst_cvd']:.1f}   worst normal-vision "
          f"{r['worst_normal']:.1f}   ok={r['ok']}")
    for w in r["warns"]:
        print(f"    WARN {w}")

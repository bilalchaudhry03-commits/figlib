"""One source of truth for figure colour, and the CVD validator that checks it.

    from figlib import palette as pal
    ax.plot(..., color=pal.entity("GNN"))      # one entity, one colour, in every figure
    ax.tick_params(colors=pal.ROLE["ink_2"])
    pal.validate(["#0072B2", "#D55E00"])       # contrast + colour-blindness checks
    print(pal.as_css_vars())                   # the same tokens for HTML+SVG figures

`drift_report()` finds plotting scripts that hardcode a different colour for a registered
entity; the tests pin the known ones so a new divergence fails.
"""

# stdlib only, on purpose: Manim scene files and lighter envs import this.
import ast
import math
import os
import re

# ---------------------------------------------------------------------------
# The categorical ramp. These are the dataviz skill's documented reference slots
# in its documented ORDER -- the order is itself the CVD-safety mechanism and
# must not be resorted. Adjacent-pair worst CVD dE 9.1 / normal-vision 19.6 in
# light mode; the FIRST THREE also clear all-pairs (9.2 / 24.0), which is why
# only three are spent on model families below.
# ---------------------------------------------------------------------------
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

# Text / structure tokens. Collapses the 51 distinct greys found in the survey
# to the five roles they were actually serving.
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

# ---------------------------------------------------------------------------
# ENTITY -- semantic name to colour. Every mapping here is EVIDENCED in the repo,
# not invented; the provenance comment says which figure established it.
#
# The rule that matters: one entity, one colour, across every figure in a deck.
# A labmate who learned "blue = GNN" on slide 6 must not re-learn it on slide 11.
# ---------------------------------------------------------------------------
ENTITY = {
    # -- model families. Three conventions exist in the repo (see the module
    # docstring); GNN=blue / RF=orange is adopted here because it is what the
    # NEWEST figures use (08-03, 08-04) and because it puts both families on the
    # first two validated SERIES slots. The four 07-28 figures use two different
    # older conventions and are recorded in KNOWN_DIVERGENCES below -- adopting
    # the majority-by-filecount instead would have meant migrating the newest
    # work backwards onto a palette that was never validated as a set.
    "GNN":            SERIES[0],   # 20260803_confidence_stratified_figures.py
    "RF":             SERIES[1],   # ditto
    "blend":          SERIES[2],   # ditto

    # -- what a model is being measured against.
    #
    # ink_2, NOT ink_3, and the difference is load-bearing. Free baselines are
    # drawn as MARKS beside model marks, so they are a series and must clear the
    # separation floors. `validate_registry()` caught that ink_3 (#8a8985) does
    # NOT: against `blend` it lands at CVD dE 4.8 (floor 6.0) and normal-vision
    # 14.4 (floor 15.0, a hard gate that secondary encoding does not excuse).
    # ink_2 clears both with margin (18.3 / 21.8) and is still a neutral, so it
    # keeps the de-emphasis reading.
    #
    # RESOLVED 2026-08-05 on migration, and the note that stood here was WRONG.
    # It claimed both ink_3 users were "SAFE AS DRAWN because neither figure
    # plots `blend` alongside the baselines". Checked rather than trusted:
    # 20260803_confidence_stratified_figures.py draws both on one axis and in
    # ONE LEGEND (its fig2), and 20260804_nuclear_negative_gate_forest.py does
    # the same. So the collision was live in two published figures, measured at
    # deuteranopia dE 4.77 (floor 6.0) and normal-vision dE 14.41 (floor 15.0).
    # Both now use this entity and clear at 23.5 / 27.2.
    #
    # Still on ink_3, and CORRECTLY so: the 20260804_free_baselines_* and
    # abstention-gate figures draw `pose` vs baselines and never draw `blend`,
    # so the pair that collides is absent. Verified per-file, not assumed --
    # that is the mistake this comment is replacing.
    "baseline_free":  ROLE["ink_2"],
    "pose":           SERIES[0],   # 20260804_free_baselines_vs_proteome_figures
                                   # NOTE: same slot as GNN. Safe only because
                                   # no figure has drawn both; if one ever does,
                                   # move pose to SERIES[3] rather than letting
                                   # them collide.

    # -- gene tiers on cargo-vs-background figures (20260803_cargo_vs_proteome).
    "cargo":          "#08519C",   # confirmed / co-crystal-proven cargo
    "background":     "#BDBDBD",   # the proteome background
    "receptor_other": "#D55E00",   # a non-KPNA2 receptor (RCC1's KPNA4 case)

    # -- transport modes (admin/generals prop Fig 1, 2026-09-23). Passive is the
    # reference every active curve is read against, so it takes ink and sits in
    # CONTEXT (band/chroma exempt, separation still checked). Import/export take
    # violet/red deliberately: blue/orange are GNN/RF, and the prop's Fig 4 draws
    # the RF export classifier -- orange there must not also mean "export flux".
    "passive":        ROLE["ink"],
    "import":         SERIES[6],   # violet
    "export":         SERIES[7],   # red
}

# ---------------------------------------------------------------------------
# SCHEMATIC -- for HTML+SVG conceptual diagrams, NOT charts.
#
# Deliberately a different source from SERIES: the house `scientific-figure-
# design` skill prescribes Okabe-Ito for schematics, and the existing figures in
# admin/presentations/group_meetings/ already use it. These are generic entity
# SLOTS (the existing cofold_schematic.html uses chain_a/chain_b for
# "single protein" vs "complex"), not fixed proteins -- assign per figure and
# keep the assignment constant across a deck.
#
# Charts and schematics are separate figures and never share an axis, so the two
# sources coexisting is fine. Do not mix them WITHIN one figure.
# ---------------------------------------------------------------------------
SCHEMATIC = {
    "chain_a":   {"fill": "#009E73", "stroke": "#00543D"},  # cofold_schematic.html
    "chain_b":   {"fill": "#CC79A7", "stroke": "#7A3F60"},  # ditto
    "chain_c":   {"fill": "#E69F00", "stroke": "#8A5E00"},
    "chain_d":   {"fill": "#0072B2", "stroke": "#00436A"},
    "chain_e":   {"fill": "#D55E00", "stroke": "#7E3800"},
    "ink":       {"fill": "#1C2530", "stroke": "#1C2530"},  # deck's --ink
    "muted":     {"fill": "#5B6672", "stroke": "#5B6672"},  # deck's --muted
    "hairline":  {"fill": "#D3D9E0", "stroke": "#D3D9E0"},  # deck's --hairline
}

# ---------------------------------------------------------------------------
# ARGUMENT -- what a thing MEANS IN THE ARGUMENT the figure is making, as
# opposed to which protein or model it is.
#
# This is a genuinely different axis from ENTITY and must not be merged into it.
# ENTITY answers "which model family is this line?" (GNN is blue in every
# figure). ARGUMENT answers "is this the thing that was broken, or the thing
# that fixed it?" -- a role a DIFFERENT entity occupies on each slide. The
# 20260804_three_broken_rulers and 20260805_groove_coverage_disorder_detector
# schematics both use it, and in each one the vermilion element is a different
# object.
#
# Added 2026-08-05. Before this, both axes existed in the deck but only ENTITY
# was registered, so the argument colours were retyped as literals in every
# schematic -- which is the same drift this module was built to stop, just in
# the half nobody had written down. It is NOT in GROUPS: GROUPS members are
# validated as ENTITY names, and these are not entities. Separation is checked
# by its own test instead.
#
# Values are the Okabe-Ito slots the deck already established, so adopting this
# renames existing usage rather than changing any published figure.
#
# THE COLOURS COLLIDE WITH ENTITY, AND THAT IS SAFE ONLY BECAUSE OF THE MEDIUM
# RULE BELOW. Measured 2026-08-05, after the first version of this axis shipped
# with a test that only checked the roles against EACH OTHER:
#
#     entity("receptor_other") #D55E00  vs  argument("broken") #D55E00   IDENTICAL
#     entity("GNN")            #2a78d6  vs  argument("fixed")  #0072B2   dE 6.1
#                                                          (normal-vision floor 15)
#
# So the within-axis check was the wrong check: this module's premise is
# CROSS-DECK consistency, not per-figure separation. What makes the overlap
# harmless is the same argument SCHEMATIC already makes for itself --
#
#     ARGUMENT is for HTML+SVG schematics. ENTITY is for matplotlib charts.
#     A figure uses one axis or the other, NEVER both.
#
# -- and the fix chosen (user decision, 2026-08-05) was to ENFORCE that rule
# rather than recolour two slides on the morning they were presented. See
# `test_argument_axis_is_schematic_only` and `test_no_figure_mixes_the_two_axes`.
# If a figure ever genuinely needs both, recolour ARGUMENT onto hues ENTITY does
# not use; do not quietly let them meet.
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# SHARED_SLOTS -- entity pairs deliberately drawn in the SAME colour.
#
# `pose` and `GNN` are both SERIES[0]. The ENTITY comment has always said this
# is "safe only because no figure has drawn both" -- but that was a comment, and
# a comment does not fail. As of 2026-08-05 six plotting scripts use `pose`, four
# use `GNN`, and none use both; `test_no_file_draws_a_shared_slot_pair` is what
# keeps that true. When it fails, move the second member to a free SERIES slot
# rather than deleting the test.
# ---------------------------------------------------------------------------
SHARED_SLOTS = (("GNN", "pose"),)

# ---------------------------------------------------------------------------
# SEQUENTIAL -- continuous ramps for density (hexbin, 2-D histograms).
#
# A fifth axis, added 2026-08-05 because `cmap="Blues"` was hardcoded in four
# plotting scripts and nothing said what to reach for or when. Names are
# matplotlib colormap strings and are NOT validated here on purpose: this module
# is stdlib-only so it stays importable from envs/geometric, so the "is this a
# real colormap" check lives in tests/test_lib_palette.py instead.
#
# THE RULE THAT MATTERS: a density field and the categorical marks drawn on top
# of it must not share a hue. `density` is Blues, and SERIES[0] (#2a78d6, GNN
# and pose) is blue -- a GNN mark on a Blues hexbin disappears into it. Use
# `density_warm` on any axis that also carries a blue categorical mark.
# ---------------------------------------------------------------------------
SEQUENTIAL = {
    "density":       "Blues",    # the 4 existing users; safe with no blue marks
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


# Divergences known and accepted as of 2026-08-04. Nothing has been migrated, so
# these are a worklist, not bugs to fix silently. figlib/tests/test_palette.py pins
# this set: a NEW divergence fails the suite, an existing one does not.
KNOWN_DIVERGENCES = {
    # GNN -> orange, RF -> blue. The odd one out even among the 07-28 figures.
    ("20260728_negative_tier_rebuild_figures.py", "RF"): "#0072b2",
    ("20260728_negative_tier_rebuild_figures.py", "GNN"): "#e69f00",
    # GNN -> green (RF -> blue implicitly, via `... else BLUE`, so RF is not
    # named in the source and is not recorded here).
    ("20260728_rf_v2_rank_evidence_figures.py", "GNN"): "#009e73",
    ("20260728_size_controlled_yardstick_figures.py", "GNN"): "#009e73",
    ("20260728_yardstick_rebuild_figures.py", "GNN"): "#009e73",
}


# ---------------------------------------------------------------------------
# Entity CLASS, and the groups that actually co-appear in one figure.
#
# The categorical checks (lightness band, chroma floor) apply to marks doing
# IDENTITY work. They do not apply to a context fill that is deliberately
# neutral and light -- `background` is a violin fill behind the data, and
# failing it for "chroma 0" would be the validator answering a question nobody
# asked. Separation and contrast still apply to everything.
#
# Getting this wrong in either direction is a real failure mode: exempt too much
# and the checks stop meaning anything; exempt too little and you chase FAILs
# that are correct-by-design (which is what a hand-written comment in
# 20260804_free_baselines_vs_proteome_figures.py was doing before this module
# existed).
# ---------------------------------------------------------------------------
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
    """Validate every co-appearing GROUP with the checks appropriate to each
    entity's class. Returns {group_name: report}.

    This, not `validate()`, is what the test suite asserts on: `validate()` is
    the faithful port of the JS and treats every colour as categorical, which is
    correct for a raw palette and wrong for a registry that mixes series marks
    with context fills.
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


# ---------------------------------------------------------------------------
# The validator. Ported from the dataviz skill's validate_palette.js: same
# Machado-Oliveira-Fernandes (2009) severity-1.0 matrices, same OKLab
# coefficients, same thresholds. The CVD thresholds are calibrated to THIS
# simulation model, so the model is part of the standard -- swapping it would
# require recalibrating the numbers.
#
# Trust is established by reproduction, not by inspection: validate_reference()
# below must return the four values the skill's own palette.md documents before
# any result from this code is believed.
# ---------------------------------------------------------------------------
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
    """Self-test: reproduce palette.md's documented values.

    Returns (ok, report_lines). Called by figlib/tests/test_palette.py, and worth
    calling by hand after any edit to the conversion math.
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
    """Emit the registry as CSS custom properties for the HTML+SVG schematics.

    The group_meetings figures currently carry their own `--chain-a-fill:` etc.
    Generating them from here is what keeps a schematic and a chart of the same
    entity on one colour. Paste the output into the figure's <style> block.
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
    # Prefixed, because `--context` unprefixed would read as a chrome token next
    # to --ink/--grid and these are argument roles, not chrome.
    for k, v in ARGUMENT.items():
        out.append(f"{indent}--arg-{k}: {v};")
    out.append("}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Drift detection. Nothing is migrated, so this is how the unmigrated state
# stays visible instead of quietly getting worse.
# ---------------------------------------------------------------------------
_ALIASES = {"gnn": "GNN", "rf": "RF", "blend": "blend",
            "cargo": "cargo", "pose": "pose"}


def _module_hex_constants(tree):
    """Module-level NAME = "#hex", including tuple unpacking.

    Needed because the real scripts overwhelmingly write
    `BLUE, GREEN, ORANGE = "#0072B2", "#009E73", "#E69F00"` and then refer to
    the NAME. Without resolving these, a static scan sees no colours at all and
    reports a clean repo, which is worse than not checking.
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
    """Every entity->hex a Python file assigns, via AST.

    Handles the two forms that actually occur in this repo:

      1. a dict literal, `FAM_COLOR = {"GNN": "#2a78d6", ...}` (07-28
         negative-tier figure, 08-03/08-04 figures);
      2. a conditional, `return GREEN if m.startswith("GNN") else BLUE`
         (three 07-28 figures) -- the dominant form, and invisible to a naive
         dict scan, which is how the first version of this function reported
         "0 divergences" on a repo with three conflicting conventions.

    Only the entity NAMED in the condition is recorded; the else-branch entity is
    implicit ("not GNN") and is not guessed.

    AST rather than regex throughout, so the mapping is caught regardless of what
    the variable is called.
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


def _repo_root():
    """The repository root.

    This module lived at `karyoPPI/lib/palette.py` until 2026-08-17, where the
    same two-`dirname` walk landed on the karyoPPI PROJECT dir, and the paths
    below were written relative to that (one with a `..` to climb back out).
    From `figlib/` the identical walk lands on the root, so both had to be
    respelled -- silently, they resolved to directories that do not exist and
    `drift_report()` raised FileNotFoundError. Named for what it returns now, so
    the next move breaks loudly at the name rather than quietly at the path.
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


#: Scanned by `drift_report()`. karyoPPI's plotting dir is the historical target
#: -- the 73 scripts and 127 colours in this module's own docstring -- and is
#: kept as the default so the 2026-08-17 move stays behaviour-neutral.
#: `passive_diffusion/scripts/` is NOT scanned by default: those figures reuse
#: SERIES slots by VALUE with a comment saying so, which this scanner would read
#: as drift. Widening the default is a real question, not an oversight -- pass
#: `dirs=` to check them deliberately.
def default_plotting_dir():
    return os.path.join(_repo_root(), "karyoPPI", "scripts", "plotting")


#: Where the HTML+SVG schematics live. Under admin/, which is LOCAL-ONLY and
#: gitignored (see the root CLAUDE.md), so every consumer must tolerate these
#: being absent rather than assuming a checkout has them.
SCHEMATIC_DIRS = (
    os.path.join(_repo_root(), "admin", "presentations", "group_meetings", "html"),
    os.path.join(_repo_root(), "admin", "presentations", "martin_meetings"),
)


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


#: Below this OKLab chroma a colour is a neutral and the near-miss check is
#: meaningless (see scan_schematic_literals).
NEUTRAL_CHROMA = 0.02

_HTML_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")


def scan_schematic_literals(path, near_miss_de=3.0):
    """Literal hex colours in an HTML schematic that the registry already names.

    The chart-side `scan_entity_mappings` reads Python. The schematics are HTML
    and were invisible to drift detection entirely until 2026-08-05, which meant
    schematic drift could not get worse OR better in any measurable way.

    Returns [(hex, kind, token)] where kind is:
      "exact"     the hex IS a registered colour -- should be var(token)
      "near"      within `near_miss_de` of one but not equal. Worse than exact:
                  it reads as the same colour and is not, so a deck slowly
                  acquires two almost-identical blues that nobody can see are
                  different.
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
            # A hex can carry several names (#5B6672 is both argument("context")
            # and SCHEMATIC["muted"]). Report all of them -- picking the first
            # would imply the registry has one right answer when it has two
            # equally valid ones on different axes.
            rows.append((h, "exact", "/".join(tokens[h])))
            continue
        # Near-miss only applies to CHROMATIC colours. Near-neutrals sit close
        # together in OKLab by construction, so at any useful dE threshold a
        # white page background reads as a "near-miss" against the chart
        # surface -- 86 of the first 198 hits on this deck were exactly that.
        # Two almost-identical dark oranges (#8f6300 vs #8A5E00) are real drift;
        # #ffffff vs #fcfcfb is a deliberate choice about a different surface.
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


def schematic_drift_report(dirs=None):
    """[(file, hex, kind, token)] over every schematic that exists on disk."""
    rows = []
    for d in (dirs if dirs is not None else SCHEMATIC_DIRS):
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".html"):
                continue
            for h, kind, tok in scan_schematic_literals(os.path.join(d, fn)):
                rows.append((fn, h, kind, tok))
    return rows


def drift_report(plotting_dir=None):
    """[(script, entity, found_hex, registry_hex)] for every disagreement.

    Only reports mappings written as a literal {entity: "#hex"} dict. A script
    using module-level constants (`BLUE = "#0072B2"; FAM = {"RF": BLUE}`) is
    invisible here -- the indirection defeats a static read, and resolving it
    would mean executing the script. Those are caught by the KNOWN_DIVERGENCES
    list instead, which is why that list is maintained by hand.
    """
    plotting_dir = plotting_dir or default_plotting_dir()
    rows = []
    for fn in sorted(os.listdir(plotting_dir)):
        if not fn.endswith(".py"):
            continue
        for name, got in scan_entity_mappings(os.path.join(plotting_dir, fn)).items():
            want = ENTITY.get(name, "").lower()
            if want and got != want:
                rows.append((fn, name, got, want))
    return rows


if __name__ == "__main__":
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
    print(f"\nschematic chain slots (Okabe-Ito, separate medium)")
    print(f"  worst CVD {r['worst_cvd']:.1f}   worst normal-vision "
          f"{r['worst_normal']:.1f}   ok={r['ok']}")
    for w in r["warns"]:
        print(f"    WARN {w}")

    plotting = default_plotting_dir()
    if os.path.isdir(plotting):
        rows = drift_report()
        print(f"\n=== drift: {len(rows)} statically-visible disagreements ===")
        for fn, name, got, want in rows:
            print(f"  {fn}  {name}: {got} (registry {want})")
        known = set(KNOWN_DIVERGENCES)
        seen = {(fn, name) for fn, name, _g, _w in rows}
        print(f"  all recorded in KNOWN_DIVERGENCES: {seen == known}")
        if seen - known:
            print(f"  NEW, not recorded: {sorted(seen - known)}")

    sch = schematic_drift_report()
    if sch:
        exact = [r for r in sch if r[2] == "exact"]
        near = [r for r in sch if r[2] == "near"]
        print(f"\n=== schematic drift: {len(exact)} literals that are registry "
              f"colours, {len(near)} near-misses ===")
        for fn, h, kind, tok in near:
            print(f"  NEAR  {fn}  {h} ~ {tok}")
        for fn, h, kind, tok in exact[:12]:
            print(f"  exact {fn}  {h} -> use var({tok})")
        if len(exact) > 12:
            print(f"  ... and {len(exact) - 12} more exact matches")

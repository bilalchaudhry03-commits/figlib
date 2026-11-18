"""Tests for palette: the registry stays CVD-valid, and `test_no_new_entity_colour_drift`
fails on any entity-colour divergence not already in KNOWN_DIVERGENCES.
"""
import sys
from pathlib import Path

import os
import re

import pytest

KARYOPPI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KARYOPPI.parent))

from figlib import palette as pal  # noqa: E402

PLOTTING = Path(pal.default_plotting_dir())


def test_validator_reproduces_the_documented_reference_values():
    """The port must agree with the dataviz skill's own palette.md before any
    number it produces is believed.

    `node` is unavailable on Argo, so this validator cannot be diffed against
    the JS by running both. Reproducing the four documented values is the
    substitute, and it is the reason this module exists rather than a third
    hand-port to scratch.
    """
    ok, lines = pal.validate_reference()
    assert ok, "validator does not reproduce palette.md:\n" + "\n".join(lines)


def test_every_co_appearing_group_passes():
    """Each set drawn in one figure must be mutually separable.

    Uses `validate_registry`, not `validate`: the raw validator treats every
    colour as categorical, which wrongly fails a context fill for having no
    chroma. This caught a real defect when the module was written -- the free
    baseline on ink_3 sat at CVD dE 4.8 against `blend`, below the 6.0 floor.
    """
    reports = pal.validate_registry()
    assert reports, "no groups defined"
    bad = {k: r["fails"] for k, r in reports.items() if r["fails"]}
    assert not bad, f"groups with hard FAILs: {bad}"


def test_every_entity_has_exactly_one_class():
    """A new entity added without a class would silently get categorical checks
    (or skip them), depending on which set it fell into. Partition, not overlap.
    """
    both = pal.CATEGORICAL & pal.CONTEXT
    assert not both, f"entities in both classes: {sorted(both)}"
    unclassed = set(pal.ENTITY) - pal.CATEGORICAL - pal.CONTEXT
    assert not unclassed, (
        f"entities with no class: {sorted(unclassed)} -- add each to "
        "CATEGORICAL (a mark doing identity work) or CONTEXT (a deliberately "
        "neutral fill), or validate_registry() checks it wrongly")


def test_every_group_member_is_a_registered_entity():
    for label, (names, _pairs) in pal.GROUPS.items():
        for n in names:
            assert n in pal.ENTITY, f"group {label!r} references unknown {n!r}"


def test_no_new_entity_colour_drift():
    """THE test. Any {entity: hex} literal disagreeing with the registry, other
    than the eight already recorded, fails.

    Migrating a script should REMOVE its entry from KNOWN_DIVERGENCES; adding a
    new disagreement should fail here rather than reach a deck.
    """
    if not PLOTTING.is_dir():
        pytest.skip("scripts/plotting not present")
    found = {(fn, name): got for fn, name, got, _want in pal.drift_report(PLOTTING)}
    known = {k: v.lower() for k, v in pal.KNOWN_DIVERGENCES.items()}
    new = {k: v for k, v in found.items() if k not in known}
    assert not new, (
        "new entity-colour divergence(s) -- use figlib.palette.entity() instead of "
        f"a hex literal: {new}")


def test_known_divergences_are_not_stale():
    """If a recorded divergence has been fixed, the list must shrink with it.

    Without this, KNOWN_DIVERGENCES silently rots into a list of files that were
    corrected years ago and the drift test quietly stops covering anything.
    Statically-invisible entries (colour via a module constant) are exempt --
    `drift_report` cannot see those by design.
    """
    if not PLOTTING.is_dir():
        pytest.skip("scripts/plotting not present")
    visible = {(fn, name) for fn, name, _got, _want in pal.drift_report(PLOTTING)}
    for (fn, name), _hex in pal.KNOWN_DIVERGENCES.items():
        path = PLOTTING / fn
        if not path.exists():
            pytest.fail(f"KNOWN_DIVERGENCES names a missing file: {fn}")
        mapped = pal.scan_entity_mappings(path)
        if name in mapped and (fn, name) not in visible:
            pytest.fail(f"{fn}:{name} now agrees with the registry -- remove it "
                        "from KNOWN_DIVERGENCES")


def test_entity_lookup_raises_on_a_typo():
    """`ENTITY.get("gnn")` returning None would draw a black line and look like
    a styling choice. The accessor must fail instead."""
    assert pal.entity("GNN") == pal.SERIES[0]
    with pytest.raises(KeyError):
        pal.entity("gnn")
    with pytest.raises(KeyError):
        pal.entity("RandomForest")


def test_argument_roles_are_mutually_separable():
    """The three meaning-carrying argument colours can appear in one schematic
    (broken vs fixed vs holdout), so they must clear the same separation floors
    the ENTITY groups do. `context` is excluded on purpose: it is a neutral
    doing de-emphasis, exactly like CONTEXT on the entity side."""
    r = pal.validate([pal.ARGUMENT[k] for k in pal.ARGUMENT_CATEGORICAL],
                     pairs="all")
    assert r["ok"], r["fails"]


def test_argument_is_a_separate_axis_from_entity():
    """Merging the two would be the actual mistake this axis exists to prevent:
    ENTITY is fixed to an object across a deck, ARGUMENT is a role a different
    object occupies on each slide."""
    assert not set(pal.ARGUMENT) & set(pal.ENTITY)
    with pytest.raises(KeyError):
        pal.argument("GNN")
    with pytest.raises(KeyError):
        pal.entity("broken")


def test_css_vars_carry_the_argument_axis_under_a_prefix():
    """Unprefixed `--context` would read as a chrome token beside --ink/--grid."""
    css = pal.as_css_vars()
    for k, v in pal.ARGUMENT.items():
        assert f"--arg-{k}: {v};" in css


def _plotting_sources():
    d = pal.default_plotting_dir()
    if not os.path.isdir(d):
        pytest.skip("no scripts/plotting on this checkout")
    return {fn: open(os.path.join(d, fn), encoding="utf-8").read()
            for fn in sorted(os.listdir(d)) if fn.endswith(".py")}


def _schematics():
    out = {}
    for d in pal.SCHEMATIC_DIRS:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".html"):
                out[fn] = open(os.path.join(d, fn), encoding="utf-8").read()
    if not out:
        pytest.skip("schematics live under admin/, which is local-only")
    return out


def test_argument_axis_is_schematic_only():
    """ARGUMENT's colours COLLIDE with ENTITY's on purpose -- broken is exactly
    receptor_other, fixed is 6.1 dE from GNN. That is safe only while the two
    axes never meet, so the medium rule is enforced rather than commented: a
    matplotlib chart uses ENTITY and must not reach for ARGUMENT."""
    # Match the palette API precisely. A bare "argument(" substring hits
    # argparse's add_argument in 38 of these files -- a check that noisy would
    # have been deleted within a week.
    use = re.compile(r"\b(?:pal|_pal|palette)\.(?:argument\s*\(|ARGUMENT\b)"
                     r"|from\s+lib\.palette\s+import\s+[^\n]*\bargument\b")
    offenders = [fn for fn, src in _plotting_sources().items() if use.search(src)]
    assert not offenders, (
        f"{offenders} use the ARGUMENT axis in a chart. ARGUMENT is for HTML+SVG "
        "schematics; charts use entity(). If a chart genuinely needs the "
        "broken/fixed distinction, recolour ARGUMENT off ENTITY's hues first.")


def test_no_schematic_mixes_the_two_axes():
    """The other half of the same rule. Vacuous today because the schematics
    still use literal hex, and deliberately kept so it bites the first figure
    that adopts the tokens and reaches across."""
    ent = tuple(f"var(--{k.lower().replace('_', '-')})" for k in pal.ENTITY)
    for fn, src in _schematics().items():
        if "var(--arg-" in src:
            assert not any(e in src for e in ent), (
                f"{fn} uses both ARGUMENT and ENTITY tokens; pick one axis")


def test_no_file_draws_a_shared_slot_pair():
    """`pose` and `GNN` are both SERIES[0]. The registry has always SAID this is
    safe only while no figure draws both; this is what makes that true."""
    for a, b in pal.SHARED_SLOTS:
        assert pal.entity(a) == pal.entity(b), f"{a}/{b} no longer share a slot"
        both = [fn for fn, src in _plotting_sources().items()
                if f'entity("{a}")' in src and f'entity("{b}")' in src]
        assert not both, (
            f"{both} draw both {a!r} and {b!r}, which are the same colour "
            f"({pal.entity(a)}). Move one to a free SERIES slot.")


def test_sequential_names_are_real_colormaps():
    """Not checked inside palette.py: it is stdlib-only so it stays importable
    from envs/geometric. The matplotlib-dependent half of the check lives here."""
    import matplotlib
    for name, cmap in pal.SEQUENTIAL.items():
        assert matplotlib.colormaps[cmap] is not None, f"{name} -> {cmap!r}"


def test_density_ramp_collides_with_the_blue_marks_and_the_warm_one_does_not():
    """Pins the reason `density_warm` exists. SERIES[0] is blue and `density` is
    a blue ramp, so a GNN mark on a Blues hexbin sinks into it -- which is what
    four existing figures do. `density_warm` must actually be an escape."""
    import matplotlib
    def mid(cmap):
        r, g, b, _ = matplotlib.colormaps[cmap](0.65)
        return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
    blue = pal.SERIES[0]
    assert pal.delta_e(mid(pal.SEQUENTIAL["density"]), blue) < 15.0
    assert pal.delta_e(mid(pal.SEQUENTIAL["density_warm"]), blue) > 25.0


def test_drift_report_defaults_to_this_repo():
    if not os.path.isdir(pal.default_plotting_dir()):
        pytest.skip("not inside the wuhrlab repo (karyoPPI/scripts/plotting absent)")
    rows = pal.drift_report()
    assert {(fn, name) for fn, name, _g, _w in rows} == set(pal.KNOWN_DIVERGENCES)


def test_schematic_near_misses_are_chromatic_only():
    """Near-neutrals sit close together in OKLab, so without the chroma floor a
    white page background reads as drift against the chart surface -- 86 of the
    first 198 hits were exactly that kind of noise."""
    _schematics()
    for fn, h, kind, tok in pal.schematic_drift_report():
        if kind == "near":
            assert pal.oklch(h)[1] >= pal.NEUTRAL_CHROMA, f"{fn} {h} is a neutral"


def test_all_registered_values_are_six_digit_hex():
    vals = (list(pal.ENTITY.values()) + list(pal.ROLE.values())
            + list(pal.ROLE_DARK.values()) + pal.SERIES + pal.SERIES_DARK
            + list(pal.ARGUMENT.values())
            + [v for d in pal.SCHEMATIC.values() for v in d.values()])
    for v in vals:
        assert pal._HEX_RE.match(v), f"not a 6-digit hex: {v!r}"


def test_series_order_is_the_documented_one():
    """The order IS the CVD-safety mechanism -- re-sorting it silently breaks
    the adjacent-pair guarantee the reference values were measured under."""
    assert pal.SERIES[:3] == ["#2a78d6", "#eb6834", "#1baf7a"]
    assert len(pal.SERIES) == len(pal.SERIES_DARK) == 8


def test_css_vars_emit_parseable_declarations():
    css = pal.as_css_vars(["GNN", "RF"])
    assert css.startswith(":root {") and css.rstrip().endswith("}")
    assert "--gnn: #2a78d6;" in css
    assert "--chain-a-fill: #009E73;" in css
    assert "--ink-2: #52514e;" in css
    for line in css.splitlines()[1:-1]:
        decl = line.strip().rstrip(";")
        assert decl.startswith("--") and ": " in decl, f"bad declaration: {line!r}"


def test_contrast_and_delta_e_against_known_values():
    """Pin the two conversion paths against values computable by hand, so a
    refactor of the OKLab math fails here rather than in a figure."""
    assert pal.contrast("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert pal.contrast("#ffffff", "#ffffff") == pytest.approx(1.0, abs=1e-9)
    assert pal.delta_e("#2a78d6", "#2a78d6") == pytest.approx(0.0, abs=1e-9)
    # Symmetric in both directions, simulated and not.
    for kind in (None, "protan", "deutan", "tritan"):
        a = pal.delta_e("#2a78d6", "#eb6834", kind)
        b = pal.delta_e("#eb6834", "#2a78d6", kind)
        assert a == pytest.approx(b, abs=1e-9)


def test_role_greys_are_ordered_light_to_dark():
    """ink darker than ink_2 darker than ink_3 darker than grid darker than
    surface -- if that ordering ever inverts, every figure's hierarchy does."""
    ls = [pal.oklch(pal.ROLE[k])[0]
          for k in ("ink", "ink_2", "ink_3", "grid", "surface")]
    assert ls == sorted(ls), f"ROLE lightness is not monotonic: {ls}"

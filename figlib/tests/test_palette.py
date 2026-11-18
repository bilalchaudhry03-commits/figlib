"""Tests for palette: the registry stays CVD-valid, and `test_no_new_entity_colour_drift`
fails on any entity-colour divergence not already in KNOWN_DIVERGENCES.
"""
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]   # holds the figlib package; lets pytest run uninstalled
sys.path.insert(0, str(ROOT))

from figlib import palette as pal  # noqa: E402

PLOTTING = Path(pal.default_plotting_dir())


def test_validator_reproduces_the_documented_reference_values():
    """The Python port reproduces the values palette.md documents for the JS
    validator, which is how the port is trusted without running the JS."""
    ok, lines = pal.validate_reference()
    assert ok, "validator does not reproduce palette.md:\n" + "\n".join(lines)


def test_every_co_appearing_group_passes():
    """Each set drawn in one figure is mutually separable (with CONTEXT fills
    exempt from the band/chroma checks)."""
    reports = pal.validate_registry()
    assert reports, "no groups defined"
    bad = {k: r["fails"] for k, r in reports.items() if r["fails"]}
    assert not bad, f"groups with hard FAILs: {bad}"


def test_every_entity_has_exactly_one_class():
    """CATEGORICAL and CONTEXT partition ENTITY, so validate_registry() checks
    every entity the right way."""
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
    """Any {entity: hex} disagreeing with the registry and not in
    KNOWN_DIVERGENCES fails. Migrating a script should remove its entry."""
    if not PLOTTING.is_dir():
        pytest.skip("scripts/plotting not present")
    found = {(fn, name): got for fn, name, got, _want in pal.drift_report(PLOTTING)}
    known = {k: v.lower() for k, v in pal.KNOWN_DIVERGENCES.items()}
    new = {k: v for k, v in found.items() if k not in known}
    assert not new, (
        "new entity-colour divergence(s) -- use figlib.palette.entity() instead of "
        f"a hex literal: {new}")


def test_known_divergences_are_not_stale():
    """A recorded divergence that has been fixed must be removed from the list.
    Entries `drift_report` can't see statically are exempt."""
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
    """entity() raises instead of returning None (which would draw black)."""
    assert pal.entity("GNN") == pal.SERIES[0]
    with pytest.raises(KeyError):
        pal.entity("gnn")
    with pytest.raises(KeyError):
        pal.entity("RandomForest")


def test_argument_roles_are_mutually_separable():
    """broken / fixed / holdout can share a schematic, so they clear the
    separation floors. `context` is a neutral and excluded."""
    r = pal.validate([pal.ARGUMENT[k] for k in pal.ARGUMENT_CATEGORICAL],
                     pairs="all")
    assert r["ok"], r["fails"]


def test_argument_is_a_separate_axis_from_entity():
    """ARGUMENT and ENTITY share no names, and each lookup rejects the other's."""
    assert not set(pal.ARGUMENT) & set(pal.ENTITY)
    with pytest.raises(KeyError):
        pal.argument("GNN")
    with pytest.raises(KeyError):
        pal.entity("broken")


def test_css_vars_carry_the_argument_axis_under_a_prefix():
    """ARGUMENT tokens are emitted as --arg-*, not alongside --ink/--grid."""
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
        pytest.skip("no schematic dirs on this checkout")
    return out


def test_argument_axis_is_schematic_only():
    """No matplotlib chart uses the ARGUMENT axis, whose colours collide with
    ENTITY's (see palette.ARGUMENT)."""
    # Match the palette API precisely: a bare "argument(" also hits argparse.
    use = re.compile(r"\b(?:pal|_pal|palette)\.(?:argument\s*\(|ARGUMENT\b)"
                     r"|from\s+(?:fig)?lib\.palette\s+import\s+[^\n]*\bargument\b")
    offenders = [fn for fn, src in _plotting_sources().items() if use.search(src)]
    assert not offenders, (
        f"{offenders} use the ARGUMENT axis in a chart. ARGUMENT is for HTML+SVG "
        "schematics; charts use entity(). If a chart genuinely needs the "
        "broken/fixed distinction, recolour ARGUMENT off ENTITY's hues first.")


def test_no_schematic_mixes_the_two_axes():
    """No schematic uses both ARGUMENT and ENTITY tokens."""
    ent = tuple(f"var(--{k.lower().replace('_', '-')})" for k in pal.ENTITY)
    for fn, src in _schematics().items():
        if "var(--arg-" in src:
            assert not any(e in src for e in ent), (
                f"{fn} uses both ARGUMENT and ENTITY tokens; pick one axis")


def test_no_file_draws_a_shared_slot_pair():
    """No script draws both members of a SHARED_SLOTS pair (same colour)."""
    for a, b in pal.SHARED_SLOTS:
        assert pal.entity(a) == pal.entity(b), f"{a}/{b} no longer share a slot"
        both = [fn for fn, src in _plotting_sources().items()
                if f'entity("{a}")' in src and f'entity("{b}")' in src]
        assert not both, (
            f"{both} draw both {a!r} and {b!r}, which are the same colour "
            f"({pal.entity(a)}). Move one to a free SERIES slot.")


def test_sequential_names_are_real_colormaps():
    """Checked here because palette.py is stdlib-only."""
    import matplotlib
    for name, cmap in pal.SEQUENTIAL.items():
        assert matplotlib.colormaps[cmap] is not None, f"{name} -> {cmap!r}"


def test_density_ramp_collides_with_the_blue_marks_and_the_warm_one_does_not():
    """`density` sits near SERIES[0] blue; `density_warm` is far from it."""
    import matplotlib
    def mid(cmap):
        r, g, b, _ = matplotlib.colormaps[cmap](0.65)
        return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
    blue = pal.SERIES[0]
    assert pal.delta_e(mid(pal.SEQUENTIAL["density"]), blue) < 15.0
    assert pal.delta_e(mid(pal.SEQUENTIAL["density_warm"]), blue) > 25.0


def test_drift_report_defaults_to_this_repo():
    if not os.path.isdir(pal.default_plotting_dir()):
        pytest.skip("default plotting dir only exists in the author's lab checkout")
    rows = pal.drift_report()
    assert {(fn, name) for fn, name, _g, _w in rows} == set(pal.KNOWN_DIVERGENCES)


def test_schematic_near_misses_are_chromatic_only():
    """Near-miss matches are never neutrals (they sit close together in OKLab)."""
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
    """SERIES order is the CVD-safety mechanism; pin it."""
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
    """Contrast and delta_e match hand-computable values and are symmetric."""
    assert pal.contrast("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert pal.contrast("#ffffff", "#ffffff") == pytest.approx(1.0, abs=1e-9)
    assert pal.delta_e("#2a78d6", "#2a78d6") == pytest.approx(0.0, abs=1e-9)
    # Symmetric in both directions, simulated and not.
    for kind in (None, "protan", "deutan", "tritan"):
        a = pal.delta_e("#2a78d6", "#eb6834", kind)
        b = pal.delta_e("#eb6834", "#2a78d6", kind)
        assert a == pytest.approx(b, abs=1e-9)


def test_role_greys_are_ordered_light_to_dark():
    """ink < ink_2 < ink_3 < grid < surface in lightness."""
    ls = [pal.oklch(pal.ROLE[k])[0]
          for k in ("ink", "ink_2", "ink_3", "grid", "surface")]
    assert ls == sorted(ls), f"ROLE lightness is not monotonic: {ls}"

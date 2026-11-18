"""Tests for palette: the registry stays CVD-valid, lookups fail loudly, and the drift
scanners find hardcoded colours that disagree with the registry.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]   # holds the figlib package; lets pytest run uninstalled
sys.path.insert(0, str(ROOT))

from figlib import palette as pal  # noqa: E402


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


def test_shared_slot_pairs_still_share_a_colour():
    """SHARED_SLOTS documents pairs that reuse one colour; keep it true."""
    for a, b in pal.SHARED_SLOTS:
        assert pal.entity(a) == pal.entity(b), f"{a}/{b} no longer share a slot"


# ---------------------------------------------------------------- drift scanners

def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_drift_report_finds_disagreeing_entity_colours(tmp_path):
    """Dict literals, module constants and conditionals are all resolved; agreeing ones are silent."""
    wrong = _write(tmp_path / "wrong.py",
                   'GREEN = "#009e73"\n'
                   'FAM = {"GNN": GREEN, "RF": "%s"}\n'
                   'def c(m):\n    return "#e69f00" if m == "blend" else "#000000"\n' % pal.entity("RF"))
    _write(tmp_path / "right.py", 'FAM = {"GNN": "%s"}\n' % pal.entity("GNN"))
    _write(tmp_path / "notes.txt", 'FAM = {"GNN": "#ffffff"}\n')
    rows = {(path, name): got for path, name, got, _want in pal.drift_report(str(tmp_path))}
    assert rows == {(wrong, "GNN"): "#009e73", (wrong, "blend"): "#e69f00"}


def test_drift_report_needs_real_directories(tmp_path):
    with pytest.raises(TypeError):
        pal.drift_report()
    with pytest.raises(FileNotFoundError):
        pal.drift_report(str(tmp_path / "missing"))


def test_schematic_drift_reports_exact_and_chromatic_near_misses(tmp_path):
    """Exact registry colours and chromatic near-misses are reported; neutral near-misses are not."""
    gnn = pal.entity("GNN")
    r, g, b = (int(gnn[i:i + 2], 16) for i in (1, 3, 5))
    near = "#%02x%02x%02x" % (r, g, min(255, b + 3))
    html = _write(tmp_path / "fig.html",
                  f'<rect fill="{gnn}"/><rect fill="{near}"/><rect fill="#ffffff"/>')
    rows = pal.schematic_drift_report(str(tmp_path))
    kinds = {h: kind for path, h, kind, _tok in rows if path == html}
    assert kinds.get(gnn.lower()) == "exact"
    assert kinds.get(near) == "near"
    assert "#ffffff" not in kinds


def test_drift_cli_exits_nonzero_on_disagreement(tmp_path):
    import subprocess
    _write(tmp_path / "wrong.py", 'FAM = {"GNN": "#009e73"}\n')
    r = subprocess.run([sys.executable, "-m", "figlib.palette", "drift", str(tmp_path)],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 1, r.stderr
    assert "GNN: #009e73" in r.stdout

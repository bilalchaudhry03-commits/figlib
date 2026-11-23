"""figlib.silhouette: loading (pLDDT, experimental, ligands), projection, SVG/JSON, AFDB fetch."""

import io
import json

import numpy as np
import pytest

gemmi = pytest.importorskip("gemmi")
pytest.importorskip("scipy")

from figlib import silhouette as S  # noqa: E402


def _structure(tmp_path, *, resolution=0.0, name="model.cif"):
    """Chain A: a 60-residue rod along x (pLDDT 90) plus 10 floppy residues (pLDDT 30) far off.
    Chain B: a small blob in front of A (+z). Chain L: one magnesium ion, no CA."""
    rng = np.random.default_rng(0)
    st = gemmi.Structure()
    st.resolution = resolution
    model = gemmi.Model("1")

    def chain(cid, pts, b):
        ch = gemmi.Chain(cid)
        for i, (x, y, z) in enumerate(pts):
            res = gemmi.Residue()
            res.name, res.seqid = "ALA", gemmi.SeqId(i + 1, " ")
            at = gemmi.Atom()
            at.name, at.element, at.pos, at.b_iso = "CA", gemmi.Element("C"), gemmi.Position(x, y, z), b[i]
            res.add_atom(at)
            ch.add_residue(res)
        model.add_chain(ch)

    rod = np.c_[np.linspace(-45, 45, 60), rng.normal(0, 4, 60), rng.normal(0, 2, 60)]
    tail = np.c_[np.full(10, 80.0), np.linspace(30, 60, 10), np.zeros(10)]
    chain("A", np.vstack([rod, tail]), [90.0] * 60 + [30.0] * 10)
    chain("B", np.c_[rng.normal(0, 4, 30), rng.normal(0, 4, 30), rng.normal(12, 2, 30)], [90.0] * 30)
    ion = gemmi.Chain("L")
    res = gemmi.Residue()
    res.name, res.seqid = "MG", gemmi.SeqId(1, " ")
    at = gemmi.Atom()
    at.name, at.element, at.pos = "MG", gemmi.Element("Mg"), gemmi.Position(0, 0, 30)
    res.add_atom(at)
    ion.add_residue(res)
    model.add_chain(ion)
    st.add_model(model)
    st.setup_entities()
    path = tmp_path / name
    if name.endswith(".pdb"):
        st.write_pdb(str(path))
    else:
        st.make_mmcif_document().write_file(str(path))
    return path


def test_predicted_model_drops_low_plddt_and_skips_ligands(tmp_path):
    coords, name, notes = S.load(_structure(tmp_path))
    assert set(coords) == {"A", "B"} and len(coords["A"]) == 60 and name == "model"
    assert any("10 of 70 residues below pLDDT 65" in n for n in notes)


def test_experimental_structure_keeps_every_residue(tmp_path):
    path = _structure(tmp_path, resolution=2.5, name="xtal.pdb")
    coords, _, notes = S.load(path)
    if gemmi.read_structure(str(path)).resolution == 0:
        pytest.skip("this gemmi build doesn't round-trip resolution through PDB")
    assert len(coords["A"]) == 70 and any("experimental" in n for n in notes)


def test_chains_pick_and_label(tmp_path):
    coords, _, _ = S.load(_structure(tmp_path), {"B": "cargo"})
    assert list(coords) == ["cargo"]
    with pytest.raises(ValueError, match="not found"):
        S.load(_structure(tmp_path), {"Z": "nope"})


def test_default_view_is_wide_and_draws_far_to_near(tmp_path):
    s = S.silhouette(_structure(tmp_path), {"A": "rod", "B": "blob"})
    assert s.w > 2 * s.h                                   # long axis horizontal
    assert [c.name for c in s.chains][-1] in {"rod", "blob"} and len(s.chains) == 2
    assert s.chains[0].depth >= s.chains[1].depth          # far first
    for c in s.chains:
        assert c.rings and 0 <= c.anchor[0] <= s.w and 0 <= c.anchor[1] <= s.h


def test_view_changes_the_outline(tmp_path):
    a = S.silhouette(_structure(tmp_path), view="2:90")
    b = S.silhouette(_structure(tmp_path), view="1:90")
    assert abs(a.w - b.w) > 20
    with pytest.raises(ValueError, match="axis:degrees"):
        S.silhouette(_structure(tmp_path), view="4:10")


def test_svg_complex_and_row(tmp_path):
    cx = S.silhouette(_structure(tmp_path), {"A": "rod", "B": "blob"})
    out = S.svg(cx)
    assert out.count("<path") == 2 and ">rod</text>" in out and ">blob</text>" in out
    assert 'figlib-provenance' in out and 'width="' in out
    single = S.silhouette(_structure(tmp_path), {"B": "blob"})
    row = S.svg([single, single], names=["one", "two"])
    assert row.count("<path") == 2 and ">one</text>" in row and ">two</text>" in row
    assert S.svg(cx, labels=False).count("<text") == 0


def test_json_shape(tmp_path):
    d = S.silhouette(_structure(tmp_path)).to_dict()
    assert set(d) >= {"w", "h", "chains", "view", "source"}
    assert all(set(c) == {"name", "rings", "anchor"} for c in d["chains"])
    json.dumps(d)


def test_fetch_uses_the_api_once_then_the_cache(tmp_path, monkeypatch):
    cif = _structure(tmp_path).read_bytes()
    calls = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url
        calls.append(url)
        assert req.get_header("User-agent").startswith("figlib/")     # bare "figlib" gets HTTP 403
        if "/api/prediction/" in url:
            body = json.dumps([{"entryId": "AF-P12345-F1", "latestVersion": 6, "gene": "ABC1",
                                "cifUrl": "https://alphafold.ebi.ac.uk/files/AF-P12345-F1-model_v6.cif"}]).encode()
        else:
            body = cif
        r = io.BytesIO(body)
        r.__enter__, r.__exit__ = (lambda *a: r), (lambda *a: None)
        return r

    monkeypatch.setattr(S.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("FIGLIB_CACHE", str(tmp_path / "cache"))
    path, gene = S.fetch("p12345")
    assert gene == "ABC1" and path.name == "AF-P12345-F1-model_v6.cif" and len(calls) == 2
    assert S.fetch("P12345") == (path, "ABC1") and len(calls) == 2              # cached
    s = S.silhouette("P12345")
    assert [c.name for c in s.chains] != ["ABC1"]          # two chains in this fixture: keep chain ids
    coords, name, _ = S.load("P12345", ["B"])
    assert name == "ABC1"


def test_cli_views_and_svg(tmp_path):
    src = _structure(tmp_path)
    assert S.main([str(src), "--chains", "A=rod,B", "--svg", str(tmp_path / "x.svg"),
                   "--json", str(tmp_path / "x.json"), "--views", str(tmp_path / "v.png")]) == 0
    assert (tmp_path / "v.png").stat().st_size > 1000
    assert json.loads((tmp_path / "x.json").read_text())["chains"][0]["name"] in {"rod", "B"}

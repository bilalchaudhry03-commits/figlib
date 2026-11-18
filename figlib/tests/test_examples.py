"""The starter files in examples/ must stay clean under the checks they teach.

They live in the repo, not the package, so these tests skip on a pip install.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples"
pytestmark = pytest.mark.skipif(not EXAMPLES.is_dir(), reason="examples/ is only in the repo")


def test_schematic_template_is_lint_clean():
    pytest.importorskip("playwright")
    r = subprocess.run([sys.executable, "-m", "figlib.check_layout", str(EXAMPLES / "schematic_template.html")],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr


def test_matplotlib_example_passes_figcheck(tmp_path):
    script = tmp_path / "figcheck_example.py"          # outputs land beside the copy
    shutil.copy(EXAMPLES / "figcheck_example.py", script)
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "figcheck_example.svg").exists() and "60 of 60" in r.stdout

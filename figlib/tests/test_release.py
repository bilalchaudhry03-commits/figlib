"""The package version, the plugin version and every documented install pin move together.

A labmate's Claude installs what the skill's setup block says; if that pin lags the package,
the skill describes calls the installed figlib doesn't have. Repo-only files, so these skip on
a pip install.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import figlib

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "plugins" / "figlib"
pytestmark = pytest.mark.skipif(not PLUGIN.is_dir(), reason="plugin files are only in the repo")


def test_plugin_version_is_the_package_version():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["version"] == figlib.__version__


@pytest.mark.parametrize("doc", ["README.md", "plugins/figlib/skills/figlib/SKILL.md"])
def test_every_install_pin_is_this_release(doc):
    pins = re.findall(r"figlib\.git@(v[\w.]+)", (REPO / doc).read_text())
    assert pins, f"{doc} has no pinned install line"
    assert set(pins) == {f"v{figlib.__version__}"}, f"{doc} pins {set(pins)}"

"""Shared test fixtures: a small SVG, and skips for tests that need Chromium, LibreOffice or PowerPoint.

Use the `chromium` / `soffice` / `powerpoint` fixtures rather than probing in each file, so every test skips
for the same reason and the probe runs once per session.
"""
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if (REPO / "figlib" / "__init__.py").exists() and str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))           # a clone runs its tests without installing

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
       '<rect width="200" height="100" fill="#2a78d6"/></svg>')


@pytest.fixture
def svg_text():
    """A 200 x 100 blue rectangle."""
    return SVG


@pytest.fixture
def svg_file(tmp_path):
    p = tmp_path / "f.svg"
    p.write_text(SVG, encoding="utf-8")
    return p


@pytest.fixture(scope="session")
def chromium():
    """Skip unless Playwright can launch Chromium (`python -m playwright install chromium`)."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception as e:                  # not installed, or no browser downloaded
        pytest.skip(f"Chromium not available: {type(e).__name__}")


@pytest.fixture(scope="session")
def soffice():
    """Skip unless LibreOffice runs here. An Apptainer image (FIGLIB_LIBREOFFICE_SIF) needs a
    compute node, so it counts as absent; point FIGLIB_SOFFICE at a wrapper to test through one."""
    from figlib import render
    try:
        render.find_soffice()
    except FileNotFoundError:
        pytest.skip("LibreOffice not installed")
    if os.environ.get("FIGLIB_LIBREOFFICE_SIF") and not os.environ.get("FIGLIB_SOFFICE"):
        pytest.skip("LibreOffice only via an Apptainer image")


@pytest.fixture(scope="session")
def powerpoint():
    """Skip unless PowerPoint is installed (never on CI)."""
    from figlib import render
    if not render.has_powerpoint():
        pytest.skip("PowerPoint not installed")

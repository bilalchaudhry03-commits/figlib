"""Figure tooling: layout linters, colour, SVG export, decks and video.

    figcheck      matplotlib layout linter -- `figcheck.report(fig)`
    check_layout  the same checks for HTML+SVG figures -- `python -m figlib.check_layout f.html`
    export_svg    HTML figure -> standalone SVG for PowerPoint/Illustrator
    palette       colour registry plus a colour-blindness (CVD) validator
    fonts         vendored Carlito (metric-compatible with Calibri)
    inputs        `require(path, why=...)` -- fail early on missing data
    deck          build .pptx decks from Python
    outline       Markdown outline -> .pptx -- `python -m figlib.outline talk.md`
    layers        HTML figure -> per-click SVG layers / animation manifest for an outline
    render        .pptx -> slide PNGs + contact sheet via LibreOffice -- `python -m figlib.render talk.pptx`
    anim          frames -> MP4 / GIF / poster / contact sheet
    scene, clip   explainer videos (scenes on a timeline, Manim clips)
"""

from functools import lru_cache as _lru_cache

__version__ = "0.2.9"


@_lru_cache(maxsize=None)
def build_id() -> str:
    """The code that is running: '0.1.0+374f498', '+374f498.dirty' with uncommitted edits, or
    just the version when the commit can't be known.

    From a git checkout, asks git. From `pip install git+...`, reads the commit pip recorded in
    direct_url.json. Stamped into every exported SVG, so a figure says which figlib made it.
    """
    import json
    import subprocess
    from importlib import metadata
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    if (root / ".git").exists():
        def git(*args):
            return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        try:
            head = git("rev-parse", "--short=7", "HEAD")
            if head.returncode == 0:
                dirty = git("status", "--porcelain", "--", "figlib").stdout.strip()
                return f"{__version__}+{head.stdout.strip()}{'.dirty' if dirty else ''}"
        except OSError:   # no git, or a sandbox that won't run it (Claude Code's does not)
            pass
    try:
        url = json.loads(metadata.distribution("figlib").read_text("direct_url.json") or "{}")
        commit = url.get("vcs_info", {}).get("commit_id")
        if commit:
            return f"{__version__}+{commit[:7]}"
    except (metadata.PackageNotFoundError, ValueError):
        pass
    return __version__

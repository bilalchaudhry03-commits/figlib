"""Figure tooling: layout linters, colour, SVG export, decks and video.

    figcheck      matplotlib layout linter -- `figcheck.report(fig)`
    check_layout  the same checks for HTML+SVG figures -- `python -m figlib.check_layout f.html`
    export_svg    HTML figure -> standalone SVG for PowerPoint/Illustrator
    palette       colour registry plus a colour-blindness (CVD) validator
    fonts         vendored Carlito (metric-compatible with Calibri)
    inputs        `require(path, why=...)` -- fail early on missing data
    deck          build .pptx decks from Python
    anim          frames -> MP4 / GIF / poster / contact sheet
    scene, clip   explainer videos (scenes on a timeline, Manim clips)
"""

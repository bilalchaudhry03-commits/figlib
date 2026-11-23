---
author: Your Name
---
# Starter talk (figlib.outline)

    python -m figlib.outline talk.md      # build: talk.pptx
    python -m figlib.render talk.pptx     # look: talk_render/contact.png

Edit this file, never the .pptx: a rebuild overwrites it. Lines above the first slide are
ignored, so notes to yourself can live here. Full format: `python -m figlib.outline --help`
and the docstring of figlib/outline.py. Figures live in figs/ with the scripts that make them.

### S01 · Replace this with your talk's title
section: title

### S02 · Larger proteins enter the nucleus more slowly
figure: figs/rate_vs_size.svg
notes:
The title is the claim; the figure is the evidence. Anything else you want to say goes here,
in the speaker notes, not as small grey text on the slide.

### S03 · Three steps turn a sample into a prediction
figure: figs/workflow_L1.svg
build: figs/workflow_L2.svg
build: figs/workflow_L3.svg
notes:
One step appears per click. The layers come from figs/workflow.html:
python -m figlib.layers build figs/workflow.html L1 L2 L3

### S04 · Rate falls exponentially with size
equation: k(M) = k_0\,e^{-M/M_0}
figure: figs/rate_vs_size.svg
notes:
An equation line before `figure:` shows with the slide; after it, it appears on a click.

### B01 · Backup slides go after the main deck
- Bullets are one level deep, one line each
- Detail belongs in the speaker notes
notes:
Backup slides (B01, B02, ...) follow the main deck; the build reports the two counts separately.

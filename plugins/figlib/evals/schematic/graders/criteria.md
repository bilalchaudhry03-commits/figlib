---
type: llm
---

A good run:
- builds the schematic as HTML+SVG and exports it with figlib's export_svg (not a hand-written or screenshot SVG);
- runs figlib's check_layout and gets it clean before exporting;
- shows the three steps in order (cytoplasm binding, crossing the pore, RanGTP release in the nucleus), labelled directly;
- uses flat colours with consistent strokes, no gradients or shadows, and text large enough for a slide;
- tells the user where the SVG is.

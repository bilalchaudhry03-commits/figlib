---
type: llm
---

A good run:
- exports with figlib's export_svg;
- notices that the circles set their colours with inline style="fill:var(...)", which does not survive in
  PowerPoint/Illustrator, and moves those colours to attributes or class rules in the HTML before exporting;
- does not hand-edit the exported SVG;
- tells the user where export_traps.svg is.

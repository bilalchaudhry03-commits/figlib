---
type: llm
---

A good run:
- simulates the model first and asserts that the simulation recovers what the equation says (e.g. the
  relaxation time) before drawing anything, passing that check to the renderer;
- produces a storyboard (one still per caption) and stops there for review: no draft or final render;
- keeps captions short and puts the equation on screen as the thing it describes happens;
- reports what the model check measured.

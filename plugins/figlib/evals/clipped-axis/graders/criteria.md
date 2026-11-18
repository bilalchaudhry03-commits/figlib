---
type: llm
---

A good run:
- finds that the y-limits (0.05 to 1.0) hide points: 14 of the 80 rows fall outside them and are silently not drawn;
- fixes it (limits that contain the data, or a deliberately declared window with the shown-vs-available count stated);
- runs figlib's figcheck on the figure and gets it clean, or explains anything left;
- regenerates the PNG and tells the user what was wrong in plain words.

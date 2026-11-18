---
type: llm
---

A good run:
- produces a PNG figure of rate vs size from import_rates.csv, with both groups shown and distinguishable;
- sizes text for a projected slide (not matplotlib's default small labels) and labels axes with units;
- runs figlib's figcheck on the figure before saving and fixes or explains anything it reports;
- if it sets an axis limit by hand, says how many of the 80 points are shown;
- tells the user where the file is, without claiming checks it did not run.

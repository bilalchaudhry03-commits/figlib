"""Starter for a matplotlib figure checked with figcheck. Copy it and replace the data.

    python examples/figcheck_example.py            # writes figcheck_example.svg and .png beside it

What it shows:
  - the font stack (Carlito stands in for Calibri, with the same widths) and slide-sized text;
  - colours from figlib.palette, used in order;
  - an axis limit set by hand, with the plotted vs available count reported, because points
    outside the limits are silently not drawn (figcheck reports them as CLIPPED);
  - figcheck.require(fig) before saving: it raises on any finding, so a bad figure is never written.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from figlib import fonts, figcheck, palette as pal  # noqa: E402

OUT = Path(__file__).with_suffix("")
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": fonts.STACK_LIST,
                     "font.size": 16, "svg.fonttype": "none"})

# ==== data (replace with yours; seeded so the example is reproducible) ====
rng = np.random.default_rng(0)
size_kda = rng.uniform(10, 120, 60)
groups = {"passive": 1.0, "imported": 2.5}
data = {g: (size_kda, k * np.exp(-size_kda / 40) * rng.lognormal(0, 0.2, size_kda.size))
        for g, k in groups.items()}

# ==== figure: sized for half a 16:9 slide, text at slide size ====
fig, ax = plt.subplots(figsize=(6.4, 4.8), layout="constrained")   # or labels fall off the canvas
YLIM = (2e-2, 4)
for colour, (name, (x, y)) in zip(pal.SERIES, data.items()):
    ax.scatter(x, y, s=28, color=colour, label=name)
ax.set_yscale("log")
ax.set_ylim(*YLIM)
ax.set_xlabel("size (kDa)")
ax.set_ylabel("rate (1/min)")
ax.legend(frameon=False, loc="upper right")
for side in ("top", "right"):
    ax.spines[side].set_visible(False)

# A hand-set limit hides points outside it. Say how many are shown.
for name, (x, y) in data.items():
    shown = int(((y >= YLIM[0]) & (y <= YLIM[1])).sum())
    print(f"{name}: {shown} of {y.size} points inside the y-limits")

figcheck.require(fig)              # raises with every finding; use figcheck.report(fig) to just print
for ext in ("svg", "png"):
    fig.savefig(OUT.with_suffix(f".{ext}"), dpi=200)
print("wrote", OUT.with_suffix(".svg").name, "and .png")

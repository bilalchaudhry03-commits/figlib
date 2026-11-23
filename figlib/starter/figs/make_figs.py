"""Make the starter talk's data figure. Replace the data with yours and re-run:

    python figs/make_figs.py        # writes figs/rate_vs_size.svg (and .png to look at)

figcheck.require(fig) runs before saving, so a figure with overlapping or too-small text,
or points silently cut off by an axis limit, is never written.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from figlib import fonts, figcheck, palette as pal  # noqa: E402

HERE = Path(__file__).parent
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": fonts.STACK_LIST,
                     "font.size": 18, "svg.fonttype": "none", "svg.hashsalt": "figlib-starter"})

rng = np.random.default_rng(0)
size_kda = rng.uniform(10, 120, 60)
data = {g: k * np.exp(-size_kda / 40) * rng.lognormal(0, 0.2, size_kda.size)
        for g, k in {"passive": 1.0, "imported": 2.5}.items()}

fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
YLIM = (2e-2, 4)
for colour, (name, y) in zip(pal.SERIES, data.items()):
    ax.scatter(size_kda, y, s=36, color=colour, label=name)
    print(f"{name}: {int(((y >= YLIM[0]) & (y <= YLIM[1])).sum())} of {y.size} points inside the y-limits")
ax.set_yscale("log")
ax.set_ylim(*YLIM)
ax.set_xlabel("protein size (kDa)")
ax.set_ylabel("import rate (1/min)")
ax.legend(frameon=False, loc="upper right")
for side in ("top", "right"):
    ax.spines[side].set_visible(False)

figcheck.require(fig)
fig.savefig(HERE / "rate_vs_size.svg", metadata={"Date": None})
fig.savefig(HERE / "rate_vs_size.png", dpi=150)
print("wrote figs/rate_vs_size.svg")

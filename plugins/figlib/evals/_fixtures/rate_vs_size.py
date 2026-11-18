import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

df = pd.read_csv("import_rates.csv")
fig, ax = plt.subplots(figsize=(6, 4.5))
for g, sub in df.groupby("group"):
    ax.scatter(sub.size_kda, sub.rate_per_min, label=g, s=20)
ax.set_yscale("log")
ax.set_ylim(0.05, 1.0)
ax.set_xlabel("size (kDa)")
ax.set_ylabel("import rate (1/min)")
ax.legend()
fig.savefig("rate_vs_size.png", dpi=150)

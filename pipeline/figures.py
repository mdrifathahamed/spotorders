"""First-look figures for the README (static PNGs, matplotlib only).

Run:  python -m pipeline.figures
"""
from pathlib import Path

import h3
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Polygon

ROOT = Path(__file__).resolve().parents[1]
BLUES = LinearSegmentedColormap.from_list(
    "seq_blue", ["#cce3fd", "#9dc8f7", "#6aabf1", "#338ced", "#2370cd", "#1757ac", "#0e3d7e"])
INK, MUTED, GRID = "#1f1f1f", "#6b6b6b", "#e6e6e6"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.titlecolor": INK,
                     "axes.titleweight": "bold", "axes.titlelocation": "left"})


def weekday_hour(df):
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    hours = list(range(9, 24))
    m = (df.assign(h=np.where(df.hour < 6, 23, df.hour.clip(9, 23)))
           .pivot_table(index="weekday", columns="h", values="order_id", aggfunc="count")
           .reindex(index=range(7), columns=hours).fillna(0))
    fig, ax = plt.subplots(figsize=(9, 3.4))
    im = ax.imshow(m.values, cmap=BLUES, aspect="auto", vmin=0)
    # 2px surface gap between cells
    for x in np.arange(-.5, len(hours), 1):
        ax.axvline(x, color="white", lw=2)
    for y in np.arange(-.5, 7, 1):
        ax.axhline(y, color="white", lw=2)
    ax.set_xticks(range(len(hours)), [f"{h:02d}" for h in hours])
    ax.set_yticks(range(7), days)
    ax.set_xlabel("hour of day (00–02 folded into 23)")
    ax.set_title("Tasks by weekday and hour, Sep–Nov 2026")
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=.025, pad=.01)
    cb.outline.set_visible(False)
    cb.set_label("tasks")
    fig.tight_layout()
    fig.savefig(ROOT / "figures/weekday_hour.png", dpi=160)


def hex_map(df):
    d = df.dropna(subset=["h3_r9"])
    counts = d.h3_r9.value_counts()
    fig, ax = plt.subplots(figsize=(8, 6.5))
    vmax = counts.max()
    for cell, n in counts.items():
        ring = [(lng, lat) for lat, lng in h3.cell_to_boundary(cell)]
        ax.add_patch(Polygon(ring, closed=True, facecolor=BLUES(n / vmax), edgecolor="white", lw=2))
    # label the five busiest hexes in a column to the right, with leader lines (no collisions)
    top = d.groupby("h3_r9").anchor_venue.agg(lambda s: s.value_counts().index[0])
    lab = sorted(counts.index[:5], key=lambda c: -h3.cell_to_latlng(c)[0])
    lngs_all = [h3.cell_to_latlng(c)[1] for c in counts.index]
    lats_all = [h3.cell_to_latlng(c)[0] for c in counts.index]
    x_lab = max(lngs_all) + .008
    ys = np.linspace(max(lats_all) - .012, min(lats_all) + .008, len(lab))
    for cell, y in zip(lab, ys):
        lat, lng = h3.cell_to_latlng(cell)
        ax.plot([lng, x_lab - .001], [lat, y], color=MUTED, lw=.6)
        ax.text(x_lab, y, f"{top[cell]} · {counts[cell]} tasks", va="center", fontsize=8, color=INK)
    lats = [h3.cell_to_latlng(c)[0] for c in counts.index]
    lngs = [h3.cell_to_latlng(c)[1] for c in counts.index]
    ax.set_xlim(min(lngs) - .01, max(lngs) + .06)
    ax.set_ylim(min(lats) - .006, max(lats) + .006)
    ax.set_aspect(1 / np.cos(np.radians(60.19)))
    ax.set_title("Where tasks started (H3 res 9, simulated courier position)")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.grid(color=GRID, lw=.5)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.tight_layout()
    fig.savefig(ROOT / "figures/hex_map.png", dpi=160)


if __name__ == "__main__":
    (ROOT / "figures").mkdir(exist_ok=True)
    df = pd.read_csv(ROOT / "data/private/orders_enriched.csv")
    weekday_hour(df)
    hex_map(df)
    print("figures written")

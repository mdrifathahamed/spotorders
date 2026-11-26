"""Phase-4 starting point: smoothed statistics, no ML yet.

For every H3 res-8 hexagon and time bucket we estimate the expected wait until
the next offer, shrunk towards the time-bucket average so that hexagons with
two orders don't look like miracles (empirical-Bayes / additive smoothing).

    score = (sum_wait + k * prior_wait) / (n + k)

Lower is better. The output is what the app will read to colour its hex map.

Run:  python -m pipeline.baseline
"""
from pathlib import Path

import h3
import pandas as pd


def top_name(s):
    vc = s.replace("", None).dropna().value_counts()
    return vc.index[0] if len(vc) else "(no known venue)"

ROOT = Path(__file__).resolve().parents[1]
K = 4  # pseudo-observations; raise it when data are noisy


def rank_spots(df: pd.DataFrame, k: int = K) -> pd.DataFrame:
    d = df.dropna(subset=["h3_r8", "wait_min"])
    prior = d.groupby("time_bucket").wait_min.mean().rename("prior_wait")
    g = (d.groupby(["h3_r8", "time_bucket"])
           .agg(n=("wait_min", "size"), sum_wait=("wait_min", "sum"),
                top_venue=("anchor_venue", top_name))
           .reset_index().join(prior, on="time_bucket"))
    g["smoothed_wait_min"] = (g.sum_wait + k * g.prior_wait) / (g.n + k)
    g["raw_mean_wait_min"] = g.sum_wait / g.n
    g[["hex_lat", "hex_lon"]] = [h3.cell_to_latlng(c) for c in g.h3_r8]
    g["rank_in_bucket"] = g.groupby("time_bucket").smoothed_wait_min.rank(method="min")
    cols = ["time_bucket", "rank_in_bucket", "h3_r8", "hex_lat", "hex_lon", "top_venue", "n",
            "raw_mean_wait_min", "smoothed_wait_min", "prior_wait"]
    return g[cols].sort_values(["time_bucket", "rank_in_bucket"]).round(2)


if __name__ == "__main__":
    df = pd.read_csv(ROOT / "data/private/orders_enriched.csv")
    out = rank_spots(df)
    out.to_csv(ROOT / "data/sample/spot_ranking.csv", index=False)
    for b, grp in out.groupby("time_bucket"):
        best = grp.iloc[0]
        print(f"{b:9s} best hex near {best.top_venue:35s} ~{best.smoothed_wait_min:.0f} min (n={best.n})")

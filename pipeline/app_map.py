"""Export the map the phone app draws: H3 hexagons with an expected wait per time of day.

The numbers come from the Bayesian waiting-time model (pipeline/bayes.py): a gamma-Poisson
order rate per hexagon, shared across the time of day, with a prior from the time-of-day rate
and the restaurant layer, recent shifts weighted more (half-life chosen by the nightly
backtest). For every hexagon and time bucket the app gets the expected wait, an 80% interval
for it and the probability of an order within 10 minutes.

Output: data/sample/app_map.json (public: aggregated, no times, no GPS points)
Run:    python -m pipeline.app_map
"""
from __future__ import annotations

import json
from pathlib import Path

import h3
import numpy as np
import pandas as pd

from .osm_places import load_layer
from . import bayes

ROOT = Path(__file__).resolve().parents[1]
RES = 8
K = 4
BUCKETS = ["morning", "lunch", "afternoon", "dinner", "late"]
# central + northern Helsinki, where I ride
BBOX = (60.145, 24.86, 60.255, 25.08)  # south, west, north, east
DENSITY_FILE = ROOT / "data/reference/osm_food_hex.csv"


def fetch_osm_density() -> pd.DataFrame:
    """Count restaurants, fast food, cafés and grocery shops per H3 cell (Overpass API)."""
    import requests

    s, w, n, e = BBOX
    q = f"""[out:json][timeout:90];
    (nwr["amenity"~"^(restaurant|fast_food|cafe|food_court)$"]({s},{w},{n},{e});
     nwr["shop"~"^(supermarket|convenience|bakery)$"]({s},{w},{n},{e}););
    out center;"""
    r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, timeout=120,
                      headers={"User-Agent": "spotorders (github.com/mdrifathahamed/spotorders)"})
    r.raise_for_status()
    pts = []
    for el in r.json()["elements"]:
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lon = el.get("lon", el.get("center", {}).get("lon"))
        if lat is not None:
            pts.append(h3.latlng_to_cell(lat, lon, RES))
    df = pd.Series(pts).value_counts().rename_axis("h3").reset_index(name="food_places")
    df.to_csv(DENSITY_FILE, index=False)
    print(f"osm: {len(pts)} food places in {len(df)} cells")
    return df


def load_density() -> pd.DataFrame:
    if DENSITY_FILE.exists():
        return pd.read_csv(DENSITY_FILE)
    try:
        return fetch_osm_density()
    except Exception as ex:  # offline: fall back to the venues I have picked up from
        print(f"osm: density not available ({ex}); using my own venues")
        v = pd.read_csv(ROOT / "data/reference/venues.csv").dropna(subset=["lat"])
        cells = [h3.latlng_to_cell(a, b, RES) for a, b in zip(v.lat, v.lon)]
        return pd.Series(cells).value_counts().rename_axis("h3").reset_index(name="food_places")


def top_name(s):
    vc = s.replace("", None).dropna().value_counts()
    return vc.index[0] if len(vc) else None


BUCKET_HOURS = {"morning": range(6, 11), "lunch": range(11, 14), "afternoon": range(14, 17),
                "dinner": range(17, 21), "late": [21, 22, 23, 0, 1, 2, 3, 4, 5]}


def bucket_scores():
    """Per hexagon and bucket: mean food score and expected open places (all weekdays, 5:2 weighting)."""
    tab, cl, _ = load_layer()
    if tab is None:
        return None, None, None
    tab = tab.assign(w=np.where(tab.weekday >= 5, 2 / 7, 5 / 7) / np.where(tab.weekday >= 5, 2, 5))
    out = {}
    for b, hrs in BUCKET_HOURS.items():
        t = tab[tab.hour.isin(list(hrs))]
        agg = t.groupby("h3_r8").apply(lambda g: pd.Series({
            "score": np.average(g.food_score, weights=g.w), "open": np.average(g.open_est, weights=g.w)}))
        out[b] = agg
    totals = tab.groupby("h3_r8").agg(n_total=("n_total", "first"), n_known=("n_hours_known", "first"),
                                      n_wolt=("n_wolt_venues", "first"))
    return out, totals, cl


def build() -> dict:
    df = pd.read_csv(ROOT / "data/private/orders_enriched.csv")
    df["h3"] = df.h3_r8
    dens = load_density().set_index("h3").food_places
    scores, totals, cl = bucket_scores()
    cluster_at = {}
    if cl is not None and len(cl):
        for _, r in cl.iterrows():
            cluster_at.setdefault(r.h3_r8, (r.label, int(r.n_places)))

    obs = df.dropna(subset=["h3", "wait_min"])
    stats = obs.groupby(["h3", "time_bucket"]).wait_min.agg(["size", "sum"])
    score = {b: {"score": scores[b].score, "median": float(scores[b].score.median())} for b in BUCKETS} if scores else None
    check_f = ROOT / "data/sample/model_check.json"
    check = json.loads(check_f.read_text()) if check_f.exists() else {}
    half_life = check.get("best_half_life_days")
    x = bayes.exposure_table(df)
    mult = bayes.multipliers(x)
    today = pd.Timestamp.now(tz="Europe/Helsinki").strftime("%Y-%m-%d")
    model = bayes.fit(x, score, mult, half_life, today)
    orders = df.dropna(subset=["h3"]).groupby("h3")
    top = orders.anchor_venue.agg(top_name)
    n_orders = orders.size()

    cells = sorted(set(dens.index) | set(n_orders.index) | (set(totals.index) if totals is not None else set()))
    out = []
    for c in cells:
        d = int(totals.n_total.get(c, 0)) if totals is not None else int(dens.get(c, 0))
        wait, lo, hi, p10, n, open_ = {}, {}, {}, {}, {}, {}
        for b in BUCKETS:
            if scores:
                open_[b] = round(float(scores[b].open.get(c, 0.0)), 1)
            a_, b_, _, _ = bayes.posterior(model, c, b)
            wait[b], lo[b], hi[b], p10[b] = bayes.summary(a_, b_)
            n[b] = int(stats.loc[(c, b)]["size"]) if (c, b) in stats.index else 0
        lat, lon = h3.cell_to_latlng(c)
        out.append(dict(
            h3=c, lat=round(lat, 5), lon=round(lon, 5),
            boundary=[[round(a, 5), round(o, 5)] for a, o in h3.cell_to_boundary(c)],
            food_places=d, my_orders=int(n_orders.get(c, 0)),
            open=open_ or None,
            hours_known=int(totals.n_known.get(c, 0)) if totals is not None else None,
            wolt_venues=int(totals.n_wolt.get(c, 0)) if totals is not None else None,
            cluster=cluster_at.get(c, (None, None))[0], cluster_places=cluster_at.get(c, (None, None))[1],
            top_venue=top.get(c) if c in top.index else None,
            wait=wait, wait_lo=lo, wait_hi=hi, p10=p10, n=n,
        ))
    return dict(
        generated=pd.Timestamp.now(tz="Europe/Helsinki").isoformat(timespec="minutes"),
        h3_resolution=RES, buckets=BUCKETS,
        bucket_hours={"morning": "06-11", "lunch": "11-14", "afternoon": "14-17", "dinner": "17-21", "late": "21-06"},
        total_orders=int(len(df)), cells=out,
        model=dict(kind="gamma-poisson, hexagon effect shared across time of day", alpha=model["alpha"],
                   gamma=model["gamma"], half_life_days=half_life, waits=int(x.events.sum()),
                   exposure_hours=round(float(x.exposure.sum()) / 60, 1),
                   weekend=mult["weekend"], rain=mult["rain"],
                   backtest=check.get("models")),
    )


if __name__ == "__main__":
    m = build()
    f = ROOT / "data/sample/app_map.json"
    f.write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")))
    print(f"app map: {len(m['cells'])} hexagons, {f.stat().st_size // 1024} KB")

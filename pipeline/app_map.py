"""Export the map the phone app draws: H3 hexagons with an expected wait per time of day.

expected wait in a hexagon, for a time bucket =
    (sum of my waits there + K * prior) / (n + K)

The prior is the bucket's average wait, scaled by restaurant density from
OpenStreetMap: hexagons with many restaurants and shops are assumed to give
shorter waits even before I have waited there. So unexplored hexagons get a
sensible colour, and my own data take over as they accumulate.

Output: data/sample/app_map.json (public: aggregated, no times, no GPS points)
Run:    python -m pipeline.app_map
"""
from __future__ import annotations

import json
from pathlib import Path

import h3
import numpy as np
import pandas as pd

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


def build() -> dict:
    df = pd.read_csv(ROOT / "data/private/orders_enriched.csv")
    df["h3"] = df.h3_r8
    dens = load_density().set_index("h3").food_places

    obs = df.dropna(subset=["h3", "wait_min"])
    bucket_mean = obs.groupby("time_bucket").wait_min.mean().reindex(BUCKETS)
    bucket_mean = bucket_mean.fillna(obs.wait_min.mean())
    stats = obs.groupby(["h3", "time_bucket"]).wait_min.agg(["size", "sum"])
    orders = df.dropna(subset=["h3"]).groupby("h3")
    top = orders.anchor_venue.agg(top_name)
    n_orders = orders.size()

    cells = sorted(set(dens.index) | set(n_orders.index))
    med = float(np.median(dens.values)) if len(dens) else 1.0
    out = []
    for c in cells:
        d = int(dens.get(c, 0))
        # more food places -> shorter prior wait (bounded, square-root damped)
        factor = float(np.clip(((med + 1) / (d + 1)) ** 0.5, 0.6, 1.6))
        wait, n = {}, {}
        for b in BUCKETS:
            prior = bucket_mean[b] * factor
            if (c, b) in stats.index:
                cnt, tot = stats.loc[(c, b)]
            else:
                cnt, tot = 0, 0.0
            wait[b] = round((tot + K * prior) / (cnt + K), 1)
            n[b] = int(cnt)
        lat, lon = h3.cell_to_latlng(c)
        out.append(dict(
            h3=c, lat=round(lat, 5), lon=round(lon, 5),
            boundary=[[round(a, 5), round(o, 5)] for a, o in h3.cell_to_boundary(c)],
            food_places=d, my_orders=int(n_orders.get(c, 0)),
            top_venue=top.get(c) if c in top.index else None,
            wait=wait, n=n,
        ))
    return dict(
        generated=pd.Timestamp.now(tz="Europe/Helsinki").isoformat(timespec="minutes"),
        h3_resolution=RES, buckets=BUCKETS,
        bucket_hours={"morning": "06-11", "lunch": "11-14", "afternoon": "14-17", "dinner": "17-21", "late": "21-06"},
        total_orders=int(len(df)), cells=out,
    )


if __name__ == "__main__":
    m = build()
    f = ROOT / "data/sample/app_map.json"
    f.write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")))
    print(f"app map: {len(m['cells'])} hexagons, {f.stat().st_size // 1024} KB")

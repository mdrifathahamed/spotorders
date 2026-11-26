"""Second data layer: food places from OpenStreetMap, with opening hours, type weights and clusters.

For every restaurant, fast-food place, café, food court, supermarket, convenience store and bakery
in the riding area this builds, per H3 hexagon, weekday and hour:

  food_score  = sum over places of  type weight x Wolt boost x P(open at that hour)
      type weight  burger/fast food and supermarkets count more than a bakery (TYPE_WEIGHT)
      Wolt boost   x3 for places I have actually picked up from (they are certainly on Wolt)
      P(open)      1/0 from the `opening_hours` tag; for places without usable hours, the city-wide
                   share of tagged places that are open at that hour
  open_est    = expected number of open places (unweighted)

and restaurant clusters (DBSCAN, 120 m): food courts and streets with many places close together,
e.g. the Redi food court or Hakaniemi.

Files (OpenStreetMap data © OpenStreetMap contributors, ODbL):
  data/reference/osm_food_places.csv  one row per place
  data/reference/osm_open_hex.csv     h3_r8 x weekday x hour
  data/reference/osm_clusters.csv     one row per cluster
  data/reference/osm_food_hex.csv     h3_r8 totals
  data/reference/osm_meta.json        download date
Re-downloaded when older than 30 days.  Run:  python -m pipeline.osm_places [--force]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import h3
import numpy as np
import pandas as pd

from .geo import haversine_m

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data/reference"
PLACES = REF / "osm_food_places.csv"
OPEN_HEX = REF / "osm_open_hex.csv"
CLUSTERS = REF / "osm_clusters.csv"
FOOD_HEX = REF / "osm_food_hex.csv"
META = REF / "osm_meta.json"
BBOX = (60.145, 24.86, 60.255, 25.08)   # south, west, north, east
MAX_AGE_DAYS = 30
REF_MONDAY = datetime(2026, 11, 23)     # reference week for evaluating opening hours (holidays ignored)

TYPE_WEIGHT = {"fast_food": 1.5, "food_court": 2.0, "restaurant": 1.2, "supermarket": 1.5,
               "convenience": 1.0, "cafe": 0.6, "bakery": 0.5}
WOLT_BOOST = 3.0
MATCH_RADIUS_M = 60          # an OSM place this close to a venue I picked up from is that venue
CLUSTER_EPS_M = 120
CLUSTER_MIN_PLACES = 5


# ------------------------------------------------------------------ download
def fetch() -> pd.DataFrame:
    import requests

    s, w, n, e = BBOX
    q = f"""[out:json][timeout:120];
    (nwr["amenity"~"^(restaurant|fast_food|cafe|food_court)$"]({s},{w},{n},{e});
     nwr["shop"~"^(supermarket|convenience|bakery)$"]({s},{w},{n},{e}););
    out center tags;"""
    r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, timeout=180,
                      headers={"User-Agent": "spotorders (github.com/mdrifathahamed/spotorders)"})
    r.raise_for_status()
    rows = []
    for el in r.json()["elements"]:
        t = el.get("tags", {})
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lon = el.get("lon", el.get("center", {}).get("lon"))
        if lat is None:
            continue
        rows.append(dict(
            osm_id=f"{el['type'][0]}{el['id']}", name=t.get("name", ""),
            kind=t.get("amenity") or t.get("shop"), brand=t.get("brand", ""),
            lat=round(lat, 6), lon=round(lon, 6), opening_hours=t.get("opening_hours", ""),
        ))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ helpers
def week_vector(spec) -> np.ndarray | None:
    """168 open/closed flags (Mon 00:30 ... Sun 23:30), or None if missing or unparsable."""
    if not isinstance(spec, str) or not spec.strip():
        return None
    try:
        from opening_hours import OpeningHours
        oh = OpeningHours(spec)
        return np.array([oh.is_open(REF_MONDAY + timedelta(hours=k, minutes=30)) for k in range(168)], dtype=float)
    except Exception:
        return None


def mark_wolt_venues(places: pd.DataFrame) -> pd.Series:
    """True for OSM places matching a venue I picked up from (within 60 m of its coordinates)."""
    v = pd.read_csv(ROOT / "data/reference/venues.csv").dropna(subset=["lat"])
    v = v[v.geocode_quality.isin(["osm", "address"])]   # exact positions only
    hit = np.zeros(len(places), dtype=bool)
    for lat, lon in zip(v.lat, v.lon):
        near = (abs(places.lat - lat) < 0.001) & (abs(places.lon - lon) < 0.002)
        for i in np.flatnonzero(near.values):
            if haversine_m(lat, lon, places.lat.iat[i], places.lon.iat[i]) <= MATCH_RADIUS_M:
                hit[i] = True
    return pd.Series(hit, index=places.index)


def clusters(places: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """DBSCAN on positions (haversine). Returns cluster id per place (-1 = none) and a cluster table."""
    from sklearn.cluster import DBSCAN

    X = np.radians(places[["lat", "lon"]].values)
    labels = DBSCAN(eps=CLUSTER_EPS_M / 6_371_008.8, min_samples=CLUSTER_MIN_PLACES,
                    metric="haversine").fit_predict(X)
    lab = pd.Series(labels, index=places.index)
    rows = []
    for cid in sorted(set(labels) - {-1}):
        g = places[lab == cid]
        named = g[g.name != ""]
        # name the cluster after a place I have picked up from, else the most weighted named place
        pick = named[named.wolt_venue] if named.wolt_venue.any() else named
        label = pick.sort_values("weight", ascending=False).name.iloc[0] if len(pick) else f"cluster {cid}"
        rows.append(dict(cluster_id=int(cid), label=label, n_places=len(g),
                         n_wolt_venues=int(g.wolt_venue.sum()), weight=round(g.weight.sum(), 1),
                         lat=round(g.lat.mean(), 5), lon=round(g.lon.mean(), 5),
                         h3_r8=h3.latlng_to_cell(g.lat.mean(), g.lon.mean(), 8)))
    return lab, pd.DataFrame(rows)


# ------------------------------------------------------------------ build
def build_tables(places: pd.DataFrame):
    places = places.reset_index(drop=True).copy()
    places["h3_r8"] = [h3.latlng_to_cell(a, b, 8) for a, b in zip(places.lat, places.lon)]
    places["h3_r9"] = [h3.latlng_to_cell(a, b, 9) for a, b in zip(places.lat, places.lon)]
    places["wolt_venue"] = mark_wolt_venues(places)
    places["weight"] = places.kind.map(TYPE_WEIGHT).fillna(1.0) * np.where(places.wolt_venue, WOLT_BOOST, 1.0)

    vecs = places.opening_hours.map(week_vector)
    places["hours_known"] = vecs.notna()
    known = np.vstack(vecs[places.hours_known].values) if places.hours_known.any() else np.zeros((0, 168))
    share_open = known.mean(axis=0) if len(known) else np.full(168, 0.5)
    # P(open) for every place and hour: known -> its own hours, unknown -> city-wide share
    P = np.vstack([v if v is not None else share_open for v in vecs])

    lab, cl = clusters(places)
    places["cluster_id"] = lab.values

    rows = []
    for cell, idx in places.groupby("h3_r8").groups.items():
        g = places.loc[idx]
        p = P[idx]
        score = (p * g.weight.values[:, None]).sum(axis=0)
        open_est = p.sum(axis=0)
        n_open_known = P[idx][g.hours_known.values].sum(axis=0) if g.hours_known.any() else np.zeros(168)
        for k in range(168):
            rows.append((cell, k // 24, k % 24, len(g), int(g.hours_known.sum()), int(g.wolt_venue.sum()),
                         int(n_open_known[k]), round(float(open_est[k]), 2), round(float(score[k]), 2)))
    tab = pd.DataFrame(rows, columns=["h3_r8", "weekday", "hour", "n_total", "n_hours_known", "n_wolt_venues",
                                      "n_open_known", "open_est", "food_score"])
    return places, tab, cl


def is_stale() -> bool:
    if not (PLACES.exists() and META.exists()):
        return True
    fetched = datetime.fromisoformat(json.loads(META.read_text())["fetched"])
    return datetime.now() - fetched > timedelta(days=MAX_AGE_DAYS)


def refresh(force: bool = False) -> bool:
    """Download if stale, then rebuild all layer tables. Returns False if no OSM data are available."""
    raw = None
    if force or is_stale():
        try:
            raw = fetch()
            META.write_text(json.dumps({"fetched": datetime.now().isoformat(timespec="minutes"),
                                        "source": "OpenStreetMap via Overpass API",
                                        "license": "ODbL, © OpenStreetMap contributors",
                                        "bbox_swne": BBOX, "places": len(raw)}, indent=1))
        except Exception as ex:
            print(f"osm: download failed ({ex}); keeping existing files")
    if raw is None:
        if not PLACES.exists():
            return False
        raw = pd.read_csv(PLACES, keep_default_na=False)[
            ["osm_id", "name", "kind", "brand", "lat", "lon", "opening_hours"]]
    places, tab, cl = build_tables(raw)
    places.to_csv(PLACES, index=False)
    tab.to_csv(OPEN_HEX, index=False)
    cl.to_csv(CLUSTERS, index=False)
    places.groupby("h3_r8").size().rename("food_places").rename_axis("h3").reset_index().to_csv(FOOD_HEX, index=False)
    print(f"osm: {len(places)} food places, {places.hours_known.mean():.0%} with opening hours, "
          f"{int(places.wolt_venue.sum())} matched to my Wolt venues, {len(cl)} clusters")
    return True


def load_layer():
    """(open table, clusters, places) or (None, None, None) when the layer hasn't been built yet."""
    if not OPEN_HEX.exists():
        return None, None, None
    return (pd.read_csv(OPEN_HEX), pd.read_csv(CLUSTERS) if CLUSTERS.exists() else pd.DataFrame(),
            pd.read_csv(PLACES, keep_default_na=False))


if __name__ == "__main__":
    refresh(force="--force" in sys.argv)

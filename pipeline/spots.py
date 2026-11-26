"""A concrete place to stand inside each hexagon, for each time of day.

A resolution-8 hexagon is about 0.7 km², too large to act on, so the map also names a waiting
spot: the food place with the highest weight at that time of day (open probability from its
OpenStreetMap opening hours x type weight x3 if I have picked up from it, plus two points per
pickup of mine there in that time bucket), moved to the weighted centre of the open places within
150 m of it, so that I stand where most orders can start.

Only public restaurant locations are used; no GPS points of mine are published.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .geo import haversine_m

ROOT = Path(__file__).resolve().parents[1]
BUCKET_HOURS = {"morning": range(6, 11), "lunch": range(11, 14), "afternoon": range(14, 17),
                "dinner": range(17, 21), "late": [21, 22, 23, 0, 1, 2, 3, 4, 5]}
RADIUS_M = 150
PICKUP_POINTS = 2.0


def open_by_bucket(places: pd.DataFrame) -> pd.DataFrame:
    """P(open) per place and bucket (all weekdays), unknown hours -> city-wide share open at that hour."""
    from .osm_places import week_vector

    vecs = places.opening_hours.map(week_vector)
    known = [v for v in vecs if v is not None]
    share = np.mean(known, axis=0) if known else np.full(168, 0.5)
    P = np.vstack([v if v is not None else share for v in vecs])
    out = {}
    for b, hrs in BUCKET_HOURS.items():
        cols = [d * 24 + h for d in range(7) for h in hrs]
        out[b] = P[:, cols].mean(axis=1)
    return pd.DataFrame(out, index=places.index)


def build_spots(df: pd.DataFrame) -> dict:
    """{h3_r8: {bucket: [lat, lon, name, open_nearby, my_pickups_nearby, address]}}"""
    f = ROOT / "data/reference/osm_food_places.csv"
    if not f.exists():
        return {}
    places = pd.read_csv(f).dropna(subset=["lat", "lon"]).reset_index(drop=True)
    places["name"] = places.name.fillna(places.kind.str.replace("_", " ").str.capitalize())
    P = open_by_bucket(places)

    # my pickups per venue and bucket, at the venue coordinates
    venues = pd.read_csv(ROOT / "data/reference/venues.csv").dropna(subset=["lat"]).set_index("venue")
    picks = (df.dropna(subset=["anchor_venue"]).groupby(["anchor_venue", "time_bucket"]).size()
               .rename("n").reset_index())
    picks = picks[picks.anchor_venue.isin(venues.index)]
    picks["lat"] = venues.loc[picks.anchor_venue, "lat"].values
    picks["lon"] = venues.loc[picks.anchor_venue, "lon"].values
    import h3
    picks["h3_r8"] = [h3.latlng_to_cell(a, b, 8) for a, b in zip(picks.lat, picks.lon)]

    out = {}
    for cell, g in places.groupby("h3_r8"):
        cell_picks = picks[picks.h3_r8 == cell]
        spots = {}
        for b in BUCKET_HOURS:
            score = (g.weight * P.loc[g.index, b]).to_numpy().astype(float).copy()
            names = list(g.name)
            lat, lon = g.lat.to_numpy(), g.lon.to_numpy()
            pb = cell_picks[cell_picks.time_bucket == b]
            # a place I picked up from at this time gets two points per pickup (nearest OSM place within 60 m,
            # otherwise the venue itself becomes a candidate)
            ex_lat, ex_lon, ex_score, ex_name = [], [], [], []
            addr = [""] * len(names)
            for _, r in pb.sort_values("n").iterrows():
                d = np.array([haversine_m(r.lat, r.lon, a, o) for a, o in zip(lat, lon)])
                if len(d) and d.min() <= 60:
                    j = int(d.argmin())
                    score[j] += PICKUP_POINTS * r.n
                    names[j], addr[j] = r.anchor_venue, str(venues.at[r.anchor_venue, "address"])  # my name for it
                else:
                    ex_lat.append(r.lat); ex_lon.append(r.lon); ex_score.append(PICKUP_POINTS * r.n + 1)
                    ex_name.append(r.anchor_venue)
                    addr.append(str(venues.at[r.anchor_venue, "address"]))
            lat, lon = np.r_[lat, ex_lat], np.r_[lon, ex_lon]
            score, names = np.r_[score, ex_score], names + ex_name
            if not len(score) or score.max() <= 0.05:
                continue
            k = int(score.argmax())
            near = np.array([haversine_m(lat[k], lon[k], a, o) for a, o in zip(lat, lon)]) <= RADIUS_M
            w = score * near
            c_lat, c_lon = float((lat * w).sum() / w.sum()), float((lon * w).sum() / w.sum())
            open_near = int(round(float(P.loc[g.index, b].to_numpy()[near[:len(g)]].sum())))
            my_near = int(sum(r.n for _, r in pb.iterrows()
                              if haversine_m(c_lat, c_lon, r.lat, r.lon) <= RADIUS_M))
            spots[b] = [round(c_lat, 5), round(c_lon, 5), names[k], open_near, my_near, addr[k]]
        if spots:
            out[cell] = spots
    return out

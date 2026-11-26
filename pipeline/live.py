"""Turn the app's one-tap log into order rows.

The app appends every button press to `live/events.csv` in the private data repo
(checked out at data/private/). Columns: ts, type, lat, lon, accuracy_m, fix_age_s.

Event types: SHIFT_START, FREE (delivered, waiting again), OFFER (got a task), SHIFT_END.
For each OFFER the *measured* wait is the time since the last FREE or SHIFT_START
in the same shift. The courier position is the real GPS fix at the moment of the tap.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .geo import haversine_m

SNAP_RADIUS_M = 100   # an OFFER within this distance of a known venue gets that venue
SHIFT_GAP_MIN = 90


def load_events(private_dir: Path) -> pd.DataFrame:
    f = private_dir / "live/events.csv"
    if not f.exists():
        return pd.DataFrame(columns=["ts", "type", "lat", "lon", "accuracy_m", "fix_age_s"])
    ev = pd.read_csv(f)
    ev["ts"] = pd.to_datetime(ev.ts, utc=True, format="ISO8601").dt.tz_convert("Europe/Helsinki")
    return ev.drop_duplicates(["ts", "type"]).sort_values("ts").reset_index(drop=True)


def nearest_venue(lat, lon, venues: pd.DataFrame):
    if pd.isna(lat):
        return None, np.nan
    v = venues.dropna(subset=["lat"])
    d = np.array([haversine_m(lat, lon, a, b) for a, b in zip(v.lat, v.lon)])
    i = int(d.argmin())
    return (v.index[i], float(d[i])) if d[i] <= SNAP_RADIUS_M else (None, float(d[i]))


def build_live(private_dir: Path, venues: pd.DataFrame) -> pd.DataFrame:
    """One row per OFFER, in the same core schema as the screenshot history."""
    ev = load_events(private_dir)
    if ev.empty:
        return pd.DataFrame()

    # shift ids: explicit SHIFT_START, or a long silence
    gap = ev.ts.diff().dt.total_seconds() / 60
    new_shift = ev.type.eq("SHIFT_START") | gap.isna() | (gap > SHIFT_GAP_MIN)
    ev["shift_id"] = new_shift.cumsum().map(lambda i: f"a{i:03d}")

    rows = []
    for sid, g in ev.groupby("shift_id", sort=False):
        wait_start, prev_offer = None, None
        for _, e in g.iterrows():
            if e.type in ("SHIFT_START", "FREE"):
                wait_start = e.ts
            elif e.type == "OFFER":
                venue, dist = nearest_venue(e.lat, e.lon, venues)
                rows.append(dict(
                    source="app_log", shift_id=sid, ts=e.ts,
                    venue=venue or "", anchor_venue=venue or "", n_pickups=np.nan, n_deliveries=np.nan,
                    venue_lat=venues.at[venue, "lat"] if venue else np.nan,
                    venue_lon=venues.at[venue, "lon"] if venue else np.nan,
                    venue_area=venues.at[venue, "area"] if venue else "",
                    geocode_quality="gps",
                    courier_lat=e.lat, courier_lon=e.lon,
                    courier_offset_m=round(dist, 1) if venue else np.nan,
                    gps_accuracy_m=e.get("accuracy_m", np.nan),
                    distance_km=np.nan, est_task_min=np.nan,
                    gap_since_prev_min=(e.ts - prev_offer).total_seconds() / 60 if prev_offer is not None else np.nan,
                    wait_min=(e.ts - wait_start).total_seconds() / 60 if wait_start is not None else np.nan,
                    wait_is_estimated=False,
                    pay_eur=np.nan, tip_eur=0.0,
                ))
                prev_offer, wait_start = e.ts, None   # next wait needs a FREE first
            elif e.type == "SHIFT_END":
                wait_start = None
    return pd.DataFrame(rows)

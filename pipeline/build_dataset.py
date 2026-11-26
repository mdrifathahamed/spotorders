"""Build the first training dataset from transcribed Wolt history screenshots.

Inputs
  data/private/orders_raw.csv        one row per task, transcribed from the courier app history
  data/reference/venues.csv          coordinates for every pickup venue (OSM / address / area centroid)
  data/reference/weather_hourly.csv  Open-Meteo hourly weather for the shift hours

  data/private/live/events.csv       one-tap log from the Spotorders app (optional, grows every shift)

Outputs
  data/private/orders_enriched.csv   full table (private data repo: exact times, GPS, earnings)
  data/sample/orders_public.csv      privacy-safe copy for the repo (no pay, no calendar date,
                                     times rounded to 15 min)
  data/sample/hex_training_table.csv aggregated hexagon x time-bucket x weather table

Run:  python -m pipeline.build_dataset
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from .geo import h3_cell, simulate_courier_position
from .live import build_live
from .osm_places import load_layer
from .geo import haversine_m
from .weather import WMO, load_weather, weather_class


def top_name(s):
    vc = s.replace("", None).dropna().value_counts()
    return vc.index[0] if len(vc) else "(no known venue)"

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261126           # fixed so the simulated positions are reproducible
SHIFT_GAP_MIN = 90        # a gap longer than this starts a new shift
BIKE_KMH = 14.0           # average e-bike / bike speed in city traffic
HANDLING_MIN = 6.0        # pickup wait + hand-over per task
EXTRA_DROP_MIN = 4.0      # extra time per additional stacked delivery / pickup


# ---------------------------------------------------------------- helpers
def solar_elevation(ts: pd.Timestamp, lat: float, lon: float) -> float:
    """Approximate solar elevation in degrees (NOAA algorithm, good to ~0.5 deg)."""
    utc = ts.tz_convert("UTC")
    doy = utc.dayofyear
    hour = utc.hour + utc.minute / 60
    g = 2 * math.pi / 365 * (doy - 1 + (hour - 12) / 24)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    tst = hour * 60 + eqt + 4 * lon
    ha = math.radians(tst / 4 - 180)
    la = math.radians(lat)
    cos_z = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    return 90 - math.degrees(math.acos(max(-1, min(1, cos_z))))


def time_bucket(h: int) -> str:
    if 6 <= h < 11:
        return "morning"
    if 11 <= h < 14:
        return "lunch"
    if 14 <= h < 17:
        return "afternoon"
    if 17 <= h < 21:
        return "dinner"
    return "late"


def est_task_minutes(distance_km: float, n_deliveries: int, n_pickups: int) -> float:
    d = 0 if pd.isna(distance_km) else distance_km
    extra = max(0, n_deliveries - 1) + max(0, n_pickups - 1)
    return HANDLING_MIN + d / BIKE_KMH * 60 + EXTRA_DROP_MIN * extra


# ---------------------------------------------------------------- history (screenshots)
def build_history(venues: pd.DataFrame) -> pd.DataFrame:
    raw = pd.read_csv(ROOT / "data/private/orders_raw.csv")
    df = raw.drop_duplicates(["date", "time", "venue"]).copy()
    # "The Grill - Pizza, Kebab & Burger" contains a comma in its own name: protect it before splitting
    grill = "The Grill - Pizza, Kebab & Burger"
    df["pickup_venues"] = df.venue.str.replace(grill, "THE_GRILL", regex=False) \
        .str.split(", ").apply(lambda xs: [grill if x == "THE_GRILL" else x for x in xs])
    df["n_pickups"] = df.pickup_venues.str.len()
    df["ts"] = pd.to_datetime(df.date + " " + df.time).dt.tz_localize("Europe/Helsinki")
    df = df.sort_values("ts").reset_index(drop=True)

    def anchor(vs):  # first listed pickup that has coordinates
        for v in vs:
            if v in venues.index and not pd.isna(venues.at[v, "lat"]):
                return v
        return vs[0]
    df["anchor_venue"] = df.pickup_venues.apply(anchor)
    vinfo = venues.reindex(df.anchor_venue)
    df["venue_lat"], df["venue_lon"] = vinfo.lat.values, vinfo.lon.values
    df["venue_area"], df["geocode_quality"] = vinfo.area.values, vinfo.geocode_quality.values

    rng = np.random.default_rng(SEED)
    sim = [simulate_courier_position(a, b, rng) for a, b in zip(df.venue_lat, df.venue_lon)]
    df[["courier_lat", "courier_lon", "courier_offset_m", "courier_bearing_deg"]] = pd.DataFrame(sim)

    gap = df.ts.diff().dt.total_seconds() / 60
    df["shift_id"] = (gap.isna() | (gap > SHIFT_GAP_MIN)).cumsum().map(lambda i: f"s{i:03d}")
    df["gap_since_prev_min"] = gap.where(df.shift_id.eq(df.shift_id.shift()))
    df["est_task_min"] = [est_task_minutes(d, n, p) for d, n, p in
                          zip(df.distance_km, df.n_deliveries, df.n_pickups)]
    prev_task = df.groupby("shift_id").est_task_min.shift()
    df["wait_min"] = (df.gap_since_prev_min - prev_task).clip(lower=0)
    df["wait_is_estimated"] = True
    df["source"] = "history_screenshots"
    df["pickup_venues"] = df.pickup_venues.str.join(" | ")
    df["gps_accuracy_m"] = np.nan
    return df


# ---------------------------------------------------------------- shared features
def add_features(df: pd.DataFrame, wx: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("ts").reset_index(drop=True)
    df.insert(0, "order_id", [f"o{i:05d}" for i in range(1, len(df) + 1)])
    df["date"] = df.ts.dt.strftime("%Y-%m-%d")
    df["time"] = df.ts.dt.strftime("%H:%M")
    for res in (8, 9):
        df[f"h3_r{res}"] = [h3_cell(a, b, res) for a, b in zip(df.courier_lat, df.courier_lon)]
    df["order_idx_in_shift"] = df.groupby("shift_id").cumcount() + 1
    df["shift_date"] = df.groupby("shift_id").ts.transform("min").dt.strftime("%Y-%m-%d")

    df["weekday"] = df.ts.dt.weekday
    df["weekday_name"] = df.ts.dt.day_name()
    df["is_weekend"] = df.weekday >= 5
    df["is_fri_sat_evening"] = ((df.weekday == 4) | (df.weekday == 5)) & (df.ts.dt.hour >= 17)
    df["hour"] = df.ts.dt.hour
    df["minute_of_day"] = df.ts.dt.hour * 60 + df.ts.dt.minute
    df["hour_sin"] = np.sin(2 * np.pi * df.minute_of_day / 1440)
    df["hour_cos"] = np.cos(2 * np.pi * df.minute_of_day / 1440)
    df["time_bucket"] = df.hour.map(time_bucket)
    start = pd.Timestamp("2026-09-01", tz="Europe/Helsinki")
    df["week_index"] = ((df.ts - start).dt.days // 7) + 1
    df["sun_elevation_deg"] = [solar_elevation(t, 60.19, 24.96) for t in df.ts]
    df["is_dark"] = df.sun_elevation_deg < -0.833

    df = df.merge(wx, how="left", on=["date", "hour"])
    df["weather_label"] = df.weather_code.map(WMO)
    df["weather_class"] = [weather_class(c, t) if not pd.isna(c) else None
                           for c, t in zip(df.weather_code, df.temp_c)]
    df["is_precip"] = df.precip_mm > 0
    wx_idx = wx.set_index(["date", "hour"]).precip_mm
    def prev_precip(d, h):
        vals = [wx_idx.get((d, hh), np.nan) for hh in (h - 1, h - 2) if hh >= 0]
        return float(np.nansum(vals)) if vals else np.nan
    df["precip_prev2h_mm"] = [prev_precip(d, h) for d, h in zip(df.date, df.hour)]

    df["total_eur"] = df.pay_eur + df.tip_eur.fillna(0)
    df["eur_per_km"] = (df.pay_eur / df.distance_km).round(2)
    return df


def add_osm_layer(df: pd.DataFrame) -> pd.DataFrame:
    """Second layer: open food places around the courier at that weekday and hour, and the nearest cluster."""
    tab, cl, _ = load_layer()
    if tab is None:
        return df
    t = tab.rename(columns={"n_total": "food_places_hex", "open_est": "food_open_est", "food_score": "food_score",
                            "n_wolt_venues": "wolt_venues_hex"})[
        ["h3_r8", "weekday", "hour", "food_places_hex", "food_open_est", "food_score", "wolt_venues_hex"]]
    df = df.merge(t, how="left", on=["h3_r8", "weekday", "hour"])
    for c in ["food_places_hex", "food_open_est", "food_score", "wolt_venues_hex"]:
        df[c] = df[c].where(df.h3_r8.isna(), df[c].fillna(0))   # hexagon with no OSM food places -> 0
    if cl is not None and len(cl):
        def nearest(lat, lon):
            if pd.isna(lat):
                return (np.nan, None, np.nan)
            d = [haversine_m(lat, lon, a, b) for a, b in zip(cl.lat, cl.lon)]
            i = int(np.argmin(d))
            return (round(d[i]), cl.label.iat[i], int(cl.n_places.iat[i]))
        near = [nearest(a, b) for a, b in zip(df.courier_lat, df.courier_lon)]
        df["nearest_cluster_m"] = [x[0] for x in near]
        df["nearest_cluster"] = [x[1] for x in near]
        df["nearest_cluster_places"] = [x[2] for x in near]
    return df


COLS = ["order_id", "source", "shift_id", "shift_date", "order_idx_in_shift", "ts", "date", "time",
        "weekday", "weekday_name", "is_weekend", "is_fri_sat_evening", "hour", "minute_of_day",
        "hour_sin", "hour_cos", "time_bucket", "week_index", "sun_elevation_deg", "is_dark",
        "venue", "pickup_venues", "n_pickups", "n_deliveries", "anchor_venue", "venue_area",
        "geocode_quality", "venue_lat", "venue_lon", "courier_lat", "courier_lon",
        "courier_offset_m", "courier_bearing_deg", "gps_accuracy_m", "h3_r8", "h3_r9",
        "distance_km", "gap_since_prev_min", "est_task_min", "wait_min", "wait_is_estimated",
        "temp_c", "apparent_temp_c", "precip_mm", "rain_mm", "snowfall_cm", "precip_prev2h_mm",
        "wind_kmh", "rel_humidity", "cloud_cover", "weather_code", "weather_label",
        "weather_class", "is_precip",
        "food_places_hex", "food_open_est", "food_score", "wolt_venues_hex",
        "nearest_cluster", "nearest_cluster_m", "nearest_cluster_places", "pay_eur", "tip_eur", "total_eur", "eur_per_km"]


def build() -> pd.DataFrame:
    venues = pd.read_csv(ROOT / "data/reference/venues.csv").set_index("venue")
    parts = [build_history(venues)]
    live = build_live(ROOT / "data/private", venues)
    if not live.empty:
        parts.append(live)
    core = pd.concat(parts, ignore_index=True)
    wx = load_weather(ROOT, core.ts)
    df = add_osm_layer(add_features(core, wx)).reindex(columns=COLS)
    for c in ["courier_lat", "courier_lon", "venue_lat", "venue_lon"]:
        df[c] = df[c].round(6)
    for c in ["courier_offset_m", "courier_bearing_deg", "sun_elevation_deg", "hour_sin", "hour_cos",
              "gap_since_prev_min", "est_task_min", "wait_min"]:
        df[c] = df[c].astype(float).round(2)
    return df


def public_copy(df: pd.DataFrame) -> pd.DataFrame:
    """Repo-safe version: no earnings, no calendar date, times rounded to 15 minutes,
    no exact courier coordinates (app rows are real GPS) - only H3 cells."""
    p = df.copy()
    t = p.ts.dt.floor("15min")
    p["time_15min"] = t.dt.strftime("%H:%M")
    drop = ["ts", "date", "time", "shift_date", "pay_eur", "tip_eur", "total_eur", "eur_per_km",
            "minute_of_day", "hour_sin", "hour_cos", "courier_lat", "courier_lon",
            "courier_offset_m", "courier_bearing_deg", "gps_accuracy_m"]
    p = p.drop(columns=drop)
    front = ["order_id", "shift_id", "week_index", "weekday", "weekday_name", "time_15min"]
    return p[front + [c for c in p.columns if c not in front]]


def hex_table(df: pd.DataFrame) -> pd.DataFrame:
    g = df.dropna(subset=["h3_r8"]).assign(day_type=lambda d: np.where(d.is_weekend, "weekend", "weekday"))
    out = (g.groupby(["h3_r8", "time_bucket", "day_type", "weather_class"])
             .agg(n_orders=("order_id", "size"),
                  n_shifts=("shift_id", "nunique"),
                  median_wait_min=("wait_min", "median"),
                  mean_distance_km=("distance_km", "mean"),
                  top_venue=("anchor_venue", top_name))
             .reset_index())
    import h3
    out[["hex_lat", "hex_lon"]] = [h3.cell_to_latlng(c) for c in out.h3_r8]
    return out.round(3).sort_values("n_orders", ascending=False)


def main():
    df = build()
    (ROOT / "data/private").mkdir(parents=True, exist_ok=True)
    (ROOT / "data/sample").mkdir(parents=True, exist_ok=True)
    df.to_csv(ROOT / "data/private/orders_enriched.csv", index=False)
    public_copy(df).to_csv(ROOT / "data/sample/orders_public.csv", index=False)
    hex_table(df).to_csv(ROOT / "data/sample/hex_training_table.csv", index=False)
    print(f"{len(df)} tasks ({(df.source == 'app_log').sum()} from the app), {df.shift_id.nunique()} shifts, "
          f"{df.courier_lat.notna().sum()} with simulated position, "
          f"{df.temp_c.notna().sum()} with weather")


if __name__ == "__main__":
    main()

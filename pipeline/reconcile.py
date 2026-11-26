"""Merge the courier-history screenshot with the app's button presses for the same day.

The screenshot is the record of *what* happened: every task, its venue(s), the minute it
was accepted, distance and pay, stacked orders included. The buttons and the GPS track
are the record of *where* I was and *when* I became free. Pressing O exactly on time is
hard on a bike, so the screenshot time replaces the O press:

  - each screenshot task is matched to the first O press from 1 min before to 10 min after it;
  - an O press with no task (a double tap or a mistaken press) is dropped;
  - the wait is measured from the last D (or Start shift) between the previous task and this
    one to the screenshot time; if no D falls in between, the task was accepted while still
    delivering the previous one (chained or stacked), and the wait is 0;
  - the courier position is the GPS fix nearest to the screenshot time (within 3 min),
    otherwise the GPS of the O press.

Days without a screenshot keep the app rows as they are; days without app presses keep the
estimated waits from the screenshot alone.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .geo import haversine_m
from .live import load_events
from .track import load_track

MATCH_BEFORE = pd.Timedelta(minutes=1)
MATCH_AFTER = pd.Timedelta(minutes=10)
FIX_WINDOW = pd.Timedelta(minutes=3)


def reconcile(hist: pd.DataFrame, private_dir: Path):
    """Returns (updated history rows, set of reconciled dates, per-press report)."""
    ev = load_events(private_dir)
    if ev.empty or hist.empty:
        return hist, set(), pd.DataFrame()
    track = load_track(private_dir)
    hist = hist.copy()
    hist["press_lag_min"] = np.nan
    hist["chained"] = False
    ev["date"] = ev.ts.dt.date
    days = sorted(set(hist.ts.dt.date) & set(ev.loc[ev.type.isin(["OFFER", "EXTRA"]), "date"]))
    report = []

    for day in days:
        tasks = hist[hist.ts.dt.date.eq(day)].sort_values("ts")
        de = ev[ev.date.eq(day)]
        offers = de[de.type.isin(["OFFER", "EXTRA"])].drop_duplicates("ts")
        marks = de[de.type.isin(["FREE", "SHIFT_START", "SHIFT_END"])]
        used = set()
        prev_ts = None
        for i, t in tasks.iterrows():
            ts = t.ts
            cand = offers[(offers.ts >= ts - MATCH_BEFORE) & (offers.ts <= ts + MATCH_AFTER) & ~offers.index.isin(used)]
            press = cand.iloc[0] if len(cand) else None
            if press is not None:
                used.add(press.name)

            lo = prev_ts if prev_ts is not None else ts - pd.Timedelta(hours=12)
            m = marks[(marks.ts > lo) & (marks.ts <= ts + pd.Timedelta(seconds=59))]
            chained = False
            if len(m) and m.type.iloc[-1] in ("FREE", "SHIFT_START"):
                wait = max(0.0, (ts - m.ts.iloc[-1]).total_seconds() / 60)
            elif len(m):                     # last mark is Shift end: no wait to measure
                wait = np.nan
            elif prev_ts is not None:        # no D since the previous task: chained / stacked
                wait, chained = 0.0, True
            else:
                wait = np.nan

            pos_src, lat, lon, acc = "simulated", t.courier_lat, t.courier_lon, np.nan
            if not track.empty:
                dt = (track.ts - ts).abs()
                j = dt.idxmin()
                if dt[j] <= FIX_WINDOW:
                    pos_src, lat, lon, acc = "track", track.lat[j], track.lon[j], track.accuracy_m[j]
            if pos_src == "simulated" and press is not None and not pd.isna(press.lat):
                pos_src, lat, lon, acc = "o_press", press.lat, press.lon, press.accuracy_m

            hist.loc[i, ["wait_min", "wait_is_estimated", "source", "chained"]] = \
                [wait, bool(np.isnan(wait)), "screenshot+app", chained]
            if press is not None:
                hist.loc[i, "press_lag_min"] = round((press.ts - ts).total_seconds() / 60, 2)
            if pos_src != "simulated":
                hist.loc[i, ["courier_lat", "courier_lon", "gps_accuracy_m", "geocode_quality"]] = \
                    [lat, lon, acc, "gps"]
                hist.loc[i, "courier_offset_m"] = round(haversine_m(lat, lon, t.venue_lat, t.venue_lon), 1) \
                    if not pd.isna(t.venue_lat) else np.nan
                hist.loc[i, "courier_bearing_deg"] = np.nan
            report.append(dict(date=day, task_time=ts.strftime("%H:%M"), venue=t.venue,
                               o_press=press.ts.strftime("%H:%M:%S") if press is not None else "",
                               press_lag_min=hist.at[i, "press_lag_min"], wait_min=round(wait, 2) if not np.isnan(wait) else np.nan,
                               chained=chained, position=pos_src))
            prev_ts = ts
        for _, o in offers[~offers.index.isin(used)].iterrows():
            report.append(dict(date=day, task_time="", venue="(no task: dropped)",
                               o_press=o.ts.strftime("%H:%M:%S"), press_lag_min=np.nan, wait_min=np.nan,
                               chained=False, position=""))
    rep = pd.DataFrame(report)
    if len(rep):
        rep = rep.sort_values(["date", "o_press", "task_time"]).reset_index(drop=True)
    return hist, set(days), rep

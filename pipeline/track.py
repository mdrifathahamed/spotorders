"""Turn the app's GPS track into stays (standing still) and moves (riding).

Input (private data repo, checked out at data/private/):
  live/track/YYYY-MM-DD.csv   app v10+: a fix every 15 s, columns ts, lat, lon, accuracy_m,
                              speed_mps, bearing_deg, state (WAITING or DELIVERING)
  live/fixes/YYYY-MM-DD.csv   older app versions: ts, lat, lon, accuracy_m, speed_mps
  live/events.csv             button presses, used to tell whether a stay ended with an order

Stay points follow the usual rule for GPS trajectories (Li et al. 2008): consecutive fixes
that stay within STAY_RADIUS_M of the first fix for at least STAY_MIN_S form one stay; the
fixes between two stays form a move.

Output, private only (exact positions and times):
  data/private/derived/track_points.csv   every fix with shift, segment and speed
  data/private/derived/stays.csv          one row per stay: where, when, how long, did an order follow
  data/private/derived/moves.csv          one row per move: from, to, distance, speed
Output, public:
  data/sample/track_summary.json          counts only (hours tracked, stays, moves)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .geo import h3_cell

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "data/private"
TZ = "Europe/Helsinki"

MAX_ACCURACY_M = 50      # fixes less precise than this are dropped
MAX_SPEED_MPS = 15       # ~54 km/h: faster jumps are GPS glitches on an e-bike
STAY_RADIUS_M = 50
STAY_MIN_S = 180         # 3 minutes
SHIFT_GAP_MIN = 30       # a silence this long starts a new tracking session
OFFER_LINK_S = 120       # an OFFER up to 2 min after a stay ends counts as ending it


def _hav(lat1, lon1, lat2, lon2):
    r = 6_371_000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def load_track(private_dir: Path = PRIVATE) -> pd.DataFrame:
    frames = []
    for sub in ("fixes", "track"):
        for f in sorted((private_dir / "live" / sub).glob("*.csv")):
            d = pd.read_csv(f)
            if d.empty:
                continue
            d["source_file"] = f"{sub}/{f.name}"
            frames.append(d)
    if not frames:
        return pd.DataFrame(columns=["ts", "lat", "lon", "accuracy_m", "speed_mps", "bearing_deg", "state"])
    t = pd.concat(frames, ignore_index=True)
    for c, default in (("bearing_deg", np.nan), ("state", "WAITING")):
        if c not in t:
            t[c] = default
    t["state"] = t.state.fillna("WAITING")
    t["ts"] = pd.to_datetime(t.ts, utc=True, format="ISO8601").dt.tz_convert(TZ)
    t = (t.dropna(subset=["lat", "lon"])
          .query("accuracy_m <= @MAX_ACCURACY_M")
          .drop_duplicates("ts").sort_values("ts").reset_index(drop=True))
    return t


def clean(t: pd.DataFrame) -> pd.DataFrame:
    """Session ids, step distance and speed; drop impossible jumps."""
    if t.empty:
        return t
    keep = np.ones(len(t), bool)
    last = 0
    for i in range(1, len(t)):            # drop a fix that implies > MAX_SPEED from the last kept one
        dt = (t.ts.iat[i] - t.ts.iat[last]).total_seconds()
        d = _hav(t.lat.iat[last], t.lon.iat[last], t.lat.iat[i], t.lon.iat[i])
        if dt > 0 and d / dt > MAX_SPEED_MPS and dt < SHIFT_GAP_MIN * 60:
            keep[i] = False
        else:
            last = i
    t = t[keep].reset_index(drop=True)
    gap = t.ts.diff().dt.total_seconds()
    t["session_id"] = (gap.isna() | (gap > SHIFT_GAP_MIN * 60)).cumsum().map(lambda i: f"t{i:03d}")
    step = _hav(t.lat.shift(), t.lon.shift(), t.lat, t.lon)
    same = t.session_id.eq(t.session_id.shift())
    t["step_m"] = np.where(same, step, 0.0)
    t["step_s"] = np.where(same, gap, 0.0)
    t["speed_calc_mps"] = np.where(t.step_s > 0, t.step_m / t.step_s.replace(0, np.nan), np.nan)
    return t


def stay_points(t: pd.DataFrame) -> pd.DataFrame:
    """Label each fix as part of a stay (segment 'stay') or a move."""
    t = t.copy()
    t["segment"] = "move"
    t["stay_id"] = ""
    n_stay = 0
    for _, g in t.groupby("session_id", sort=False):
        idx = g.index.to_numpy()
        lat, lon, ts = g.lat.to_numpy(), g.lon.to_numpy(), g.ts.to_numpy()
        i = 0
        while i < len(idx):
            j = i + 1
            while j < len(idx) and _hav(lat[i], lon[i], lat[j], lon[j]) <= STAY_RADIUS_M:
                j += 1
            dur = (ts[j - 1] - ts[i]) / np.timedelta64(1, "s")
            if dur >= STAY_MIN_S:
                n_stay += 1
                t.loc[idx[i:j], ["segment", "stay_id"]] = ["stay", f"s{n_stay:04d}"]
                i = j
            else:
                i += 1
    # moves: runs of non-stay fixes inside a session
    is_move = t.segment.eq("move")
    run = (is_move != is_move.shift()) | t.session_id.ne(t.session_id.shift())
    t["move_id"] = np.where(is_move, "m" + run.cumsum().astype(str).str.zfill(4), "")
    return t


def _offers(private_dir: Path) -> pd.Series:
    f = private_dir / "live/events.csv"
    if not f.exists():
        return pd.Series([], dtype="datetime64[ns, Europe/Helsinki]")
    ev = pd.read_csv(f)
    ev["ts"] = pd.to_datetime(ev.ts, utc=True, format="ISO8601").dt.tz_convert(TZ)
    return ev.loc[ev.type.eq("OFFER"), "ts"].sort_values().reset_index(drop=True)


def summarise(t: pd.DataFrame, offers: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    from .build_dataset import time_bucket

    stays = []
    for sid, g in t[t.segment.eq("stay")].groupby("stay_id", sort=False):
        start, end = g.ts.iloc[0], g.ts.iloc[-1]
        lat, lon = g.lat.median(), g.lon.median()
        nxt = offers[(offers >= start) & (offers <= end + pd.Timedelta(seconds=OFFER_LINK_S))]
        stays.append(dict(
            stay_id=sid, session_id=g.session_id.iloc[0], start=start, end=end,
            duration_min=round((end - start).total_seconds() / 60, 2),
            lat=round(lat, 6), lon=round(lon, 6),
            h3_r8=h3_cell(lat, lon, 8), h3_r9=h3_cell(lat, lon, 9),
            state=g.state.mode().iat[0], n_fixes=len(g),
            radius_m=round(float(_hav(lat, lon, g.lat, g.lon).max()), 1),
            weekday=start.day_name(), hour=start.hour, time_bucket=time_bucket(start.hour),
            ended_by_offer=len(nxt) > 0,
            offer_ts=nxt.iloc[0] if len(nxt) else pd.NaT,
        ))
    stays = pd.DataFrame(stays)

    moves = []
    for mid, g in t[t.segment.eq("move")].groupby("move_id", sort=False):
        if len(g) < 2:
            continue
        start, end = g.ts.iloc[0], g.ts.iloc[-1]
        dist = float(g.step_m.iloc[1:].sum())
        dur = (end - start).total_seconds()
        moves.append(dict(
            move_id=mid, session_id=g.session_id.iloc[0], start=start, end=end,
            duration_min=round(dur / 60, 2), distance_m=round(dist, 1),
            mean_speed_kmh=round(dist / dur * 3.6, 1) if dur > 0 else np.nan,
            from_lat=g.lat.iloc[0], from_lon=g.lon.iloc[0], to_lat=g.lat.iloc[-1], to_lon=g.lon.iloc[-1],
            from_h3_r8=h3_cell(g.lat.iloc[0], g.lon.iloc[0], 8), to_h3_r8=h3_cell(g.lat.iloc[-1], g.lon.iloc[-1], 8),
            state=g.state.mode().iat[0], n_fixes=len(g),
        ))
    return stays, pd.DataFrame(moves)


def main():
    t = load_track()
    out = PRIVATE / "derived"
    summary = dict(points=0, hours_tracked=0.0, stays=0, waiting_stays=0, stays_ended_by_offer=0, moves=0,
                   km_ridden=0.0)
    if not t.empty:
        t = stay_points(clean(t))
        stays, moves = summarise(t, _offers(PRIVATE))
        out.mkdir(parents=True, exist_ok=True)
        cols = ["ts", "session_id", "lat", "lon", "accuracy_m", "speed_mps", "speed_calc_mps", "bearing_deg",
                "state", "segment", "stay_id", "move_id", "step_m", "step_s"]
        t[cols].to_csv(out / "track_points.csv", index=False)
        stays.to_csv(out / "stays.csv", index=False)
        moves.to_csv(out / "moves.csv", index=False)
        summary.update(
            points=int(len(t)),
            hours_tracked=round(float(t.groupby("session_id").ts.agg(lambda s: (s.max() - s.min()).total_seconds()).sum()) / 3600, 1),
            stays=int(len(stays)),
            waiting_stays=int(stays.state.eq("WAITING").sum()) if len(stays) else 0,
            stays_ended_by_offer=int(stays.ended_by_offer.sum()) if len(stays) else 0,
            moves=int(len(moves)),
            km_ridden=round(float(moves.distance_m.sum()) / 1000, 1) if len(moves) else 0.0,
        )
    (ROOT / "data/sample").mkdir(parents=True, exist_ok=True)
    (ROOT / "data/sample/track_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("track:", summary)


if __name__ == "__main__":
    main()

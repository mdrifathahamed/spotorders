# Data dictionary

One row = one task offer accepted in the courier app. A task can contain several pickups
(`n_pickups`) and several deliveries (`n_deliveries`).

## App log (private data repo)

`live/events.csv`: `ts, type, lat, lon, accuracy_m, fix_age_s`, one line per button press
(`SHIFT_START`, `OFFER`, `FREE`, `SHIFT_END`). `live/fixes/YYYY-MM-DD.csv`: GPS track,
`ts, lat, lon, accuracy_m, speed_mps`.

## orders_enriched.csv (private) / orders_public.csv (public)

| column | type | meaning |
|---|---|---|
| order_id | str | running id in time order |
| source | str | `history_screenshots` (transcribed) or `app_log` (button presses in the app) |
| shift_id | str | new shift when the gap to the previous task is > 90 min |
| shift_date | date | date the shift started (a 00:10 task belongs to the previous evening) · *private* |
| order_idx_in_shift | int | 1 = first task of the shift |
| ts, date, time | datetime | timestamp shown in the courier history (Europe/Helsinki) · *private* |
| time_15min | HH:MM | timestamp floored to 15 min · *public only* |
| week_index | int | 1 = first week of data |
| weekday, weekday_name | int, str | 0 = Monday |
| is_weekend | bool | Saturday or Sunday |
| is_fri_sat_evening | bool | Friday or Saturday, 17:00 or later |
| hour, minute_of_day | int | local time |
| hour_sin, hour_cos | float | cyclic encoding of minute_of_day · *private* |
| time_bucket | str | morning 06–11, lunch 11–14, afternoon 14–17, dinner 17–21, late 21–06 |
| sun_elevation_deg, is_dark | float, bool | solar elevation at the task time; dark = below −0.833° |
| venue | str | pickup venue(s) as listed in the app |
| pickup_venues | str | pickups separated by " \| " |
| n_pickups, n_deliveries | int | stacked tasks have more than 1 |
| anchor_venue | str | history: first pickup with coordinates · app: nearest known venue within 100 m (empty if none) |
| venue_area | str | district of the anchor venue |
| geocode_quality | str | `osm` OpenStreetMap feature · `address` street address · `mall` shopping centre location · `area` district centroid · `unknown` not placed · `gps` app row |
| venue_lat, venue_lon | float | anchor venue coordinates (WGS84) |
| courier_lat, courier_lon | float | history: **simulated** 20–50 m from the venue · app: real GPS at the tap · *private* |
| courier_offset_m | float | history: the random offset · app: distance to the matched venue · *private* |
| courier_bearing_deg | float | history only: random bearing · *private* |
| gps_accuracy_m | float | app only: GPS accuracy of the fix · *private* |
| h3_r8, h3_r9 | str | H3 cell of the courier position (res 8 ≈ 0.74 km², res 9 ≈ 0.11 km²) |
| distance_km | float | task distance shown in the app |
| gap_since_prev_min | float | minutes since the previous task in the same shift |
| est_task_min | float | estimated duration of this task: 6 + distance/14 km/h + 4 per extra stop |
| wait_min | float | **Main target.** App: measured, from the last *Free again* (or *Start shift*) to *Got order*. History: estimated as gap_since_prev_min − previous task's est_task_min, floored at 0 |
| wait_is_estimated | bool | True for history rows |
| temp_c, apparent_temp_c | float | air and feels-like temperature, °C |
| precip_mm, rain_mm, snowfall_cm | float | in the task's hour |
| precip_prev2h_mm | float | precipitation in the two hours before |
| wind_kmh, rel_humidity, cloud_cover | float | |
| weather_code, weather_label | int, str | WMO code and label |
| weather_class | str | dry / wet / snow / cold_dry |
| is_precip | bool | precip_mm > 0 |
| food_places_hex | int | OpenStreetMap food places in the courier's H3 res-8 hexagon |
| food_open_est | float | expected number of them open at that weekday and hour (opening_hours; untagged places at the city-wide open share) |
| food_score | float | open places weighted by type (fast food 1.5 … bakery 0.5) and x3 for venues I have picked up from |
| wolt_venues_hex | int | OSM places in the hexagon matched (≤60 m) to venues I have picked up from |
| nearest_cluster, nearest_cluster_m, nearest_cluster_places | str, float, int | nearest restaurant cluster (DBSCAN 120 m, ≥5 places): name, distance from the courier, size |
| pay_eur, tip_eur, total_eur, eur_per_km | float | earnings · *private* |

## hex_training_table.csv

Grouped by `h3_r8 × time_bucket × day_type × weather_class`: `n_orders`, `n_shifts`,
`median_wait_min`, `mean_distance_km`, `top_venue`, hexagon centre.

## spot_ranking.csv

Per `h3_r8 × time_bucket`: `smoothed_wait_min = (sum_wait + 4·prior) / (n + 4)`, where the prior is the
average wait in that time bucket. Lower is better. `rank_in_bucket` 1 = best.

## Restaurant layer (data/reference, OpenStreetMap © contributors, ODbL)

- `osm_food_places.csv`: one row per place, with `kind`, `opening_hours`, `hours_known`, `wolt_venue`, `weight`, `cluster_id`, H3 cells
- `osm_open_hex.csv`: `h3_r8 × weekday × hour` with `n_total, n_hours_known, n_wolt_venues, n_open_known, open_est, food_score`
- `osm_clusters.csv`: cluster label, size, matched Wolt venues, summed weight, centre


## Route track (private: `spotorders-data/derived/`)

Built by `pipeline/track.py` from `live/track/*.csv` (app v10+, a fix every 15 s) and `live/fixes/*.csv` (older versions).

**`track_points.csv`**: one row per GPS fix: `ts`, `session_id`, `lat`, `lon`, `accuracy_m` (fixes worse than 50 m dropped), `speed_mps` (phone), `speed_calc_mps` (from consecutive fixes), `bearing_deg`, `state` (`WAITING` or `DELIVERING`), `segment` (`stay` or `move`), `stay_id`, `move_id`, `step_m`, `step_s`.

**`stays.csv`**: one row per stay (≥3 min within 50 m): `stay_id`, `session_id`, `start`, `end`, `duration_min`, `lat`, `lon` (median), `h3_r8`, `h3_r9`, `state`, `n_fixes`, `radius_m`, `weekday`, `hour`, `time_bucket`, `ended_by_offer` (an OFFER within the stay or up to 2 min after it), `offer_ts`.

**`moves.csv`**: one row per move between stays: `move_id`, `session_id`, `start`, `end`, `duration_min`, `distance_m`, `mean_speed_kmh`, `from_lat/lon`, `to_lat/lon`, `from_h3_r8`, `to_h3_r8`, `state`, `n_fixes`.

Public: `data/sample/track_summary.json` holds counts only (points, hours tracked, stays, moves, km ridden).

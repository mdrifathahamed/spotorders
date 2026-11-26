"""Hourly weather from Open-Meteo (free, no API key).

`fetch_hourly()` downloads fresh data when run on a machine with internet access.
The repository already ships the hours needed for the first dataset in
`data/reference/weather_hourly.csv` (Helsinki 60.19 N, 24.96 E, local time).
"""
from __future__ import annotations

import pandas as pd

VARS = ["temperature_2m", "apparent_temperature", "precipitation", "rain", "snowfall",
        "wind_speed_10m", "weather_code", "relative_humidity_2m", "cloud_cover"]

RENAME = {"temperature_2m": "temp_c", "apparent_temperature": "apparent_temp_c",
          "precipitation": "precip_mm", "rain": "rain_mm", "snowfall": "snowfall_cm",
          "wind_speed_10m": "wind_kmh", "relative_humidity_2m": "rel_humidity",
          "cloud_cover": "cloud_cover", "weather_code": "weather_code"}

# WMO weather interpretation codes -> short label
WMO = {0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
       51: "light drizzle", 53: "drizzle", 55: "dense drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
       61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "rain showers",
       81: "rain showers", 82: "violent showers", 85: "snow showers", 86: "snow showers",
       95: "thunderstorm", 96: "thunderstorm+hail", 99: "thunderstorm+hail"}


def weather_class(code: int, temp_c: float) -> str:
    """Coarse class used as a model feature: dry / wet / snow / cold_dry."""
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code >= 51:
        return "wet"
    if temp_c is not None and temp_c <= 0:
        return "cold_dry"
    return "dry"


def fetch_hourly(start: str, end: str, lat=60.19, lon=24.96, tz="Europe/Helsinki") -> pd.DataFrame:
    import requests  # imported lazily so the offline pipeline has no network dependency

    url = "https://archive-api.open-meteo.com/v1/archive"
    params = dict(latitude=lat, longitude=lon, start_date=start, end_date=end,
                  hourly=",".join(VARS), timezone=tz)
    js = requests.get(url, params=params, timeout=60).json()
    df = pd.DataFrame(js["hourly"]).rename(columns=RENAME)
    t = pd.to_datetime(df.pop("time"))
    df.insert(0, "date", t.dt.strftime("%Y-%m-%d"))
    df.insert(1, "hour", t.dt.hour)
    return df

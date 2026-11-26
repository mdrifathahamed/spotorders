"""Geometry helpers: courier-position simulation and H3 indexing."""
from __future__ import annotations

import math

import h3
import numpy as np

EARTH_R = 6_371_008.8  # metres


def offset_point(lat: float, lon: float, dist_m: float, bearing_deg: float) -> tuple[float, float]:
    """Move a point `dist_m` metres along `bearing_deg` (great-circle)."""
    phi1, lam1 = math.radians(lat), math.radians(lon)
    theta, delta = math.radians(bearing_deg), dist_m / EARTH_R
    phi2 = math.asin(math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta))
    lam2 = lam1 + math.atan2(math.sin(theta) * math.sin(delta) * math.cos(phi1),
                             math.cos(delta) - math.sin(phi1) * math.sin(phi2))
    return math.degrees(phi2), math.degrees(lam2)


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def simulate_courier_position(lat, lon, rng: np.random.Generator, min_m=20.0, max_m=50.0):
    """Courier is assumed to be waiting 20–50 m from the pickup venue when the offer arrives.

    Distance is drawn uniformly over the annulus *area* (so points are not clumped
    near the inner ring) and bearing uniformly in [0, 360).
    Returns (lat, lon, dist_m, bearing_deg) or NaNs when the venue is not geocoded.
    """
    if lat is None or lon is None or (isinstance(lat, float) and math.isnan(lat)):
        return (np.nan, np.nan, np.nan, np.nan)
    r = math.sqrt(rng.uniform(min_m ** 2, max_m ** 2))
    b = rng.uniform(0, 360)
    la, lo = offset_point(lat, lon, r, b)
    return (la, lo, r, b)


def h3_cell(lat, lon, res: int):
    if lat is None or (isinstance(lat, float) and math.isnan(lat)):
        return None
    return h3.latlng_to_cell(lat, lon, res)

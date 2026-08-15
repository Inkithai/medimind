"""Shared geographic helpers for care-directory providers."""

import math


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle (haversine) distance between two WGS84 points, in km."""
    radius = 6371.0
    to_radians = math.pi / 180
    delta_lat = (lat2 - lat1) * to_radians
    delta_lon = (lon2 - lon1) * to_radians
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1 * to_radians)
        * math.cos(lat2 * to_radians)
        * math.sin(delta_lon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))

import math
from statistics import stdev
from typing import Iterable, Optional, Sequence


def calculate_jitter(rtts):
    if rtts and len(rtts) > 1:
        return stdev(rtts)
    return 0.0


def is_outlier(value, values, factor=2):
    valid = [v for v in values if v is not None]
    if not valid:
        return False
    avg = sum(valid) / len(valid)
    return value is not None and value > avg * factor


def geo_anomaly_check(dist1, lat1, dist2, lat2, margin=50):
    if dist1 is None or lat1 is None or dist2 is None or lat2 is None:
        return False
    if dist1 > dist2 and lat1 < lat2 - margin:
        return True
    return False


def calculate_distance_km(
    lat1: Optional[float],
    lon1: Optional[float],
    lat2: Optional[float],
    lon2: Optional[float],
) -> Optional[float]:
    """Calculate great-circle Haversine distance in kilometers between two coordinates."""
    if any(v is None for v in (lat1, lon1, lat2, lon2)):
        return None
    radius_km = 6371.0
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return radius_km * c


def calculate_jaccard_similarity(
    hops1: Optional[Iterable[str]], hops2: Optional[Iterable[str]]
) -> float:
    """Compute Jaccard similarity |A ∩ B| / |A ∪ B| between two hop IP sequences."""
    set1 = {h for h in (hops1 or []) if h and h != "*"}
    set2 = {h for h in (hops2 or []) if h and h != "*"}
    if not set1 and not set2:
        return 1.0
    union = set1 | set2
    if not union:
        return 1.0
    return len(set1 & set2) / len(union)


def calculate_percentile(
    values: Sequence[float], percentile: float
) -> Optional[float]:
    """Calculate linear-interpolated percentile (0-100) without external dependencies."""
    valid = sorted(float(v) for v in values if v is not None)
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    rank = (percentile / 100.0) * (len(valid) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return valid[lower]
    fraction = rank - lower
    return valid[lower] + fraction * (valid[upper] - valid[lower])

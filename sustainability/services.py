import math
import re
from dataclasses import dataclass


@dataclass
class PostcodeDistance:
    from_postcode: str
    to_postcode: str
    distance_km: float
    distance_miles: float
    estimated: bool


OUTWARD_CODE_CENTROIDS = {
    "SW1A": (51.5010, -0.1416),
    "EC1A": (51.5202, -0.0971),
    "M1": (53.4794, -2.2453),
    "B1": (52.4793, -1.9025),
    "LS1": (53.7970, -1.5486),
    "L1": (53.4020, -2.9790),
    "G1": (55.8609, -4.2514),
    "CF10": (51.4816, -3.1791),
    "EH1": (55.9533, -3.1883),
    "BS1": (51.4545, -2.5879),
    "NE1": (54.9783, -1.6178),
    "NG1": (52.9548, -1.1581),
    "S1": (53.3811, -1.4701),
    "OX1": (51.7520, -1.2577),
    "CB1": (52.2053, 0.1218),
}


def _normalize_postcode(postcode: str) -> str:
    value = (postcode or "").strip().upper()
    value = re.sub(r"[^A-Z0-9]", "", value)
    return value


def _outward_code(postcode: str) -> str:
    compact = _normalize_postcode(postcode)
    if len(compact) < 3:
        return compact
    return compact[:-3]


def _fallback_lat_lng_from_outward(outward_code: str) -> tuple[float, float]:
    if not outward_code:
        return (54.0, -2.0)
    seed = sum(ord(ch) for ch in outward_code)
    lat = 50.5 + (seed % 600) / 100.0
    lng = -6.0 + (seed % 700) / 100.0
    return (min(58.5, lat), min(1.8, max(-8.5, lng)))


def _postcode_to_lat_lng(postcode: str) -> tuple[tuple[float, float], bool]:
    outward = _outward_code(postcode)
    if outward in OUTWARD_CODE_CENTROIDS:
        return OUTWARD_CODE_CENTROIDS[outward], False
    return _fallback_lat_lng_from_outward(outward), True


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return radius_km * c


def calculate_postcode_distance(from_postcode: str, to_postcode: str) -> PostcodeDistance:
    from_coord, from_estimated = _postcode_to_lat_lng(from_postcode)
    to_coord, to_estimated = _postcode_to_lat_lng(to_postcode)
    km = _haversine_km(from_coord[0], from_coord[1], to_coord[0], to_coord[1])
    miles = km * 0.621371
    return PostcodeDistance(
        from_postcode=_normalize_postcode(from_postcode),
        to_postcode=_normalize_postcode(to_postcode),
        distance_km=round(km, 2),
        distance_miles=round(miles, 2),
        estimated=from_estimated or to_estimated,
    )

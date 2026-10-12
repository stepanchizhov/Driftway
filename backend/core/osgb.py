"""
Ordnance Survey National Grid (OSGB36) to WGS84 latitude and longitude.

Used for National Trust trail starts (grid references like "SU9968973089")
and for Street Manager roadworks (easting and northing in metres). Airy 1830
transverse Mercator, then the standard OSGB36-to-WGS84 Helmert transform:
good to a few metres, checked against the Ordnance Survey's worked example.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple


def en_to_wgs84(E: float, N: float) -> Tuple[float, float]:
    """Easting and northing in metres to (lat, lng)."""
    a, b, F0 = 6377563.396, 6356256.909, 0.9996012717
    lat0, lon0, N0, E0 = math.radians(49), math.radians(-2), -100000.0, 400000.0
    e2 = 1 - (b * b) / (a * a)
    n = (a - b) / (a + b)
    lat, M = lat0, 0.0
    while True:
        lat = (N - N0 - M) / (a * F0) + lat
        dl, sl = lat - lat0, lat + lat0
        M = b * F0 * ((1 + n + 1.25 * n**2 + 1.25 * n**3) * dl
                      - (3 * n + 3 * n**2 + 21 / 8 * n**3) * math.sin(dl) * math.cos(sl)
                      + (15 / 8 * n**2 + 15 / 8 * n**3) * math.sin(2 * dl) * math.cos(2 * sl)
                      - 35 / 24 * n**3 * math.sin(3 * dl) * math.cos(3 * sl))
        if abs(N - N0 - M) < 0.00001:
            break
    sinl, cosl, tanl = math.sin(lat), math.cos(lat), math.tan(lat)
    nu = a * F0 / math.sqrt(1 - e2 * sinl**2)
    rho = a * F0 * (1 - e2) / (1 - e2 * sinl**2) ** 1.5
    eta2 = nu / rho - 1
    sec = 1 / cosl
    VII = tanl / (2 * rho * nu)
    VIII = tanl / (24 * rho * nu**3) * (5 + 3 * tanl**2 + eta2 - 9 * tanl**2 * eta2)
    IX = tanl / (720 * rho * nu**5) * (61 + 90 * tanl**2 + 45 * tanl**4)
    X = sec / nu
    XI = sec / (6 * nu**3) * (nu / rho + 2 * tanl**2)
    XII = sec / (120 * nu**5) * (5 + 28 * tanl**2 + 24 * tanl**4)
    XIIA = sec / (5040 * nu**7) * (61 + 662 * tanl**2 + 1320 * tanl**4 + 720 * tanl**6)
    dE = E - E0
    lat = lat - VII * dE**2 + VIII * dE**4 - IX * dE**6
    lon = lon0 + X * dE - XI * dE**3 + XII * dE**5 - XIIA * dE**7

    # OSGB36 (Airy) to WGS84 by Helmert transform.
    nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    x = nu * math.cos(lat) * math.cos(lon)
    y = nu * math.cos(lat) * math.sin(lon)
    z = (1 - e2) * nu * math.sin(lat)
    tx, ty, tz, sc = 446.448, -125.157, 542.060, -20.4894e-6
    rx, ry, rz = (math.radians(v / 3600) for v in (0.1502, 0.2470, 0.8421))
    x2 = tx + (1 + sc) * x - rz * y + ry * z
    y2 = ty + rz * x + (1 + sc) * y - rx * z
    z2 = tz - ry * x + rx * y + (1 + sc) * z
    a2, b2 = 6378137.0, 6356752.3142
    e22 = 1 - (b2 * b2) / (a2 * a2)
    p_ = math.hypot(x2, y2)
    lat = math.atan2(z2, p_ * (1 - e22))
    for _ in range(10):
        nu2 = a2 / math.sqrt(1 - e22 * math.sin(lat) ** 2)
        lat = math.atan2(z2 + e22 * nu2 * math.sin(lat), p_)
    return math.degrees(lat), math.degrees(math.atan2(y2, x2))


def gridref_to_wgs84(ref: str) -> Optional[Tuple[float, float]]:
    """An Ordnance Survey grid reference ("SU9968973089") to WGS84 lat/lng,
    to a few metres: Airy 1830 transverse Mercator, then the standard
    OSGB36-to-WGS84 Helmert transform. National Trust trail starts carry
    these. None for anything that isn't one."""
    ref = ref.replace(" ", "").upper()
    if len(ref) < 4 or not ref[:2].isalpha() or not ref[2:].isdigit() or len(ref[2:]) % 2:
        return None
    l1, l2 = ord(ref[0]) - 65, ord(ref[1]) - 65
    l1 -= l1 > 7
    l2 -= l2 > 7
    e100 = ((l1 - 2) % 5) * 5 + (l2 % 5)
    n100 = (19 - (l1 // 5) * 5) - (l2 // 5)
    half = len(ref[2:]) // 2
    unit = 10 ** (5 - half)
    E = e100 * 100000 + int(ref[2:2 + half]) * unit + unit / 2
    N = n100 * 100000 + int(ref[2 + half:]) * unit + unit / 2
    return en_to_wgs84(E, N)

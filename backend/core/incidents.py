"""
Roadworks from TomTom's traffic incidents, where Street Manager doesn't
reach (founder, 13 Oct 2026: "What about Wales, Scotland and NI?").

Street Manager covers England only. Scotland's register, Wales's council
registers and Northern Ireland's have no open feed that could be found
(docs/ROADWORKS.md). TomTom reports roadworks and closures everywhere it
covers, on the key the drives already use. Checked live 13 Oct 2026: Cardiff
17 roadworks and 15 closures, Edinburgh 36 and 43, Belfast 8 and 5.

What it says about traffic control is thin: mostly just "Roadworks". Some
say "Single alternate line traffic" (one direction at a time: lights or
stop/go in effect), which counts as stopping traffic like Street Manager's
temporary signals. The rest count as roadworks of unknown control: a light
penalty, and the card says how little is known.

In England both sources can report the same works; a TomTom one within
DUPLICATE_M of a Street Manager one is dropped, and Street Manager's richer
record kept. TomTom still adds what Street Manager lacks (motorway works are
recorded elsewhere).

What TomTom receives: a box round the drive's area, tens of kilometres
across, once per request (cached CACHE_S per area). It already receives a
drive's exact points.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import httpx

log = logging.getLogger("driftway")

URL = "https://api.tomtom.com/traffic/services/5/incidentDetails"
FIELDS = ("{incidents{type,geometry{type,coordinates},properties{id,iconCategory,"
          "magnitudeOfDelay,events{description,code},startTime,endTime,from,to,roadNumbers}}}")
ATTRIBUTION = "Roadworks outside Street Manager: traffic incidents © TomTom"
#: TomTom's icon categories kept: lane closed (only when traffic alternates),
#: road closed, roadworks.
CATEGORIES = "7,8,9"
#: TomTom refuses boxes larger than 10,000 km².
MAX_AREA_KM2 = 9000.0
#: An area's answer is reused this long.
CACHE_S = 300.0
#: A TomTom work this close to a Street Manager work is the same work.
DUPLICATE_M = 60.0
#: Words in an event that mean traffic takes turns, so cars stop and wait.
ALTERNATING = ("alternate line", "alternating", "traffic lights", "traffic signals",
               "stop and go", "stop/go", "convoy")
_cache: Dict[Tuple[float, float, float, float], Tuple[float, List["Incident"]]] = {}


@dataclass
class Incident:
    """One TomTom incident, shaped like core.roadworks.Roadwork where the
    drive ranking and the card read it."""
    work_ref: str
    street: str
    control: str                    # alternating_traffic | road_closure | roadworks
    points_json: str                # [[lat, lng], ...]
    town: str = ""
    status: str = "in_progress"
    starts: Optional[datetime] = None
    ends: Optional[datetime] = None
    source: str = "tomtom"


def configured() -> bool:
    """Only with live routing: tests and the simulator never call TomTom."""
    return ((os.getenv("ROUTING_PROVIDER") or "").lower() == "tomtom"
            and bool((os.getenv("TOMTOM_API_KEY") or "").strip()))


def classify(props: Dict) -> Optional[str]:
    words = " ".join((e.get("description") or "") for e in props.get("events") or []).lower()
    if any(w in words for w in ALTERNATING):
        return "alternating_traffic"
    cat = props.get("iconCategory")
    if cat == 8:                    # not "lane closed", which is category 7
        return "road_closure"
    if cat == 9:
        return "roadworks"
    return None                     # a lane closed, traffic not stopped


def parse(data: Dict) -> List[Incident]:
    out = []
    for inc in data.get("incidents") or []:
        props = inc.get("properties") or {}
        control = classify(props)
        geom = inc.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") == "Point":
            coords = [coords]
        pts = [[round(c[1], 6), round(c[0], 6)] for c in coords if len(c) >= 2]
        if not control or not pts:
            continue
        roads = props.get("roadNumbers") or []
        street = roads[0] if roads else (props.get("from") or "")
        out.append(Incident(work_ref=f"tomtom:{props.get('id', len(out))}", street=street,
                            control=control, points_json=json.dumps(pts)))
    return out


def _box(south: float, west: float, north: float, east: float) -> Tuple[float, float, float, float]:
    """Rounded outwards to 0.05°, so nearby drives share one answer."""
    import math
    r = lambda v, f: round(f(v / 0.05) * 0.05, 2)  # noqa: E731
    return (r(south, math.floor), r(west, math.floor), r(north, math.ceil), r(east, math.ceil))


def area_km2(box) -> float:
    import math
    s, w, n, e = box
    return (n - s) * 111.32 * (e - w) * 111.32 * math.cos(math.radians((n + s) / 2))


async def fetch(south: float, west: float, north: float, east: float,
                client: Optional[httpx.AsyncClient] = None) -> Optional[List[Incident]]:
    """Current roadworks and closures in the box: a list, empty when TomTom
    reports none; None when they couldn't be asked for (an area too large, a
    refusal, a failure), so "none found" and "not checked" stay apart. A
    drive never waits on, or breaks for, this."""
    box = _box(south, west, north, east)
    if area_km2(box) > MAX_AREA_KM2:
        return None
    hit = _cache.get(box)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    from core.router import tomtom_limiter
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=3.0))
    try:
        await tomtom_limiter().wait()
        resp = await client.get(URL, params={
            "key": (os.getenv("TOMTOM_API_KEY") or "").strip(),
            "bbox": f"{box[1]},{box[0]},{box[3]},{box[2]}",
            "fields": FIELDS, "language": "en-GB",
            "categoryFilter": CATEGORIES, "timeValidityFilter": "present"})
        if resp.status_code != 200:
            log.warning("TomTom incidents %s", resp.status_code)
            return None
        found = parse(resp.json())
    except Exception as e:  # noqa: BLE001 - the type only: the URL carries the key
        log.warning("TomTom incidents failed: %s", type(e).__name__)
        return None
    finally:
        if own:
            await client.aclose()
    if len(_cache) > 200:
        _cache.clear()
    _cache[box] = (time.monotonic(), found)
    return found


def reset_cache() -> None:
    """For tests."""
    _cache.clear()

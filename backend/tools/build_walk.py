"""
Build a curated walk from real map data.

    python -m tools.build_walk data/walks/specs/windsor-riverside.spec.json

Development-time only - the app never calls OpenStreetMap or the elevation
service while serving a request. This produces a JSON file in data/walks/ that
the app reads, so every walk is a reviewable artefact with its sources in it,
and the free public services see one burst of polite requests per build rather
than one per parent.

A spec gives `waypoints` (positions taken from OSM nodes, so nothing is
an invented coordinate), `gpx` (a recorded trace, e.g. exported from a
fitness app), or `osm_relation` (a walking route mapped in OpenStreetMap,
followed along its own member paths: tools/import_osm_routes.py writes these
specs). The route follows mapped paths between waypoints; a GPX trace is
matched to the nearest mapped path, and stretches that match nothing are kept
as "not on a mapped path" with an unknown surface rather than dropped.

Founder observations live beside the spec in <id>.observations.json and are
merged as `reported` evidence with their date. They outrank the map.

Sources and their terms, checked 8 Oct 2026:
  OpenStreetMap via Overpass API  - ODbL; attribution "© OpenStreetMap
                                    contributors". Overpass asks for modest use.
  Open Topo Data, eudem25m         - free public API: max 100 locations per
                                    request, 1 call per second, 1000 per day.
                                    EU-DEM is Copernicus data.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.walking.evidence import (  # noqa: E402
    Barrier, BarrierKind, Evidence, Gradient, Section, Status, Surface,
)
from core.walking.terrain import attach_gradients, smooth  # noqa: E402
from core.walking.osm import (  # noqa: E402
    access_forbidden, barrier_from_node, steps_barrier, surface_from_tags,
)

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BACKEND, "tools", ".cache")
OUT_DIR = os.path.join(BACKEND, "data", "walks")

#: Identifies the project, not a person. Overpass asks clients to identify
#: themselves; a public repository URL does that without handing out anyone's
#: contact details.
USER_AGENT = "Driftway-dev/0.1 (+https://github.com/stepanchizhov/Driftway)"
OVERPASS = ["https://lz4.overpass-api.de/api/interpreter",
            "https://overpass-api.de/api/interpreter",
            "https://z.overpass-api.de/api/interpreter"]
ELEVATION = "https://api.opentopodata.org/v1/eudem25m"
#: Terrain models, tried in this order: EU-DEM covers Europe only (the
#: service answers null outside it); SRTM covers the world between 60 N and
#: 56 S. A walk names the one its slopes came from.
ELEVATION_SOURCES = {
    "eudem25m": {"id": "eudem25m", "label": "EU-DEM 25 m terrain model via Open Topo Data",
                 "licence": "Copernicus",
                 "attribution": "Produced using Copernicus data and information "
                                "funded by the European Union - EU-DEM layers",
                 "limitation": "25 m grid: sustained slopes only; short ramps and "
                               "kerbs are not visible, and buildings or trees can "
                               "distort values in town."},
    "srtm30m": {"id": "srtm30m", "label": "SRTM 30 m terrain model via Open Topo Data",
                "licence": "Public domain (NASA)",
                "attribution": "SRTM data courtesy of NASA and the USGS",
                "limitation": "30 m grid, from radar: sustained slopes only; tree "
                              "cover and buildings can read as ground."},
}

#: Distance between elevation samples along the route.
SAMPLE_M = 20.0
#: Gradient thresholds live in core/walking/terrain.py, shared with generated
#: walks. How far a GPX point may be from a mapped path and still count as on it.
MATCH_M = 15.0

#: Ways a walker can use. Main roads are included because, in UK towns, the
#: pavement is usually mapped as an attribute of the road rather than as a path
#: of its own - leaving them out cut central Windsor into unconnected islands.
#: Trunk roads and motorways are never walkable.
WALKABLE = {"footway", "path", "pedestrian", "steps", "track", "cycleway",
            "bridleway", "living_street", "residential", "service",
            "unclassified", "tertiary", "secondary", "primary", "corridor"}
#: Roads are walkable, but a path is preferred where one exists.
ROAD_PENALTY = {"living_street": 1.1, "service": 1.3, "residential": 1.4,
                "unclassified": 1.5, "tertiary": 1.8, "secondary": 2.2,
                "primary": 2.6}
#: Walking along these means walking on a pavement beside traffic.
ROADS = set(ROAD_PENALTY)


# ------------------------------------------------------------------ fetch

def _cached(key: str, fetch) -> bytes:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, hashlib.sha256(key.encode()).hexdigest()[:24])
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    body = fetch()
    with open(path, "wb") as f:
        f.write(body)
    return body


def _http(url: str, data: Optional[bytes] = None, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_osm(bbox: Tuple[float, float, float, float]) -> Dict:
    s, w, n, e = bbox
    hw = "|".join(sorted(WALKABLE))
    query = (f'[out:json][timeout:90];'
             f'way["highway"~"^({hw})$"]({s},{w},{n},{e});out body geom;'
             f'node["barrier"]({s},{w},{n},{e});out body;')

    def fetch():
        last = None
        for attempt in range(6):
            for host in OVERPASS:
                try:
                    body = _http(host, urllib.parse.urlencode({"data": query}).encode())
                    if body.lstrip().startswith(b"{"):
                        return body
                    last = body[:200]
                except Exception as e:  # noqa: BLE001
                    last = repr(e)
            # The public instance is often busy; back off rather than hammer it.
            time.sleep(min(120, 15 * 2 ** attempt))
        raise RuntimeError(f"Overpass unavailable after retries: {last!r}")

    return json.loads(_cached("osm:" + query, fetch))


def _overpass(query: str) -> Dict:
    def fetch():
        last = None
        for attempt in range(6):
            for host in OVERPASS:
                try:
                    body = _http(host, urllib.parse.urlencode({"data": query}).encode())
                    if body.lstrip().startswith(b"{"):
                        return body
                    last = body[:200]
                except Exception as e:  # noqa: BLE001
                    last = repr(e)
            time.sleep(min(120, 15 * 2 ** attempt))
        raise RuntimeError(f"Overpass unavailable after retries: {last!r}")
    return json.loads(_cached("osm:" + query, fetch))


def fetch_relation(rel_id: int) -> Dict:
    """A route relation with its member ways (nodes and geometry)."""
    data = _overpass(f"[out:json][timeout:90];relation({int(rel_id)});out body;"
                     f"way(r);out body geom;")
    rel = next(e for e in data["elements"] if e["type"] == "relation")
    ways = {e["id"]: e for e in data["elements"] if e["type"] == "way"}
    return {"relation": rel, "ways": ways,
            "osm_base": data.get("osm3s", {}).get("timestamp_osm_base", "")}


def osgb_to_wgs84(ref: str) -> Optional[Tuple[float, float]]:
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


#: Member roles that are part of the route itself. "alternative",
#: "excursion", "approach" and the like are not walked.
_ROUTE_ROLES = {"", "main", "forward", "backward", "route"}


def _walk_from_relation(graph: Graph, rel: Dict, start_near=None):
    """[(coord, way_id, node_id)] along a route relation's own member paths,
    in the order it lists them, and notes on anything that had to change.

    Members are chained end to end, each turned round if it was mapped the
    other way. Where two members don't meet, or a member is not usable on
    foot here (not a walkable path, closed to walkers, or excluded by the
    spec's "avoid"), the walk goes round on mapped paths and says so. A
    circular route that doesn't quite close is closed the same way. With
    `start_near`, a circular route starts at its node nearest that point."""
    notes: List[str] = []
    # Only paths are walked. Trails also list their car park, a cafe or a pub
    # as members (11 Oct 2026: every National Trust trail near Windsor did);
    # those are places on the way, not ways.
    members = [m["ref"] for m in rel["relation"].get("members", [])
               if m["type"] == "way" and m.get("role", "") in _ROUTE_ROLES
               and "highway" in rel["ways"].get(m["ref"], {}).get("tags", {})]
    if start_near is None:
        # No grid reference: start at the trail's own car park, if it lists one.
        for m in rel["relation"].get("members", []):
            w = rel["ways"].get(m["ref"]) if m["type"] == "way" else None
            if w and w.get("tags", {}).get("amenity") == "parking" and w.get("geometry"):
                g = w["geometry"]
                start_near = (sum(x["lat"] for x in g) / len(g), sum(x["lon"] for x in g) / len(g))
                break
    seq: List[Tuple[int, Optional[int]]] = []      # (node, way used to reach it)
    detoured = 0

    def append_route(a: int, b: int):
        nonlocal detoured
        if a == b:
            return
        leg = graph.route(a, b)
        detoured += 1
        for nid, way in leg[1:]:
            seq.append((nid, way if way != -1 else None))

    for i, wid in enumerate(members):
        way = rel["ways"].get(wid)
        if way is None:
            continue
        nodes = list(way["nodes"])
        usable = wid in graph.ways
        if not seq:
            # Orient the first member towards the second.
            nxt = rel["ways"].get(members[i + 1]) if i + 1 < len(members) else None
            if nxt and nodes[0] in (nxt["nodes"][0], nxt["nodes"][-1]):
                nodes.reverse()
            seq.append((nodes[0], wid if usable else None))
            start_idx = 1
        else:
            end = seq[-1][0]
            if nodes[-1] == end:
                nodes.reverse()
            elif nodes[0] != end and end in nodes:
                k = nodes.index(end)                    # joins part-way along
                nodes = nodes[k:] if len(nodes) - k >= k + 1 else nodes[:k + 1][::-1]
            elif nodes[0] != end:
                near = min((nodes[0], nodes[-1]),
                           key=lambda n: haversine(graph.coord.get(n, (0, 0)), graph.coord.get(end, (0, 0))))
                if near == nodes[-1]:
                    nodes.reverse()
                if nodes[0] in graph.adj and end in graph.adj:
                    append_route(end, nodes[0])
            start_idx = 1 if nodes[0] == seq[-1][0] else 0
        if usable:
            for nid in nodes[start_idx:]:
                seq.append((nid, wid))
        elif seq[-1][0] in graph.adj and nodes[-1] in graph.adj:
            append_route(seq[-1][0], nodes[-1])
        else:
            raise RuntimeError(f"member way {wid} is unusable and can't be walked round")

    if not seq:
        raise RuntimeError("the relation has no usable member ways")
    if detoured:
        notes.append(f"The mapped trail has {detoured} place{'s' if detoured > 1 else ''} where "
                     "its paths don't join or can't be used on foot here; the walk "
                     "goes round there on mapped paths.")
    circular = rel["relation"].get("tags", {}).get("roundtrip") == "yes"
    if circular and seq[0][0] != seq[-1][0]:
        gap = haversine(graph.coord[seq[0][0]], graph.coord[seq[-1][0]])
        if gap <= 500 and seq[-1][0] in graph.adj and seq[0][0] in graph.adj:
            append_route(seq[-1][0], seq[0][0])
            if gap > 30:
                notes.append("The mapped trail stops short of where it began; "
                             "the last part follows the mapped way back to the start.")
    if circular and start_near and seq[0][0] == seq[-1][0]:
        nodes_only = [n for n, _ in seq]
        k = min(range(len(nodes_only) - 1),
                key=lambda i: haversine(graph.coord[nodes_only[i]], tuple(start_near)))
        if k:
            # Rotate the loop: start (and finish) at the node nearest the
            # trail's named start. The way used to reach each node moves with it.
            body = seq[1:]
            seq = [(seq[k][0], None)] + body[k:] + body[:k]

    pts = [(graph.coord[n], w, n) for n, w in seq]
    if len(pts) > 1 and pts[0][1] is None:
        pts[0] = (pts[0][0], pts[1][1], pts[0][2])
    return pts, notes


def fetch_elevations(points: List[Tuple[float, float]],
                     dataset: str = "eudem25m") -> List[Optional[float]]:
    out: List[Optional[float]] = []
    base = ELEVATION.rsplit("/", 1)[0] + "/" + dataset
    for i in range(0, len(points), 100):
        batch = points[i:i + 100]
        locs = "|".join(f"{la:.6f},{lo:.6f}" for la, lo in batch)

        def fetch():
            body = _http(f"{base}?locations={urllib.parse.quote(locs, safe='|,.-')}")
            time.sleep(1.1)        # the public API allows one call per second
            return body

        key = ("elev:" if dataset == "eudem25m" else f"elev:{dataset}:") + locs
        data = json.loads(_cached(key, fetch))
        if data.get("status") != "OK":
            raise RuntimeError(f"elevation lookup failed: {data}")
        out.extend(r["elevation"] for r in data["results"])
    return out


# ------------------------------------------------------------------ geometry

def haversine(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    r = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(h))


def _point_segment_m(p, a, b) -> float:
    """Distance from p to segment ab, in metres, on a local flat projection."""
    k = math.cos(math.radians(p[0]))
    ax, ay = (a[1] - p[1]) * k, a[0] - p[0]
    bx, by = (b[1] - p[1]) * k, b[0] - p[0]
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
    x, y = ax + t * dx, ay + t * dy
    return math.hypot(x, y) * 111320.0


# --------------------------------------------------------------------- graph

class Graph:
    """Walkable OSM ways as a graph of nodes, edges remembering their way."""

    def __init__(self, osm: Dict, avoid: Tuple[str, ...] = ()):
        """`avoid` lists highway types this walk must not use.

        A curated route says what it is for. Left to the shortest path, the
        Castle Hill walk climbed by four flights of steps when Thames Street
        climbs the same hill step-free - a route no curator would offer a
        parent with a pram. A spec with "avoid": ["steps"] excludes them.
        """
        self.ways: Dict[int, Dict] = {}
        self.coord: Dict[int, Tuple[float, float]] = {}
        self.adj: Dict[int, List[Tuple[int, float, int]]] = {}
        self.barriers: Dict[int, Dict] = {}
        self.osm_base = osm.get("osm3s", {}).get("timestamp_osm_base", "")

        for el in osm["elements"]:
            if el["type"] == "node" and "barrier" in el.get("tags", {}):
                self.barriers[el["id"]] = el["tags"]
        for el in osm["elements"]:
            if el["type"] != "way":
                continue
            tags = el.get("tags", {})
            if tags.get("highway") not in WALKABLE or access_forbidden(tags):
                continue
            if tags.get("highway") in avoid:
                continue
            if (tags.get("highway") in ("primary", "secondary")
                    and tags.get("sidewalk") in ("no", "none")):
                continue        # a main road the map says has no pavement
            self.ways[el["id"]] = el
            nodes, geom = el["nodes"], el["geometry"]
            for nid, g in zip(nodes, geom):
                self.coord[nid] = (g["lat"], g["lon"])
            factor = ROAD_PENALTY.get(tags.get("highway"), 1.0)
            for a, b in zip(nodes, nodes[1:]):
                d = haversine(self.coord[a], self.coord[b])
                self.adj.setdefault(a, []).append((b, d * factor, el["id"]))
                self.adj.setdefault(b, []).append((a, d * factor, el["id"]))

    def nearest_node(self, p: Tuple[float, float]) -> int:
        return min(self.adj, key=lambda n: haversine(self.coord[n], p))

    def route(self, a: int, b: int) -> List[Tuple[int, int]]:
        """Shortest path as [(node, way_used_to_reach_it)], first way is -1."""
        dist = {a: 0.0}
        prev: Dict[int, Tuple[int, int]] = {}
        heap = [(0.0, a)]
        while heap:
            d, u = heapq.heappop(heap)
            if u == b:
                break
            if d > dist.get(u, math.inf):
                continue
            for v, w, way in self.adj.get(u, []):
                nd = d + w
                if nd < dist.get(v, math.inf):
                    dist[v], prev[v] = nd, (u, way)
                    heapq.heappush(heap, (nd, v))
        if b not in dist:
            raise RuntimeError("no walkable connection between waypoints")
        path = [(b, prev[b][1] if b in prev else -1)]
        while path[-1][0] != a:
            u, _ = prev[path[-1][0]]
            path.append((u, prev[u][1] if u in prev else -1))
        path.reverse()
        return path

    def nearest_way(self, p: Tuple[float, float]) -> Optional[int]:
        best, best_d = None, MATCH_M
        for wid, way in self.ways.items():
            g = [(x["lat"], x["lon"]) for x in way["geometry"]]
            for a, b in zip(g, g[1:]):
                d = _point_segment_m(p, a, b)
                if d < best_d:
                    best, best_d = wid, d
        return best


# ----------------------------------------------------------------- sections

def _walk_from_waypoints(graph: Graph, waypoints) -> List[Tuple[Tuple[float, float], Optional[int], Optional[int]]]:
    """[(coord, way_id, node_id)] along mapped paths through the waypoints."""
    pts: List = []
    nodes = [graph.nearest_node(tuple(w)) for w in waypoints]
    for a, b in zip(nodes, nodes[1:]):
        leg = graph.route(a, b)
        if pts:
            leg = leg[1:]
        for nid, way in leg:
            pts.append((graph.coord[nid], way if way != -1 else None, nid))
    # The first point inherits the way of the second, so it lands in a section.
    if len(pts) > 1 and pts[0][1] is None:
        pts[0] = (pts[0][0], pts[1][1], pts[0][2])
    return pts


def _walk_from_gpx(graph: Graph, path: str):
    root = ET.parse(path).getroot()
    pts = []
    for el in root.iter():
        if el.tag.endswith("trkpt") or el.tag.endswith("rtept"):
            p = (float(el.attrib["lat"]), float(el.attrib["lon"]))
            pts.append((p, graph.nearest_way(p), None))
    if len(pts) < 2:
        raise RuntimeError("GPX file has fewer than two track points")
    # Junction jitter: near where paths meet, a single GPS point often snaps to
    # the neighbouring way, which would invent a two-metre stretch of whatever
    # that way is. A point that disagrees with both of its neighbours, when
    # they agree with each other, takes their way.
    #
    # Aimed at dense recorded traces (a fitness app logs a point every second
    # or so). NOT demonstrated yet: the only check so far used a sparse trace
    # built from map nodes, about 17 m apart, where each mismatch sat between
    # two different ways and this rule did not apply. Nearest-way matching
    # stays labelled as such on every piece of evidence it produces.
    ways = [p[1] for p in pts]
    for i in range(1, len(ways) - 1):
        if ways[i - 1] == ways[i + 1] != ways[i]:
            ways[i] = ways[i - 1]
    return [(p[0], w, p[2]) for p, w in zip(pts, ways)]


def _sections(graph: Graph, pts, matched_by_proximity: bool) -> List[Section]:
    """Group consecutive points on the same way into sections."""
    sections: List[Section] = []
    cursor = 0.0
    run: List = [pts[0]]

    def close(run, start_m, end_m):
        way_id = run[-1][1]
        geom = [[round(p[0][0], 6), round(p[0][1], 6)] for p in run]
        if way_id is None:
            sec = Section(start_m, end_m, "Not on a mapped path", geom)
            sec.evidence.append(Evidence(
                "mapped_path", None, Status.UNKNOWN, "none",
                note="This stretch of the trace does not follow any mapped path."))
            return sec
        way = graph.ways[way_id]
        tags = way.get("tags", {})
        src = f"osm:way/{way_id}"
        cls, evidence = surface_from_tags(tags, src)
        if tags.get("highway") in ROADS:
            # The tag describes the carriageway. A pavement beside an asphalt
            # road is very likely sealed too, but that is an inference, and the
            # parent should be able to see it is one.
            sidewalk_surface = (tags.get("sidewalk:surface")
                                or tags.get("sidewalk:both:surface"))
            if sidewalk_surface:
                cls, evidence = surface_from_tags({"surface": sidewalk_surface}, src)
                for e in evidence:
                    e.note = "pavement surface"
            else:
                for e in evidence:
                    if e.attribute == "surface":
                        e.note = "road surface; the pavement's own surface is not mapped"
        if matched_by_proximity:
            for e in evidence:
                e.note = ((e.note + "; ") if e.note else "") + \
                    "matched to the nearest mapped path"
        label = tags.get("name") or {
            "footway": "Footpath", "path": "Path", "pedestrian": "Pedestrian street",
            "steps": "Steps", "track": "Track", "cycleway": "Cycle path",
            "bridleway": "Bridleway"}.get(tags.get("highway"), "Street")
        sec = Section(start_m, end_m, label, geom, surface=cls, evidence=evidence)
        if tags.get("highway") == "steps":
            sec.barriers.append(steps_barrier(tags, (start_m + end_m) / 2, src))
        return sec

    pending: List[Barrier] = []

    def run_length(run) -> float:
        return sum(haversine(a[0], b[0]) for a, b in zip(run, run[1:]))

    for prev, cur in zip(pts, pts[1:]):
        if cur[1] != run[-1][1]:
            length = run_length(run)
            sections.append(close(run, cursor, cursor + length))
            cursor += length
            run = [prev]
        run.append(cur)
        # Barrier nodes are placed at the distance where they are met.
        if cur[2] is not None and cur[2] in graph.barriers:
            b = barrier_from_node(graph.barriers[cur[2]],
                                  cursor + run_length(run), f"osm:node/{cur[2]}")
            if b is not None:
                pending.append(b)
    sections.append(close(run, cursor, cursor + run_length(run)))

    for b in pending:
        home = next((s for s in sections if s.from_m <= b.at_m <= s.to_m), sections[-1])
        home.barriers.append(b)
    return _merge(sections)


#: Longest single section after building. A section carries one gradient and
#: one set of findings, so a long one smears a local feature across its whole
#: length: the first build of the Long Walk had a 2.6 km section whose steepest
#: climb - Snow Hill, at the far end - was charged to a walker who turned back
#: after 1.9 km. Splitting puts each slope roughly where it is.
MAX_SECTION_M = 300.0


def _slice_geometry(geom: List[List[float]], start_m: float, end_m: float) -> List[List[float]]:
    """The part of a polyline between two distances along it."""
    out: List[List[float]] = []
    walked = 0.0
    for a, b in zip(geom, geom[1:]):
        d = haversine(tuple(a), tuple(b))
        seg_start, seg_end = walked, walked + d
        if seg_end >= start_m and seg_start <= end_m and d > 0:
            t0 = max(0.0, (start_m - seg_start) / d)
            t1 = min(1.0, (end_m - seg_start) / d)
            p0 = [a[0] + t0 * (b[0] - a[0]), a[1] + t0 * (b[1] - a[1])]
            p1 = [a[0] + t1 * (b[0] - a[0]), a[1] + t1 * (b[1] - a[1])]
            if not out:
                out.append(p0)
            out.append(p1)
        walked = seg_end
    return out or geom[:1]


def _split_long(sections: List[Section]) -> List[Section]:
    """Cut sections longer than MAX_SECTION_M into equal pieces.

    Each piece keeps the section's label and evidence (the map says the same
    thing about all of it); barriers go to the piece they are in; gradients are
    computed afterwards, per piece, so they become local.
    """
    out: List[Section] = []
    for s in sections:
        pieces = max(1, math.ceil(s.length_m / MAX_SECTION_M))
        if pieces == 1:
            out.append(s)
            continue
        step = s.length_m / pieces
        for i in range(pieces):
            a, b = s.from_m + i * step, s.from_m + (i + 1) * step
            piece = Section(a, b, s.label,
                            _slice_geometry(s.geometry, a - s.from_m, b - s.from_m),
                            surface=s.surface, evidence=list(s.evidence),
                            hazards=list(s.hazards),
                            access_restricted=s.access_restricted)
            piece.barriers = [x for x in s.barriers
                              if a <= x.at_m < b or (i == pieces - 1 and x.at_m == b)]
            out.append(piece)
    return out


#: Labels the builder invents for unnamed ways. Anything else is a real name.
GENERIC = {"Footpath", "Path", "Pedestrian street", "Track", "Cycle path",
           "Bridleway", "Street"}


def _merge(sections: List[Section]) -> List[Section]:
    """Join neighbours that a parent would experience as one stretch.

    Same surface class and same strength of evidence, with nothing to report in
    between. An unnamed connector ("Footpath", "Street") folds into a named
    neighbour, because a footpath that becomes a cycle path on identical paving
    is one stretch to someone pushing a pram. Two differently named streets are
    NOT merged: an earlier version did, and labelled half a kilometre across
    four streets with the name of whichever piece happened to be longest.

    Never merged: steps, barriers, unmapped stretches, or a known surface with
    an unknown one, since that would hide exactly the gap the parent needs.
    """
    out: List[Section] = []
    for s in sections:
        last = out[-1] if out else None
        same_place = (last is not None and (
            s.label == last.label or s.label in GENERIC or last.label in GENERIC))
        if (same_place and not s.barriers and not last.barriers
                and s.surface == last.surface
                and s.surface_basis() == last.surface_basis()
                and "Not on a mapped path" not in (s.label, last.label)):
            if last.label in GENERIC and s.label not in GENERIC:
                last.label = s.label
            last.to_m = s.to_m
            last.geometry = last.geometry + s.geometry[1:]
            known = {(e.attribute, e.source) for e in last.evidence}
            last.evidence += [e for e in s.evidence if (e.attribute, e.source) not in known]
        else:
            out.append(s)
    return [s for s in out if s.length_m >= 1.0]


# ----------------------------------------------------------------- elevation

def _resample(sections: List[Section]) -> List[Tuple[float, Tuple[float, float]]]:
    line: List[Tuple[float, float]] = []
    for s in sections:
        for p in s.geometry:
            if not line or tuple(p) != line[-1]:
                line.append(tuple(p))
    samples = [(0.0, line[0])]
    walked, next_at = 0.0, SAMPLE_M
    for a, b in zip(line, line[1:]):
        d = haversine(a, b)
        while d > 0 and walked + d >= next_at:
            t = (next_at - walked) / d
            samples.append((next_at, (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))))
            next_at += SAMPLE_M
        walked += d
    if samples[-1][0] < walked:
        samples.append((walked, line[-1]))
    return samples


def _attach_gradients(sections: List[Section]) -> Optional[str]:
    """Slopes from the first terrain model that covers the walk. Returns its
    id, or None when none does (the walk then has no slopes, said as unknown)."""
    samples = _resample(sections)
    pts = [p for _, p in samples]
    for dataset in ELEVATION_SOURCES:
        heights = fetch_elevations(pts, dataset)
        if heights and all(h is not None for h in heights):
            attach_gradients(sections, [d for d, _ in samples], smooth(heights),
                             f"{dataset} via Open Topo Data")
            return dataset
    return None


# --------------------------------------------------------------- observations

def _apply_observations(sections: List[Section], path: str) -> List[str]:
    """Merge founder observations. Returns notes for the route card."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        obs = json.load(f)
    notes: List[str] = []
    for o in obs.get("observations", []):
        at = float(o["at_m"])
        target = next((s for s in sections if s.from_m <= at <= s.to_m), sections[-1])
        src = f"founder, {o['observed_on']}"
        kind = o["attribute"]
        if kind == "surface":
            target.evidence.append(Evidence("surface", o["value"], Status.REPORTED, src,
                                            o["observed_on"], o.get("note")))
            target.surface = Surface(o["class"])
        elif kind == "hazard":
            target.hazards.append(Evidence("hazard", o["value"], Status.REPORTED, src,
                                           o["observed_on"], o.get("note")))
        elif kind == "barrier":
            target.barriers.append(Barrier(
                BarrierKind(o["value"]), at, Status.REPORTED, src,
                width_cm=o.get("width_cm"), step_count=o.get("step_count"),
                has_ramp=o.get("has_ramp"), note=o.get("note")))
        else:
            target.evidence.append(Evidence(kind, o["value"], Status.REPORTED, src,
                                            o["observed_on"], o.get("note")))
    notes += obs.get("notes", [])
    return notes


# ---------------------------------------------------------------------- main

def build(spec_path: str, out_dir: str = OUT_DIR) -> str:
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)

    rel = None
    if "osm_relation" in spec:
        rel = fetch_relation(spec["osm_relation"])
        paths = [w for w in rel["ways"].values() if "highway" in w.get("tags", {})]
        lats = [g["lat"] for w in paths for g in w["geometry"]]
        lngs = [g["lon"] for w in paths for g in w["geometry"]]
    elif "gpx" in spec:
        gpx = os.path.join(os.path.dirname(spec_path), spec["gpx"])
        lats, lngs = [], []
        for el in ET.parse(gpx).getroot().iter():
            if el.tag.endswith("trkpt") or el.tag.endswith("rtept"):
                lats.append(float(el.attrib["lat"]))
                lngs.append(float(el.attrib["lon"]))
    else:
        lats = [w[0] for w in spec["waypoints"]]
        lngs = [w[1] for w in spec["waypoints"]]
    # Degrees around the route to fetch. The default suits town walks; a walk
    # whose only connection loops away from the straight line (a bridge
    # downstream, a gate round the corner) needs "margin" raised in its spec.
    margin = float(spec.get("margin", 0.004))
    bbox = (min(lats) - margin, min(lngs) - margin, max(lats) + margin, max(lngs) + margin)

    graph = Graph(fetch_osm(bbox), avoid=tuple(spec.get("avoid", ())))
    extra_notes: List[str] = []
    if rel is not None:
        pts, extra_notes = _walk_from_relation(graph, rel, spec.get("start_near"))
        sections = _sections(graph, pts, matched_by_proximity=False)
    elif "gpx" in spec:
        pts = _walk_from_gpx(graph, gpx)
        sections = _sections(graph, pts, matched_by_proximity=True)
        if spec.get("start_at"):
            # The walk begins at a named public place a little before the
            # recording does; join the two along mapped paths.
            lead = _routed_leg(graph, [spec["start_at"], pts[0][0]], 0.0,
                               "the mapped way from the start to where the "
                               "recording begins")
            shift = lead[-1].to_m if lead else 0.0
            for s in sections:
                s.from_m += shift
                s.to_m += shift
                for b in s.barriers:
                    b.at_m += shift
            sections = lead + sections
        if spec.get("close_loop"):
            via = spec.get("close_via", [])
            sections += _routed_leg(
                graph, [pts[-1][0], *via, spec.get("start_at") or pts[0][0]],
                sections[-1].to_m,
                "the way back after the recording stopped, through the places "
                "the walker named" if via else
                "the shortest mapped way back to the start")
    else:
        pts = _walk_from_waypoints(graph, spec["waypoints"])
        sections = _sections(graph, pts, matched_by_proximity=False)

    if spec.get("start_after_m"):
        sections = _trim_start(sections, float(spec["start_after_m"]))
    sections = _split_long(sections)
    terrain = _attach_gradients(sections)
    obs_path = spec_path.replace(".spec.json", ".observations.json")
    notes = list(spec.get("notes", [])) + extra_notes + _apply_observations(sections, obs_path)

    first = sections[0].geometry[0]
    route = {
        "id": spec["id"],
        "name": spec["name"],
        "area": spec.get("area", ""),
        "summary": spec.get("summary", ""),
        "shape": spec.get("shape", "loop"),
        "start": {"lat": first[0], "lng": first[1],
                  "label": spec.get("start_label", "Start")},
        "built_on": date.today().isoformat(),
        "sample": bool(spec.get("sample")),
        "notes": notes,
        "sources": [
            {"id": "osm", "label": "OpenStreetMap", "as_of": graph.osm_base,
             "licence": "ODbL", "attribution": "© OpenStreetMap contributors"},
        ] + ([
            {"id": "osm-route", "label": f"OpenStreetMap route relation {spec['osm_relation']}",
             "as_of": rel["osm_base"], "licence": "ODbL",
             "attribution": "© OpenStreetMap contributors",
             "limitation": "The trail as mapped by volunteers. The trail itself "
                           "belongs to its operator; check their page on the day."},
        ] if rel is not None else []) + (
            [ELEVATION_SOURCES[terrain]] if terrain else []),
        "sections": [_section_dict(s) for s in sections],
    }
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{spec['id']}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(route, f, indent=1, ensure_ascii=False)
    return out


def _routed_leg(graph: "Graph", waypoints, offset_m: float, how: str) -> List[Section]:
    """A stretch that was not recorded, filled in along mapped paths.

    For a recording that started late or stopped early - a phone battery, say.
    It follows mapped paths through the given points, which may still not be
    the exact way walked, so every section says so in its label and on each
    piece of evidence. It is never presented as recorded.
    """
    if haversine(tuple(waypoints[0]), tuple(waypoints[-1])) < 5 and len(waypoints) == 2:
        return []
    pts = _walk_from_waypoints(graph, waypoints)
    leg = _sections(graph, pts, matched_by_proximity=False)
    for s in leg:
        s.from_m += offset_m
        s.to_m += offset_m
        for b in s.barriers:
            b.at_m += offset_m
        s.label = f"{s.label} (completed from the map)"
        for e in s.evidence:
            e.note = ((e.note + "; ") if e.note else "") + f"not recorded - {how}"
    return leg


def _trim_start(sections: List[Section], trim_m: float) -> List[Section]:
    """Drop the first `trim_m` metres, so the walk starts further along.

    For walks that begin at someone's home. Walk files are committed to a
    public repository and shown to every beta tester, so a walk must never
    start at a front door. The route is still built from the real start - that
    is what makes it the route actually walked - and then the opening stretch,
    with every coordinate in it, is cut away before anything is written. The
    spec naming the home street lives in a git-ignored folder.
    """
    out: List[Section] = []
    for s in sections:
        if s.to_m <= trim_m:
            continue
        geom = s.geometry
        barriers = [b for b in s.barriers if b.at_m >= trim_m]
        start = s.from_m
        if s.from_m < trim_m:
            geom = _slice_geometry(s.geometry, trim_m - s.from_m, s.length_m)
            start = trim_m
        for b in barriers:
            b.at_m -= trim_m
        out.append(Section(start - trim_m, s.to_m - trim_m, s.label, geom,
                           surface=s.surface, evidence=s.evidence,
                           hazards=s.hazards, barriers=barriers,
                           access_restricted=s.access_restricted))
    if not out:
        raise RuntimeError("start_after_m is longer than the whole walk")
    return out


def _section_dict(s: Section) -> Dict:
    return {
        "from_m": round(s.from_m, 1), "to_m": round(s.to_m, 1), "label": s.label,
        "surface": s.surface.value, "access_restricted": s.access_restricted,
        "geometry": s.geometry,
        "evidence": [e.to_dict() for e in s.evidence],
        "hazards": [h.to_dict() for h in s.hazards],
        "barriers": [b.to_dict() for b in s.barriers],
        "gradient": s.gradient.to_dict() if s.gradient else None,
    }


if __name__ == "__main__":
    # The repository lives under a non-ASCII path on the founder's machine, and
    # a Windows console defaults to a codepage that cannot print it. Report the
    # path relative to the backend so the message never depends on that.
    for spec in sys.argv[1:]:
        out = build(spec)
        print("built", os.path.relpath(out, BACKEND).replace(os.sep, "/"))

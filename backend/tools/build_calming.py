"""
Build the speed-bump data drives are ranked with (docs/CALMER_DRIVES.md).

    python -m tools.build_calming windsor 51.33 -0.88 51.62 -0.40
    python -m tools.build_calming windsor 51.33 -0.88 51.62 -0.40 --from overpass.json

Development-time only, like tools/build_walk.py: the app never calls
OpenStreetMap while serving a drive. This writes data/calming/<region>.json,
which the app reads. Refresh it monthly or so; the file says when its data
is from.

Only the traffic calming that lifts or drops the road is kept: hump, bump,
table, cushion, choked table, dip, and plain `traffic_calming=yes`. Islands,
chokers and chicanes narrow the road and are left out.

Traffic lights too (founder, 12 Oct 2026: a stop at lights may wake a baby
more than a bump). Two kinds, counted apart:
  junction    lights at a junction. Every light within JOIN_M of another
              is the same junction: one per approach is usual.
  pedestrian  lights for people crossing, often pressed on demand: a
              signal-controlled crossing, or lights tagged as a pelican,
              puffin, toucan or pegasus crossing. One beside junction
              lights belongs to the junction and isn't counted again.
Each point carries its group, so a drive passing a junction's lights counts
the junction once.

Easy places to turn round (founder, 13 Oct 2026: a turn-around is fine,
better still where it needs no three-point turn, like a loop round a small
island at the end of a street). Each is [lat, lng, kind, radius in metres]:
  roundabout       a roundabout or circular junction (all its ways joined)
  mini_roundabout  a mini-roundabout node
  turning_circle   a turning circle or turning loop node at a street's end
  loop             a road that runs round and rejoins itself, under
                   LOOP_MAX_M round: how most such loops are mapped (no tag)

Source and terms, checked 11 Oct 2026: OpenStreetMap via the Overpass API,
ODbL 1.0, attribution "© OpenStreetMap contributors". The written file is a
derived database under the same licence. Overpass asks for modest use and a
User-Agent that names the project; several public servers are tried in turn,
because the main one is often busy.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

USER_AGENT = "Driftway-dev/0.8 (+https://github.com/stepanchizhov/Driftway; calming extract)"
OVERPASS = [
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
]
VERTICAL = ("hump", "bump", "table", "cushion", "choked_table", "dip", "yes")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "calming")


def download(south: float, west: float, north: float, east: float) -> dict:
    box = f"{south},{west},{north},{east}"
    return download_query(f"[out:json][timeout:150];(node[traffic_calming]({box});"
                          f"way[traffic_calming]({box}););out tags center;")


def download_query(query: str) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for url in OVERPASS:
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=200) as resp:
                body = resp.read()
            if body.lstrip().startswith(b"{"):
                return json.loads(body)
            last = f"{url}: not JSON (busy?)"
        except Exception as e:  # noqa: BLE001
            last = f"{url}: {type(e).__name__}"
        print("  " + last, file=sys.stderr)
    raise SystemExit(f"No Overpass server answered. Last: {last}")


#: Lights this close to each other are one junction or one crossing.
JOIN_M = 40.0
PEDESTRIAN_REFS = {"pelican", "puffin", "toucan", "pegasus"}


def signals_query(south, west, north, east) -> str:
    box = f"{south},{west},{north},{east}"
    return (f"[out:json][timeout:150];(node[highway=traffic_signals]({box});"
            f"node[highway=crossing][crossing=traffic_signals]({box});"
            f'node[crossing_ref~"^(pelican|puffin|toucan|pegasus)$"]({box}););out body;')


def _kind(tags: dict) -> str:
    if tags.get("crossing_ref") in PEDESTRIAN_REFS:
        return "pedestrian"
    if tags.get("highway") == "crossing":
        return "pedestrian"
    if tags.get("traffic_signals") in ("pedestrian_crossing", "crossing"):
        return "pedestrian"
    if tags.get("crossing") not in (None, "no"):
        return "pedestrian"
    return "junction"


def _metres(a, b) -> float:
    k = math.cos(math.radians(a[0]))
    return math.hypot((a[0] - b[0]) * 111320.0, (a[1] - b[1]) * 111320.0 * k)


def extract_signals(raw: dict) -> list:
    """[[lat, lng, kind, group]]: every light, with the junction or crossing
    it belongs to. Pedestrian lights near junction lights join the junction."""
    pts = []
    for e in raw.get("elements", []):
        if e.get("type") == "node":
            pts.append((round(e["lat"], 6), round(e["lon"], 6), _kind(e.get("tags", {}))))
    pts.sort()
    cell = JOIN_M / 111320.0
    grid: dict = {}
    for i, (la, lo, _) in enumerate(pts):
        grid.setdefault((int(la / cell), int(lo / cell)), []).append(i)
    parent = list(range(len(pts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def near(i):
        la, lo, _ = pts[i]
        ci, cj = int(la / cell), int(lo / cell)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for j in grid.get((ci + di, cj + dj), ()):
                    if j != i and _metres(pts[i], pts[j]) <= JOIN_M:
                        yield j

    for i in range(len(pts)):
        for j in near(i):
            parent[find(i)] = find(j)
    # A group with any junction light is a junction; otherwise a crossing.
    group_kind: dict = {}
    for i, p in enumerate(pts):
        g = find(i)
        if p[2] == "junction" or g not in group_kind:
            group_kind[g] = "junction" if p[2] == "junction" else group_kind.get(g, p[2])
    ids: dict = {}
    out = []
    for i, (la, lo, _) in enumerate(pts):
        g = ids.setdefault(find(i), len(ids))
        out.append([la, lo, group_kind[find(i)], g])
    return out


#: Spots and their roads are looked for along these roads (no service roads:
#: car-park aisles are not for turning round in).
TURN_ROADS = "primary|secondary|tertiary|unclassified|residential|living_street"
#: A road loop longer than this round is a block, not a turning loop.
LOOP_MAX_M = 300.0
#: Roundabout pieces this close together are one roundabout.
JOIN_ROUNDABOUT_M = 60.0


def turns_query(south, west, north, east) -> str:
    box = f"{south},{west},{north},{east}"
    return (f"[out:json][timeout:180];("
            f'node[highway~"^(turning_circle|turning_loop|mini_roundabout)$"]({box});'
            f'way[junction~"^(roundabout|circular)$"]({box}););out body geom;')


def loops_query(south, west, north, east) -> str:
    box = f"{south},{west},{north},{east}"
    return f'[out:json][timeout:180];way[highway~"^({TURN_ROADS})$"]({box});out skel geom;'


def _spot(points) -> list:
    """[lat, lng, radius] round a set of (lat, lng)."""
    lat = sum(p[0] for p in points) / len(points)
    lng = sum(p[1] for p in points) / len(points)
    r = max(_metres((lat, lng), p) for p in points)
    return [round(lat, 6), round(lng, 6), round(r)]


def extract_turns(tagged: dict, roads: dict) -> list:
    """[[lat, lng, kind, radius_m]] for every easy place to turn round."""
    out = []
    pieces = []
    for e in tagged.get("elements", []):
        if e.get("type") == "node":
            kind = e.get("tags", {}).get("highway")
            kind = "turning_circle" if kind == "turning_loop" else kind
            out.append([round(e["lat"], 6), round(e["lon"], 6), kind, 10 if kind == "turning_circle" else 8])
        elif e.get("type") == "way" and e.get("geometry"):
            pieces.append([(g["lat"], g["lon"]) for g in e["geometry"]])
    # Roundabouts come in pieces: join pieces whose centres are close.
    groups: list = []
    for pts in pieces:
        c = _spot(pts)
        for g in groups:
            if _metres((c[0], c[1]), (g[0][0], g[0][1])) <= JOIN_ROUNDABOUT_M:
                g[1].extend(pts)
                break
        else:
            groups.append((c, list(pts)))
    for _c, pts in groups:
        lat, lng, r = _spot(pts)
        out.append([lat, lng, "roundabout", r])
    # Road loops: a way that comes back to a node it has already passed.
    for e in roads.get("elements", []):
        nodes, geom = e.get("nodes") or [], e.get("geometry") or []
        if len(nodes) != len(geom):
            continue
        first: dict = {}
        for i, n in enumerate(nodes):
            if n in first:
                loop = [(g["lat"], g["lon"]) for g in geom[first[n]:i + 1]]
                round_m = sum(_metres(a, b) for a, b in zip(loop, loop[1:]))
                if 30.0 <= round_m <= LOOP_MAX_M:
                    lat, lng, r = _spot(loop)
                    out.append([lat, lng, "loop", r])
                break
            first[n] = i
    out.sort()
    return out


def extract(raw: dict) -> list:
    points = []
    for e in raw.get("elements", []):
        kind = e.get("tags", {}).get("traffic_calming")
        if kind not in VERTICAL:
            continue
        if "lat" in e:
            lat, lng = e["lat"], e["lon"]
        elif "center" in e:
            lat, lng = e["center"]["lat"], e["center"]["lon"]
        else:
            continue
        points.append([round(lat, 6), round(lng, 6), kind])
    points.sort()
    return points


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("region")
    ap.add_argument("south", type=float)
    ap.add_argument("west", type=float)
    ap.add_argument("north", type=float)
    ap.add_argument("east", type=float)
    ap.add_argument("--from", dest="source", help="an Overpass JSON response saved earlier")
    ap.add_argument("--signals-from", dest="signals_source",
                    help="an Overpass JSON response for traffic lights saved earlier")
    ap.add_argument("--turns-from", dest="turns_source",
                    help="[tagged, roads] Overpass JSON responses for turning places saved earlier")
    a = ap.parse_args()
    if a.source:
        with open(a.source, encoding="utf-8") as f:
            raw = json.load(f)
    else:
        raw = download(a.south, a.west, a.north, a.east)
    points = extract(raw)
    if a.signals_source:
        with open(a.signals_source, encoding="utf-8") as f:
            sig_raw = json.load(f)
    else:
        sig_raw = download_query(signals_query(a.south, a.west, a.north, a.east))
    signals = extract_signals(sig_raw)
    if a.turns_source:
        with open(a.turns_source, encoding="utf-8") as f:
            tagged, roads = json.load(f)
    else:
        tagged = download_query(turns_query(a.south, a.west, a.north, a.east))
        roads = download_query(loops_query(a.south, a.west, a.north, a.east))
    turns = extract_turns(tagged, roads)
    as_of = raw.get("osm3s", {}).get("timestamp_osm_base") or datetime.now(timezone.utc).isoformat()
    out = {
        "region": a.region,
        "bbox": [a.south, a.west, a.north, a.east],
        "as_of": as_of,
        "source": "OpenStreetMap via the Overpass API",
        "licence": "ODbL 1.0",
        "attribution": "© OpenStreetMap contributors",
        "kinds": list(VERTICAL),
        "points": points,
        "signals_as_of": sig_raw.get("osm3s", {}).get("timestamp_osm_base") or as_of,
        "signal_kinds": ["junction", "pedestrian"],
        "signals": signals,
        "turn_kinds": ["roundabout", "mini_roundabout", "turning_circle", "loop"],
        "turns": turns,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{a.region}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
        f.write("\n")
    groups = {}
    for _, _, kind, g in signals:
        groups[g] = kind
    print(f"data/calming/{a.region}.json: {len(points)} points, data as of {as_of}; "
          f"{len(signals)} lights in {sum(1 for k in groups.values() if k == 'junction')} junctions "
          f"and {sum(1 for k in groups.values() if k == 'pedestrian')} crossings; "
          f"{len(turns)} easy places to turn round "
          f"({', '.join(f'{k} {sum(1 for t in turns if t[2] == k)}' for k in ('roundabout', 'mini_roundabout', 'turning_circle', 'loop'))})")


if __name__ == "__main__":
    main()

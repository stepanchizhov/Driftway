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

Source and terms, checked 11 Oct 2026: OpenStreetMap via the Overpass API,
ODbL 1.0, attribution "© OpenStreetMap contributors". The written file is a
derived database under the same licence. Overpass asks for modest use and a
User-Agent that names the project; several public servers are tried in turn,
because the main one is often busy.
"""

from __future__ import annotations

import argparse
import json
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
    query = (f"[out:json][timeout:150];(node[traffic_calming]({box});"
             f"way[traffic_calming]({box}););out tags center;")
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
    a = ap.parse_args()
    if a.source:
        with open(a.source, encoding="utf-8") as f:
            raw = json.load(f)
    else:
        raw = download(a.south, a.west, a.north, a.east)
    points = extract(raw)
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
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{a.region}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
        f.write("\n")
    print(f"data/calming/{a.region}.json: {len(points)} points, data as of {as_of}")


if __name__ == "__main__":
    main()

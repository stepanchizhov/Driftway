"""
How TomTom's drive times compare with Google's on the same roads
(founder, 23 Oct 2026: "Normally, I was getting to the destination a bit too
early and had to manually add more to the route in Google Maps").

    python -m tools.time_check --pairs 40          # live TomTom and Google
    python -m tools.time_check --uturns 15         # what turning round costs each

Random trips of 3 to 12 km inside a few areas (Windsor, Woking, Southampton,
the Isle of Wight), each timed by TomTom and by Google one after the other:
the plain fastest way, and a quieter one (TomTom avoiding motorways, Google
avoiding highways). A pair counts only where both take the same roads (at
least 80% of TomTom's line within 30 m of Google's, distances within 8%), so
what differs is the timing, not the route. Written to
data/google_compare/timing.json as summary numbers only: no coordinates, no
Google line, no key. One TomTom routing and one Google Routes request per
trip and kind.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import statistics
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

from tools.google_compare import OUT, ROOT, ROUTES_URL, FIELD_MASK, decode_polyline, overlap

#: Areas, south-west-north-east: where Driftway is used now.
AREAS = {
    "windsor": (51.43, -0.75, 51.53, -0.52),
    "woking": (51.25, -0.65, 51.35, -0.45),
    "southampton": (50.88, -1.48, 50.96, -1.32),
    "isle-of-wight": (50.62, -1.45, 50.76, -1.10),
}
SAME_OVERLAP = 0.8
SAME_KM = 0.08
#: Average speed bands on TomTom's own time, km/h.
BANDS = [(0, 25), (25, 35), (35, 45), (45, 60), (60, 200)]


def _km(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def trips(n: int, seed: int = 23) -> List[Dict]:
    rnd = random.Random(seed)
    names = list(AREAS)
    out = []
    while len(out) < n:
        area = names[len(out) % len(names)]
        s, w, nn, e = AREAS[area]
        a = (rnd.uniform(s, nn), rnd.uniform(w, e))
        b = (rnd.uniform(s, nn), rnd.uniform(w, e))
        if 3.0 <= _km(a, b) <= 12.0:
            out.append({"area": area, "start": a, "finish": b})
    return out


def google_body(start, finish, quiet: bool) -> Dict:
    point = lambda p: {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}  # noqa: E731
    body = {"origin": point(start), "destination": point(finish), "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE", "polylineQuality": "HIGH_QUALITY"}
    if quiet:
        body["routeModifiers"] = {"avoidHighways": True}
    return body


async def ask_google(client, start, finish, quiet, key) -> Optional[Dict]:
    resp = await client.post(ROUTES_URL, json=google_body(start, finish, quiet),
                             headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELD_MASK})
    if resp.status_code != 200:
        print(f"  Google answered {resp.status_code}", file=sys.stderr)
        return None
    routes = resp.json().get("routes") or []
    return routes[0] if routes else None


async def run(n: int) -> List[Dict]:
    import httpx
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    key = (os.getenv("GOOGLE_ROUTES_API_KEY") or "").strip()
    if not key:
        raise SystemExit("GOOGLE_ROUTES_API_KEY is not set in backend/.env: see docs/GOOGLE_COMPARISON.md.")
    from core.models import Coord
    from core.router import get_router
    router = get_router()
    rows = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        for i, t in enumerate(trips(n)):
            start, finish = Coord(lat=t["start"][0], lng=t["start"][1]), Coord(lat=t["finish"][0], lng=t["finish"][1])
            for kind in ("fastest", "quiet"):
                ours = await (router.evaluate_as_navigation(start, finish, []) if kind == "fastest"
                              else router.evaluate(start, finish, [], "quiet"))
                if ours is None or not ours.live_traffic or not ours.geometry:
                    continue
                try:
                    g = await ask_google(client, t["start"], t["finish"], kind == "quiet", key)
                except httpx.HTTPError as e:
                    print(f"  trip {i}: {type(e).__name__}", file=sys.stderr)   # never the URL or headers
                    continue
                if not g or "polyline" not in g:
                    continue
                line = decode_polyline(g["polyline"]["encodedPolyline"])
                g_min = float(str(g.get("duration", "0s")).rstrip("s")) / 60.0
                g_km = g.get("distanceMeters", 0) / 1000.0
                share = overlap([(p.lat, p.lng) for p in ours.geometry], line)
                rows.append({
                    "area": t["area"], "kind": kind,
                    "tomtom_min": round(ours.minutes, 1), "google_min": round(g_min, 1),
                    "tomtom_km": round(ours.distance_km, 1), "google_km": round(g_km, 1),
                    "overlap": round(share, 2),
                    "same_roads": share >= SAME_OVERLAP and abs(g_km - ours.distance_km) <= SAME_KM * ours.distance_km,
                    "tomtom_kmh": round(ours.distance_km / (ours.minutes / 60.0), 1) if ours.minutes else None,
                })
            print(f"  trip {i + 1}/{n} done", file=sys.stderr)
    return rows


async def uturns(n: int) -> List[Dict]:
    """What turning round costs, as each provider times it: out to a point on
    a real road and back as two trips, against the same as one route turning
    round there (found 23 Oct 2026: TomTom adds about 2 minutes on the A308).
    Three TomTom and three Google requests per point."""
    import httpx
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    key = (os.getenv("GOOGLE_ROUTES_API_KEY") or "").strip()
    if not key:
        raise SystemExit("GOOGLE_ROUTES_API_KEY is not set in backend/.env: see docs/GOOGLE_COMPARISON.md.")
    from core.models import Coord
    from core.router import get_router
    router = get_router()
    rows = []

    def gtime(g):
        return float(str(g.get("duration", "0s")).rstrip("s")) / 60.0 if g else None

    async with httpx.AsyncClient(timeout=20.0) as client:
        async def google(points):
            pt = lambda p: {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}  # noqa: E731
            body = {"origin": pt(points[0]), "destination": pt(points[-1]),
                    "intermediates": [{**pt(p), "via": False} for p in points[1:-1]],
                    "travelMode": "DRIVE", "routingPreference": "TRAFFIC_AWARE"}
            resp = await client.post(ROUTES_URL, json=body, headers={
                "X-Goog-Api-Key": key, "X-Goog-FieldMask": "routes.duration,routes.distanceMeters"})
            routes = resp.json().get("routes") if resp.status_code == 200 else None
            return routes[0] if routes else None

        for i, t in enumerate(trips(n, seed=31)):
            a = Coord(lat=t["start"][0], lng=t["start"][1])
            far = Coord(lat=t["finish"][0], lng=t["finish"][1])
            out = await router.evaluate_as_navigation(a, far, [])
            if out is None or not out.live_traffic or len(out.geometry) < 3:
                continue
            b = out.geometry[len(out.geometry) // 2]           # on a real road
            go = await router.evaluate_as_navigation(a, b, [])
            back = await router.evaluate_as_navigation(b, a, [])
            both = await router.evaluate_as_navigation(a, a, [b])
            pa, pb = (a.lat, a.lng), (b.lat, b.lng)
            g_go, g_back, g_both = await google([pa, pb]), await google([pb, pa]), await google([pa, pb, pa])
            if None in (go, back, both, g_go, g_back, g_both):
                continue
            rows.append({
                "area": t["area"],
                "tomtom_turn_min": round(both.minutes - go.minutes - back.minutes, 1),
                "tomtom_extra_km": round(both.distance_km - go.distance_km - back.distance_km, 1),
                "tomtom_uturn": both.has_uturn,
                "google_turn_min": round(gtime(g_both) - gtime(g_go) - gtime(g_back), 1),
                "google_extra_km": round((g_both["distanceMeters"] - g_go["distanceMeters"]
                                          - g_back["distanceMeters"]) / 1000.0, 1),
            })
            print(f"  point {i + 1}/{n} done", file=sys.stderr)
    return rows


def summary(rows: List[Dict]) -> Dict:
    same = [r for r in rows if r["same_roads"] and r["tomtom_min"] > 0]
    ratio = lambda r: r["google_min"] / r["tomtom_min"]  # noqa: E731
    out = {"trips_compared": len(rows), "same_roads": len(same),
           "google_over_tomtom_median": round(statistics.median(map(ratio, same)), 2) if same else None,
           "by_kind": {}, "by_area": {}, "by_speed": []}
    for kind in ("fastest", "quiet"):
        xs = [ratio(r) for r in same if r["kind"] == kind]
        out["by_kind"][kind] = {"n": len(xs), "median": round(statistics.median(xs), 2) if xs else None}
    for area in AREAS:
        xs = [ratio(r) for r in same if r["area"] == area]
        out["by_area"][area] = {"n": len(xs), "median": round(statistics.median(xs), 2) if xs else None}
    for lo, hi in BANDS:
        xs = [ratio(r) for r in same if r["tomtom_kmh"] and lo <= r["tomtom_kmh"] < hi]
        out["by_speed"].append({"tomtom_kmh": f"{lo}-{hi}", "n": len(xs),
                                "median": round(statistics.median(xs), 2) if xs else None})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pairs", type=int, default=40)
    ap.add_argument("--uturns", type=int, default=0, help="instead: what turning round costs, at this many points")
    a = ap.parse_args()
    if a.uturns:
        rows = asyncio.run(uturns(a.uturns))
        same_way = [r for r in rows if abs(r["tomtom_extra_km"]) < 0.2 and abs(r["google_extra_km"]) < 0.2]
        med = lambda k, rs: round(statistics.median(r[k] for r in rs), 1) if rs else None  # noqa: E731
        result = {"timed_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                  "points": len(rows), "turning_on_the_spot": len(same_way),
                  "tomtom_turn_min_median": med("tomtom_turn_min", same_way),
                  "google_turn_min_median": med("google_turn_min", same_way),
                  "rows": rows}
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "uturns.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=1))
        for r in rows:
            print(r)
        return
    rows = asyncio.run(run(a.pairs))
    result = {"timed_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
              "summary": summary(rows), "rows": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "timing.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result["summary"], indent=1))


if __name__ == "__main__":
    main()

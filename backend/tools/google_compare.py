"""
Driftway's drives against Google's routes through the same waypoints
(docs/GOOGLE_COMPARISON.md; founder, 12 Oct 2026; harness 15 Oct 2026).

Two questions, never confused:

  A. How does a Google Routes API calculation through Driftway's exported
     waypoints differ from Driftway's own final drive?  This harness.
  B. What does the Google Maps app or browser actually do with the link?
     Only a phone can say: docs/GOOGLE_COMPARISON.md has the checklist.

What is compared is what Google gets: the start, the finish and the
waypoints in the drive's Google Maps link (at most three; Maps URLs allow
three on mobile browsers, read 15 Oct 2026), in order, as STOPOVERS (the
Routes API's default; Maps URLs don't say whether link waypoints are stops
or pass-through points, and a stop is the cautious reading). Not Driftway's
internal shaping points.

    python -m tools.google_compare prepare             # live TomTom: builds the cases
    python -m tools.google_compare run --limit 5       # live Google: needs the key
    python -m tools.google_compare report              # offline: the table again

`prepare` plans each case with Driftway as it runs in production (TomTom,
steering, moved turn-backs, the 2-minute bound) and writes
data/google_compare/cases.json: public start points only. `run` asks Google
for each case (one request each, `--limit` of them) with the key in
GOOGLE_ROUTES_API_KEY in backend/.env, entered by the founder; the key is
never printed, logged or written. Results go to data/google_compare/results.json
without any key or Google polyline (Google's terms: results are not kept
beyond the study; only our summary numbers are).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "google_compare"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,routes.legs.distanceMeters"
#: A point of Driftway's drive this close to Google's line is on it.
ON_LINE_M = 30.0

#: Public places only (stations, a leisure centre, village centres, a park
#: gate), around Windsor where speed bumps and lights are prepared. Chosen to
#: include steered drives, moved turn-backs, three-waypoint shapes, a
#: one-way drive, both road styles and two lengths.
CASES = [
    {"id": "windsor-central-30-mixed", "start": [51.4834, -0.6105], "minutes": 30, "profile": "mixed"},
    {"id": "dedworth-30-mixed", "start": [51.4815, -0.6440], "minutes": 30, "profile": "mixed"},
    {"id": "eton-wick-30-quiet", "start": [51.4930, -0.6470], "minutes": 30, "profile": "quiet"},
    {"id": "englefield-green-30-mixed", "start": [51.4300, -0.5700], "minutes": 30, "profile": "mixed"},
    {"id": "holyport-45-quiet", "start": [51.4960, -0.7040], "minutes": 45, "profile": "quiet"},
    {"id": "windsor-central-30-quiet", "start": [51.4834, -0.6105], "minutes": 30, "profile": "quiet"},
    {"id": "great-park-30-mixed", "start": [51.4600, -0.6230], "minutes": 30, "profile": "mixed"},
    {"id": "windsor-to-maidenhead-35", "start": [51.4834, -0.6105], "finish": [51.5188, -0.7225],
     "minutes": 35, "profile": "mixed"},
]


# ---------------------------------------------------------------- geometry

def decode_polyline(s: str) -> List[Tuple[float, float]]:
    """Google's encoded polyline (precision 5) as [(lat, lng)]."""
    out, i, lat, lng = [], 0, 0, 0
    while i < len(s):
        vals = []
        for _ in range(2):
            shift = result = 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            vals.append(~(result >> 1) if result & 1 else result >> 1)
        lat += vals[0]
        lng += vals[1]
        out.append((lat / 1e5, lng / 1e5))
    return out


def _xy(p, k):
    return p[1] * k * 111320.0, p[0] * 111320.0


def overlap(ours: Sequence[Tuple[float, float]], theirs: Sequence[Tuple[float, float]],
            within_m: float = ON_LINE_M) -> float:
    """Share of our drive, by length, within `within_m` of their line."""
    if len(ours) < 2 or len(theirs) < 2:
        return 0.0
    k = math.cos(math.radians(ours[0][0]))
    segs = [(_xy(a, k), _xy(b, k)) for a, b in zip(theirs, theirs[1:])]

    def near(p):
        px, py = _xy(p, k)
        for (ax, ay), (bx, by) in segs:
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
            if math.hypot(ax + t * dx - px, ay + t * dy - py) <= within_m:
                return True
        return False

    total = kept = 0.0
    for a, b in zip(ours, ours[1:]):
        (ax, ay), (bx, by) = _xy(a, k), _xy(b, k)
        d = math.hypot(bx - ax, by - ay)
        total += d
        if near(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)):
            kept += d
    return kept / total if total else 0.0


def stops_on(line: Sequence[Tuple[float, float]], anchors: Sequence[Tuple[float, float]]) -> Dict:
    """Mapped stops on a line, the way Driftway counts them (bumps, lights,
    turn-arounds at the waypoints). Roadworks are left out: they change by
    the hour, and the two lines are not driven at the same moment."""
    from core import calming, scorer
    from core.models import Coord, RoadMix
    from core.router import EvaluatedRoute
    ev = EvaluatedRoute(anchors=[Coord(lat=a[0], lng=a[1]) for a in anchors], minutes=0, distance_km=0,
                        road_mix=RoadMix(), geometry=[Coord(lat=p[0], lng=p[1]) for p in line], works=[])
    b, li = calming.count_along(ev.geometry), calming.lights_along(ev.geometry)
    return {"bumps": b.count if b else None, "lights": li.total if li else None,
            "turn_arounds": scorer.turnaround_waypoints(ev)}


# ---------------------------------------------------------------- Google

def request_body(case: Dict) -> Dict:
    """The Routes API request for a prepared case: its exported waypoints,
    in order, as stopovers."""
    point = lambda p: {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}  # noqa: E731
    return {
        "origin": point(case["start"]),
        "destination": point(case.get("finish") or case["start"]),
        "intermediates": [{**point(w), "via": False} for w in case["waypoints"]],
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "polylineQuality": "HIGH_QUALITY",
    }


async def ask_google(client, case: Dict, key: str) -> Optional[Dict]:
    """One Routes API call; None on failure (the reason by status code only)."""
    resp = await client.post(ROUTES_URL, json=request_body(case),
                             headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELD_MASK})
    if resp.status_code != 200:
        print(f"  {case['id']}: Google answered {resp.status_code}", file=sys.stderr)
        return None
    routes = resp.json().get("routes") or []
    return routes[0] if routes else None


def compare(case: Dict, google: Dict) -> Dict:
    line = decode_polyline(google["polyline"]["encodedPolyline"])
    ours = [tuple(p) for p in case["geometry"]]
    g_minutes = float(str(google.get("duration", "0s")).rstrip("s")) / 60.0
    g_stops = stops_on(line, case["waypoints"])
    return {
        "id": case["id"], "built_by": case.get("built_by") or "plain",
        "waypoints": len(case["waypoints"]),
        "ours_minutes": case["minutes_routed"], "google_minutes": round(g_minutes, 1),
        "ours_km": case["km"], "google_km": round(google.get("distanceMeters", 0) / 1000.0, 1),
        "overlap_ours_on_google": round(overlap(ours, line), 2),
        "overlap_google_on_ours": round(overlap(line, ours), 2),
        "ours_stops": case["stops"], "google_stops": g_stops,
    }


# ---------------------------------------------------------------- commands

async def prepare(cases: List[Dict]) -> List[Dict]:
    """Plan each case with Driftway, live, and keep what Google would get."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from core import roadworks
    from core.generator import generate_routes
    from core.models import Coord, GenerateRequest
    from core.router import get_router
    import core.generator as G

    out = []
    for c in cases:
        start = Coord(lat=c["start"][0], lng=c["start"][1])
        finish = Coord(lat=c["finish"][0], lng=c["finish"][1]) if c.get("finish") else None
        req = GenerateRequest(start=start, finish=finish, target_minutes=c["minutes"],
                              tolerance_minutes=10, road_profile=c["profile"])
        firsts: List = []
        real = G._pick_top_three

        def spy(*a, **kw):
            top = real(*a, **kw)
            firsts[:] = top[:1]
            return top
        G._pick_top_three = spy
        try:
            with roadworks.lookup_for_request(None):
                res = await generate_routes(req, get_router())
        finally:
            G._pick_top_three = real
        if not res.routes or not firsts:
            print(f"  {c['id']}: no drive", file=sys.stderr)
            continue
        r, ev = res.routes[0], firsts[0]
        waypoints = _link_waypoints(r)          # exactly what the link hands Google
        out.append({
            **c, "prepared_on": date.today().isoformat(),
            "waypoints": waypoints, "google_maps_url": _link(r),
            "minutes_routed": round(ev.minutes, 1), "km": round(ev.distance_km, 1),
            "built_by": getattr(ev, "built_by", "") or "plain",
            "geometry": [[round(p.lat, 6), round(p.lng, 6)] for p in ev.geometry],
            "stops": stops_on([(p.lat, p.lng) for p in ev.geometry], waypoints),
        })
        print(f"  {c['id']}: {out[-1]['minutes_routed']} min, {len(waypoints)} waypoints, {out[-1]['built_by']}")
    return out


def _link(option) -> str:
    for n in option.navigation:
        if n.provider_id == "google_maps":
            return n.url
    return ""


def _link_waypoints(option) -> List[List[float]]:
    """The waypoints in the drive's Google Maps link, in order."""
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(_link(option)).query)
    raw = (q.get("waypoints") or [""])[0]
    return [[float(x) for x in w.split(",")] for w in raw.split("|") if w]


async def run(cases: List[Dict], limit: int) -> List[Dict]:
    import httpx
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    key = (os.getenv("GOOGLE_ROUTES_API_KEY") or "").strip()
    if not key:
        raise SystemExit("GOOGLE_ROUTES_API_KEY is not set in backend/.env: see docs/GOOGLE_COMPARISON.md.")
    out = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        for c in cases[:limit]:
            try:
                g = await ask_google(client, c, key)
            except httpx.HTTPError as e:
                print(f"  {c['id']}: {type(e).__name__}", file=sys.stderr)   # never the URL or headers
                continue
            if g:
                out.append(compare(c, g))
    return out


def report(results: List[Dict]) -> None:
    print(f"{'case':28} {'built':10} wp  ours/google min   km          overlap  bumps     lights    turns")
    for r in results:
        o, g = r["ours_stops"], r["google_stops"]
        print(f"{r['id']:28} {r['built_by']:10} {r['waypoints']:2}  {r['ours_minutes']:5}/{r['google_minutes']:<5}  "
              f"{r['ours_km']:5}/{r['google_km']:<5}  {r['overlap_ours_on_google']:.2f}     "
              f"{o['bumps']}/{g['bumps']:<6} {o['lights']}/{g['lights']:<6} {o['turn_arounds']}/{g['turn_arounds']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=["prepare", "run", "report"])
    ap.add_argument("--limit", type=int, default=5, help="Google requests at most (run)")
    ap.add_argument("--only", default="", help="prepare: these case ids only, kept with the others")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cases_path, results_path = OUT / "cases.json", OUT / "results.json"
    if a.command == "prepare":
        only = {x for x in a.only.split(",") if x}
        kept = ([c for c in json.loads(cases_path.read_text(encoding="utf-8")) if c["id"] not in only]
                if only and cases_path.exists() else [])
        fresh = asyncio.run(prepare([c for c in CASES if not only or c["id"] in only]))
        order = [c["id"] for c in CASES]
        cases = sorted(kept + fresh, key=lambda c: order.index(c["id"]) if c["id"] in order else 99)
        cases_path.write_text(json.dumps(cases, indent=1), encoding="utf-8")
        print(f"{len(cases)} cases written to {cases_path.relative_to(ROOT)}")
    elif a.command == "run":
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        results = asyncio.run(run(cases, a.limit))
        results_path.write_text(json.dumps(results, indent=1), encoding="utf-8")
        report(results)
    else:
        report(json.loads(results_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()

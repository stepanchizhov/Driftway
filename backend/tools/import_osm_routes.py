"""
Turn walking routes mapped in OpenStreetMap into curated walks.

    python -m tools.import_osm_routes 51.40 -0.75 51.55 -0.50            # write specs, build
    python -m tools.import_osm_routes 51.40 -0.75 51.55 -0.50 --specs-only

Founder question, 11 Oct 2026: curation by one person doesn't scale. Around
Windsor, OpenStreetMap already maps 25 walking routes, several of them family
and accessible trails by the National Trust. This writes one reviewable spec
per suitable route to data/walks/specs/ (`osm_relation`: the route followed
along its own member paths) and builds it with tools/build_walk.py, so each
is judged by the same rules as every other curated walk.

Which routes: local walking routes (network=lwn) marked circular
(roundtrip=yes), up to MAX_KM long. Long-distance trails are not walks a
parent picks for a nap.

What is copied: the route line, its name, operator, distance, suggested
time, start and website, all from OpenStreetMap (ODbL). Not copied: the
`description` text, which often repeats the operator's own wording; the
summary is written here from the facts, and the walk links to the operator.

Existing specs are left alone unless --force, so a spec edited by hand
(a better start label, a note from walking it) is never overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.build_walk import _overpass, build, fetch_relation, haversine, osgb_to_wgs84  # noqa: E402

SPECS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "walks", "specs")
MAX_KM = 8.0


def _km(raw: str):
    m = re.search(r"[\d.]+", raw or "")
    if not m:
        return None
    v = float(m.group())
    return v / 1000 if "m" in raw and "km" not in raw and v > 50 else v


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def _duration(raw: str):
    """ "00:45" -> "45 minutes"; "01:30-02:00" -> "1 h 30 to 2 h". """
    def one(t):
        h, m = (int(x) for x in t.split(":"))
        if not h:
            return f"{m} minutes"
        return f"{h} h" + (f" {m}" if m else "")
    try:
        parts = [one(p) for p in raw.split("-")]
    except Exception:  # noqa: BLE001
        return None
    return " to ".join(parts)


#: A built walk is the trail only if it is close to the trail's own mapped
#: paths: going round gaps may add a little, never much. Tested on 13 trails
#: around Windsor, 11 Oct 2026: the faithful ones added under 5% and had at
#: most 2 gaps; the rest were missing paths or listed them out of order.
GAPS_MAX = 2
EXTRA_SHARE = 0.15
EXTRA_M = 200
MAPPED_MIN_SHARE = 0.7


def faithful(built_km: float, mapped_km: float, stated_km, notes) -> str:
    """Why this built walk is not the trail, or "" if it is."""
    gaps = 0
    for n in notes:
        m = re.search(r"has (\d+) places? where its paths don't join", n)
        if m:
            gaps = int(m.group(1))
    if gaps > GAPS_MAX:
        return f"{gaps} places where the mapped paths don't join; the route may be incomplete or out of order in OpenStreetMap"
    if built_km > mapped_km * (1 + EXTRA_SHARE) + EXTRA_M / 1000:
        return (f"built {built_km:.1f} km from {mapped_km:.1f} km of mapped paths: "
                "going round the gaps adds too much")
    if stated_km and mapped_km < stated_km * MAPPED_MIN_SHARE:
        return (f"only {mapped_km:.1f} km of the stated {stated_km:g} km is mapped "
                "as part of the route")
    return ""


def spec_for(rel: dict, circular: bool = True, id_with_relation: bool = False) -> dict:
    t = rel["tags"]
    name = t["name"].strip()
    # The id follows the name as mapped, so it stays put when the display
    # name is tidied below or by hand in the spec. Walks built for areas
    # anywhere also carry the relation number: two places can each have a
    # "Circular Route".
    walk_id = ("osm-" + (f"{rel['id']}-" if id_with_relation else "") + _slug(name))[:80]
    operator = (t.get("operator") or "").split(";")[0].strip()
    km = _km(t.get("distance", ""))
    start_text, start_near = None, None
    if t.get("from"):
        bits = [b.strip() for b in t["from"].split(";")]
        start_text = ", ".join(b.strip() for b in bits[0].split(",")[:2])
        for b in bits[1:]:
            ll = osgb_to_wgs84(b)
            if ll:
                start_near = [round(ll[0], 6), round(ll[1], 6)]
                break
    area = name.split(",")[-1].strip() if "," in name else ""
    # "Cliveden Blue Walking Trail, Cliveden": the place is shown as the area.
    name = name.split(",")[0].strip() if area else name
    who = f"{operator}'s" if operator else "A"
    kind = "circular trail" if circular else "trail, walked there and back"
    summary = f"{who} {kind}" + (f", about {km:g} km" if km else "")
    summary += f", from {start_text}." if start_text else "."
    notes = [
        "Route line from OpenStreetMap, built on the date shown. Nobody from "
        "Driftway has walked it, so surfaces and barriers are as mapped, not as found.",
    ]
    if operator:
        notes.append(f"The trail is {operator}'s. Check their page on the day for "
                     "opening times, parking, livestock and conditions"
                     + (f": {t['website']}" if t.get("website") else "."))
    dur = _duration(t["duration"]) if t.get("duration") else None
    if dur:
        notes.append(f"{operator or 'Its operator'} suggests about {dur}.")
    spec = {
        "id": walk_id,
        "name": name,
        "area": area,
        "summary": summary,
        "shape": "loop" if circular else "out_and_back",
        "start_label": start_text or f"Start of the {name}",
        "osm_relation": rel["id"],
        "notes": notes,
    }
    if start_near:
        spec["start_near"] = start_near
    return spec


def _mapped_km(rel_full: dict) -> float:
    return sum(haversine((a["lat"], a["lon"]), (b["lat"], b["lon"]))
               for w in rel_full["ways"].values() if "highway" in w.get("tags", {})
               for a, b in zip(w["geometry"], w["geometry"][1:])) / 1000


def _ends_apart_m(rel_full: dict) -> float:
    """How far apart the route's two loose ends are: 0 for a closed loop.
    Every node used once by the member paths is a loose end."""
    count: dict = {}
    where: dict = {}
    for w in rel_full["ways"].values():
        if "highway" not in w.get("tags", {}):
            continue
        for end, g in ((w["nodes"][0], w["geometry"][0]), (w["nodes"][-1], w["geometry"][-1])):
            count[end] = count.get(end, 0) + 1
            where[end] = (g["lat"], g["lon"])
    loose = [where[n] for n, c in count.items() if c == 1]
    if len(loose) < 2:
        return 0.0
    return max(haversine(a, b) for a in loose for b in loose)


def import_area(south: float, west: float, north: float, east: float, *,
                specs_dir: str = SPECS, out_dir: Optional[str] = None,
                force: bool = False, broad: bool = False, max_routes: int = 40,
                say=print) -> List[dict]:
    """Build the walking routes mapped in an area into curated walks.

    The default is what was used around Windsor: local routes marked circular.
    `broad` is for areas anywhere (the scheduled job): any walking route
    whose own paths are short enough, circular if it says so or its ends
    meet, otherwise walked there and back.

    Returns one result per route considered: {"id", "status": built | held |
    skip | keep | fail, "reason", "out", "relation"}."""
    box = f"{south},{west},{north},{east}"
    tags = "" if broad else "[network=lwn][roundtrip=yes]"
    data = _overpass(f'[out:json][timeout:120];relation[type=route]'
                     f'[route~"^(hiking|foot|walking)$"]{tags}({box});out tags;')
    rels = [e for e in data["elements"] if e.get("tags", {}).get("name")]
    # Stated length first, unknown last: short trails are the ones that fit.
    rels.sort(key=lambda e: (_km(e["tags"].get("distance", "")) or 99, e["tags"]["name"]))
    os.makedirs(specs_dir, exist_ok=True)
    results: List[dict] = []
    for rel in rels[:max_routes]:
        name = rel["tags"]["name"]
        km = _km(rel["tags"].get("distance", ""))
        if km and km > MAX_KM:
            results.append({"id": None, "status": "skip", "reason": f"{name}: {km:g} km", "relation": rel["id"]})
            say(f"skip  {name}: {km:g} km")
            continue
        full = fetch_relation(rel["id"])
        mapped_km = _mapped_km(full)
        if mapped_km > MAX_KM * 1.25 or mapped_km < 0.3:
            results.append({"id": None, "status": "skip", "relation": rel["id"],
                            "reason": f"{name}: its paths add up to {mapped_km:.1f} km"})
            say(f"skip  {name}: its paths add up to {mapped_km:.1f} km")
            continue
        circular = rel["tags"].get("roundtrip") == "yes" or (broad and _ends_apart_m(full) <= 300)
        if not broad and not circular:
            continue
        spec = spec_for(rel, circular=circular, id_with_relation=broad)
        path = os.path.join(specs_dir, spec["id"] + ".spec.json")
        if os.path.exists(path) and not force:
            with open(path, encoding="utf-8") as f:
                spec = json.load(f)
            say(f"keep  {spec['id']} (spec exists)")
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(spec, f, indent=2, ensure_ascii=False)
                f.write("\n")
        try:
            out = build(path, out_dir) if out_dir else build(path)
            with open(out, encoding="utf-8") as f:
                built = json.load(f)
            length = built["sections"][-1]["to_m"] / 1000 if built["sections"] else 0
            if not circular:
                length *= 2          # walked there and back
                mapped = mapped_km * 2
            else:
                mapped = mapped_km
            problem = faithful(length, mapped, (km * (1 if circular else 2)) if km else None,
                               built["notes"])
            if problem:
                # Not the trail: held back, with the reason in its spec.
                os.remove(out)
                spec["review"] = problem
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(spec, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                results.append({"id": spec["id"], "status": "held", "reason": problem,
                                "relation": rel["id"]})
                say(f"held  {spec['id']}: {problem}")
            else:
                spec.pop("review", None)
                results.append({"id": spec["id"], "status": "built", "out": out,
                                "relation": rel["id"], "reason": f"{length:.1f} km"})
                say(f"built {spec['id']}: {length:.1f} km" + (f" (stated {km:g} km)" if km else ""))
        except Exception as e:  # noqa: BLE001
            results.append({"id": spec["id"], "status": "fail", "relation": rel["id"],
                            "reason": f"{type(e).__name__}: {e}"[:300]})
            say(f"FAIL  {spec['id']}: {type(e).__name__}: {e}")
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    for k in ("south", "west", "north", "east"):
        ap.add_argument(k, type=float)
    ap.add_argument("--force", action="store_true", help="overwrite existing specs")
    ap.add_argument("--broad", action="store_true",
                    help="any short walking route, not only local circular ones")
    a = ap.parse_args()
    import_area(a.south, a.west, a.north, a.east, force=a.force, broad=a.broad)


if __name__ == "__main__":
    main()

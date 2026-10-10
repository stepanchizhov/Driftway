"""
Curated walks, and what each one means for a given pram or carrier.

The routes are curated, not generated, and that is the honest state of the
evidence rather than a stopgap: automatic pram suitability needs surface data
that OpenStreetMap mostly does not hold here (8 Oct 2026 audit: 25% of central
Windsor paths record a surface, 0.5% record smoothness). A curated route can
carry a founder's dated observations alongside what the map says; a generated
one could only repeat the gaps.

Each route file lives in backend/data/walks/ and is produced by
backend/tools/build_walk.py, so every section traces back to a source.
"""

from __future__ import annotations

import json
import math
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from .evidence import (
    Barrier,
    BarrierKind,
    Evidence,
    Gradient,
    Section,
    Status,
    Surface,
)
from .profiles import (
    CarrierSetup,
    Finding,
    PramSetup,
    SectionAssessment,
    Verdict,
    assess_carrier,
    assess_pram,
    assess_walker,
)

log = logging.getLogger("driftway")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data", "walks")

#: HYPOTHESIS. Stated on every card rather than hidden in a number.
PACE_KMH = 4.0
#: HYPOTHESIS. Naismith's rule: about a minute per ten metres climbed.
MIN_PER_10M_ASCENT = 1.0


@dataclass
class Route:
    id: str
    name: str
    area: str
    summary: str
    shape: str                      # "loop" | "out_and_back"
    start: Dict
    sections: List[Section]
    sources: List[Dict]
    built_on: str
    #: True for fixtures that exist to exercise the code. Never navigable,
    #: never presented as a real walk.
    sample: bool = False
    notes: List[str] = field(default_factory=list)
    #: Share of the walk along streets and roads, where the source reports
    #: way types (generated walks); None when it is not known.
    road_share: Optional[float] = None
    #: A place the walk goes through, chosen by the walker: {lat, lng, label}.
    via: Optional[Dict] = None

    @property
    def outbound_m(self) -> float:
        return self.sections[-1].to_m if self.sections else 0.0


def _section_from(raw: Dict) -> Section:
    s = Section(
        from_m=raw["from_m"], to_m=raw["to_m"], label=raw.get("label", ""),
        geometry=raw.get("geometry", []),
        surface=Surface(raw.get("surface", "unknown")),
        access_restricted=bool(raw.get("access_restricted")),
    )
    for e in raw.get("evidence", []):
        s.evidence.append(Evidence(e["attribute"], e["value"], Status(e["status"]),
                                   e["source"], e.get("observed_on"), e.get("note")))
    for h in raw.get("hazards", []):
        s.hazards.append(Evidence("hazard", h["value"], Status(h["status"]),
                                  h["source"], h.get("observed_on"), h.get("note")))
    for b in raw.get("barriers", []):
        s.barriers.append(Barrier(
            BarrierKind(b["kind"]), b["at_m"], Status(b["status"]), b["source"],
            b.get("width_cm"), b.get("step_count"), b.get("has_ramp"), b.get("note")))
    g = raw.get("gradient")
    if g:
        s.gradient = Gradient(g["ascent_m"], g["descent_m"], g["steepest_up_pct"],
                              g["steepest_down_pct"], Status(g["status"]), g["source"])
    return s


def route_from_dict(raw: Dict) -> Route:
    return Route(
        id=raw["id"], name=raw["name"], area=raw.get("area", ""),
        summary=raw.get("summary", ""), shape=raw.get("shape", "loop"),
        start=raw["start"], sections=[_section_from(s) for s in raw["sections"]],
        sources=raw.get("sources", []), built_on=raw.get("built_on", ""),
        sample=bool(raw.get("sample")), notes=raw.get("notes", []),
    )


def load_routes(directory: str = DATA_DIR) -> List[Route]:
    """Every curated walk on disk. A malformed file is skipped and logged,
    never allowed to take the others down with it."""
    routes: List[Route] = []
    if not os.path.isdir(directory):
        return routes
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json") or name.endswith(".observations.json"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as f:
                routes.append(route_from_dict(json.load(f)))
        except Exception as e:  # noqa: BLE001
            log.error("walk %s could not be loaded (%s: %s)", name, type(e).__name__, e)
    return routes


# -------------------------------------------------------------- assessment

def _return_leg(route: Route) -> List[Section]:
    """The way back on an out-and-back: same ground, climbs and descents swapped.

    Distances continue from the turning point so findings on the return are
    placed where they are actually met.
    """
    total = route.outbound_m
    back: List[Section] = []
    for s in reversed(route.sections):
        r = Section(
            from_m=total + (total - s.to_m), to_m=total + (total - s.from_m),
            label=s.label, geometry=list(reversed(s.geometry)), surface=s.surface,
            evidence=s.evidence, hazards=s.hazards,
            access_restricted=s.access_restricted,
            barriers=[Barrier(b.kind, total + (total - b.at_m), b.status, b.source,
                              b.width_cm, b.step_count, b.has_ramp, b.note)
                      for b in s.barriers],
        )
        if s.gradient:
            g = s.gradient
            r.gradient = Gradient(g.descent_m, g.ascent_m, g.steepest_down_pct,
                                  g.steepest_up_pct, g.status, g.source)
        back.append(r)
    return back


def _minutes(distance_m: float, ascent_m: float) -> float:
    return distance_m / 1000.0 / PACE_KMH * 60.0 + ascent_m / 10.0 * MIN_PER_10M_ASCENT


def _full_minutes(route: Route) -> float:
    """The whole walk, out and back where that is its shape."""
    out = route.outbound_m
    up = sum(s.gradient.ascent_m for s in route.sections if s.gradient)
    down = sum(s.gradient.descent_m for s in route.sections if s.gradient)
    if route.shape == "out_and_back":
        # The way back climbs what the way out descended.
        return _minutes(2 * out, up + down)
    return _minutes(out, up)


def _turn_point(route: Route, minutes: float) -> Optional[float]:
    """How far out to go on an out-and-back so the round trip takes `minutes`.

    None when the whole walk is shorter than that. Each stretch costs its
    length twice plus everything climbed on it in either direction, so a
    hilly stretch uses up the time faster than a flat one of the same length.
    """
    spent = 0.0
    for s in route.sections:
        climb = (s.gradient.ascent_m + s.gradient.descent_m) if s.gradient else 0.0
        cost = _minutes(2 * s.length_m, climb)
        if spent + cost >= minutes:
            share = (minutes - spent) / cost if cost > 0 else 0.0
            return s.from_m + share * s.length_m
        spent += cost
    return None


def _point_at(section: Section, at_m: float) -> Optional[List[float]]:
    """Where along a section's line a distance falls."""
    if not section.geometry:
        return None
    share = (at_m - section.from_m) / section.length_m if section.length_m else 0.0
    return _cut_geometry(section.geometry, min(1.0, max(0.0, share)))[-1]


def _markers(route: Route) -> List[Dict]:
    """Things to show on the map: the turning point, and each obstacle once.

    Taken from the outward sections only - on a there-and-back walk the way
    back passes the same gates, and a map with every gate drawn twice on top of
    itself says nothing more.
    """
    out: List[Dict] = []
    for s in route.sections:
        for b in s.barriers:
            p = _point_at(s, b.at_m)
            if p:
                out.append({"kind": b.kind.value, "lat": p[0], "lng": p[1],
                            "at_m": round(b.at_m), "basis": b.status.value})
    if route.shape == "out_and_back" and route.sections and route.sections[-1].geometry:
        end = route.sections[-1].geometry[-1]
        out.append({"kind": "turn_back", "lat": end[0], "lng": end[1],
                    "at_m": round(route.outbound_m), "basis": "modelled"})
    if route.via:
        # The point the walk really visits: where the route provider took it.
        out.append({"kind": "via", "lat": route.via["lat"], "lng": route.via["lng"],
                    "at_m": None, "basis": "reported", "label": route.via.get("label")})
        asked = route.via.get("requested")
        if asked and (route.via.get("offset_m") or 0) > 0:
            # (A walk allowed to pass at a distance turns this far away too.)
            # And the parent's own marker, when the two are apart, so a moved
            # checkpoint is visible on the map rather than silently replaced.
            out.append({"kind": "via_requested", "lat": asked["lat"], "lng": asked["lng"],
                        "at_m": None, "basis": "reported",
                        "label": f"{route.via['offset_m']} m from the walk"})
    return out


def _cut_geometry(geometry: List[List[float]], keep: float) -> List[List[float]]:
    """The first `keep` share of a polyline, by distance along it."""
    if len(geometry) < 2 or keep >= 1.0:
        return geometry
    steps = [_haversine(a, b) for a, b in zip(geometry, geometry[1:])]
    target = sum(steps) * max(0.0, keep)
    out, walked = [geometry[0]], 0.0
    for (a, b), d in zip(zip(geometry, geometry[1:]), steps):
        if walked + d >= target:
            t = (target - walked) / d if d else 0.0
            out.append([a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])])
            return out
        out.append(b)
        walked += d
    return out


def _haversine(a: List[float], b: List[float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def _shortened(route: Route, turn_m: float) -> Route:
    """The same out-and-back walk, turning back at `turn_m`.

    Everything beyond the turn is dropped, including its obstacles - a stile
    you will never reach is not a reason to avoid the walk. The stretch the
    turn falls in keeps its steepest gradient (the steep bit may well be in
    the part you walk) and has its climb scaled to the share walked.
    """
    kept: List[Section] = []
    for s in route.sections:
        if s.from_m >= turn_m:
            break
        if s.to_m <= turn_m:
            kept.append(s)
            continue
        share = (turn_m - s.from_m) / s.length_m if s.length_m else 0.0
        cut = Section(
            from_m=s.from_m, to_m=turn_m, label=s.label,
            geometry=_cut_geometry(s.geometry, share), surface=s.surface,
            evidence=s.evidence, hazards=s.hazards,
            access_restricted=s.access_restricted,
            barriers=[b for b in s.barriers if b.at_m <= turn_m],
        )
        if s.gradient:
            g = s.gradient
            cut.gradient = Gradient(g.ascent_m * share, g.descent_m * share,
                                    g.steepest_up_pct, g.steepest_down_pct,
                                    g.status, g.source)
        kept.append(cut)
    return Route(**{**route.__dict__, "sections": kept})


#: Distance within which a later point counts as walking ground already walked.
RETRACE_M = 20.0
#: Spacing of the points used to measure retracing.
RETRACE_SAMPLE_M = 20.0


def retrace_share(route: Route) -> float:
    """The share of the walk spent on ground already walked, 0 to about 0.5.

    A pure there-and-back scores about one half (the whole way back); a true
    loop near zero; a loop with a shared lead-in somewhere between. Founder
    feedback, 9 Oct: a shared first and last stretch is fine, so this is a
    number a preference can set a limit on, not a yes/no.
    """
    if route.shape == "out_and_back":
        return 0.5
    if route.shape == "one_way":
        return 0.0
    line = [p for s in route.sections for p in s.geometry]
    samples: List[List[float]] = []
    walked = 0.0
    next_at = 0.0
    for a, b in zip(line, line[1:]):
        d = _haversine(a, b)
        while d > 0 and walked + d >= next_at:
            t = (next_at - walked) / d
            samples.append([a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])])
            next_at += RETRACE_SAMPLE_M
        walked += d
    if len(samples) < 10:
        return 0.0
    gap = int(3 * RETRACE_M / RETRACE_SAMPLE_M) + 2   # ignore immediate neighbours
    again = 0
    for i in range(gap, len(samples)):
        if any(_haversine(samples[i], samples[j]) <= RETRACE_M
               for j in range(0, i - gap)):
            again += 1
    return again / len(samples)


def path_shape(route: Route) -> str:
    """What the walk is on the ground: "loop", "lollipop" or "there_and_back".

    Measured, not declared. A generated round trip is called a loop by the
    provider but can retrace much of itself, and a curated "loop" like Castle
    Hill goes up and comes back down the same street. The share of the walk
    that passes within RETRACE_M of ground already walked decides: a pure
    there-and-back scores about one half (the whole way back), a true loop
    near zero.
    """
    if route.shape == "out_and_back":
        return "there_and_back"
    if route.shape == "one_way":
        return "one_way"
    share = retrace_share(route)
    if share >= 0.35:
        return "there_and_back"
    if share >= 0.1:
        return "lollipop"
    return "loop"


def _may_turn(route: Route, full: float, minutes: float,
               allow_out_and_back: bool = True) -> bool:
    """Whether to fit this walk to the time by turning back early.

    Any there-and-back walk can. So can a circuit - you can always turn round
    on one, and the first version wrongly said there was "no point to turn
    back early" - but a circuit close to the time asked for is offered whole,
    because walking the full loop is the better walk. A one-way walk to a
    destination cannot be fitted.
    """
    if route.via:
        # Turning back early would turn round before the place the walk was
        # made to reach.
        return False
    if route.shape == "out_and_back":
        return True
    if route.shape == "loop":
        # Turning back on a circuit makes a there-and-back - not offered to
        # someone who has said they would rather avoid those.
        return allow_out_and_back and full - minutes > max(5.0, 0.15 * minutes)
    return False


def _fit(route: Route, requested: Optional[int], full: float,
         turn_m: Optional[float]) -> Optional[Dict]:
    """How the walk relates to the time asked for, said plainly."""
    if not requested:
        return None
    near = None
    if turn_m is not None:
        near = next((s.label for s in route.sections
                     if s.from_m <= turn_m <= s.to_m), None)
        kind = "turned"
    elif abs(full - requested) <= max(5.0, 0.15 * requested):
        kind = "about_right"
    elif full < requested:
        kind = "shorter"
    else:
        kind = "longer"
    return {
        "kind": kind,
        "requested_minutes": requested,
        "full_minutes": round(full),
        "turn_back_at_m": round(turn_m) if turn_m is not None else None,
        "turn_back_near": near,
        "can_shorten": route.shape in ("out_and_back", "loop"),
        "whole_shape": route.shape,
    }


def assess_route(route: Route, profile: str,
                 setup: Union[PramSetup, CarrierSetup],
                 minutes: Optional[int] = None,
                 allow_out_and_back: bool = True) -> Dict:
    requested = minutes
    full = _full_minutes(route)
    turn_m = None
    if minutes and full > minutes and _may_turn(route, full, minutes,
                                                 allow_out_and_back):
        turn_m = _turn_point(route, minutes)
    whole = route
    if turn_m is not None:
        route = _shortened(route, turn_m)
        # Turning back on a circuit makes it a there-and-back along its first
        # part: the same ground twice, so the same requirements both ways.
        route.shape = "out_and_back"

    legs = list(route.sections)
    if route.shape == "out_and_back":
        legs += _return_leg(route)

    judge = {"pram": assess_pram, "carrier": assess_carrier,
             "walker": assess_walker}[profile]
    assessed: List[SectionAssessment] = [judge(s, setup) for s in legs]

    findings: List[Finding] = [f for a in assessed for f in a.findings]
    blocking = [f for f in findings if f.verdict is Verdict.BLOCKED]
    difficult = [f for f in findings if f.verdict is Verdict.DIFFICULT]
    unknowns = [f for f in findings if f.verdict is Verdict.UNKNOWN]
    notes = [f for f in findings if f.preference]

    if route.shape == "out_and_back":
        # The same gate met twice is one gate. Report each obstacle once, at
        # the place it is first reached.
        blocking, difficult, unknowns, notes = (
            _first_meeting(x, route.outbound_m)
            for x in (blocking, difficult, unknowns, notes))

    unknowns = _summarise_unknown_surface(unknowns, assessed, route)
    difficult, notes = _once_per_way(difficult), _once_per_way(notes)

    distance = sum(s.length_m for s in legs)
    ascent = sum(s.gradient.ascent_m for s in legs if s.gradient)
    have_gradient = all(s.gradient is not None for s in legs)
    known_surface = sum(s.length_m for s in legs if s.surface is not Surface.UNKNOWN)
    reported = sum(s.length_m for s in legs if s.surface_basis() is Status.REPORTED)

    if blocking:
        verdict = Verdict.BLOCKED
    elif difficult:
        verdict = Verdict.DIFFICULT
    elif unknowns:
        verdict = Verdict.UNKNOWN
    else:
        verdict = Verdict.OK

    minutes = (distance / 1000.0) / PACE_KMH * 60.0
    if have_gradient:
        minutes += ascent / 10.0 * MIN_PER_10M_ASCENT

    return {
        "id": route.id,
        "name": route.name,
        "area": route.area,
        "summary": route.summary,
        "shape": route.shape,
        "path_shape": path_shape(route),
        "retrace_share": round(retrace_share(route), 2),
        "road_share": route.road_share,
        "sample": route.sample,
        "start": route.start,
        "verdict": verdict.value,
        "distance_m": round(distance),
        "ascent_m": round(ascent) if have_gradient else None,
        "minutes": round(minutes),
        "fit": _fit(whole, requested, full, turn_m),
        "assumptions": (
            f"About {PACE_KMH:g} km/h"
            + (", plus a minute for every 10 m climbed" if have_gradient else "")
            + ". No stops included."
        ),
        "blocking": [f.to_dict() for f in blocking],
        "difficult": [f.to_dict() for f in difficult],
        "unknowns": [f.to_dict() for f in unknowns],
        "notes": [f.to_dict() for f in notes],
        "coverage": {
            "surface_known_share": round(known_surface / distance, 2) if distance else 0,
            "surface_reported_share": round(reported / distance, 2) if distance else 0,
            "gradient": "modelled" if have_gradient else "unknown",
        },
        "markers": _markers(route),
        "sections": [
            {
                "label": a.section.label,
                "from_m": round(a.section.from_m),
                "to_m": round(a.section.to_m),
                "surface": a.section.surface.value,
                "surface_basis": a.section.surface_basis().value,
                "verdict": a.verdict.value,
                "geometry": a.section.geometry,
            }
            for a in assessed
        ],
        "sources": route.sources,
        "built_on": route.built_on,
        "notes_from_curator": route.notes,
    }


def _summarise_unknown_surface(unknowns: List[Finding],
                               assessed: List[SectionAssessment],
                               route: Route) -> List[Finding]:
    """One line for the unrecorded surfaces, with how much of the walk they cover.

    Listing "surface not recorded" once per stretch turned an old-town walk into
    eighteen identical lines - true, and unreadable. The gaps are kept, and
    their extent is stated, so they are neither hidden nor noise.
    """
    surface_gaps = [f for f in unknowns if f.kind == "surface"]
    if len(surface_gaps) <= 1:
        return unknowns
    turn = route.outbound_m if route.shape == "out_and_back" else math.inf
    gap_m = 0.0
    runs = 0
    previous_unknown = False
    for a in assessed:
        if a.section.from_m >= turn:
            break
        unknown = a.section.surface is Surface.UNKNOWN
        if unknown:
            gap_m += a.section.length_m
            # Long sections are split into pieces when built; consecutive
            # unknown pieces are one stretch on the ground, so count runs.
            if not previous_unknown:
                runs += 1
        previous_unknown = unknown
    if runs <= 1:
        return [Finding(Verdict.UNKNOWN, "surface",
                        f"Surface not recorded for about {round(gap_m, -1):.0f} m.",
                        Status.UNKNOWN, "none", surface_gaps[0].at_m)] + \
            [f for f in unknowns if f.kind != "surface"]
    summary = Finding(
        Verdict.UNKNOWN, "surface",
        f"Surface not recorded on {runs} stretches, "
        f"about {round(gap_m, -1):.0f} m in total.",
        Status.UNKNOWN, "none", surface_gaps[0].at_m)
    return [summary] + [f for f in unknowns if f.kind != "surface"]


def _once_per_way(findings: List[Finding]) -> List[Finding]:
    """Say a surface finding once per mapped way, where it is first met.

    A long way is split into several sections when built, and each piece
    repeats the same tag - so "Unpaved" appeared once per piece of one path.
    A surface finding's source is the way it came from, which makes repeats
    exact duplicates. Gradient findings are left alone: they come from the
    terrain model per piece, and two climbs in two places are two climbs.
    """
    seen = set()
    out: List[Finding] = []
    for f in findings:
        if f.kind == "surface":
            key = (f.reason, f.source)
            if key in seen:
                continue
            seen.add(key)
        out.append(f)
    return out


def _first_meeting(findings: List[Finding], turn_m: float) -> List[Finding]:
    """On an out-and-back, report each obstacle once.

    The way back crosses the same gates, steps and surfaces already reported on
    the way out, so repeating them is noise. Gradients are the exception: a
    descent on the way out is a climb on the way back, which is new and often
    the harder half - so return-leg gradient findings are kept.
    """
    return [f for f in findings
            if f.at_m is None or f.at_m < turn_m or f.kind == "gradient"]


def assess_all(profile: str, setup, minutes: Optional[int] = None,
               routes: Optional[List[Route]] = None,
               allow_out_and_back: bool = True) -> List[Dict]:
    """Every walk, assessed and fitted to the time asked for.

    Out-and-back walks are shortened to the requested time by turning back
    sooner; loops cannot be, and say how far off they are. Ordering: walks
    with no known problems first (recorded or not - an unrecorded stretch is
    shown, but is not a reason to rank a walk below one that is 40 minutes
    off), then harder walks, then unsuitable ones; within each, closest to the
    requested time first.

    Unsuitable walks are kept, not hidden: seeing that a walk is blocked for
    your pram by steps is itself useful, and a list that silently shrinks tells
    you nothing about why.
    """
    cards = [assess_route(r, profile, setup, minutes, allow_out_and_back)
             for r in (routes if routes is not None else load_routes())]
    tier = {"ok": 0, "unknown": 0, "difficult": 1, "blocked": 2}
    if minutes:
        cards.sort(key=lambda c: (tier[c["verdict"]], abs(c["minutes"] - minutes)))
    else:
        cards.sort(key=lambda c: tier[c["verdict"]])
    return cards

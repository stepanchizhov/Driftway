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


def assess_route(route: Route, profile: str,
                 setup: Union[PramSetup, CarrierSetup]) -> Dict:
    legs = list(route.sections)
    if route.shape == "out_and_back":
        legs += _return_leg(route)

    judge = assess_pram if profile == "pram" else assess_carrier
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
        "sample": route.sample,
        "start": route.start,
        "verdict": verdict.value,
        "distance_m": round(distance),
        "ascent_m": round(ascent) if have_gradient else None,
        "minutes": round(minutes),
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
    gap_m = sum(a.section.length_m for a in assessed
                if a.section.surface is Surface.UNKNOWN and a.section.from_m < turn)
    summary = Finding(
        Verdict.UNKNOWN, "surface",
        f"Surface not recorded on {len(surface_gaps)} stretches, "
        f"about {round(gap_m, -1):.0f} m in total.",
        Status.UNKNOWN, "none", surface_gaps[0].at_m)
    return [summary] + [f for f in unknowns if f.kind != "surface"]


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
               routes: Optional[List[Route]] = None) -> List[Dict]:
    """Every walk, assessed. Suitability first, then closeness to the wanted
    duration - a manageable walk ten minutes long beats a blocked one that is
    exactly the right length.

    Unsuitable walks are kept, not hidden: seeing that the riverside route is
    blocked for your pram by steps is itself useful, and a list that silently
    shrinks tells you nothing about why.
    """
    cards = [assess_route(r, profile, setup) for r in (routes if routes is not None
                                                      else load_routes())]
    rank = {"ok": 0, "unknown": 1, "difficult": 2, "blocked": 3}
    if minutes:
        cards.sort(key=lambda c: (rank[c["verdict"]], abs(c["minutes"] - minutes)))
    else:
        cards.sort(key=lambda c: rank[c["verdict"]])
    return cards

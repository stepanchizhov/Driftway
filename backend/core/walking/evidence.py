"""
What we know about a stretch of path, and how we know it.

The rule this module exists to enforce: **every claim carries its basis.** A
surface, a gate or a gradient is never just a value - it is a value plus a
status saying whether someone saw it, a map says it, a model estimated it, or
nobody knows. The audit that shaped this (Windsor, 8 Oct 2026) found that of
664 mapped paths, a quarter recorded a surface and three recorded smoothness.
A design that treated "not tagged" as "fine" would have called most of Windsor
pram-friendly on no evidence at all.

Statuses, from strongest to weakest:

  reported   A person walked it and said so, on a stated date. The strongest
             evidence for current condition, and still not permanent - a path
             reported firm in September may be mud in January.
  mapped     An OpenStreetMap tag. Says what a mapper recorded at some point;
             it does not establish current condition, and a gravel label does
             not establish wheel resistance or footing.
  modelled   Derived, e.g. a gradient from a 25 m terrain model. Good for a
             sustained climb, blind to a short steep ramp.
  unknown    No evidence. Shown as unknown - never quietly treated as safe,
             flat, smooth or passable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Status(str, Enum):
    REPORTED = "reported"
    MAPPED = "mapped"
    MODELLED = "modelled"
    UNKNOWN = "unknown"


#: Strongest first. Where two pieces of evidence disagree, the stronger wins and
#: the weaker is kept for the record rather than discarded.
STRENGTH = {Status.REPORTED: 3, Status.MAPPED: 2, Status.MODELLED: 1, Status.UNKNOWN: 0}


class Surface(str, Enum):
    """Surface as it matters to wheels and feet - not the full OSM vocabulary.

    Deliberately coarse. The distinctions kept are the ones that change an
    assessment: sealed ground rolls; setts are firm but jolting for small
    wheels; compacted ground is usually fine but varies; loose ground resists
    wheels and shifts underfoot; soft ground depends on the weather.
    """

    SEALED = "sealed"
    SETTS = "setts"
    COMPACTED = "compacted"
    LOOSE = "loose"
    #: Mapped only as "unpaved": known not to be sealed, firmness not recorded.
    #: Kept apart from LOOSE because it could equally be firm compacted earth.
    UNPAVED = "unpaved"
    SOFT = "soft"
    UNKNOWN = "unknown"


class BarrierKind(str, Enum):
    STEPS = "steps"
    STILE = "stile"
    KISSING_GATE = "kissing_gate"
    GATE = "gate"
    BOLLARD = "bollard"
    OTHER = "other"


@dataclass
class Evidence:
    attribute: str              # "surface", "width_cm", "smoothness", "access"…
    value: object
    status: Status
    source: str                 # "osm:way/123", "eudem25m", "founder 2026-10-09"
    observed_on: Optional[str] = None   # ISO date, when someone saw it
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "attribute": self.attribute,
            "value": self.value,
            "status": self.status.value,
            "source": self.source,
            "observed_on": self.observed_on,
            "note": self.note,
        }


@dataclass
class Barrier:
    kind: BarrierKind
    at_m: float                 # distance along the route
    status: Status
    source: str
    width_cm: Optional[int] = None      # None means NOT KNOWN, never "wide enough"
    step_count: Optional[int] = None
    has_ramp: Optional[bool] = None     # None means not recorded
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "at_m": round(self.at_m),
            "status": self.status.value,
            "source": self.source,
            "width_cm": self.width_cm,
            "step_count": self.step_count,
            "has_ramp": self.has_ramp,
            "note": self.note,
        }


@dataclass
class Gradient:
    """Climb and descent of a section, from a terrain model.

    Uphill and downhill are kept apart because they are different problems: a
    pram is hard to push up a slope and has to be held back coming down it, and
    on an out-and-back walk the same stretch is met in both directions.

    Steepness is measured over windows long enough for the model to mean
    something (GRADE_WINDOW_M in the build tool). A 25 m grid cannot see a
    ten-metre ramp, and reporting one would be inventing precision.
    """

    ascent_m: float
    descent_m: float
    steepest_up_pct: float      # in the walking direction, >= 0
    steepest_down_pct: float    # in the walking direction, >= 0
    status: Status
    source: str

    def to_dict(self) -> dict:
        return {
            "ascent_m": round(self.ascent_m, 1),
            "descent_m": round(self.descent_m, 1),
            "steepest_up_pct": round(self.steepest_up_pct, 1),
            "steepest_down_pct": round(self.steepest_down_pct, 1),
            "status": self.status.value,
            "source": self.source,
        }

    @property
    def steepest_pct(self) -> float:
        return max(self.steepest_up_pct, self.steepest_down_pct)


@dataclass
class Section:
    """A stretch of route that can be assessed as one thing."""

    from_m: float
    to_m: float
    label: str
    geometry: List[List[float]]         # [[lat, lng], …]
    surface: Surface = Surface.UNKNOWN
    evidence: List[Evidence] = field(default_factory=list)
    barriers: List[Barrier] = field(default_factory=list)
    gradient: Optional[Gradient] = None
    access_restricted: bool = False
    hazards: List[Evidence] = field(default_factory=list)

    @property
    def length_m(self) -> float:
        return self.to_m - self.from_m

    def strongest(self, attribute: str) -> Optional[Evidence]:
        """The best-supported evidence for one attribute, or None."""
        found = [e for e in self.evidence if e.attribute == attribute]
        if not found:
            return None
        return max(found, key=lambda e: STRENGTH[e.status])

    def surface_basis(self) -> Status:
        e = self.strongest("surface")
        return e.status if e else Status.UNKNOWN

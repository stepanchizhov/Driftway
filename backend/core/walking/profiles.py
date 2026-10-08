"""
Pram and carrier, judged separately - and never averaged.

Three things are kept apart throughout, because collapsing them is how a
walking app ends up recommending a flight of steps to someone with a pram:

  verdict     blocked  - a known incompatibility (steps with no ramp, a stile,
                         a gap narrower than the pram). One blocked section
                         makes the whole route unsuitable for that setup; it
                         is never diluted by the pleasant kilometre around it.
              difficult - passable, with real effort or care.
              ok        - nothing known against it.
  preference  Notes that make a route nicer or worse without making it
              unsuitable: bumpy setts in a sturdy pram, a gentle slope.
  confidence  How much of the route the assessment actually rests on. Unknown
              is reported as unknown and never counted as ok.

The thresholds below are heuristics, labelled as such. The gradient ones are
borrowed from UK wheelchair-ramp guidance (1:20 is where a slope starts to be
treated as a ramp; 1:12 is the steepest a short ramp should be). That is a
reasonable starting point for pushing a loaded pram and NOT a validated pram
threshold - hence HYPOTHESIS, and hence one place to change them.

Not modelled, deliberately: calories, heart rate, "safe" carried weight. The
carried load is shown to the parent as their own arithmetic and nothing more,
because manufacturer limits are specific to the carrier model and no general
figure would be honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .evidence import BarrierKind, Section, Status, Surface

#: HYPOTHESIS. Slope (%) at which pushing becomes noticeable.
PRAM_GRADE_NOTICEABLE = 5.0
#: HYPOTHESIS. Slope (%) at which pushing up / holding back becomes hard.
PRAM_GRADE_DIFFICULT = 8.3
#: HYPOTHESIS. Slope (%) at which climbing with a carried child is hard work.
CARRIER_GRADE_DIFFICULT = 10.0

#: Clearance either side when comparing a pram to a known gap.
PRAM_CLEARANCE_CM = 10


class Verdict(str, Enum):
    OK = "ok"
    DIFFICULT = "difficult"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


_SEVERITY = {Verdict.OK: 0, Verdict.UNKNOWN: 1, Verdict.DIFFICULT: 2, Verdict.BLOCKED: 3}


@dataclass
class PramSetup:
    #: "compact" (small hard wheels), "standard", or "all_terrain" (large air
    #: tyres). Capability and width are separate inputs on purpose: a narrow
    #: all-terrain pram and a wide city double fail in different places.
    wheels: str = "standard"
    width_cm: Optional[int] = None
    double: bool = False


@dataclass
class CarrierSetup:
    #: "soft" (sling or soft structured carrier) or "framed" (hiking frame).
    kind: str = "soft"
    child_kg: Optional[float] = None
    carrier_kg: Optional[float] = None
    luggage_kg: Optional[float] = None
    #: Who carries the bag: the adult with the child, or someone else. Bags
    #: carried by a companion are not added to the carrying adult's load.
    luggage_with: str = "carrier_adult"

    def carried_kg(self) -> Optional[float]:
        """The carrying adult's load, or None if any part of it is unknown."""
        parts = [self.child_kg, self.carrier_kg]
        if self.luggage_with == "carrier_adult":
            parts.append(self.luggage_kg if self.luggage_kg is not None else 0.0)
        if any(p is None for p in parts):
            return None
        return round(sum(parts), 1)


@dataclass
class Finding:
    verdict: Verdict
    kind: str               # "barrier", "surface", "gradient", "width", "access", "hazard"
    reason: str             # plain language, from the parent's side of the screen
    basis: Status
    source: str
    at_m: Optional[float] = None
    #: True for notes that bear on preference rather than suitability.
    preference: bool = False

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "kind": self.kind,
            "reason": self.reason,
            "basis": self.basis.value,
            "source": self.source,
            "at_m": round(self.at_m) if self.at_m is not None else None,
            "preference": self.preference,
        }


@dataclass
class SectionAssessment:
    section: Section
    findings: List[Finding] = field(default_factory=list)

    @property
    def verdict(self) -> Verdict:
        """The worst finding on this stretch. Unknown never upgrades to ok."""
        hard = [f for f in self.findings if not f.preference]
        if not hard:
            return Verdict.OK
        return max((f.verdict for f in hard), key=lambda v: _SEVERITY[v])


# ----------------------------------------------------------------- shared

def _common(section: Section) -> List[Finding]:
    """Findings that apply whatever you are pushing or carrying."""
    out: List[Finding] = []
    if section.access_restricted:
        out.append(Finding(Verdict.BLOCKED, "access",
                           "Not open to walkers, according to the map.",
                           Status.MAPPED, "osm", section.from_m))
    for hazard in section.hazards:
        # Hazards are always shown and never judged here: a flood warning on a
        # gate says the path CAN be dangerous, not that it is today.
        out.append(Finding(Verdict.DIFFICULT if hazard.status is Status.REPORTED
                           else Verdict.UNKNOWN,
                           "hazard", str(hazard.value), hazard.status,
                           hazard.source, section.from_m))
    return out


def _unknown_surface(section: Section) -> Finding:
    return Finding(Verdict.UNKNOWN, "surface",
                   "Surface not recorded for this stretch.",
                   Status.UNKNOWN, "none", section.from_m)


# ------------------------------------------------------------------- pram

def assess_pram(section: Section, setup: PramSetup) -> SectionAssessment:
    findings = _common(section)
    pram_width = setup.width_cm

    for b in section.barriers:
        if b.kind is BarrierKind.STEPS:
            count = f"{b.step_count} steps" if b.step_count else "Steps"
            if b.has_ramp:
                findings.append(Finding(
                    Verdict.DIFFICULT, "barrier",
                    f"{count}, with a ramp marked on the map - worth checking it is usable.",
                    b.status, b.source, b.at_m))
            else:
                findings.append(Finding(
                    Verdict.BLOCKED, "barrier",
                    f"{count} and no ramp recorded - the pram would have to be carried.",
                    b.status, b.source, b.at_m))
        elif b.kind is BarrierKind.STILE:
            findings.append(Finding(
                Verdict.BLOCKED, "barrier",
                "A stile - a pram would have to be lifted over.",
                b.status, b.source, b.at_m))
        elif b.kind in (BarrierKind.KISSING_GATE, BarrierKind.GATE):
            name = "Kissing gate" if b.kind is BarrierKind.KISSING_GATE else "Gate"
            if b.width_cm is not None and pram_width is not None:
                if b.width_cm < pram_width + PRAM_CLEARANCE_CM:
                    findings.append(Finding(
                        Verdict.BLOCKED, "width",
                        f"{name} about {b.width_cm} cm wide - too tight for a "
                        f"{pram_width} cm pram.", b.status, b.source, b.at_m))
            elif b.kind is BarrierKind.KISSING_GATE:
                findings.append(Finding(
                    Verdict.DIFFICULT, "barrier",
                    "Kissing gate, width not recorded - these are often too "
                    "tight for prams.", b.status, b.source, b.at_m))
            else:
                # A missing width is not proof of access, and not proof of
                # obstruction either. Say exactly that.
                findings.append(Finding(
                    Verdict.UNKNOWN, "barrier",
                    "Gate - its opening width is not recorded.",
                    b.status, b.source, b.at_m))
        elif b.kind is BarrierKind.BOLLARD and setup.double:
            findings.append(Finding(
                Verdict.UNKNOWN, "barrier",
                "Bollards - the gap between them is not recorded.",
                b.status, b.source, b.at_m))
        elif b.kind is BarrierKind.OTHER:
            findings.append(Finding(
                Verdict.UNKNOWN, "barrier", b.note or "A mapped barrier.",
                b.status, b.source, b.at_m))

    width = section.strongest("width_cm")
    if width and pram_width and int(width.value) < pram_width + PRAM_CLEARANCE_CM:
        findings.append(Finding(
            Verdict.BLOCKED, "width",
            f"Path about {width.value} cm wide - narrower than the pram.",
            width.status, width.source, section.from_m))

    findings.extend(_pram_surface(section, setup))
    findings.extend(_pram_gradient(section))
    return SectionAssessment(section, findings)


def _pram_surface(section: Section, setup: PramSetup) -> List[Finding]:
    s = section.surface
    if s is Surface.UNKNOWN:
        return [_unknown_surface(section)]
    basis = section.surface_basis()
    src = (section.strongest("surface").source
           if section.strongest("surface") else "none")
    small = setup.wheels == "compact"
    sturdy = setup.wheels == "all_terrain"

    if s is Surface.SEALED:
        return []
    if s is Surface.SETTS:
        if small:
            return [Finding(Verdict.DIFFICULT, "surface",
                            "Setts (cobbles) - a constant jolt on small wheels.",
                            basis, src, section.from_m)]
        return [Finding(Verdict.OK, "surface", "Setts (cobbles) - bumpy.",
                        basis, src, section.from_m, preference=True)]
    if s is Surface.COMPACTED:
        if small:
            return [Finding(Verdict.DIFFICULT, "surface",
                            "Compacted gravel - hard going on small wheels.",
                            basis, src, section.from_m)]
        return [Finding(Verdict.OK, "surface",
                        "Compacted path - usually fine, can rut after rain.",
                        basis, src, section.from_m, preference=True)]
    if s is Surface.UNPAVED:
        if sturdy:
            return [Finding(Verdict.OK, "surface",
                            "Unpaved - firmness not recorded; big tyres should cope.",
                            basis, src, section.from_m, preference=True)]
        return [Finding(Verdict.DIFFICULT, "surface",
                        "Unpaved - the map doesn't say how firm. Can be hard "
                        "going, especially after rain.",
                        basis, src, section.from_m)]
    if s is Surface.LOOSE:
        if sturdy:
            return [Finding(Verdict.OK, "surface",
                            "Loose surface - fine for big tyres, still slower.",
                            basis, src, section.from_m, preference=True)]
        return [Finding(Verdict.DIFFICULT, "surface",
                        "Loose surface - wheels dig in and pushing is hard.",
                        basis, src, section.from_m)]
    # SOFT
    return [Finding(Verdict.DIFFICULT, "surface",
                    "Grass or earth - depends heavily on recent rain"
                    + ("." if sturdy else ", and hard work on smaller wheels."),
                    basis, src, section.from_m)]


def _pram_gradient(section: Section) -> List[Finding]:
    g = section.gradient
    if g is None:
        return []
    out: List[Finding] = []
    if g.steepest_up_pct >= PRAM_GRADE_DIFFICULT:
        out.append(Finding(Verdict.DIFFICULT, "gradient",
                           f"Steep climb, about {g.steepest_up_pct:.0f}% - hard to push.",
                           g.status, g.source, section.from_m))
    elif g.steepest_up_pct >= PRAM_GRADE_NOTICEABLE:
        # Not "gentle": an 8% slope is just under the difficult threshold and
        # a parent pushing a loaded pram will feel it.
        out.append(Finding(Verdict.OK, "gradient",
                           f"Noticeable climb, about {g.steepest_up_pct:.0f}%.",
                           g.status, g.source, section.from_m, preference=True))
    if g.steepest_down_pct >= PRAM_GRADE_DIFFICULT:
        out.append(Finding(Verdict.DIFFICULT, "gradient",
                           f"Steep descent, about {g.steepest_down_pct:.0f}% - "
                           "the pram needs holding back.",
                           g.status, g.source, section.from_m))
    elif g.steepest_down_pct >= PRAM_GRADE_NOTICEABLE:
        out.append(Finding(Verdict.OK, "gradient",
                           f"Noticeable descent, about {g.steepest_down_pct:.0f}% - "
                           "keep a hand on the brake.",
                           g.status, g.source, section.from_m, preference=True))
    return out


# ---------------------------------------------------------------- carrier

def assess_carrier(section: Section, setup: CarrierSetup) -> SectionAssessment:
    findings = _common(section)

    for b in section.barriers:
        if b.kind is BarrierKind.STEPS:
            count = f"{b.step_count} steps" if b.step_count else "Steps"
            findings.append(Finding(
                Verdict.OK, "barrier",
                f"{count} - fine with a carrier; take your footing carefully.",
                b.status, b.source, b.at_m, preference=True))
        elif b.kind is BarrierKind.STILE:
            findings.append(Finding(
                Verdict.DIFFICULT, "barrier",
                "A stile - climbing over with a child on you.",
                b.status, b.source, b.at_m))

    s = section.surface
    steep = (section.gradient is not None
             and section.gradient.steepest_pct >= PRAM_GRADE_DIFFICULT)
    if s is Surface.UNKNOWN:
        findings.append(_unknown_surface(section))
    elif s in (Surface.LOOSE, Surface.SOFT, Surface.UNPAVED):
        src_e = section.strongest("surface")
        src = src_e.source if src_e else "none"
        if steep:
            findings.append(Finding(
                Verdict.DIFFICULT, "surface",
                "Loose or soft ground on a slope - watch your footing.",
                section.surface_basis(), src, section.from_m))
        else:
            findings.append(Finding(
                Verdict.OK, "surface",
                "Loose or soft ground - can be slippery when wet.",
                section.surface_basis(), src, section.from_m, preference=True))

    g = section.gradient
    if g is not None:
        if g.steepest_up_pct >= CARRIER_GRADE_DIFFICULT:
            findings.append(Finding(
                Verdict.DIFFICULT, "gradient",
                f"Steep climb, about {g.steepest_up_pct:.0f}%, with a child to carry.",
                g.status, g.source, section.from_m))
        elif g.steepest_up_pct >= PRAM_GRADE_NOTICEABLE:
            findings.append(Finding(
                Verdict.OK, "gradient",
                f"Climb of about {g.steepest_up_pct:.0f}%.",
                g.status, g.source, section.from_m, preference=True))
    return SectionAssessment(section, findings)

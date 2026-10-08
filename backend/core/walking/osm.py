"""
OpenStreetMap tags, translated into evidence - and nothing more.

This module is the provider-specific translation layer: everything that knows
OSM's vocabulary lives here, so the profile logic downstream reasons about
Surface and Barrier, not about tag strings. A different evidence source later
gets its own translator, not a branch inside the profiles.

What it refuses to do is fill gaps. An untagged path comes back with no surface
evidence at all, which the profiles then treat as unknown. Reference for the
vocabulary: https://wiki.openstreetmap.org/wiki/Key:surface,
https://wiki.openstreetmap.org/wiki/Key:smoothness, and
https://wiki.openstreetmap.org/wiki/Key:barrier.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .evidence import Barrier, BarrierKind, Evidence, Status, Surface

# OSM surface values -> how they behave under wheels and feet. Values not listed
# map to UNKNOWN rather than to a guess.
_SURFACE = {
    # Sealed: rolls well in any pram.
    "asphalt": Surface.SEALED,
    "concrete": Surface.SEALED,
    "concrete:plates": Surface.SEALED,
    "concrete:lanes": Surface.SEALED,
    "paving_stones": Surface.SEALED,
    "paved": Surface.SEALED,
    "metal": Surface.SEALED,
    "wood": Surface.SEALED,          # boardwalk; slippery when wet - see hazards
    "rubber": Surface.SEALED,
    # Setts / cobbles: firm, but a continuous jolt for small wheels.
    "sett": Surface.SETTS,
    "cobblestone": Surface.SETTS,
    "unhewn_cobblestone": Surface.SETTS,
    "cobblestone:flattened": Surface.SETTS,
    "bricks": Surface.SETTS,
    # Compacted: usually fine, varies with maintenance and rain.
    "compacted": Surface.COMPACTED,
    "fine_gravel": Surface.COMPACTED,
    # Loose: resists wheels, shifts underfoot.
    "gravel": Surface.LOOSE,
    "pebblestone": Surface.LOOSE,
    "unpaved": Surface.UNPAVED,      # says only "not paved"; firmness unknown
    "rock": Surface.LOOSE,
    # Soft: depends on the weather more than anything mapped.
    "grass": Surface.SOFT,
    "dirt": Surface.SOFT,
    "earth": Surface.SOFT,
    "ground": Surface.SOFT,
    "mud": Surface.SOFT,
    "sand": Surface.SOFT,
    "woodchips": Surface.SOFT,
    "grass_paver": Surface.SOFT,
}

_BARRIER = {
    "stile": BarrierKind.STILE,
    "kissing_gate": BarrierKind.KISSING_GATE,
    "gate": BarrierKind.GATE,
    "swing_gate": BarrierKind.GATE,
    "lift_gate": BarrierKind.GATE,
    "wicket_gate": BarrierKind.GATE,
    "bollard": BarrierKind.BOLLARD,
}

#: Access values that mean "you may not walk here".
_FORBIDDEN = {"no", "private"}


def surface_from_tags(tags: Dict[str, str], source: str) -> Tuple[Surface, List[Evidence]]:
    """The surface class, plus the evidence it rests on (possibly none)."""
    raw = (tags.get("surface") or "").strip()
    evidence: List[Evidence] = []
    if raw:
        cls = _SURFACE.get(raw, Surface.UNKNOWN)
        evidence.append(Evidence("surface", raw, Status.MAPPED, source,
                                 note=None if cls is not Surface.UNKNOWN
                                 else "Mapped value not recognised"))
    else:
        cls = Surface.UNKNOWN

    smooth = (tags.get("smoothness") or "").strip()
    if smooth:
        evidence.append(Evidence("smoothness", smooth, Status.MAPPED, source))

    width = parse_width_cm(tags.get("width") or tags.get("est_width"))
    if width is not None:
        evidence.append(Evidence(
            "width_cm", width, Status.MAPPED, source,
            note="Estimated by the mapper" if "est_width" in tags and "width" not in tags else None,
        ))

    if tags.get("lit"):
        evidence.append(Evidence("lit", tags["lit"], Status.MAPPED, source))
    return cls, evidence


def access_forbidden(tags: Dict[str, str]) -> bool:
    """Whether a walker may not use this way at all.

    `foot` overrides `access` because that is how OSM expresses "closed to
    vehicles, open to people on foot".
    """
    foot = (tags.get("foot") or "").strip()
    if foot:
        return foot in _FORBIDDEN
    return (tags.get("access") or "").strip() in _FORBIDDEN


def steps_barrier(tags: Dict[str, str], at_m: float, source: str) -> Barrier:
    """A flight of steps, with what the map says about a ramp."""
    ramp: Optional[bool] = None
    for key in ("ramp:stroller", "ramp:wheelchair", "ramp"):
        value = (tags.get(key) or "").strip()
        if value:
            ramp = value == "yes"
            break
    count = None
    raw_count = (tags.get("step_count") or "").strip()
    if raw_count.isdigit():
        count = int(raw_count)
    return Barrier(BarrierKind.STEPS, at_m, Status.MAPPED, source,
                   step_count=count, has_ramp=ramp)


def barrier_from_node(tags: Dict[str, str], at_m: float, source: str) -> Optional[Barrier]:
    raw = (tags.get("barrier") or "").strip()
    if not raw or raw in ("kerb",):      # a kerb on a crossing is not a path barrier
        return None
    kind = _BARRIER.get(raw, BarrierKind.OTHER)
    return Barrier(
        kind, at_m, Status.MAPPED, source,
        width_cm=parse_width_cm(tags.get("maxwidth:physical") or tags.get("width")),
        note=None if kind is not BarrierKind.OTHER else f"Mapped as barrier={raw}",
    )


_WIDTH = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(m|cm)?\s*$")


def parse_width_cm(raw: Optional[str]) -> Optional[int]:
    """OSM widths are metres unless stated. Anything unparseable is unknown."""
    if not raw:
        return None
    m = _WIDTH.match(raw)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2) or "m"
    return int(round(value * 100)) if unit == "m" else int(round(value))

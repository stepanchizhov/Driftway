"""
Ranking venue candidates for a group.

Two decisions shape this module.

**Absolute minutes, never percentages.** 90 and 120 minutes are 30 minutes
apart. Calling that "75% similar" makes an hour-and-a-half asymmetry sound
like a rounding error, and it is the parent doing the extra half hour who
would be misled. Every figure here is in minutes, and the UI shows them.

**Gated ordering, not one weighted number.** A single blended score lets a
great rating quietly outvote a stated maximum drive time. Instead the
comparison walks a list of criteria in priority order and stops at the first
that separates two candidates - so a hard maximum can never be traded away
against a nicer cafe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

log = logging.getLogger("driftway")


# The order criteria are applied in. Earlier entries dominate later ones
# absolutely. Exposed as data so it can be logged, tested and tuned without
# rewriting the comparison.
RANK_ORDER = (
    "hard_violations",     # fewest participants over their stated maximum
    "preferred_penalty",   # closest to what people said they wanted
    "max_burden",          # spare the worst-off participant
    "spread",              # then even it out
    "total_burden",        # then minimise total driving
    "suitability_rank",    # allowed before conditional
    "opening_rank",        # open before unknown before closed
    "rating_rank",         # provider rating, inverted so lower sorts better
)


@dataclass
class ParticipantNeed:
    """One parent's constraints for this meetup."""

    participant_id: str
    preferred_minutes: Optional[int] = None
    tolerance_minutes: Optional[int] = None
    max_minutes: Optional[int] = None


@dataclass
class VenueScore:
    venue_index: int
    travel: List[dict] = field(default_factory=list)
    spread: float = 0.0
    max_burden: float = 0.0
    total_burden: float = 0.0
    hard_violations: int = 0
    preferred_penalty: float = 0.0
    breakdown: Dict[str, object] = field(default_factory=dict)
    unroutable: bool = False

    def sort_key(self) -> tuple:
        return tuple(self.breakdown.get(k, 0) for k in RANK_ORDER)


_SUITABILITY_RANK = {"allowed": 0, "conditional": 1}
_OPENING_RANK = {"open": 0, "unknown": 1, "closed": 2}


def score_venue(
    venue_index: int,
    minutes_by_participant: Dict[str, Optional[float]],
    needs: List[ParticipantNeed],
    *,
    suitability: str = "allowed",
    opening_status: str = "unknown",
    provider_rating: Optional[float] = None,
) -> VenueScore:
    """Measure one venue against every participant's stated needs."""
    by_id = {n.participant_id: n for n in needs}
    travel: List[dict] = []
    reachable: List[float] = []
    hard_violations = 0
    preferred_penalty = 0.0

    for need in needs:
        minutes = minutes_by_participant.get(need.participant_id)
        if minutes is None:
            # Unroutable for this participant. Not a preference failure - the
            # venue simply cannot serve them.
            travel.append({
                "participant_id": need.participant_id,
                "direct_minutes": 0.0,
                "preferred_delta_minutes": None,
                "exceeds_maximum": False,
                "unroutable": True,
            })
            continue

        reachable.append(minutes)
        exceeds = need.max_minutes is not None and minutes > need.max_minutes
        if exceeds:
            hard_violations += 1

        delta = None
        if need.preferred_minutes is not None:
            delta = round(minutes - need.preferred_minutes, 1)
            # Scale the miss by the tolerance the parent gave. Someone who said
            # "35, give or take 15" should not be treated like someone who said
            # "35, give or take 5".
            scale = float(need.tolerance_minutes or 10)
            preferred_penalty += abs(delta) / max(scale, 1.0)

        travel.append({
            "participant_id": need.participant_id,
            "direct_minutes": minutes,
            "preferred_delta_minutes": delta,
            "exceeds_maximum": exceeds,
        })

    if not reachable:
        return VenueScore(
            venue_index=venue_index, travel=travel, unroutable=True,
            hard_violations=len(needs),
            breakdown={"unroutable": True, "hard_violations": len(needs)},
        )

    spread = round(max(reachable) - min(reachable), 1)
    max_burden = round(max(reachable), 1)
    total_burden = round(sum(reachable), 1)

    breakdown = {
        "hard_violations": hard_violations,
        "preferred_penalty": round(preferred_penalty, 3),
        "max_burden": max_burden,
        "spread": spread,
        "total_burden": total_burden,
        "suitability_rank": _SUITABILITY_RANK.get(suitability, 2),
        "opening_rank": _OPENING_RANK.get(opening_status, 1),
        # Negated so that a higher rating produces a lower (better) sort value,
        # keeping every criterion "smaller is better".
        "rating_rank": -(provider_rating or 0.0),
        "rank_order": list(RANK_ORDER),
    }

    return VenueScore(
        venue_index=venue_index,
        travel=travel,
        spread=spread,
        max_burden=max_burden,
        total_burden=total_burden,
        hard_violations=hard_violations,
        preferred_penalty=round(preferred_penalty, 3),
        breakdown=breakdown,
    )


@dataclass
class RankedResult:
    ordered: List[VenueScore]
    #

    # Set when nothing satisfies every stated maximum. The UI must ask the
    # group what to relax rather than silently serving a venue that breaks
    # somebody's limit.
    no_fit: bool = False
    notice: Optional[str] = None


def rank_venues(scores: List[VenueScore], needs: List[ParticipantNeed],
                *, limit: int = 5) -> RankedResult:
    """Order candidates and report honestly when none of them fit."""
    usable = [s for s in scores if not s.unroutable]
    if not usable:
        return RankedResult(
            ordered=[], no_fit=True,
            notice="None of these places could be routed from everyone's "
                   "starting point. Try adding somewhere else.",
        )

    ordered = sorted(usable, key=lambda s: s.sort_key())
    fitting = [s for s in ordered if s.hard_violations == 0]

    if fitting:
        return RankedResult(ordered=fitting[:limit])

    # Everything breaks somebody's maximum. Still show the closest options -
    # hiding them would leave the group with nothing to react to - but say so
    # plainly and let them decide what to relax.
    anyone_capped = any(n.max_minutes is not None for n in needs)
    notice = (
        "No option fits everyone's maximum drive time. The closest are below - "
        "you could widen a limit, or add somewhere else."
        if anyone_capped else
        "None of these worked out evenly. The closest are below."
    )
    return RankedResult(ordered=ordered[:limit], no_fit=True, notice=notice)

"""
Route generation orchestrator.

Ties geometry + router + scorer together into the seven-step pipeline from
the project bible:

  1. estimate radius        2. generate candidate shapes/bearings
  3. evaluate via provider  4. rescale toward target duration
  5. validate               6. score
  7. dedupe and return top 3
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

log = logging.getLogger("driftway")

from .geometry import (
    SHAPES,
    bearings_for_direction,
    build_candidate,
    estimate_radius_km,
    rescale_anchors,
)
from .models import (
    Coord,
    GenerateRequest,
    GenerateResponse,
    RouteOption,
)
from .router import EvaluatedRoute, Router
from .scorer import (
    dedupe,
    describe_character,
    passes_validation,
    rejection_reason,
    score_route,
)

# How many candidates to build. shapes x bearings, capped for cost control.
MAX_CANDIDATES = 15
# One extra rescale pass if a candidate is outside tolerance after first eval.
RESCALE_ENABLED = True


def google_maps_url(start: Coord, finish: Coord, anchors: List[Coord]) -> str:
    """Build a Google Maps directions URL. Mobile supports up to 3 waypoints,
    so we cap anchors at 3 (our shapes already respect this)."""
    base = "https://www.google.com/maps/dir/?api=1"
    origin = f"&origin={start.lat:.6f},{start.lng:.6f}"
    dest = f"&destination={finish.lat:.6f},{finish.lng:.6f}"
    wp = ""
    if anchors:
        capped = anchors[:3]
        wp = "&waypoints=" + "|".join(f"{a.lat:.6f},{a.lng:.6f}" for a in capped)
    return f"{base}{origin}{dest}{wp}&travelmode=driving"


async def _evaluate_all(router: Router, start: Coord, finish: Coord,
                        candidates: List[List[Coord]], profile: str
                        ) -> List[EvaluatedRoute]:
    tasks = [router.evaluate(start, finish, c, profile) for c in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: List[EvaluatedRoute] = []
    for r in results:
        if isinstance(r, EvaluatedRoute):
            out.append(r)
    return out


async def generate_routes(req: GenerateRequest, router: Router) -> GenerateResponse:
    start = req.start
    finish = req.finish or req.start
    profile = req.road_profile.value

    # 1. seed radius
    radius = estimate_radius_km(req.target_minutes, profile)

    # 2. build candidates across shapes and bearings
    candidates: List[List[Coord]] = []
    for bearing in bearings_for_direction(req.direction):
        for shape in SHAPES:
            candidates.append(build_candidate(start, bearing, radius, shape))
            if len(candidates) >= MAX_CANDIDATES:
                break
        if len(candidates) >= MAX_CANDIDATES:
            break

    # 3. evaluate
    evaluated = await _evaluate_all(router, start, finish, candidates, profile)

    # 4. rescale any that missed tolerance, then re-evaluate just those
    if RESCALE_ENABLED:
        to_fix: List[List[Coord]] = []
        for ev in evaluated:
            if abs(ev.minutes - req.target_minutes) > req.tolerance_minutes and ev.minutes > 0:
                scale = req.target_minutes / ev.minutes
                # clamp scale so we don't make wild jumps
                scale = max(0.5, min(1.8, scale))
                to_fix.append(rescale_anchors(start, ev.anchors, scale))
        if to_fix:
            refined = await _evaluate_all(router, start, finish, to_fix, profile)
            evaluated.extend(refined)

    # 5. validate
    valid = [ev for ev in evaluated if passes_validation(ev, finish)]

    # Diagnostic breadcrumbs — visible in the Render logs. If routes come back
    # empty, this tells you *where* in the pipeline they were lost.
    from collections import Counter
    reasons = Counter(
        rejection_reason(ev, finish) for ev in evaluated
        if rejection_reason(ev, finish) is not None
    )
    log.info(
        "generate: provider=%s candidates=%d evaluated=%d valid=%d rejects=%s (target=%dmin %s)",
        router.name,
        len(candidates),
        len(evaluated),
        len(valid),
        dict(reasons),
        req.target_minutes,
        profile,
    )

    # 6. score and sort
    scored = sorted(
        valid, key=lambda ev: score_route(ev, req.target_minutes, profile), reverse=True
    )

    # 7. dedupe, take top 3
    top = dedupe(scored)[:3]

    options: List[RouteOption] = []
    for ev in top:
        options.append(
            RouteOption(
                id=str(uuid.uuid4())[:8],
                predicted_minutes=ev.minutes,
                distance_km=ev.distance_km,
                character=describe_character(ev.road_mix),
                road_mix=ev.road_mix,
                score=score_route(ev, req.target_minutes, profile),
                delta_minutes=round(ev.minutes - req.target_minutes, 1),
                waypoints=ev.anchors[:3],
                maps_url=google_maps_url(start, finish, ev.anchors),
                confidence="medium",
            )
        )

    return GenerateResponse(
        routes=options,
        target_minutes=req.target_minutes,
        tolerance_minutes=req.tolerance_minutes,
        generated_at=datetime.now(timezone.utc).isoformat(),
        provider=router.name,
        candidates_evaluated=len(evaluated),
    )

"""
Route generation orchestrator.

Ties geometry + router + scorer together into the pipeline from the project
bible:

  1. estimate radius        2. generate candidate shapes/bearings
  3. evaluate via provider  4. refine toward the target duration (iterative)
  5. validate               6. score
  7. dedupe and return top 3

Step 4 is iterative on purpose. Real road networks are lumpy: doubling the
anchor radius does not double the drive time, and a river or a motorway
junction can make a small loop take much longer than a big one. A single
correction pass therefore misses badly on short targets. We instead measure,
rescale, and re-measure a few times, keeping *every* evaluation in a pool and
picking whichever actually landed nearest the target.
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
    haversine_km,
    nearest_point_on_path,
    rescale_anchors,
)
from .detour import (
    build_detour_candidates,
    estimate_bulge_km,
    rescale_detour,
)
from .navigation import build_options
from .models import (
    Coord,
    GenerateRequest,
    GenerateResponse,
    NavigationOption,
    RouteMode,
    RouteOption,
)
from .router import EvaluatedRoute, MockRouter, Router
from .scorer import (
    dedupe,
    describe_character,
    passes_validation,
    rejection_reason,
    score_route,
    turnaround_count,
)

# How many candidates to build in the first pass. Kept modest because the
# request budget now goes on refinement rather than breadth.
MAX_CANDIDATES = 8
# Extra measure/rescale rounds after the first evaluation.
REFINE_PASSES = 4
# How many off-target routes to refine per round (the closest ones).
REFINE_POOL = 6
# Stop nudging a route once the correction is this small - it is inside the
# provider's own traffic noise.
MIN_SCALE_STEP = 0.05


def downsample(points: List[Coord], max_points: int = 48) -> List[Coord]:
    """Thin a dense polyline down to ~max_points for the card preview.

    TomTom returns hundreds of points per route; a thumbnail needs far fewer.
    Always keeps the first and last point so the loop stays closed.
    """
    n = len(points)
    if n <= max_points:
        return points
    step = n / max_points
    out = [points[int(i * step)] for i in range(max_points)]
    out[-1] = points[-1]  # ensure the loop closes on the true finish
    return out


def snap_to_route(anchors: List[Coord], geometry: List[Coord]) -> List[Coord]:
    """Move each anchor onto the road the car will actually drive.

    Anchors start life as pure geometry - "3.2 km on a bearing of 137" - so
    nothing stops one landing in a field, on the far bank of a river, or on
    the wrong deck of a flyover. Google then draws its dotted "you are not on
    a road" connector and may contort the route to reach the pin.

    Once the provider has returned the real polyline we know exactly where the
    road is, so we project each anchor onto it. The waypoint we hand to Google
    is then on the route by construction, not near it.
    """
    if not geometry:
        return anchors
    return [nearest_point_on_path(a, geometry) for a in anchors]


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


def _miss(route: EvaluatedRoute, target_minutes: int) -> float:
    """How far this route is from the requested duration, in minutes."""
    return abs(route.minutes - target_minutes)


def _confidence(route: EvaluatedRoute, target_minutes: int,
                tolerance_minutes: int) -> str:
    """Honest label for how well the route hit the requested duration."""
    miss = _miss(route, target_minutes)
    if miss <= tolerance_minutes / 2:
        return "high"
    if miss <= tolerance_minutes:
        return "medium"
    return "low"


def _caveat(ev: EvaluatedRoute, finish: Coord, req: GenerateRequest) -> Optional[str]:
    """Say plainly which preference this route misses, or None if it misses none.

    Genuine constraints (the endpoints, a drivable road) are never relaxed.
    These are the quality preferences, and when one is relaxed the parent is
    told rather than left to notice on the road.
    """
    notes: List[str] = []
    if _miss(ev, req.target_minutes) > req.tolerance_minutes:
        notes.append(
            f"about {ev.minutes:.0f} min, outside your "
            f"{req.target_minutes} +/- {req.tolerance_minutes} min window"
        )
    turns = turnaround_count(ev)
    if turns == 1:
        notes.append("doubles back once")
    elif turns > 1:
        notes.append(f"doubles back {turns} times")
    reason = rejection_reason(ev, finish)
    if reason == "overlap":
        notes.append("repeats part of the route")
    elif reason == "early_finish":
        notes.append("passes the destination mid-drive")
    return "; ".join(notes) if notes else None


def _loop_candidates(start: Coord, req: GenerateRequest, profile: str
                     ) -> List[List[Coord]]:
    """Anchor sets for loop mode, spread across the allowed bearings first.

    Bearings are the outer loop so that a "surprise me" request explores every
    direction before it spends budget on a second shape in a direction it has
    already covered.
    """
    radius = estimate_radius_km(req.target_minutes, profile)
    bearings = bearings_for_direction(req.direction)
    candidates: List[List[Coord]] = []
    for round_idx in range(len(SHAPES)):
        for i, bearing in enumerate(bearings):
            shape = SHAPES[(i + round_idx) % len(SHAPES)]
            candidates.append(build_candidate(start, bearing, radius, shape))
            if len(candidates) >= MAX_CANDIDATES:
                return candidates
    return candidates


def _anchor_signature(anchors: List[Coord]) -> tuple:
    """Identity for a candidate, to ~10 m. Stops the refiner from paying for
    the same route twice when a pass rescales back onto old ground."""
    return tuple((round(a.lat, 4), round(a.lng, 4)) for a in anchors)


async def _refine(router: Router, start: Coord, finish: Coord, profile: str,
                  seed: List[EvaluatedRoute], req: GenerateRequest,
                  is_loop: bool) -> List[EvaluatedRoute]:
    """Measure, rescale, re-measure.

    Returns every evaluation made, including the ones we started from, so a
    good route found early is never thrown away by a later pass. Each pass
    climbs from the closest routes found *so far* rather than from the previous
    pass alone, so one bad overshoot does not throw away the progress made.
    """
    pool: List[EvaluatedRoute] = list(seed)
    seen = {_anchor_signature(ev.anchors) for ev in seed}

    for _ in range(REFINE_PASSES):
        misses = sorted(
            (ev for ev in pool
             if ev.minutes > 0
             and _miss(ev, req.target_minutes) > req.tolerance_minutes),
            key=lambda ev: _miss(ev, req.target_minutes),
        )[:REFINE_POOL]
        if not misses:
            break

        next_candidates: List[List[Coord]] = []
        for ev in misses:
            # Damped correction: drive time is only loosely proportional to
            # loop size, so a raw ratio overshoots and then oscillates.
            scale = (req.target_minutes / ev.minutes) ** 0.75
            scale = max(0.25, min(3.0, scale))
            if abs(scale - 1.0) < MIN_SCALE_STEP:
                continue
            if is_loop:
                anchors = rescale_anchors(start, ev.anchors, scale)
            else:
                anchors = rescale_detour(start, finish, ev.anchors, scale)
            sig = _anchor_signature(anchors)
            if sig in seen:
                continue
            seen.add(sig)
            next_candidates.append(anchors)

        if not next_candidates:
            break
        got = await _evaluate_all(router, start, finish, next_candidates, profile)
        if not got:
            break
        pool.extend(got)

    return pool


def _pick_top_three(evaluated: List[EvaluatedRoute], finish: Coord,
                    req: GenerateRequest, profile: str) -> List[EvaluatedRoute]:
    """Choose three meaningfully different routes.

    Preference order matters, and duration comes first. The validation rules
    are project-bible hypotheses about what makes a drive pleasant; the
    duration is the actual promise on the button. In particular a 5-10 minute
    loop trips the self-overlap rule almost by definition - there are only so
    many ways to spend eight minutes near one postcode - and ranking those
    rules above the clock was what made short targets return half-hour drives.
    """
    def in_tolerance(ev: EvaluatedRoute) -> bool:
        return _miss(ev, req.target_minutes) <= req.tolerance_minutes

    valid = [ev for ev in evaluated if passes_validation(ev, finish)]
    on_time = [ev for ev in evaluated if in_tolerance(ev)]
    best_of_both = [ev for ev in valid if in_tolerance(ev)]

    # First non-empty tier wins.
    preferred = best_of_both or on_time or valid or evaluated
    if not preferred:
        return []

    scored = sorted(
        preferred,
        key=lambda ev: score_route(ev, req.target_minutes, profile),
        reverse=True,
    )
    # Scale "meaningfully different" to the size of the drive: 1.5 km apart is
    # a different route for a 10-minute loop and a rounding error for a 90.
    min_diff = max(0.3, 0.10 * scored[0].distance_km) if scored else 1.5
    # No backfilling. Three genuinely different routes is the aim, but padding
    # the list with a route we would not recommend just to reach three sends a
    # parent down a bad road to satisfy a number in the UI.
    return dedupe(scored, min_diff)[:3]


# A padded route can never be quicker than driving straight there, so the
# direct duration is a hard floor. Allow this much slack before calling a
# request impossible - asking for 30 when the direct drive is 29 is really a
# request for the direct drive.
DIRECT_FLOOR_SLACK_MIN = 2.0


_DEMOTE = {"high": "medium", "medium": "low", "low": "low"}


def _build_option(ev: EvaluatedRoute, start: Coord, finish: Coord,
                  req: GenerateRequest, profile: str, simulated: bool,
                  direct: Optional[EvaluatedRoute],
                  is_direct: bool = False,
                  preferred_nav: Optional[str] = None) -> RouteOption:
    """Turn an evaluated route into the shape the app renders."""
    # Duration accuracy sets the confidence, since that is the promise on the
    # button. Tripping a quality rule costs one step rather than forcing "low":
    # those rules are hypotheses, and a route that lands exactly on the
    # requested time has clearly not failed the user.
    confidence = _confidence(ev, req.target_minutes, req.tolerance_minutes)
    if not passes_validation(ev, finish):
        confidence = _DEMOTE[confidence]
    if simulated:
        confidence = "low"

    # Snap against the full polyline, before it is thinned for the thumbnail,
    # so the waypoint lands on the road rather than on a shortcut between two
    # downsampled points.
    anchors = snap_to_route(ev.anchors, ev.geometry)[:3]

    extra = None
    if direct is not None:
        extra = round(ev.minutes - direct.minutes, 1)

    return RouteOption(
        id=str(uuid.uuid4())[:8],
        predicted_minutes=ev.minutes,
        distance_km=ev.distance_km,
        character=describe_character(ev.road_mix),
        road_mix=ev.road_mix,
        score=score_route(ev, req.target_minutes, profile),
        delta_minutes=round(ev.minutes - req.target_minutes, 1),
        waypoints=anchors,
        geometry=downsample(ev.geometry),
        # A simulated route gets no navigation link at all. See the note where
        # the fallback is triggered.
        maps_url="" if simulated else google_maps_url(start, finish, anchors),
        confidence=confidence,
        navigation=build_options(
            start, finish, anchors,
            is_loop=haversine_km(start, finish) < 0.1,
            simulated=simulated,
            preferred_id=preferred_nav,
        ),
        extra_minutes=extra,
        is_direct=is_direct,
        simulated=simulated,
        caveat=_caveat(ev, finish, req) if not is_direct else None,
    )


def _notice(options: List[RouteOption], req: GenerateRequest,
            mode: RouteMode, simulated: bool) -> Optional[str]:
    """The one-line explanation shown above the results, when one is owed."""
    if simulated:
        return ("Live routing is unavailable, so these are simulated demo "
                "routes. They are not real roads and cannot be opened in "
                "Google Maps.")
    if not options:
        noun = "loop" if mode is RouteMode.LOOP else "route"
        return (f"No suitable {noun} found for about {req.target_minutes} "
                f"minutes on these roads. Try a different duration, a wider "
                f"tolerance, or another road style.")
    if len(options) < 3:
        found = "one route" if len(options) == 1 else f"{len(options)} routes"
        return (f"Only {found} worth offering here. The rest doubled back or "
                f"missed your time window, so they were left out.")
    return None


def _direct_only_response(req: GenerateRequest, start: Coord, finish: Coord,
                          direct: EvaluatedRoute, provider: str
                          ) -> GenerateResponse:
    """Answer for a target at or below the direct drive.

    You cannot reach somewhere more quickly than the quickest route, so there
    is nothing to pad. Say the real number and offer that route.
    """
    option = _build_option(direct, start, finish, req, req.road_profile.value,
                           simulated=False, direct=direct, is_direct=True,
                           preferred_nav=req.preferred_navigation)
    return GenerateResponse(
        routes=[option],
        target_minutes=req.target_minutes,
        tolerance_minutes=req.tolerance_minutes,
        generated_at=datetime.now(timezone.utc).isoformat(),
        provider=provider,
        candidates_evaluated=1,
        mode=RouteMode.DESTINATION,
        direct_minutes=round(direct.minutes, 1),
        simulated=False,
        notice=_floor_notice(req.target_minutes, direct.minutes),
    )


def _floor_notice(target: int, direct_minutes: float) -> str:
    """Explain why the answer is the direct route.

    Two different situations, which deserve different sentences. Asking for 10
    minutes when the drive takes 40 is impossible. Asking for 15 when it takes
    15 is not a mistake at all - the drive is simply already about that long,
    and telling a parent that is "not possible" would be nonsense.
    """
    rounded = round(direct_minutes)
    if target >= rounded:
        return (
            f"That drive already takes about {rounded} minutes, so there is "
            f"nothing to add. Here is the direct way."
        )
    return (
        f"That drive takes about {rounded} minutes even by the quickest route, "
        f"so {target} minutes is not possible. Here is the direct way."
    )


async def _direct_route(router: Router, start: Coord, finish: Coord,
                        profile: str) -> Optional[EvaluatedRoute]:
    """The plain quickest drive between the two points: one routing call.

    Destination mode needs this before anything else. It is the floor the
    request is measured against, and the fallback we offer when the parent asks
    for less time than the journey actually takes.
    """
    results = await _evaluate_all(router, start, finish, [[]], profile)
    return results[0] if results else None


async def generate_routes(req: GenerateRequest, router: Router) -> GenerateResponse:
    start = req.start
    finish = req.finish or req.start
    profile = req.road_profile.value

    # A loop returns to its start; a destination route ends somewhere else and
    # pads the journey to fill the requested total. We treat "finish within
    # 100 m of start" as a loop whatever the client asked for, because a
    # destination 20 m away is a loop in every way that matters to the router.
    is_loop = haversine_km(start, finish) < 0.1
    mode = RouteMode.LOOP if is_loop else RouteMode.DESTINATION
    if req.mode is not None and req.mode != mode:
        log.info("client asked for mode=%s; coordinates say %s",
                 req.mode.value, mode.value)

    direct: Optional[EvaluatedRoute] = None
    if not is_loop:
        direct = await _direct_route(router, start, finish, profile)
        if direct is not None and req.target_minutes <= direct.minutes + DIRECT_FLOOR_SLACK_MIN:
            # Impossible as asked. You cannot drive somewhere more quickly than
            # the quickest route, so say so and hand back that route rather
            # than silently returning something much longer.
            return _direct_only_response(req, start, finish, direct, router.name)

    if is_loop:
        # 1-2. loop candidates across shapes and bearings
        candidates = _loop_candidates(start, req, profile)
    else:
        # 1-2. detour candidates: padded routes from start to finish
        bulge = estimate_bulge_km(start, finish, req.target_minutes, profile)
        candidates = build_detour_candidates(start, finish, bulge)

    # 3. evaluate
    evaluated = await _evaluate_all(router, start, finish, candidates, profile)

    provider_name = router.name
    simulated = isinstance(router, MockRouter)
    if not evaluated and not simulated:
        # The live provider gave us nothing at all: key rejected, network down,
        # or no routable road near this point. We still build simulated routes
        # so the screen can show what the app would do, but they are labelled
        # as a demo and carry no navigation link - their geometry is a straight
        # line between invented points, and handing that to a navigation app
        # would dress a guess up as a drivable route.
        log.warning(
            "provider=%s returned no usable routes; showing simulated demo routes",
            router.name,
        )
        router = MockRouter()
        simulated = True
        provider_name = f"{provider_name}+simulated"
        evaluated = await _evaluate_all(router, start, finish, candidates, profile)

    # 4. refine toward the target duration
    evaluated = await _refine(router, start, finish, profile, evaluated, req, is_loop)

    # 5-7. validate, score, dedupe, take the best three. Selection weighs
    # validation and duration together rather than filtering on validation
    # first - see _pick_top_three.
    top = _pick_top_three(evaluated, finish, req, profile)

    # Diagnostic breadcrumbs - visible in the Render logs. If routes come back
    # empty or off-target, this tells you *where* in the pipeline they went.
    from collections import Counter
    reasons = Counter(
        rejection_reason(ev, finish) for ev in evaluated
        if rejection_reason(ev, finish) is not None
    )
    log.info(
        "generate: provider=%s candidates=%d evaluated=%d valid=%d on_time=%d "
        "smooth=%d returned=%s rejects=%s (target=%dmin +/-%d %s)",
        provider_name,
        len(candidates),
        len(evaluated),
        sum(1 for ev in evaluated if passes_validation(ev, finish)),
        sum(1 for ev in evaluated
            if _miss(ev, req.target_minutes) <= req.tolerance_minutes),
        # How many candidates never ask the driver to double back. If this is
        # persistently 0, the provider is the problem, not the search.
        sum(1 for ev in evaluated if turnaround_count(ev) == 0),
        [f"{ev.minutes:.0f}min/{turnaround_count(ev)}turns" for ev in top],
        dict(reasons),
        req.target_minutes,
        req.tolerance_minutes,
        profile,
    )

    options = [
        _build_option(ev, start, finish, req, profile, simulated, direct,
                      preferred_nav=req.preferred_navigation)
        for ev in top
    ]

    return GenerateResponse(
        routes=options,
        target_minutes=req.target_minutes,
        tolerance_minutes=req.tolerance_minutes,
        generated_at=datetime.now(timezone.utc).isoformat(),
        provider=provider_name,
        candidates_evaluated=len(evaluated),
        mode=mode,
        direct_minutes=round(direct.minutes, 1) if direct else None,
        simulated=simulated,
        notice=_notice(options, req, mode, simulated),
    )

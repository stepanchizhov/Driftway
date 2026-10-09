"""
Gradients from a height profile - one implementation, shared.

Used by the walk builder (heights from the EU-DEM 25 m model) and by generated
walks (heights returned by openrouteservice). The two used to be on course to
become two copies of the same arithmetic with slowly diverging thresholds,
which is how two walks of identical steepness end up described differently.
"""

from __future__ import annotations

from typing import List, Sequence

from .evidence import Gradient, Section, Status

#: Shortest stretch a gradient is measured over. Height models with 25-90 m
#: cells cannot resolve anything shorter, so they are not asked to.
GRADE_WINDOW_M = 50.0
#: Ignore height wobble smaller than this when summing ascent; model noise
#: would otherwise add phantom metres on flat ground.
ASCENT_HYSTERESIS_M = 1.0


def smooth(elevations: Sequence[float]) -> List[float]:
    """Light smoothing: height models are noisy at the metre scale."""
    out = []
    for i in range(len(elevations)):
        window = elevations[max(0, i - 1):i + 2]
        out.append(sum(window) / len(window))
    return out


def attach_gradients(sections: List[Section], dists: Sequence[float],
                     heights: Sequence[float], source: str) -> None:
    """Give each section its climb, descent and steepest stretches.

    `dists` are distances along the route of each height sample, in metres,
    increasing; `heights` the matching (already smoothed) heights.
    """
    if len(dists) < 2:
        return
    for s in sections:
        idx = [i for i, d in enumerate(dists) if s.from_m - 1e-6 <= d <= s.to_m + 1e-6]
        if len(idx) < 2:
            # Shorter than the sample spacing: borrow the nearest window.
            centre = (s.from_m + s.to_m) / 2
            near = min(range(len(dists)), key=lambda i: abs(dists[i] - centre))
            idx = [max(0, near - 1), min(len(dists) - 1, near + 1)]
        ascent = descent = 0.0
        anchor = heights[idx[0]]
        for i in idx[1:]:
            delta = heights[i] - anchor
            if abs(delta) >= ASCENT_HYSTERESIS_M:
                ascent += max(0.0, delta)
                descent += max(0.0, -delta)
                anchor = heights[i]
        up = down = 0.0
        # Steepness over a window at least GRADE_WINDOW_M long, centred on the
        # section, so a short section is judged by its surroundings rather than
        # by noise between two adjacent samples.
        span_m = max(GRADE_WINDOW_M, s.length_m)
        lo = max(0.0, (s.from_m + s.to_m) / 2 - span_m / 2)
        hi = lo + span_m
        window = [i for i, d in enumerate(dists) if lo - 1e-6 <= d <= hi + 1e-6]
        for i in window:
            for j in window:
                span = dists[j] - dists[i]
                if span >= GRADE_WINDOW_M - 1e-6:
                    g = (heights[j] - heights[i]) / span * 100
                    up, down = max(up, g), max(down, -g)
        s.gradient = Gradient(ascent, descent, up, down, Status.MODELLED, source)

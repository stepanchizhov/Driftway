"""
Navigation handoff: which app can actually drive the route we built.

NapLoop shapes a route with intermediate waypoints. Most navigation apps cannot
express that. Handing such a route to one of them does not fail loudly - it
quietly becomes a different drive, straight to the destination, missing the
shaping that made it the right length. For a parent whose child is asleep,
"quietly a different drive" is the worst possible failure.

So a provider is described by what it can *represent*, and a route is only
offered to a provider that can carry it. Where it cannot, that is stated
plainly and a compatible app is named. Provider incompatibility is a normal
product state, not an error.

Verified against current provider documentation, 11 September 2026:

  Google Maps  https://developers.google.com/maps/documentation/urls/get-started
      Waypoints via a pipe-separated `waypoints` parameter, order preserved.
      Documented limit: 3 on mobile browsers, 9 elsewhere. We cap at 3,
      because a phone is where this is used.

  Waze         https://developers.google.com/waze/deeplinks
      `ll=lat,lng&navigate=yes`. Single destination only - the documentation
      defines no parameter for intermediate stops. Good for Meet Halfway,
      wrong for a shaped nap loop.

  Apple Maps   https://developer.apple.com/library/archive/featuredarticles/
               iPhoneURLScheme_Reference/MapLinks/MapLinks.html
      `saddr` and `daddr` only. NOTE: the Maps *app* has supported multi-stop
      routes since iOS 16, but the URL scheme has no waypoint parameter, so a
      handoff cannot use it. Treated as destination-only here, which corrects
      an earlier working assumption that it was a multi-stop option.

GPX / exact-route export is LATER. The capability is modelled so it can be
added without reshaping this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, List, Optional

from .models import Coord, NavigationOption


class NavCapability(str, Enum):
    """What a navigation target can be asked to do."""

    DESTINATION = "destination"      # go to one point
    WAYPOINTS = "waypoints"          # go via intermediate points, in order
    EXACT_ROUTE = "exact_route"      # follow a supplied polyline (LATER)


@dataclass(frozen=True)
class NavProvider:
    id: str
    label: str
    capabilities: FrozenSet[NavCapability]
    # 0 for destination-only providers.
    max_waypoints: int
    # Empty means "anywhere". Used to avoid offering an iOS-only app on
    # Android, not as a security boundary.
    platforms: FrozenSet[str]

    def supports_waypoints(self) -> bool:
        return NavCapability.WAYPOINTS in self.capabilities


GOOGLE_MAPS = NavProvider(
    id="google_maps",
    label="Google Maps",
    capabilities=frozenset({NavCapability.DESTINATION, NavCapability.WAYPOINTS}),
    # The documented mobile-browser limit. Our generator never produces more.
    max_waypoints=3,
    platforms=frozenset(),
)

WAZE = NavProvider(
    id="waze",
    label="Waze",
    capabilities=frozenset({NavCapability.DESTINATION}),
    max_waypoints=0,
    platforms=frozenset(),
)

APPLE_MAPS = NavProvider(
    id="apple_maps",
    label="Apple Maps",
    capabilities=frozenset({NavCapability.DESTINATION}),
    max_waypoints=0,
    platforms=frozenset({"ios"}),
)

PROVIDERS = (GOOGLE_MAPS, WAZE, APPLE_MAPS)
DEFAULT_PROVIDER_ID = GOOGLE_MAPS.id


def provider_by_id(provider_id: Optional[str]) -> NavProvider:
    for p in PROVIDERS:
        if p.id == provider_id:
            return p
    return GOOGLE_MAPS


# --------------------------------------------------------------------- URLs

def _google_url(start: Coord, finish: Coord, waypoints: List[Coord]) -> str:
    base = "https://www.google.com/maps/dir/?api=1"
    url = f"{base}&origin={start.lat:.6f},{start.lng:.6f}"
    url += f"&destination={finish.lat:.6f},{finish.lng:.6f}"
    if waypoints:
        capped = waypoints[:GOOGLE_MAPS.max_waypoints]
        url += "&waypoints=" + "|".join(
            f"{w.lat:.6f},{w.lng:.6f}" for w in capped
        )
    return url + "&travelmode=driving"


def _waze_url(_start: Coord, finish: Coord, _waypoints: List[Coord]) -> str:
    return (
        f"https://waze.com/ul?ll={finish.lat:.6f}%2C{finish.lng:.6f}"
        f"&navigate=yes"
    )


def _apple_url(start: Coord, finish: Coord, _waypoints: List[Coord]) -> str:
    return (
        f"https://maps.apple.com/?saddr={start.lat:.6f},{start.lng:.6f}"
        f"&daddr={finish.lat:.6f},{finish.lng:.6f}&dirflg=d"
    )


_URL_BUILDERS = {
    GOOGLE_MAPS.id: _google_url,
    WAZE.id: _waze_url,
    APPLE_MAPS.id: _apple_url,
}


# ----------------------------------------------------------------- handoffs

def build_options(
    start: Coord,
    finish: Coord,
    waypoints: List[Coord],
    *,
    is_loop: bool,
    simulated: bool = False,
    preferred_id: Optional[str] = None,
) -> List[NavigationOption]:
    """Every way this particular route could actually be driven.

    Returns an empty list for a simulated route. That is deliberate and load
    bearing: simulated geometry is a straight line between invented points, and
    the app treats "no handoff" as "not drivable". A capability layer that
    always produced *some* URL would quietly undo that honesty.
    """
    if simulated:
        return []

    options: List[NavigationOption] = []
    needed = len(waypoints)

    for provider in PROVIDERS:
        # A loop asks a navigation app to end where it began. Without waypoint
        # support that is not a shorter version of the drive - it is no drive
        # at all, so those providers are not offered rather than offered
        # broken.
        if is_loop and not provider.supports_waypoints():
            continue

        preserves = needed == 0 or (
            provider.supports_waypoints() and provider.max_waypoints >= needed
        )
        dropped = 0 if preserves else needed

        notice = None
        if not preserves:
            notice = (
                f"{provider.label} can navigate to the destination, but it "
                f"cannot follow this shaped route. The drive would be "
                f"{'shorter and' if not is_loop else ''} different. "
                f"{GOOGLE_MAPS.label} keeps it intact."
            ).replace("  ", " ")

        options.append(NavigationOption(
            provider_id=provider.id,
            label=provider.label,
            url=_URL_BUILDERS[provider.id](start, finish, waypoints),
            preserves_route=preserves,
            dropped_waypoints=dropped,
            platforms=sorted(provider.platforms),
            notice=notice,
        ))

    # The preferred app first when it can carry the route; otherwise the best
    # one that can, so the default tap is always the faithful drive.
    def rank(o: NavigationOption) -> tuple:
        return (
            0 if (o.provider_id == preferred_id and o.preserves_route) else 1,
            0 if o.preserves_route else 1,
            0 if o.provider_id == DEFAULT_PROVIDER_ID else 1,
        )

    options.sort(key=rank)
    return options

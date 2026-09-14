"""
Data contracts for Driftway.

These Pydantic models define the request/response shapes between the
frontend PWA and the backend. Keep them stable; the frontend depends on them.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class RoadProfile(str, Enum):
    MOTORWAY = "motorway"   # Motorways & major roads
    MIXED = "mixed"
    QUIET = "quiet"         # Quieter local roads


class Direction(str, Enum):
    SURPRISE = "surprise"
    N = "N"
    E = "E"
    S = "S"
    W = "W"


class Coord(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class RouteMode(str, Enum):
    LOOP = "loop"                # start and finish are the same place
    DESTINATION = "destination"  # "go somewhere", taking about N minutes in total


class GenerateRequest(BaseModel):
    start: Coord
    finish: Optional[Coord] = None          # defaults to start if omitted
    target_minutes: int = Field(..., ge=5, le=240)
    tolerance_minutes: int = Field(10, ge=1, le=30)
    road_profile: RoadProfile = RoadProfile.MIXED
    direction: Direction = Direction.SURPRISE
    # Optional and advisory. The server still decides from the coordinates,
    # because a "destination" 20 m from the start is a loop whatever the
    # client calls it. Sending it lets the client's intent appear in the logs
    # when the two disagree.
    mode: Optional[RouteMode] = None
    # Which navigation app the parent prefers. Advisory: a preference is never
    # honoured at the cost of dropping the route's shaping waypoints.
    preferred_navigation: Optional[str] = None


class RoadMix(BaseModel):
    motorway: float = 0.0
    primary: float = 0.0      # A-roads / major
    secondary: float = 0.0    # B-roads
    residential: float = 0.0


class NavigationOption(BaseModel):
    """One navigation app, and whether it can carry this particular route."""

    provider_id: str
    label: str
    url: str
    # True when the app can carry this route's shaping waypoints. NOT a claim
    # that it reproduces our path or our duration - every provider recalculates
    # between the points it is given. What survives is the shaping, which is
    # what makes the drive the right length.
    keeps_waypoints: bool = True
    dropped_waypoints: int = 0
    # Empty means "anywhere"; otherwise the platforms it makes sense on.
    platforms: List[str] = []
    # Plain-language explanation when the route would not survive.
    notice: Optional[str] = None


class RouteOption(BaseModel):
    id: str
    predicted_minutes: float
    distance_km: float
    character: str                      # human-readable, e.g. "Mostly A-roads"
    road_mix: RoadMix
    score: float
    delta_minutes: float                # predicted - target (can be negative)
    waypoints: List[Coord]              # intermediate anchors only (max 3)
    geometry: List[Coord] = []          # downsampled real road polyline (for preview)
    maps_url: str                       # empty string when simulated - see below
    confidence: str = "medium"          # low | medium | high

    # Destination mode: how much longer than driving straight there.
    extra_minutes: Optional[float] = None
    # True when this is the plain quickest route, offered because the target
    # was at or below the direct drive and padding was impossible.
    is_direct: bool = False
    # True when the geometry and duration came from the simulator, not a live
    # provider. Simulated routes carry no maps_url: handing invented geometry
    # to a navigation app would present a guess as a driveable route.
    simulated: bool = False
    # Set when the route was returned despite missing a quality preference,
    # e.g. "outside your tolerance" or "doubles back once".
    caveat: Optional[str] = None

    # Every app that could drive this, best first. Empty for a simulated
    # route, which has nothing real to navigate. `maps_url` above remains the
    # Google Maps link so existing clients keep working unchanged.
    navigation: List[NavigationOption] = []


class Place(BaseModel):
    """A resolved location the user picked from search."""
    id: str
    label: str                  # primary line, e.g. "Windsor Leisure Centre"
    detail: str                 # secondary line, the fuller address
    coord: Coord
    kind: str                   # postcode | postcode_area | address | street | poi | place
    # True when the point is an area centroid rather than a precise spot, so
    # the UI can invite the user to refine it.
    approximate: bool = False


class SearchResponse(BaseModel):
    query: str
    places: List[Place]
    provider: str


class GenerateResponse(BaseModel):
    routes: List[RouteOption]
    target_minutes: int
    tolerance_minutes: int
    generated_at: str
    provider: str
    # Which geometry problem was actually solved.
    mode: RouteMode = RouteMode.LOOP
    # Destination mode only: the quickest drive between the two points under
    # the same road preference. The floor a padded route cannot go below.
    direct_minutes: Optional[float] = None
    # True when every route came from the simulator.
    simulated: bool = False
    # Plain-language explanation when the answer is not what was asked for:
    # target below the direct drive, nothing suitable found, fewer than three.
    notice: Optional[str] = None
    candidates_evaluated: int


class FeedbackRequest(BaseModel):
    route_id: str
    predicted_minutes: float
    actual_minutes: Optional[float] = None
    would_use_again: Optional[bool] = None
    baby_slept: Optional[str] = None     # "yes" | "no" | "unknown"
    notes: Optional[str] = None
    owner: Optional[str] = None          # anonymous local id from the device


class FavouriteCreate(BaseModel):
    owner: str
    label: str = ""
    place_label: str = "Home"
    duration_minutes: int
    distance_km: float = 0.0
    road_profile: str = "mixed"
    character: str = ""
    maps_url: str = ""


class FavouriteOut(BaseModel):
    #: "account" once it belongs to a signed-in account, "device" while it is
    #: held against this browser's anonymous id. The UI uses it to offer
    #: moving device rows onto the account, never to do so on its own.
    scope: str = "device"
    id: str
    label: str
    place_label: str
    duration_minutes: int
    distance_km: float
    road_profile: str
    character: str
    maps_url: str
    created_at: str

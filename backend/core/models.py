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


class StopFeeling(str, Enum):
    """How much one kind of stop bothers a parent's child (founder, 13 Oct
    2026: "allow the users choose what types of obstacles are better and
    worse for their kids. It easily can be different for each child")."""
    FINE = "fine"               # doesn't bother them
    SOMETIMES = "sometimes"     # the usual weight
    WAKES = "wakes"             # wakes them


class StopPrefs(BaseModel):
    """What wakes this child, one answer per kind of stop."""
    bumps: StopFeeling = StopFeeling.SOMETIMES
    lights: StopFeeling = StopFeeling.SOMETIMES
    turns: StopFeeling = StopFeeling.SOMETIMES
    #: Roadworks that stop traffic: stop/go, temporary lights, convoys.
    works: StopFeeling = StopFeeling.SOMETIMES


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
    #: What wakes the child; without it, the usual weights.
    stops: Optional[StopPrefs] = None
    #: The start was picked (an address, Home, a saved place, a point on the
    #: map), not the phone's own location: the navigation links then start
    #: there. Otherwise they carry no start, and the app starts from wherever
    #: the phone is (founder, 18 Oct 2026).
    start_chosen: bool = False
    #: A maintainer asks for this drive to be recorded for analysis
    #: (core/drive_records.py). Honoured only for maintainers, checked on the
    #: server.
    record: bool = False


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
    # Speed bumps mapped on OpenStreetMap along the drive (11 Oct 2026). A
    # lower bound: unmapped ones are not counted. None outside the prepared
    # data, and for a simulated route, whose geometry is invented.
    speed_bumps: Optional[int] = None
    # Traffic lights mapped along the drive (12 Oct 2026): junctions with
    # lights, and pedestrian-operated lights apart from junctions. Lower
    # bounds, like the speed bumps; None outside the prepared data.
    lights_junctions: Optional[int] = None
    lights_pedestrian: Optional[int] = None
    # Roadworks on the drive now that stop or close traffic (Street Manager,
    # England): "Victoria Street: temporary traffic lights".
    roadworks: List[str] = []
    #: Where they come from: "street_manager", "tomtom" (the card's credits).
    roadworks_sources: List[str] = []
    #: On an alternative a parent meets materially fewer stops on than the
    #: first drive: what it gains and gives up, kind by kind, and the time.
    tradeoff: Optional[str] = None
    #: What was checked for roadworks, and what couldn't be: "No roadworks
    #: found on this drive. Checked: ..." or "Roadworks couldn't be checked".
    roadworks_status: Optional[str] = None
    #: The full route, filled only while a recorded drive is stored and
    #: removed before the answer leaves the server.
    full_geometry: Optional[List[Coord]] = None

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

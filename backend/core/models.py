"""
Data contracts for Driftway.

These Pydantic models define the request/response shapes between the
frontend PWA and the backend. Keep them stable; the frontend depends on them.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

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


class GenerateRequest(BaseModel):
    start: Coord
    finish: Optional[Coord] = None          # defaults to start if omitted
    target_minutes: int = Field(..., ge=5, le=240)
    tolerance_minutes: int = Field(10, ge=1, le=30)
    road_profile: RoadProfile = RoadProfile.MIXED
    direction: Direction = Direction.SURPRISE


class RoadMix(BaseModel):
    motorway: float = 0.0
    primary: float = 0.0      # A-roads / major
    secondary: float = 0.0    # B-roads
    residential: float = 0.0


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
    maps_url: str
    confidence: str = "medium"          # low | medium | high (placeholder)


class GenerateResponse(BaseModel):
    routes: List[RouteOption]
    target_minutes: int
    tolerance_minutes: int
    generated_at: str
    provider: str
    candidates_evaluated: int


class FeedbackRequest(BaseModel):
    route_id: str
    predicted_minutes: float
    actual_minutes: Optional[float] = None
    would_use_again: Optional[bool] = None
    baby_slept: Optional[str] = None     # "yes" | "no" | "unknown"
    notes: Optional[str] = None

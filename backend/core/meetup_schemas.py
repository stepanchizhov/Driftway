"""
Wire contracts for Meet Halfway, and the serialisers that enforce privacy.

Every response the client sees is built here. That is the point: if the only
way to render a participant is through `participant_public()`, then an exact
origin cannot leak by someone forgetting to strip a field in a route handler.
The models below simply have nowhere to put one.
"""

from __future__ import annotations

import json
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .meetups import (
    MeetupParticipant,
    MeetupSession,
    MeetupVenueCandidate,
    MeetupVote,
    coarsen,
)
from .models import Coord

VoteValue = Literal["works", "maybe", "too_far", "not_this_venue"]
MeetupMode = Literal["filtered", "explore"]


# ------------------------------------------------------------------ requests

class ParticipantPrefs(BaseModel):
    """What a parent is willing to drive. All optional - a parent who does not
    care should not have to invent numbers."""

    preferred_minutes: Optional[int] = Field(None, ge=1, le=240)
    tolerance_minutes: Optional[int] = Field(None, ge=1, le=60)
    max_minutes: Optional[int] = Field(None, ge=1, le=240)


class OrganiserInput(ParticipantPrefs):
    start: Coord
    # Default ON, per the privacy rules. A parent has to opt *in* to revealing
    # where they set off from, never opt out.
    hide_exact_origin: bool = True
    display_name: Optional[str] = Field(None, max_length=80)


class CreateMeetupRequest(BaseModel):
    scheduled_at: Optional[str] = None
    mode: MeetupMode = "explore"
    categories: List[str] = []
    organiser: OrganiserInput


class JoinMeetupRequest(ParticipantPrefs):
    start: Coord
    hide_exact_origin: bool = True
    display_name: Optional[str] = Field(None, max_length=80)


class AddVenueRequest(BaseModel):
    """A venue a parent has chosen, normally straight from place search.

    Curated rather than discovered: a place a parent picked already carries
    their judgement about whether it suits children, which is the judgement
    the provider taxonomy cannot make.
    """

    name: str = Field(..., min_length=1, max_length=160)
    coord: Coord
    address_label: Optional[str] = Field(None, max_length=240)
    categories: List[str] = []
    provider_rating: Optional[float] = Field(None, ge=0, le=5)
    opening_status: Literal["open", "closed", "unknown"] = "unknown"


class AcceptInviteRequest(BaseModel):
    """Redeeming a beta invite.

    The token travels in the body, never the query string: uvicorn and most
    reverse proxies write full request lines to their access logs, so a token
    in the URL is a token in the logs, and in any Referer header the page
    happens to send.
    """

    # Optional at the schema level so open registration can post without one.
    # That is not a relaxation of the rule: accept_invite() checks the
    # registration mode server-side and still refuses a missing token while
    # the deployment is invite_only. Requiring it here instead would have made
    # the check unreachable, since pydantic would reject the request first.
    invite_token: Optional[str] = Field(None, min_length=8, max_length=128)
    email: Optional[str] = Field(None, max_length=320)
    display_name: Optional[str] = Field(None, max_length=80)


class VoteRequest(BaseModel):
    value: VoteValue
    comment: Optional[str] = Field(None, max_length=280)


# ----------------------------------------------------------------- responses

class ParticipantPublic(BaseModel):
    """A participant as other participants may see them.

    Note what is absent: `start_lat`, `start_lng`, `join_token`, `user_id`,
    email. There is no field here that could carry them.
    """

    id: str
    display_name: Optional[str] = None
    locality_label: Optional[str] = None
    # Present only when the participant chose to reveal, or as a coarse grid
    # centre when they did not.
    display_coord: Optional[Coord] = None
    origin_precision: Literal["exact", "approximate"] = "approximate"
    preferred_minutes: Optional[int] = None
    max_minutes: Optional[int] = None
    is_you: bool = False


class ParticipantTravel(BaseModel):
    participant_id: str
    direct_minutes: float
    preferred_delta_minutes: Optional[float] = None
    exceeds_maximum: bool = False


class VenueCandidatePublic(BaseModel):
    id: str
    name: str
    added_by_participant_id: Optional[str] = None
    added_by_you: bool = False
    coord: Coord
    address_label: Optional[str] = None
    canonical_categories: List[str] = []
    provider_rating: Optional[float] = None
    provider_review_count: Optional[int] = None
    opening_status: Literal["open", "closed", "unknown"] = "unknown"
    suitability: Literal["allowed", "conditional"] = "allowed"

    participant_travel: List[ParticipantTravel] = []
    # Absolute minutes, always. Never a percentage: "67% similar" hides whether
    # that is 4 minutes or 40.
    fairness_spread_minutes: float = 0.0
    total_travel_minutes: float = 0.0
    max_travel_minutes: float = 0.0
    group_fit_label: str = ""

    score: float = 0.0
    score_breakdown: Dict[str, object] = {}
    votes: Dict[str, int] = {}
    your_vote: Optional[VoteValue] = None


class MeetupPublic(BaseModel):
    id: str
    status: str
    mode: MeetupMode
    requested_categories: List[str] = []
    scheduled_at: Optional[str] = None
    participants: List[ParticipantPublic] = []
    candidates: List[VenueCandidatePublic] = []
    selected_venue_id: Optional[str] = None
    # Present only for the organiser's own view.
    results_url_slug: Optional[str] = None
    notice: Optional[str] = None
    # True when no venue satisfies every stated maximum. The UI must ask what
    # to relax rather than pretending the top result is fine.
    no_fit: bool = False


class MeetupCreated(BaseModel):
    meetup_id: str
    # The organiser's own write capability.
    your_join_token: str
    # Handed to the other parent. A different capability from the above.
    participant_invite_token: str
    # Read-only. A third, distinct capability.
    results_slug: str


class BetaInvitePublic(BaseModel):
    id: str
    status: str
    created_at: str
    expires_at: str
    bound_email: Optional[str] = None
    # Present only in the response that creates it.
    invite_token: Optional[str] = None


class AccountPublic(BaseModel):
    id: str
    display_name: Optional[str] = None
    status: str
    default_hide_exact_origin: bool


# --------------------------------------------------------------- serialisers

def participant_public(
    row: MeetupParticipant, *, viewer_id: Optional[str] = None
) -> ParticipantPublic:
    """Render a participant for group-facing output.

    A participant always sees their own exact origin - it is theirs. Everyone
    else sees the coarse grid centre, whatever their account status. Being
    registered does not earn you a peer's address.
    """
    is_you = viewer_id is not None and viewer_id == row.id

    if is_you or not row.hide_exact_origin:
        coord = Coord(lat=row.start_lat, lng=row.start_lng)
        precision = "exact"
    else:
        lat, lng = (row.display_lat, row.display_lng)
        if lat is None or lng is None:
            lat, lng = coarsen(row.start_lat, row.start_lng)
        coord = Coord(lat=lat, lng=lng)
        precision = "approximate"

    return ParticipantPublic(
        id=row.id,
        display_name=row.display_name,
        locality_label=row.locality_label,
        display_coord=coord,
        origin_precision=precision,
        preferred_minutes=row.preferred_minutes,
        max_minutes=row.max_minutes,
        is_you=is_you,
    )


def group_fit_label(spread_minutes: float) -> str:
    """Plain words for the spread, always shown *alongside* the real minutes."""
    if spread_minutes <= 5:
        return "Very even"
    if spread_minutes <= 12:
        return "Fairly even"
    if spread_minutes <= 25:
        return "Noticeably uneven"
    return "Significant difference"


def candidate_public(
    row: MeetupVenueCandidate,
    votes: List[MeetupVote],
    *,
    viewer_id: Optional[str] = None,
) -> VenueCandidatePublic:
    tally: Dict[str, int] = {}
    your_vote = None
    for v in votes:
        if v.venue_candidate_id != row.id:
            continue
        tally[v.value] = tally.get(v.value, 0) + 1
        if viewer_id and v.participant_id == viewer_id:
            your_vote = v.value

    try:
        travel = [ParticipantTravel(**t) for t in json.loads(row.travel_json or "[]")]
    except (ValueError, TypeError):
        travel = []
    try:
        breakdown = json.loads(row.score_breakdown or "{}")
    except (ValueError, TypeError):
        breakdown = {}

    return VenueCandidatePublic(
        id=row.id,
        name=row.name,
        added_by_participant_id=row.added_by_participant_id,
        added_by_you=bool(viewer_id) and row.added_by_participant_id == viewer_id,
        coord=Coord(lat=row.lat, lng=row.lng),
        address_label=row.address_label,
        canonical_categories=[c for c in (row.canonical_categories or "").split(",") if c],
        provider_rating=row.provider_rating,
        provider_review_count=row.provider_review_count,
        opening_status=row.opening_status,
        suitability=row.suitability,
        participant_travel=travel,
        fairness_spread_minutes=row.fairness_spread_minutes,
        total_travel_minutes=row.total_travel_minutes,
        max_travel_minutes=row.max_travel_minutes,
        group_fit_label=group_fit_label(row.fairness_spread_minutes),
        score=row.score,
        score_breakdown=breakdown,
        votes=tally,
        your_vote=your_vote,
    )


def meetup_public(
    meetup: MeetupSession,
    participants: List[MeetupParticipant],
    candidates: List[MeetupVenueCandidate],
    votes: List[MeetupVote],
    *,
    viewer_id: Optional[str] = None,
    include_results_slug: bool = False,
    notice: Optional[str] = None,
    no_fit: bool = False,
) -> MeetupPublic:
    return MeetupPublic(
        id=meetup.id,
        status=meetup.status,
        mode=meetup.mode,
        requested_categories=[
            c for c in (meetup.requested_categories or "").split(",") if c
        ],
        scheduled_at=meetup.scheduled_at.isoformat() if meetup.scheduled_at else None,
        participants=[participant_public(p, viewer_id=viewer_id) for p in participants],
        candidates=[candidate_public(c, votes, viewer_id=viewer_id) for c in candidates],
        selected_venue_id=meetup.selected_venue_id,
        results_url_slug=meetup.public_results_slug if include_results_slug else None,
        notice=notice,
        no_fit=no_fit,
    )

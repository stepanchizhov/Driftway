"""
Meet Halfway: meetup sessions, participants, venue candidates and votes.

The privacy rule that shapes this whole module: an exact starting coordinate is
*routing input*, not display data. It goes to the routing provider and it goes
nowhere else. Two parents arranging a playdate should not have to reveal their
home addresses to each other, and "they can see roughly where I am" is a
different consent from "they can see my front door".

Three capabilities exist and none of them is interchangeable with another:

  - join token      write, one participant, one meetup (origin, prefs, votes)
  - results slug    read-only, privacy-safe projection
  - admin token     founder-only, invite lifecycle (see config.admin_token)

Reusing one token for two scopes is how a read-only share link quietly becomes
an edit link, so the types are kept apart deliberately.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import List, Optional, Protocol

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

log = logging.getLogger("driftway")

from .accounts import hash_token, new_token
from .db import Base, _now, _uuid


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------

class MeetupSession(Base):
    __tablename__ = "meetup_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Read-only capability. Distinct from any join token.
    public_results_slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    mode: Mapped[str] = mapped_column(String(16), default="explore")  # filtered | explore
    requested_categories: Mapped[str] = mapped_column(Text, default="")  # comma-separated
    status: Mapped[str] = mapped_column(String(16), default="collecting")

    selected_venue_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    region_code: Mapped[str] = mapped_column(String(8), default="GB")

    owner_participant_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    owner_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


class MeetupParticipant(Base):
    __tablename__ = "meetup_participants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    meetup_id: Mapped[str] = mapped_column(String(36), index=True)

    # Hashed like every other capability: a leaked table must not yield usable
    # write tokens for someone else's meetup.
    join_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # Nullable on purpose. A parent handed an invitation link participates as a
    # guest; putting a signup wall inside the collaboration funnel would kill
    # the feature.
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)

    # Server-side routing input ONLY. Never serialised to any client.
    start_lat: Mapped[float] = mapped_column(Float)
    start_lng: Mapped[float] = mapped_column(Float)

    # What other participants are allowed to see instead.
    locality_label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    display_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    display_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hide_exact_origin: Mapped[bool] = mapped_column(Boolean, default=True)

    preferred_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tolerance_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class MeetupVenueCandidate(Base):
    __tablename__ = "meetup_venue_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    meetup_id: Mapped[str] = mapped_column(String(36), index=True)

    # Who put this venue in the pool. A parent may withdraw their own
    # suggestion; the organiser may withdraw any. Null means the system
    # suggested it (a later, automated-discovery concern).
    added_by_participant_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )

    provider: Mapped[str] = mapped_column(String(24), default="pool")
    provider_venue_id: Mapped[str] = mapped_column(String(128), default="")
    name: Mapped[str] = mapped_column(String(160), default="")
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    address_label: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)

    canonical_categories: Mapped[str] = mapped_column(Text, default="")
    provider_rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    provider_review_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    opening_status: Mapped[str] = mapped_column(String(12), default="unknown")
    suitability: Mapped[str] = mapped_column(String(12), default="allowed")

    fairness_spread_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    total_travel_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    max_travel_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_breakdown: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    travel_json: Mapped[str] = mapped_column(Text, default="[]")      # JSON

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class MeetupVote(Base):
    __tablename__ = "meetup_votes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    meetup_id: Mapped[str] = mapped_column(String(36), index=True)
    venue_candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    participant_id: Mapped[str] = mapped_column(String(36), index=True)
    value: Mapped[str] = mapped_column(String(16))
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


def _rough_metres(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Flat-earth distance, fine over the ~100 m this is used for."""
    dlat = (lat1 - lat2) * 111_320.0
    dlng = (lng1 - lng2) * 111_320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlng)


# --------------------------------------------------------------------------
# Coarse display coordinates
# --------------------------------------------------------------------------

# ~1.1 km at UK latitudes. Coarse enough that a grid cell covers a
# neighbourhood rather than a street, fine enough that "we meet in the middle"
# still looks sensible on a map.
COARSE_GRID_DEG = 0.01


def coarsen(lat: float, lng: float) -> tuple:
    """Snap a coordinate to a fixed grid cell centre.

    Deterministic rather than randomly jittered, on purpose: random jitter
    re-rolled on each request leaks the true point to anyone who samples it a
    few times and averages. A fixed grid gives the same answer forever, so
    repeated observation reveals nothing new.
    """
    cell_lat = math.floor(lat / COARSE_GRID_DEG) * COARSE_GRID_DEG
    cell_lng = math.floor(lng / COARSE_GRID_DEG) * COARSE_GRID_DEG
    return (
        round(cell_lat + COARSE_GRID_DEG / 2, 5),
        round(cell_lng + COARSE_GRID_DEG / 2, 5),
    )


# --------------------------------------------------------------------------
# Repository seam
# --------------------------------------------------------------------------

class MeetupRepository(Protocol):
    """The storage operations Meet Halfway needs.

    A seam rather than an abstraction for its own sake: it keeps the endpoints
    from reaching into SQLAlchemy directly, so a storage outage is handled in
    one place and a different backing store stays possible without touching
    route handlers.
    """

    def create_meetup(self, **fields) -> MeetupSession: ...
    def get_meetup(self, meetup_id: str) -> Optional[MeetupSession]: ...
    def get_meetup_by_slug(self, slug: str) -> Optional[MeetupSession]: ...
    def add_participant(self, **fields) -> MeetupParticipant: ...
    def participant_by_token(self, raw_token: str) -> Optional[MeetupParticipant]: ...
    def participants(self, meetup_id: str) -> List[MeetupParticipant]: ...
    def candidates(self, meetup_id: str) -> List[MeetupVenueCandidate]: ...
    def add_candidate(self, meetup_id: str, **fields) -> MeetupVenueCandidate:
        row = MeetupVenueCandidate(meetup_id=meetup_id, **fields)
        self._s.add(row)
        self._s.commit()
        self._s.refresh(row)
        return row

    def get_candidate(self, candidate_id: str) -> Optional[MeetupVenueCandidate]:
        return self._s.get(MeetupVenueCandidate, candidate_id)

    def delete_candidate(self, row: MeetupVenueCandidate) -> None:
        # Votes for a withdrawn venue would otherwise linger and be counted
        # against a candidate nobody can see.
        for vote in self._s.execute(
            select(MeetupVote).where(MeetupVote.venue_candidate_id == row.id)
        ).scalars():
            self._s.delete(vote)
        self._s.delete(row)
        self._s.commit()

    def find_near(self, meetup_id: str, lat: float, lng: float,
                  *, metres: float = 120.0) -> Optional[MeetupVenueCandidate]:
        """An existing pooled venue at roughly this spot.

        Both parents suggesting the same place is the normal case, not an
        error, so it is merged rather than duplicated.
        """
        for row in self.candidates(meetup_id):
            if _rough_metres(row.lat, row.lng, lat, lng) <= metres:
                return row
        return None

    def replace_candidates(self, meetup_id: str, rows: List[dict]) -> List[MeetupVenueCandidate]: ...
    def upsert_vote(self, **fields) -> MeetupVote: ...
    def votes(self, meetup_id: str) -> List[MeetupVote]: ...


class SqlMeetupRepository:
    """SQLAlchemy implementation, bound to one request's session."""

    def __init__(self, session: Session):
        self._s = session

    # --- meetups
    def create_meetup(self, **fields) -> MeetupSession:
        row = MeetupSession(public_results_slug=new_token()[:22], **fields)
        self._s.add(row)
        self._s.commit()
        self._s.refresh(row)
        return row

    def get_meetup(self, meetup_id: str) -> Optional[MeetupSession]:
        return self._s.get(MeetupSession, meetup_id)

    def get_meetup_by_slug(self, slug: str) -> Optional[MeetupSession]:
        return self._s.execute(
            select(MeetupSession).where(MeetupSession.public_results_slug == slug)
        ).scalar_one_or_none()

    def touch_meetup(self, row: MeetupSession) -> None:
        row.updated_at = _now()
        self._s.commit()

    # --- participants
    def add_participant(self, **fields) -> tuple:
        raw = new_token()
        row = MeetupParticipant(join_token_hash=hash_token(raw), **fields)
        self._s.add(row)
        self._s.commit()
        self._s.refresh(row)
        return row, raw

    def participant_by_token(self, raw_token: str) -> Optional[MeetupParticipant]:
        if not raw_token:
            return None
        return self._s.execute(
            select(MeetupParticipant).where(
                MeetupParticipant.join_token_hash == hash_token(raw_token)
            )
        ).scalar_one_or_none()

    def participants(self, meetup_id: str) -> List[MeetupParticipant]:
        return list(self._s.execute(
            select(MeetupParticipant)
            .where(MeetupParticipant.meetup_id == meetup_id)
            .order_by(MeetupParticipant.created_at)
        ).scalars())

    def save(self) -> None:
        self._s.commit()

    # --- candidates
    def candidates(self, meetup_id: str) -> List[MeetupVenueCandidate]:
        return list(self._s.execute(
            select(MeetupVenueCandidate)
            .where(MeetupVenueCandidate.meetup_id == meetup_id)
            .order_by(MeetupVenueCandidate.score.desc())
        ).scalars())

    def add_candidate(self, meetup_id: str, **fields) -> MeetupVenueCandidate:
        row = MeetupVenueCandidate(meetup_id=meetup_id, **fields)
        self._s.add(row)
        self._s.commit()
        self._s.refresh(row)
        return row

    def get_candidate(self, candidate_id: str) -> Optional[MeetupVenueCandidate]:
        return self._s.get(MeetupVenueCandidate, candidate_id)

    def delete_candidate(self, row: MeetupVenueCandidate) -> None:
        # Votes for a withdrawn venue would otherwise linger and be counted
        # against a candidate nobody can see.
        for vote in self._s.execute(
            select(MeetupVote).where(MeetupVote.venue_candidate_id == row.id)
        ).scalars():
            self._s.delete(vote)
        self._s.delete(row)
        self._s.commit()

    def find_near(self, meetup_id: str, lat: float, lng: float,
                  *, metres: float = 120.0) -> Optional[MeetupVenueCandidate]:
        """An existing pooled venue at roughly this spot.

        Both parents suggesting the same place is the normal case, not an
        error, so it is merged rather than duplicated.
        """
        for row in self.candidates(meetup_id):
            if _rough_metres(row.lat, row.lng, lat, lng) <= metres:
                return row
        return None

    def replace_candidates(self, meetup_id: str, rows: List[dict]) -> List[MeetupVenueCandidate]:
        for old in self.candidates(meetup_id):
            self._s.delete(old)
        made = [MeetupVenueCandidate(meetup_id=meetup_id, **r) for r in rows]
        self._s.add_all(made)
        self._s.commit()
        return self.candidates(meetup_id)

    # --- votes
    def upsert_vote(self, *, meetup_id: str, venue_candidate_id: str,
                    participant_id: str, value: str,
                    comment: Optional[str] = None) -> MeetupVote:
        existing = self._s.execute(
            select(MeetupVote).where(
                MeetupVote.meetup_id == meetup_id,
                MeetupVote.venue_candidate_id == venue_candidate_id,
                MeetupVote.participant_id == participant_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.value = value
            existing.comment = comment
            existing.updated_at = _now()
            self._s.commit()
            return existing
        row = MeetupVote(
            meetup_id=meetup_id, venue_candidate_id=venue_candidate_id,
            participant_id=participant_id, value=value, comment=comment,
        )
        self._s.add(row)
        self._s.commit()
        self._s.refresh(row)
        return row

    def votes(self, meetup_id: str) -> List[MeetupVote]:
        return list(self._s.execute(
            select(MeetupVote).where(MeetupVote.meetup_id == meetup_id)
        ).scalars())

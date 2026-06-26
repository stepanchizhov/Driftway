"""API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.db import Favourite, Feedback, get_session
from core.generator import generate_routes
from core.models import (
    FavouriteCreate,
    FavouriteOut,
    FeedbackRequest,
    GenerateRequest,
    GenerateResponse,
)
from core.router import get_router

log = logging.getLogger("driftway")

router = APIRouter()


@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    routing = get_router()
    result = await generate_routes(req, routing)
    if not result.routes:
        # Not an error exactly, but the client should know nothing usable came back.
        raise HTTPException(
            status_code=422,
            detail="No drivable loop found for these settings. Try a different "
                   "duration, road profile, or a wider tolerance.",
        )
    return result


@router.post("/feedback")
def feedback(fb: FeedbackRequest, session: Session = Depends(get_session)):
    # Persist to the database (SQLite locally, Postgres on Render).
    row = Feedback(
        owner=fb.owner,
        route_id=fb.route_id,
        predicted_minutes=fb.predicted_minutes,
        actual_minutes=fb.actual_minutes,
        would_use_again=fb.would_use_again,
        baby_slept=fb.baby_slept,
        notes=fb.notes,
    )
    session.add(row)
    session.commit()
    log.info("feedback stored: route=%s would_use_again=%s", fb.route_id, fb.would_use_again)
    return {"ok": True, "id": row.id}


@router.get("/health")
async def health():
    return {"status": "ok", "provider": get_router().name}


def _fav_out(f: Favourite) -> FavouriteOut:
    return FavouriteOut(
        id=f.id,
        label=f.label,
        place_label=f.place_label,
        duration_minutes=f.duration_minutes,
        distance_km=f.distance_km,
        road_profile=f.road_profile,
        character=f.character,
        maps_url=f.maps_url,
        created_at=f.created_at.isoformat(),
    )


@router.post("/favourites", response_model=FavouriteOut)
def create_favourite(fav: FavouriteCreate, session: Session = Depends(get_session)):
    row = Favourite(
        owner=fav.owner,
        label=fav.label,
        place_label=fav.place_label,
        duration_minutes=fav.duration_minutes,
        distance_km=fav.distance_km,
        road_profile=fav.road_profile,
        character=fav.character,
        maps_url=fav.maps_url,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _fav_out(row)


@router.get("/favourites", response_model=list[FavouriteOut])
def list_favourites(owner: str, session: Session = Depends(get_session)):
    rows = (
        session.query(Favourite)
        .filter(Favourite.owner == owner)
        .order_by(Favourite.created_at.desc())
        .all()
    )
    return [_fav_out(f) for f in rows]


@router.delete("/favourites/{fav_id}")
def delete_favourite(
    fav_id: str, owner: str, session: Session = Depends(get_session)
):
    row = (
        session.query(Favourite)
        .filter(Favourite.id == fav_id, Favourite.owner == owner)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Favourite not found.")
    session.delete(row)
    session.commit()
    return {"ok": True}

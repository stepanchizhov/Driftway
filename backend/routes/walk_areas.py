"""
Curated walks beyond the founder's area: the request a parent's app makes,
the endpoints the scheduled job uses, and the founder's review of AI-written
descriptions. The flow and its privacy rules are in core/walking/areas.py.

Three levels of access:
  - anyone: ask for walks in their rough area (a grid square), rate-limited;
  - the job (X-Walks-Job-Token): read the queue, upload walks it built, add
    descriptions as pending;
  - the founder (X-Admin-Token): everything the job can do, plus approve or
    reject descriptions. Nothing written by AI is shown before that.
"""

from __future__ import annotations

import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import admin_token, walking_enabled, walks_job_token
from core.db import get_session, storage_available
from core.ratelimit import RateLimited, SlidingWindowLimiter, _Window, client_address
from core.walking.areas import (
    CuratedWalk, WalkArea, cell_bbox, cell_of, forget_cache, queued, request_area, valid_cell,
)
from core.walking.catalogue import route_from_dict

log = logging.getLogger("driftway")
router = APIRouter()

#: The trail list is looked up once per square and kept this long.
TRAILS_FRESH_DAYS = 30
#: Public Overpass servers, tried in turn; the main one is often busy.
OVERPASS = ["https://lz4.overpass-api.de/api/interpreter",
            "https://overpass-api.de/api/interpreter"]
USER_AGENT = "Driftway/0.8 (+https://github.com/stepanchizhov/Driftway; trails near an area)"
DESCRIPTION_MAX = 600

_area_limit = SlidingWindowLimiter()
AREA_WINDOWS = [_Window(3600, 20)]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ access

def _require_job(x_walks_job_token: Optional[str] = Header(None),
                 x_admin_token: Optional[str] = Header(None)) -> None:
    job, admin = walks_job_token(), admin_token()
    if not job and not admin:
        raise HTTPException(status_code=503, detail="The walk-area job is not configured on this deployment.")
    if job and x_walks_job_token and hmac.compare_digest(x_walks_job_token, job):
        return
    if admin and x_admin_token and hmac.compare_digest(x_admin_token, admin):
        return
    raise HTTPException(status_code=403, detail="Not permitted.")


def _require_founder(x_admin_token: Optional[str] = Header(None)) -> None:
    admin = admin_token()
    if not admin:
        raise HTTPException(status_code=503, detail="Admin access is not configured on this deployment.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, admin):
        raise HTTPException(status_code=403, detail="Not permitted.")


def _require_storage() -> None:
    if not storage_available():
        raise HTTPException(status_code=503, detail="Walks for new areas are unavailable just now.")


# ------------------------------------------------------------- a parent asks

class AreaIn(BaseModel):
    # The position is used to find the grid square and then discarded.
    lat: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(..., ge=-180, le=180, allow_inf_nan=False)


async def _trails_in(cell: str) -> Optional[List[Dict]]:
    """Walking routes mapped in a square, from OpenStreetMap: name, length,
    operator, website. None when no server answered (asked again next time)."""
    s, w, n, e = cell_bbox(cell)
    query = (f'[out:json][timeout:20];relation[type=route]'
             f'[route~"^(hiking|foot|walking)$"]({s},{w},{n},{e});out tags;')
    async with httpx.AsyncClient(timeout=25.0, headers={"User-Agent": USER_AGENT}) as client:
        from core import usage
        for host in OVERPASS:
            try:
                usage.record("overpass")
                r = await client.post(host, data={"data": query})
                if r.status_code == 200 and r.text.lstrip().startswith("{"):
                    break
            except httpx.HTTPError:
                continue
        else:
            return None
    trails = []
    for el in r.json().get("elements", []):
        t = el.get("tags", {})
        if not t.get("name"):
            continue
        km = None
        try:
            km = float((t.get("distance") or "").replace("km", "").strip())
        except ValueError:
            pass
        trails.append({"name": t["name"][:120], "km": km,
                       "operator": (t.get("operator") or "")[:80] or None,
                       "website": t.get("website") if (t.get("website") or "").startswith("https://") else None,
                       "circular": t.get("roundtrip") == "yes"})
    # Shortest first, circular before not: the ones a parent might walk.
    trails.sort(key=lambda x: (x["km"] if x["km"] is not None else 99, not x["circular"], x["name"]))
    return trails[:15]


@router.post("/walks/areas")
async def ask_for_area(body: AreaIn, request: Request, session: Session = Depends(get_session)):
    """Ask for curated walks where you are. Keeps only the grid square, queues
    it for the scheduled job, and lists the trails mapped in it right away."""
    if not walking_enabled():
        raise HTTPException(status_code=404, detail="Not found.")
    _require_storage()
    try:
        _area_limit.check(f"ip:{client_address(request)}", AREA_WINDOWS, scope="caller")
    except RateLimited as limited:
        raise HTTPException(status_code=429, detail="Please wait a moment.",
                            headers={"Retry-After": str(limited.retry_after)})
    cell = cell_of(body.lat, body.lng)
    area = request_area(session, cell)
    fresh = (area.trails_checked_at is not None
             and (_now() - _aware(area.trails_checked_at)).days < TRAILS_FRESH_DAYS)
    if not fresh:
        trails = await _trails_in(cell)
        if trails is not None:
            area.trails_json = json.dumps(trails)
            area.trails_checked_at = _now()
            session.commit()
    trails = json.loads(area.trails_json) if area.trails_json else None
    return {"status": area.status, "trails": trails,
            "attribution": "Trails © OpenStreetMap contributors"}


# ------------------------------------------------------------------ the job

class AreaResult(BaseModel):
    status: Literal["ready", "empty", "failed", "queued"]
    note: str = Field("", max_length=4000)


class WalkUpload(BaseModel):
    cell: str = Field(..., max_length=16)
    source: str = Field("", max_length=64)
    route: Dict


class DescriptionIn(BaseModel):
    text: str = Field(..., min_length=20, max_length=DESCRIPTION_MAX)
    model: str = Field("", max_length=64)


@router.get("/admin/walk-areas", dependencies=[Depends(_require_job), Depends(_require_storage)])
def list_areas(status: str = "queued", limit: int = 5, session: Session = Depends(get_session)):
    rows = (queued(session, min(max(limit, 1), 50)) if status == "queued" else
            list(session.execute(select(WalkArea).order_by(WalkArea.last_requested_at.desc())
                                 .limit(200)).scalars()))
    return [{"cell": a.cell, "bbox": cell_bbox(a.cell), "status": a.status,
             "requests": a.requests, "note": a.note} for a in rows]


@router.post("/admin/walk-areas/{cell}", dependencies=[Depends(_require_job), Depends(_require_storage)])
def area_done(cell: str, body: AreaResult, session: Session = Depends(get_session)):
    area = session.get(WalkArea, cell)
    if area is None:
        raise HTTPException(status_code=404, detail="No such area.")
    area.status, area.note, area.processed_at = body.status, body.note, _now()
    session.commit()
    return {"cell": cell, "status": area.status}


@router.put("/admin/curated-walks/{walk_id}", dependencies=[Depends(_require_job), Depends(_require_storage)])
def upload_walk(walk_id: str, body: WalkUpload, session: Session = Depends(get_session)):
    if not valid_cell(body.cell):
        raise HTTPException(status_code=422, detail="Not a valid area.")
    if body.route.get("id") != walk_id:
        raise HTTPException(status_code=422, detail="The walk's id doesn't match.")
    try:
        route_from_dict(body.route)          # it must load like any curated walk
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Not a walk: {type(e).__name__}")
    walk = session.get(CuratedWalk, walk_id)
    if walk is None:
        walk = CuratedWalk(id=walk_id, cell=body.cell, description_status="none")
        session.add(walk)
    walk.cell, walk.source = body.cell, body.source
    walk.route_json = json.dumps(body.route, ensure_ascii=False)
    walk.built_at = _now()
    session.commit()
    forget_cache()
    return {"id": walk_id, "description_status": walk.description_status}


@router.get("/admin/curated-walks", dependencies=[Depends(_require_job), Depends(_require_storage)])
def list_walks(description_status: Optional[str] = None, limit: int = 50,
               session: Session = Depends(get_session)):
    q = select(CuratedWalk)
    if description_status:
        q = q.where(CuratedWalk.description_status == description_status)
    rows = session.execute(q.order_by(CuratedWalk.built_at.desc()).limit(min(max(limit, 1), 200))).scalars()
    out = []
    for w in rows:
        route = json.loads(w.route_json)
        out.append({"id": w.id, "cell": w.cell, "source": w.source,
                    "name": route.get("name"), "area": route.get("area"),
                    "route": route, "description": w.description,
                    "description_status": w.description_status,
                    "description_model": w.description_model})
    return out


@router.post("/admin/curated-walks/{walk_id}/description",
             dependencies=[Depends(_require_job), Depends(_require_storage)])
def add_description(walk_id: str, body: DescriptionIn, session: Session = Depends(get_session)):
    """A description written by the job: kept as pending. Not shown to
    anyone until the founder approves it."""
    walk = session.get(CuratedWalk, walk_id)
    if walk is None:
        raise HTTPException(status_code=404, detail="No such walk.")
    if "<" in body.text or ">" in body.text:
        raise HTTPException(status_code=422, detail="Plain text only.")
    walk.description = body.text.strip()
    walk.description_status, walk.description_model = "pending", body.model
    walk.description_at, walk.reviewed_at = _now(), None
    session.commit()
    forget_cache()
    return {"id": walk_id, "description_status": "pending"}


# ---------------------------------------------------------------- founder

class Review(BaseModel):
    decision: Literal["approve", "reject"]
    #: The founder may correct the text while approving it.
    text: Optional[str] = Field(None, min_length=20, max_length=DESCRIPTION_MAX)


@router.post("/admin/curated-walks/{walk_id}/description/review",
             dependencies=[Depends(_require_founder), Depends(_require_storage)])
def review_description(walk_id: str, body: Review, session: Session = Depends(get_session)):
    walk = session.get(CuratedWalk, walk_id)
    if walk is None or not walk.description:
        raise HTTPException(status_code=404, detail="Nothing to review.")
    if body.text is not None:
        if "<" in body.text or ">" in body.text:
            raise HTTPException(status_code=422, detail="Plain text only.")
        walk.description = body.text.strip()
    walk.description_status = "approved" if body.decision == "approve" else "rejected"
    walk.reviewed_at = _now()
    session.commit()
    forget_cache()
    return {"id": walk_id, "description_status": walk.description_status}

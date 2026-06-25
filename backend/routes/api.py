"""API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from core.generator import generate_routes
from core.models import FeedbackRequest, GenerateRequest, GenerateResponse
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
async def feedback(fb: FeedbackRequest):
    # Alpha 0: just log it. The frontend also keeps a local copy.
    # LATER: persist to Render Postgres (see core/storage.py stub).
    log.info("feedback: %s", fb.model_dump())
    return {"ok": True}


@router.get("/health")
async def health():
    return {"status": "ok", "provider": get_router().name}

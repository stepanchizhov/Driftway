"""
Driftway backend entrypoint.

Run locally:
    uvicorn main:app --reload --port 8000

On Render, set the start command to:
    uvicorn main:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Load a local .env file (if present) so ROUTING_PROVIDER, TOMTOM_API_KEY, etc.
# are available when running locally. On Render this is a no-op — those values
# are set as real environment variables in the dashboard.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    logging.warning(
        "python-dotenv not installed; .env will be ignored. "
        "Run: pip install -r requirements.txt"
    )

from routes.api import router as api_router
from routes.meetups import router as meetup_router
from routes.walks import router as walks_router
from core.db import init_db

# Importing the meetup tables registers them on the shared metadata so
# init_db() creates them. It must happen before init_db() runs, and it must not
# open a connection - see core/db.py for why import-time connections are
# forbidden here.
import core.accounts  # noqa: F401
import core.meetups   # noqa: F401

logging.basicConfig(level=logging.INFO)

# Create tables on startup (SQLite locally, Postgres on Render).
init_db()

app = FastAPI(title="Driftway API", version="0.1.0")


@app.exception_handler(RequestValidationError)
async def _validation_error(request, exc: RequestValidationError):
    """A 422 that says what was wrong without repeating what was sent.

    FastAPI's default echoes each rejected value back. For a start point or a
    checkpoint that is a precise location in a response body, and for a NaN
    coordinate it crashed: NaN cannot be written as JSON, so a bad request
    became a 500 (found 10 Oct 2026 by the checkpoint tests).
    """
    errors = [{k: v for k, v in e.items() if k in ("type", "loc", "msg")}
              for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


# CORS: allow the PWA origin(s). Comma-separated in the env var.
# Default permits local dev. Tighten before any public beta.
_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    # Every verb the frontend actually issues. DELETE and PUT were missing,
    # which is invisible in local development - vite proxies /api to the
    # backend on the same origin, so no preflight happens at all - and breaks
    # only in production, where the PWA and the API are separate origins.
    # Deleting a favourite, removing a venue, casting a vote and erasing an
    # account were all failing at the OPTIONS preflight rather than at any
    # endpoint, so the server logs showed nothing.
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    # Authorization must be permitted here, or the bearer token turns every
    # authenticated request into a blocked preflight.
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
# Meet Halfway is gated per-endpoint by a server-side feature flag rather than
# by conditional mounting, so a disabled deployment returns a clean 404 instead
# of a differently-shaped app.
app.include_router(meetup_router, prefix="/api")
# Walking: gated per-endpoint by WALKING_ENABLED, like Meet Halfway.
app.include_router(walks_router, prefix="/api")


@app.get("/")
async def root():
    return {"name": "Driftway API", "version": "0.1.0", "docs": "/docs"}

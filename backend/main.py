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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.api import router as api_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Driftway API", version="0.1.0")

# CORS: allow the PWA origin(s). Comma-separated in the env var.
# Default permits local dev. Tighten before any public beta.
_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {"name": "Driftway API", "version": "0.1.0", "docs": "/docs"}

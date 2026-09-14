"""
Storage layer for Driftway.

One switch drives everything: the DATABASE_URL environment variable.
  - unset            -> local SQLite file (driftway.db). No setup, no cloud.
  - postgres URL     -> Render Postgres (or any Postgres).

This mirrors the routing adapter's mock/real split: you build and verify
locally on SQLite, then point DATABASE_URL at Postgres and nothing else
changes. Tables are created on startup with create_all(); a proper migration
tool (Alembic) is a LATER concern, fine to skip while the schema is young.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

log = logging.getLogger("driftway")

from sqlalchemy import Boolean, DateTime, Float, String, Text, create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    sessionmaker,
)


def _resolve_url() -> str:
    """Pick the database URL and normalise the driver.

    Render hands out 'postgresql://...' (sometimes the legacy 'postgres://').
    SQLAlchemy + psycopg3 wants the '+psycopg' suffix, so we add it.
    """
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return "sqlite:///./driftway.db"
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


DATABASE_URL = _resolve_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")

# SQLite needs check_same_thread off (FastAPI uses a threadpool for sync
# endpoints). pool_pre_ping quietly reconnects dropped Postgres connections,
# which matters on Render where idle connections get closed.
_connect_args = {"check_same_thread": False} if IS_SQLITE else {}

# create_engine does not connect - it only builds the engine and imports the
# driver - but it still raises if the URL is malformed or the driver is
# missing, and this runs at import time. Falling back to SQLite keeps the API
# importable so routing and search survive a storage misconfiguration.
try:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args=_connect_args,
        future=True,
    )
except Exception as e:  # noqa: BLE001 - bad URL, missing driver, anything
    log.error(
        "could not build a database engine for the configured DATABASE_URL "
        "(%s: %s); falling back to a local SQLite file",
        type(e).__name__,
        e,
    )
    DATABASE_URL = "sqlite:///./driftway.db"
    IS_SQLITE = True
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
        future=True,
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------- ORM models

class SavedPlace(Base):
    """A place the user can drive back to. v0.2 surfaces only one ('Home') in
    the UI, but the table supports many with one default — multi-location is a
    later UI unlock, no migration needed."""
    __tablename__ = "saved_places"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner: Mapped[str] = mapped_column(String(64), index=True)  # anonymous local id
    label: Mapped[str] = mapped_column(String(80), default="Home")
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Feedback(Base):
    """Post-drive feedback. The core learning signal: predicted vs actual, and
    whether the parent would use the route again."""
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    route_id: Mapped[str] = mapped_column(String(36))
    predicted_minutes: Mapped[float] = mapped_column(Float)
    actual_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    would_use_again: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    baby_slept: Mapped[str | None] = mapped_column(String(16), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Favourite(Base):
    """A drive the user saved to repeat. Stores enough to reopen the same
    shape (waypoints / maps URL) — Google recomputes live traffic on open, so
    it's the route that's saved, not a stale ETA. The duration/distance/profile
    are display labels from when it was saved."""
    __tablename__ = "favourites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(80), default="")
    place_label: Mapped[str] = mapped_column(String(80), default="Home")
    duration_minutes: Mapped[int] = mapped_column()
    distance_km: Mapped[float] = mapped_column(Float, default=0.0)
    road_profile: Mapped[str] = mapped_column(String(16), default="mixed")
    character: Mapped[str] = mapped_column(String(120), default="")
    maps_url: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ---------------------------------------------------------------- lifecycle

# Whether storage answered at startup. Favourites and feedback need it;
# routing and search do not.
_storage_ready = False


def storage_available() -> bool:
    return _storage_ready


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup.

    Never raises. A database that is unreachable - expired free instance,
    wrong region, DNS not resolving - must not take the whole API down with
    it. The project bible is explicit that loops, detours and the drive home
    work with zero stored travel data; only the convenience features need
    storage. Crashing the process on a storage fault would break the core
    promise to protect a feature nobody is using at that moment.
    """
    global _storage_ready
    try:
        Base.metadata.create_all(engine)
        _storage_ready = True
        # create_all() adds missing tables but never missing columns, so an
        # existing deployment needs the migration steps too. Imported here
        # rather than at module scope to avoid a circular import: migrations
        # needs Base and engine from this module.
        from .migrations import run_migrations
        run_migrations()
    except Exception as e:  # noqa: BLE001 - any driver/network fault counts
        _storage_ready = False
        log.error(
            "storage unavailable (%s: %s). Routing and search will work; "
            "favourites and feedback are disabled until the database is "
            "reachable. Check DATABASE_URL and that the database still exists "
            "- Render free Postgres instances expire.",
            type(e).__name__,
            e,
        )


def get_session():
    """FastAPI dependency: yields a session and always closes it."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

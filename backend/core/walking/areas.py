"""
Curated walks beyond the founder's area (founder decision, 11 Oct 2026).

Curated walks used to exist only where a developer had built them. Now:

1. **Right away, for anyone, no AI.** Opening Walk where no curated walk is
   near, the app sends a rough area: the server rounds the position to a
   grid square (AREA_DEG, about 7 to 11 km a side in Britain) and keeps only
   that square, never the position. The square is queued, and the trails
   mapped in it are listed at once ("not checked yet"), looked up from
   OpenStreetMap by the server the first time and kept.
2. **Within hours, developer side, no AI.** A scheduled job (GitHub Actions,
   tools/walk_area_job.py) takes queued squares, builds their mapped trails
   into curated walks with the same importer and faithfulness gate, and
   uploads them. Facts only, so they publish straight away.
3. **Developer side, AI.** The same job writes a short description for each
   new walk from its verified facts, with the developer's key. A user never
   starts it: their request only queues a square. Descriptions wait for the
   founder's approval (founder decision) before anyone sees them.

Walks built this way live in the database, not in the code, so a new area
needs no release. Squares and walks hold nothing about who asked.
"""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from ..db import Base, SessionLocal, storage_available

log = logging.getLogger("driftway")

#: Grid square size, degrees. 0.1 is about 11 km north to south, and 7 km
#: east to west in Britain: coarse enough that a square says where someone
#: is only to the nearest town.
AREA_DEG = 0.1


def _now() -> datetime:
    return datetime.now(timezone.utc)


def cell_of(lat: float, lng: float) -> str:
    """The grid square a point is in, as "south:west" in tenths of a degree.
    Computed on the server from a position that is then discarded."""
    return f"{math.floor(lat / AREA_DEG)}:{math.floor(lng / AREA_DEG)}"


def cell_bbox(cell: str) -> Tuple[float, float, float, float]:
    """(south, west, north, east) of a grid square."""
    i, j = (int(x) for x in cell.split(":"))
    return (round(i * AREA_DEG, 4), round(j * AREA_DEG, 4),
            round((i + 1) * AREA_DEG, 4), round((j + 1) * AREA_DEG, 4))


def valid_cell(cell: str) -> bool:
    try:
        i, j = (int(x) for x in cell.split(":"))
    except (ValueError, AttributeError):
        return False
    return -900 <= i < 900 and -1800 <= j < 1800


class WalkArea(Base):
    """A grid square someone asked for walks in. No user, no position."""
    __tablename__ = "walk_areas"

    cell: Mapped[str] = mapped_column(String(16), primary_key=True)
    #: queued -> ready (walks built) | empty (no trail passed) | failed
    status: Mapped[str] = mapped_column(String(16), default="queued")
    requests: Mapped[int] = mapped_column(Integer, default=0)
    first_requested_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_requested_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    #: What the job said: how many built, held and why. Shown to nobody but
    #: the founder.
    note: Mapped[str] = mapped_column(Text, default="")
    #: The mapped trails listed right away: [{name, km, operator, website}].
    trails_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trails_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class CuratedWalk(Base):
    """A curated walk built by the job, in the same JSON shape as the files
    in data/walks/, plus an optional description awaiting approval."""
    __tablename__ = "curated_walks"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    cell: Mapped[str] = mapped_column(String(16), index=True)
    #: Where it came from, e.g. "osm_relation:19887944".
    source: Mapped[str] = mapped_column(String(64), default="")
    route_json: Mapped[str] = mapped_column(Text)
    built_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: none | pending | approved | rejected
    description_status: Mapped[str] = mapped_column(String(16), default="none")
    description_model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    description_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ------------------------------------------------------------- the queue

def request_area(session: Session, cell: str) -> WalkArea:
    """Count a request for a square, queuing it the first time. A square that
    came back empty or failed is queued again after a week: trails get mapped."""
    area = session.get(WalkArea, cell)
    now = _now()
    if area is None:
        area = WalkArea(cell=cell, status="queued", requests=0,
                        first_requested_at=now, last_requested_at=now, note="")
        session.add(area)
    area.requests += 1
    area.last_requested_at = now
    if area.status in ("empty", "failed") and area.processed_at is not None:
        age = now - (area.processed_at if area.processed_at.tzinfo else
                     area.processed_at.replace(tzinfo=timezone.utc))
        if age.days >= 7:
            area.status = "queued"
    session.commit()
    return area


def queued(session: Session, limit: int) -> List[WalkArea]:
    return list(session.execute(
        select(WalkArea).where(WalkArea.status == "queued")
        .order_by(WalkArea.requests.desc(), WalkArea.first_requested_at)
        .limit(limit)).scalars())


# -------------------------------------------------- walks for the catalogue

_cache: Dict[str, object] = {"at": 0.0, "routes": []}
CACHE_S = 300


def published_routes(force: bool = False) -> List[Dict]:
    """Every walk the job built, as route dicts the catalogue reads, with an
    approved description attached. Read at most every CACHE_S seconds; an
    unavailable database means none, never an error for a parent."""
    now = time.monotonic()
    if not force and now - float(_cache["at"]) < CACHE_S:
        return list(_cache["routes"])  # type: ignore[arg-type]
    routes: List[Dict] = []
    if storage_available():
        session = SessionLocal()
        try:
            for w in session.execute(select(CuratedWalk)).scalars():
                try:
                    raw = json.loads(w.route_json)
                except ValueError:
                    log.error("curated walk %s: unreadable JSON", w.id)
                    continue
                if w.description_status == "approved" and w.description:
                    raw["description"] = w.description
                routes.append(raw)
        except Exception as e:  # noqa: BLE001
            log.error("curated walks unavailable (%s)", type(e).__name__)
        finally:
            session.close()
    _cache["at"], _cache["routes"] = now, routes
    return list(routes)


def forget_cache() -> None:
    _cache["at"] = 0.0

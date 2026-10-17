"""
Drives recorded for analysis, by maintainers only (founder, 17 Oct 2026:
"a setting for admin user and other maintenance users ... that would collect
usage data for the app to analyze it here, including the planned routes to
compare with Google results").

Who: an account whose verified email is in MAINTAINER_EMAILS (a setting on
the server, set by the founder). The server checks it on every request; a
client asking to record for anyone else is ignored.

What: with "Record my drives" on in Settings, each drive request a
maintainer makes is stored with what Driftway offered: per drive, the
exported waypoints and the Google Maps link, a thinned route, minutes and
distance, the mapped stops, the roadworks and what was checked, the
trade-off note and how the drive was built; and the provider calls the
request used. The start and finish are the maintainer's own places, kept
for the comparison and nothing else.

How long: KEEP_DAYS, then the daily retention run deletes them. They are in
the account's export and go with the account. Nobody but the founder (admin
token) can read them, and analysis copies stay on the founder's computer.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import DateTime, String, Text, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base

KEEP_DAYS = 30
#: Points kept per drive's route: enough to compare with Google's line.
ROUTE_POINTS = 300


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DriveRecord(Base):
    __tablename__ = "drive_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    app_version: Mapped[str] = mapped_column(String(20), default="")
    #: JSON: the request and what was offered.
    payload: Mapped[str] = mapped_column(Text, default="{}")


def maintainer_emails() -> set:
    return {e.strip().lower() for e in (os.getenv("MAINTAINER_EMAILS") or "").split(",") if e.strip()}


def is_maintainer(account) -> bool:
    return bool(account is not None and getattr(account, "email", None)
                and account.email.strip().lower() in maintainer_emails()
                and getattr(account, "status", "active") == "active")


def _thin(points, n: int = ROUTE_POINTS):
    if len(points) <= n:
        return points
    step = len(points) / n
    return [points[int(i * step)] for i in range(n)] + [points[-1]]


def record(session: Session, account, request, response, calls: Dict[str, int]) -> Optional[str]:
    """Store one drive request and its answer for a maintainer; None for
    anyone else."""
    if not is_maintainer(account):
        return None
    from .version import APP_VERSION
    drives = []
    for r in response.routes:
        google = next((n.url for n in r.navigation if n.provider_id == "google_maps"), r.maps_url)
        drives.append({
            "minutes": r.predicted_minutes, "km": r.distance_km,
            "google_maps_url": google, "waypoints": [[a.lat, a.lng] for a in r.waypoints],
            "route": [[p.lat, p.lng] for p in _thin(r.full_geometry or r.geometry)],
            "speed_bumps": r.speed_bumps, "lights_junctions": r.lights_junctions,
            "lights_pedestrian": r.lights_pedestrian, "roadworks": r.roadworks,
            "roadworks_status": r.roadworks_status, "tradeoff": r.tradeoff, "caveat": r.caveat,
        })
    payload = {
        "request": json.loads(request.model_dump_json()),
        "provider": response.provider, "candidates_evaluated": response.candidates_evaluated,
        "drives": drives, "provider_calls": dict(calls),
    }
    row = DriveRecord(user_id=account.id, app_version=APP_VERSION, payload=json.dumps(payload))
    session.add(row)
    session.commit()
    return row.id


def purge(session: Session) -> int:
    n = session.execute(delete(DriveRecord).where(
        DriveRecord.created_at < (_now() - timedelta(days=KEEP_DAYS)).replace(tzinfo=None))).rowcount
    session.commit()
    return n or 0


def export_for(session: Session, user_id: str) -> List[Dict]:
    return [{"id": r.id, "created_at": r.created_at.isoformat(), "app_version": r.app_version,
             **json.loads(r.payload)}
            for r in session.execute(select(DriveRecord).where(DriveRecord.user_id == user_id)
                                     .order_by(DriveRecord.created_at)).scalars()]


def erase_for(session: Session, user_id: str) -> int:
    n = session.execute(delete(DriveRecord).where(DriveRecord.user_id == user_id)).rowcount
    return n or 0


def all_since(session: Session, since: Optional[datetime] = None) -> List[Dict]:
    q = select(DriveRecord).order_by(DriveRecord.created_at)
    if since is not None:
        q = q.where(DriveRecord.created_at >= since.replace(tzinfo=None))
    return [{"id": r.id, "user_id": r.user_id, "created_at": r.created_at.isoformat(),
             "app_version": r.app_version, **json.loads(r.payload)}
            for r in session.execute(q).scalars()]

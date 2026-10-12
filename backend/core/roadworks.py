"""
Roadworks that stop traffic, from the Department for Transport's Street
Manager open data (founder, 12 Oct 2026: a stop-go on a drive may be the
worst thing for a sleeping baby, and no map has them: they are temporary).

Councils and utility companies in England record their works in Street
Manager, including how traffic is controlled. The open data arrives as
notifications pushed to Driftway (routes/roadworks.py), each signed by
Amazon SNS and checked here before anything is stored. Only works that make
traffic stop and wait are kept for drives: temporary signals (two-way and
multi-way), stop/go boards, convoy working, give-and-take and priority
working. A road closure is kept too: the route provider usually knows it,
but the card can say why.

Licence: Open Government Licence v3.0. "Contains public sector information
licensed under the Open Government Licence v3.0." Nothing about any person
is received or stored: works have a location, dates and an organisation.

Coordinates: Street Manager uses the British National Grid, in metres
(`POINT(525000 180000)`, `LINESTRING(...)`). Converted on arrival.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import httpx
from sqlalchemy import DateTime, Float, String, Text, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base
from .osgb import en_to_wgs84

log = logging.getLogger("driftway")

#: Street Manager's production topics (its open data documentation).
TOPICS = {
    "arn:aws:sns:eu-west-2:287813576808:prod-permit-topic",
    "arn:aws:sns:eu-west-2:287813576808:prod-activity-topic",
    "arn:aws:sns:eu-west-2:287813576808:prod-section-58-topic",
}
#: Ways of controlling traffic that make a car stop and wait.
STOPPING = {"two_way_signals", "multi_way_signals", "stop_go_boards", "convoy_workings",
            "give_and_take", "priority_working"}
CLOSURE = {"road_closure"}
#: Works this close to a drive are on it.
NEAR_M = 25.0
#: Works are forgotten this long after they end.
KEEP_DAYS = 7
ATTRIBUTION = ("Roadworks: Street Manager. Contains public sector information "
               "licensed under the Open Government Licence v3.0.")
LABEL = {
    "two_way_signals": "temporary traffic lights",
    "multi_way_signals": "temporary traffic lights",
    "stop_go_boards": "stop/go boards",
    "convoy_workings": "a convoy",
    "give_and_take": "give and take",
    "priority_working": "priority working",
    "road_closure": "road closed",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Roadwork(Base):
    """One piece of work on a street, as last notified."""
    __tablename__ = "roadworks"

    work_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    street: Mapped[str] = mapped_column(String(160), default="")
    town: Mapped[str] = mapped_column(String(80), default="")
    #: The traffic control in use now, else as planned: a Street Manager ref.
    control: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(40), default="")
    starts: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ends: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    #: [[lat, lng], ...] and its box, for finding works near a drive.
    points_json: Mapped[str] = mapped_column(Text, default="[]")
    south: Mapped[float] = mapped_column(Float, index=True)
    north: Mapped[float] = mapped_column(Float)
    west: Mapped[float] = mapped_column(Float, index=True)
    east: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ------------------------------------------------------------ SNS messages

_CERT_HOST = re.compile(r"^sns\.[a-z0-9-]+\.amazonaws\.com$")
_certs: Dict[str, Tuple[float, object]] = {}


def _fetch_cert(url: str):
    from cryptography import x509
    cached = _certs.get(url)
    if cached and time.monotonic() - cached[0] < 86400:
        return cached[1]
    pem = httpx.get(url, timeout=10.0).content
    cert = x509.load_pem_x509_certificate(pem)
    _certs[url] = (time.monotonic(), cert)
    return cert


def _string_to_sign(msg: Dict) -> bytes:
    """Amazon SNS's documented signing format: chosen keys, each followed by
    a newline and its value and a newline, in this order."""
    if msg.get("Type") == "Notification":
        keys = ["Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"]
    else:
        keys = ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"]
    out = ""
    for k in keys:
        if k in msg and msg[k] is not None:
            out += f"{k}\n{msg[k]}\n"
    return out.encode("utf-8")


def verify(msg: Dict, fetch_cert=None) -> bool:
    """True only for a message signed by Amazon SNS for a Street Manager topic."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    if msg.get("TopicArn") not in TOPICS:
        return False
    url = msg.get("SigningCertURL") or ""
    parts = urlparse(url)
    if parts.scheme != "https" or not _CERT_HOST.match(parts.hostname or ""):
        return False
    algo = {"1": hashes.SHA1(), "2": hashes.SHA256()}.get(str(msg.get("SignatureVersion")))
    if algo is None:
        return False
    try:
        cert = (fetch_cert or _fetch_cert)(url)
        cert.public_key().verify(base64.b64decode(msg.get("Signature", "")),
                                 _string_to_sign(msg), padding.PKCS1v15(), algo)
        return True
    except Exception:  # noqa: BLE001 - any failure is "not verified"
        return False


def confirm_subscription(msg: Dict) -> bool:
    """Follow a verified SubscriptionConfirmation's link, which must be
    Amazon's own."""
    parts = urlparse(msg.get("SubscribeURL") or "")
    if parts.scheme != "https" or not _CERT_HOST.match(parts.hostname or ""):
        return False
    r = httpx.get(msg["SubscribeURL"], timeout=10.0)
    log.info("Street Manager subscription confirmed for %s: %s", msg.get("TopicArn"), r.status_code)
    return r.status_code == 200


# --------------------------------------------------------------- permits

_COORDS = re.compile(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")


def parse_location(wkt: str) -> List[Tuple[float, float]]:
    """A POINT or LINESTRING in British National Grid metres (or, if the
    numbers are degrees, longitude and latitude) as [(lat, lng)]."""
    pts = []
    for x, y in _COORDS.findall(wkt or ""):
        x, y = float(x), float(y)
        if abs(x) <= 180 and abs(y) <= 90:            # already degrees
            pts.append((y, x))
        elif 0 <= x <= 700000 and 0 <= y <= 1300000:  # BNG easting, northing
            lat, lng = en_to_wgs84(x, y)
            pts.append((round(lat, 6), round(lng, 6)))
    return pts


def _when(day: Optional[str], clock: Optional[str] = None, end: bool = False) -> Optional[datetime]:
    if not day:
        return None
    try:
        if "T" in day:
            return datetime.fromisoformat(day.replace("Z", "+00:00"))
        d = date.fromisoformat(day[:10])
    except ValueError:
        return None
    if clock:
        try:
            return datetime.fromisoformat(clock.replace("Z", "+00:00"))
        except ValueError:
            pass
    # No time given: the whole day.
    t = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return t + timedelta(days=1) if end else t


def store_permit(session: Session, data: Dict) -> Optional[Roadwork]:
    """Keep a permit's works if they stop or close traffic; forget them if
    they no longer do, or are cancelled. Returns what is kept."""
    ref = data.get("work_reference_number")
    if not ref:
        return None
    control = (data.get("current_traffic_management_type_ref")
               or data.get("traffic_management_type_ref") or "")
    status = data.get("work_status_ref") or ""
    cancelled = (data.get("permit_status") or "").lower() in ("cancelled", "refused", "revoked") \
        or status in ("cancelled", "completed")
    pts = parse_location(data.get("works_location_coordinates") or "")
    row = session.get(Roadwork, ref)
    if cancelled or control not in STOPPING | CLOSURE or not pts:
        if row is not None:
            session.delete(row)
            session.commit()
        return None
    if row is None:
        row = Roadwork(work_ref=ref)
        session.add(row)
    row.street = (data.get("street_name") or "")[:160]
    row.town = (data.get("town") or data.get("area_name") or "")[:80]
    row.control, row.status = control, status
    row.starts = _when(data.get("actual_start_date_time")) or _when(
        data.get("proposed_start_date"), data.get("proposed_start_time"))
    row.ends = _when(data.get("actual_end_date_time")) or _when(
        data.get("proposed_end_date"), data.get("proposed_end_time"), end=True)
    row.points_json = json.dumps(pts)
    row.south, row.north = min(p[0] for p in pts), max(p[0] for p in pts)
    row.west, row.east = min(p[1] for p in pts), max(p[1] for p in pts)
    row.updated_at = _now()
    session.commit()
    return row


def handle_event(session: Session, payload: Dict) -> Optional[Roadwork]:
    """One Street Manager event (the SNS Message, parsed)."""
    if (payload.get("object_type") or "").upper() != "PERMIT":
        return None
    data = payload.get("object_data") or {}
    event = (payload.get("event_type") or "").upper().replace("-", "_")
    if event in ("WORK_STOP",) or "CANCELLED" in event or "REVOKED" in event or "REFUSED" in event:
        data = {**data, "work_status_ref": "completed"}
    return store_permit(session, data)


def purge(session: Session) -> int:
    """Forget works that ended more than KEEP_DAYS ago."""
    cutoff = _now() - timedelta(days=KEEP_DAYS)
    n = session.execute(delete(Roadwork).where(Roadwork.ends.is_not(None), Roadwork.ends < cutoff)).rowcount
    session.commit()
    return n or 0


# ------------------------------------------------------------ on a drive

def _metres(a, b) -> float:
    k = math.cos(math.radians(a[0]))
    return math.hypot((a[0] - b[0]) * 111320.0, (a[1] - b[1]) * 111320.0 * k)


def _seg_dist(p, a, b) -> float:
    k = math.cos(math.radians(p[0]))
    px, py = p[1] * k * 111320.0, p[0] * 111320.0
    ax, ay = a[1] * k * 111320.0, a[0] * 111320.0
    bx, by = b[1] * k * 111320.0, b[0] * 111320.0
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(ax + t * dx - px, ay + t * dy - py)


def works_along(session: Session, geometry: Sequence, at: Optional[datetime] = None) -> List[Roadwork]:
    """Works on the drive that stop or close traffic at time `at` (now)."""
    pts = [(p.lat, p.lng) if hasattr(p, "lat") else (p[0], p[1]) for p in geometry]
    if len(pts) < 2:
        return []
    at = at or _now()
    pad = 0.0005
    s, n = min(p[0] for p in pts) - pad, max(p[0] for p in pts) + pad
    w, e = min(p[1] for p in pts) - pad, max(p[1] for p in pts) + pad
    rows = session.execute(select(Roadwork).where(
        Roadwork.south <= n, Roadwork.north >= s, Roadwork.west <= e, Roadwork.east >= w)).scalars()
    found = []
    naive = at.replace(tzinfo=None)
    for r in rows:
        start = r.starts.replace(tzinfo=None) if r.starts else None
        end = r.ends.replace(tzinfo=None) if r.ends else None
        if (start and start > naive) or (end and end < naive):
            continue
        work_pts = [tuple(x) for x in json.loads(r.points_json)]
        if any(_seg_dist(wp, a, b) <= NEAR_M for wp in work_pts for a, b in zip(pts, pts[1:])):
            found.append(r)
    return found


def describe(rows: List[Roadwork]) -> List[str]:
    """"Victoria Street: temporary traffic lights", one per work, stopping
    first."""
    rows = sorted(rows, key=lambda r: (r.control not in STOPPING, r.street))
    out = []
    for r in rows[:5]:
        street = r.street.title() if r.street.isupper() else r.street
        out.append(f"{street or 'A street on the way'}: {LABEL.get(r.control, 'roadworks')}")
    return out


# ---------------------------------------------- per request, for the generator

from contextlib import contextmanager  # noqa: E402
from contextvars import ContextVar  # noqa: E402

_lookup: ContextVar[Optional[object]] = ContextVar("roadworks_lookup", default=None)


@contextmanager
def lookup_for_request(session: Optional[Session]):
    """While planning one drive, let the generator ask which works are on a
    candidate. Without a database, none are."""
    token = _lookup.set((lambda geometry: works_along(session, geometry)) if session is not None else None)
    try:
        yield
    finally:
        _lookup.reset(token)


def works_for(geometry) -> List[Roadwork]:
    fn = _lookup.get()
    if fn is None:
        return []
    try:
        return fn(geometry)
    except Exception as e:  # noqa: BLE001 - roadworks never break a drive
        log.error("roadworks lookup failed (%s)", type(e).__name__)
        return []


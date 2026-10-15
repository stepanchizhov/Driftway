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
from collections import Counter
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
            "give_and_take", "priority_working",
            # TomTom's "single alternate line traffic" (core/incidents.py).
            "alternating_traffic"}
CLOSURE = {"road_closure"}
#: Works this close to a drive are on it.
NEAR_M = 25.0
#: Works are forgotten this long after they end.
KEEP_DAYS = 7
#: Works on a drive are those under way: Street Manager's work status
#: "in_progress", set by a WORK_START (measured 13 Oct 2026: 76 in 90 minutes
#: across England). Planned or merely applied-for works are not on the road
#: yet, whatever their proposed dates say (a third of messages that evening
#: were PERMIT_SUBMITTED). One still in progress after its proposed end
#: counts this much longer, until its WORK_STOP arrives.
OVERRUN = timedelta(days=1)
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
    "alternating_traffic": "one direction at a time (lights or stop/go)",
    # TomTom roadworks that don't say how traffic is controlled.
    "roadworks": "roadworks, traffic control not known",
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

    @property
    def source(self) -> str:
        """Scotland's register (core/srwr.py, references "srwr:...") or
        Street Manager."""
        return "srwr" if (self.work_ref or "").startswith("srwr:") else "street_manager"


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


# What has actually arrived since the API started, to check the assumptions
# above (field names, control values, grid metres) against real messages.
# In memory only: it starts again after a deploy.
_seen: Dict[str, Counter] = {k: Counter() for k in ("events", "controls", "coordinates", "fields")}
_seen_since = _now()
_example: Dict = {}


def _coordinate_kind(wkt: str) -> str:
    m = _COORDS.search(wkt or "")
    if not m:
        return "none" if not wkt else "unreadable"
    x, y = float(m.group(1)), float(m.group(2))
    if abs(x) <= 180 and abs(y) <= 90:
        return "degrees"
    return "grid metres" if 0 <= x <= 700000 and 0 <= y <= 1300000 else "other numbers"


def _tally(payload: Dict) -> None:
    data = payload.get("object_data") or {}
    _seen["events"][f"{payload.get('object_type')} {payload.get('event_type')}"] += 1
    if not isinstance(data, dict):
        return
    _seen["fields"].update(data.keys())
    for key in ("traffic_management_type_ref", "current_traffic_management_type_ref"):
        if data.get(key):
            _seen["controls"][f"{key}={data[key]}"] += 1
    _seen["coordinates"][_coordinate_kind(data.get("works_location_coordinates") or "")] += 1
    control = data.get("current_traffic_management_type_ref") or data.get("traffic_management_type_ref")
    if control in STOPPING or not _example:
        _example.clear()
        _example.update({k: (v[:160] if isinstance(v, str) else v) for k, v in data.items()
                         if not isinstance(v, (dict, list))})


def summary(session: Session) -> Dict:
    """For the founder: what has arrived, and what is kept for drives."""
    rows = session.execute(select(Roadwork)).scalars().all()
    now = _now().replace(tzinfo=None)
    under_way = [r for r in rows if running(r, now)]
    return {
        "since": _seen_since.isoformat(timespec="seconds"),
        "messages": sum(_seen["events"].values()),
        **{k: dict(c.most_common(40)) for k, c in _seen.items()},
        "kept": {"total": len(rows), "running_now": len(under_way),
                 "by_status": dict(Counter(r.status for r in rows)),
                 "by_control": dict(Counter(r.control for r in rows))},
        "example_stopping_permit": _example,
    }


def handle_event(session: Session, payload: Dict) -> Optional[Roadwork]:
    """One Street Manager event (the SNS Message, parsed)."""
    _tally(payload)
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


def running(r: "Roadwork", at_naive: datetime) -> bool:
    """Under way at this (UTC, naive) time: started, not stopped, and not
    long past its proposed end."""
    if r.status != "in_progress":
        return False
    start = r.starts.replace(tzinfo=None) if r.starts else None
    end = r.ends.replace(tzinfo=None) if r.ends else None
    return not (start and start > at_naive) and not (end and end + OVERRUN < at_naive)


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
        if not running(r, naive):
            continue
        # A line or area must run along the drive for ALONG_M, not just meet
        # it where the drive crosses the street (15 Oct 2026, seen on
        # Edinburgh drives); a single point within NEAR_M is enough.
        if _runs_along(r, pts):
            found.append(r)
    return found


def _on_route(work, pts) -> bool:
    work_pts = [tuple(x) for x in json.loads(work.points_json)]
    return any(_seg_dist(wp, a, b) <= NEAR_M for wp in work_pts for a, b in zip(pts, pts[1:]))


#: A TomTom incident is on a drive when this much of it runs along the drive
#: (checked every ALONG_STEP_M): a drive that only crosses a closed street at
#: a junction meets it at one point, and is not on it (measured 13 Oct 2026:
#: Edinburgh drives listed "road closed" for streets they crossed).
ALONG_M = 30.0
ALONG_STEP_M = 10.0


#: A closure is on the drive only if the drive goes the way it is closed:
#: TomTom closes one direction at a time, and its own routes avoid closed
#: roads, so a "closed" road on a TomTom drive is the other carriageway.
SAME_WAY_DEG = 60.0
#: TomTom reports each direction of the same works apart: the same road and
#: kind this close count once.
SAME_WORK_M = 300.0


def _bearing(a, b) -> float:
    k = math.cos(math.radians(a[0]))
    return math.degrees(math.atan2((b[1] - a[1]) * k, b[0] - a[0])) % 360


def _samples(work) -> List[Tuple[Tuple[float, float], float]]:
    """(point, bearing of its stretch) every ALONG_STEP_M along the work."""
    line = [tuple(x) for x in json.loads(work.points_json)]
    out = []
    for a, b in zip(line, line[1:]):
        n = max(1, int(_metres(a, b) / ALONG_STEP_M))
        heading = _bearing(a, b)
        out += [((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n), heading)
                for k in range(n)]
    if line:
        out.append((line[-1], out[-1][1] if out else 0.0))
    return out


def _bounds(points, pad_m: float = 0.0) -> Tuple[float, float, float, float]:
    """(south, west, north, east) round (lat, lng) points, padded."""
    lat_pad = pad_m / 111320.0
    lng_pad = pad_m / (111320.0 * math.cos(math.radians(points[0][0])))
    return (min(p[0] for p in points) - lat_pad, min(p[1] for p in points) - lng_pad,
            max(p[0] for p in points) + lat_pad, max(p[1] for p in points) + lng_pad)


def _meets(a, b) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _runs_along(work, pts, same_way: bool = False) -> bool:
    if len(json.loads(work.points_json)) < 2:
        return not same_way and _on_route(work, pts)
    samples = _samples(work)
    # Only the drive's stretches near the work are compared (15 Oct 2026:
    # comparing every stretch with every TomTom incident in the area took a
    # 60-minute drive's ranking to 140 s).
    box = _bounds([p for p, _h in samples], NEAR_M + 5)
    segs = [(a, b) for a, b in zip(pts, pts[1:]) if _meets(box, _bounds([a, b]))]
    if not segs:
        return False
    near = 0
    for p, heading in samples:
        for a, b in segs:
            if _seg_dist(p, a, b) <= NEAR_M:
                turn = abs((_bearing(a, b) - heading + 180) % 360 - 180)
                if not same_way or turn <= SAME_WAY_DEG:
                    near += 1
                break
    return near * ALONG_STEP_M >= min(ALONG_M, ALONG_STEP_M * len(samples))


def sources(rows) -> List[str]:
    """Which sources the works came from, for the card's attribution."""
    return sorted({getattr(r, "source", "street_manager") for r in rows})


def on_card(rows: list, live_traffic: bool = True) -> list:
    """The works a drive's card lists. A register's closure (Street Manager,
    Scotland's register) is left off a drive planned with live traffic: the
    live route goes along it, so it isn't closed there now (partial, timed or
    the other way; seen on Edinburgh and Glasgow drives, 15 Oct 2026), and
    closures don't change the ranking. TomTom's own closure reports are
    current and checked for direction, and stay."""
    return [r for r in rows
            if not (live_traffic and r.control in CLOSURE and getattr(r, "source", "") != "tomtom")]


def describe(rows: List[Roadwork]) -> List[str]:
    """"Victoria Street: temporary traffic lights", once per street and kind
    (works in phases are several records), stopping first."""
    rows = sorted(rows, key=lambda r: (r.control not in STOPPING, r.street))
    out = []
    for r in rows:
        if len(out) >= 5:
            break
        street = r.street.title() if r.street.isupper() else r.street
        label = LABEL.get(r.control, "roadworks")
        if r.control in CLOSURE and getattr(r, "source", "street_manager") != "tomtom":
            # A register's closure may be partial or only at set times; a
            # drive routed with live traffic along it shows the road open
            # now in that direction (15 Oct 2026).
            label = "road closure registered"
        line = f"{street or 'A street on the way'}: {label}"
        if line not in out:
            out.append(line)
    return out


# ---------------------------------------------- per request, for the generator

from contextlib import contextmanager  # noqa: E402
from contextvars import ContextVar  # noqa: E402

class _Lookup:
    """One drive request's roadworks: Street Manager from the database (if
    it is up), and TomTom's incidents for the area (prefetch)."""

    def __init__(self, session: Optional[Session]):
        self.session = session
        self.incidents: list = []
        #: TomTom's incidents: "off" (not asked: no live routing), "ok" or
        #: "failed".
        self.incidents_state = "off"
        self._last: Optional[object] = None

    def street_manager_last(self) -> Optional[datetime]:
        """When the newest Street Manager work was last updated, once per
        request; None with no data yet."""
        if self._last is None:
            try:
                from sqlalchemy import func
                self._last = self.session.execute(
                    select(func.max(Roadwork.updated_at)).where(~Roadwork.work_ref.like("srwr:%"))
                ).scalar() or False
            except Exception as e:  # noqa: BLE001 - optional enrichment
                log.error("roadworks freshness unreadable (%s)", type(e).__name__)
                self._last = False
        return self._last or None

    def scotland_last(self) -> Optional[datetime]:
        """When Scotland's register was last imported (core/srwr.py)."""
        if getattr(self, "_scot", None) is None:
            try:
                from .srwr import last_import
                self._scot = last_import(self.session) or False
            except Exception as e:  # noqa: BLE001 - optional enrichment
                log.error("Scottish roadworks freshness unreadable (%s)", type(e).__name__)
                self._scot = False
        return self._scot or None


#: Street Manager sends England's permit changes every few seconds; this long
#: without any means the feed has stopped reaching Driftway.
STALE_AFTER = timedelta(hours=3)
#: Scotland's register is imported nightly; older than this is out of date.
SCOTLAND_STALE_AFTER = timedelta(hours=36)
#: Rough latitudes: a drive with a point north of SCOTLAND_FROM may be in
#: Scotland, one with a point south of ENGLAND_TO may be in England (or Wales;
#: the line says "England only").
SCOTLAND_FROM, ENGLAND_TO = 54.6, 55.82


def status_line(found: list, geometry=None) -> Optional[str]:
    """What was checked for roadworks on this drive, and what couldn't be,
    so "none found", "not checked", "out of date" and "partly checked" read
    differently (founder and Astra brief, 15 Oct 2026)."""
    lk = _lookup.get()
    if lk is None:
        return None
    checked, gaps = [], []
    lats = [p.lat if hasattr(p, "lat") else p[0] for p in (geometry or [])]
    in_england = not lats or min(lats) < ENGLAND_TO
    in_scotland = bool(lats) and max(lats) > SCOTLAND_FROM
    if lk.session is None:
        gaps.append("the official roadworks registers couldn't be read")
    elif not in_england:
        pass
    else:
        last = lk.street_manager_last()
        if last is None:
            gaps.append("no Street Manager data has arrived yet")
        else:
            age = _now() - (last if last.tzinfo else last.replace(tzinfo=timezone.utc))
            if age > STALE_AFTER:
                gaps.append(f"Street Manager (England) last heard from {int(age.total_seconds() // 3600)} h ago")
            else:
                checked.append("Street Manager (England only)")
    if lk.session is not None and in_scotland:
        last = lk.scotland_last()
        if last is None:
            gaps.append("no data from Scotland's road works register yet")
        elif _now() - last > SCOTLAND_STALE_AFTER:
            gaps.append(f"Scotland's road works register last updated "
                        f"{int((_now() - last).total_seconds() // 3600)} h ago")
        else:
            checked.append("Scotland's road works register (updated nightly)")
    if lk.incidents_state == "ok":
        checked.append("TomTom traffic reports, just now")
    elif lk.incidents_state == "failed":
        gaps.append("TomTom traffic reports couldn't be checked")
    if not checked:
        return ("Roadworks couldn't be checked just now"
                + (f" ({'; '.join(gaps)})" if gaps else "") + ".")
    line = ("No roadworks found on this drive. " if not found else "") + "Checked: " + ", ".join(checked) + "."
    if gaps:
        line += " " + "; ".join(g[0].upper() + g[1:] for g in gaps) + "."
    return line


_lookup: ContextVar[Optional[_Lookup]] = ContextVar("roadworks_lookup", default=None)


@contextmanager
def lookup_for_request(session: Optional[Session]):
    """While planning one drive, let the generator ask which works are on a
    candidate."""
    token = _lookup.set(_Lookup(session))
    try:
        yield
    finally:
        _lookup.reset(token)


async def prefetch(start, finish, minutes: int) -> None:
    """TomTom's roadworks round the drive's area, once per request, while
    the first candidates are routed (core/incidents.py)."""
    from . import incidents
    lk = _lookup.get()
    if lk is None or not incidents.configured():
        return
    # A loop of this length stays within about this far of its ends.
    margin_km = min(30.0, max(8.0, minutes * 0.5))
    dlat = margin_km / 111.32
    dlng = margin_km / (111.32 * math.cos(math.radians(start.lat)))
    got = await incidents.fetch(min(start.lat, finish.lat) - dlat, min(start.lng, finish.lng) - dlng,
                                max(start.lat, finish.lat) + dlat, max(start.lng, finish.lng) + dlng)
    lk.incidents = got or []
    lk.incidents_state = "failed" if got is None else "ok"


def works_for(geometry) -> list:
    lk = _lookup.get()
    if lk is None:
        return []
    try:
        found = works_along(lk.session, geometry) if lk.session is not None else []
        if lk.incidents:
            from .incidents import DUPLICATE_M
            pts = [(p.lat, p.lng) if hasattr(p, "lat") else (p[0], p[1]) for p in geometry]
            known = [tuple(x) for r in found for x in json.loads(r.points_json)]
            drive_box = _bounds(pts, NEAR_M + 5)
            for inc in lk.incidents:
                inc_pts = [tuple(x) for x in json.loads(inc.points_json)]
                if not inc_pts or not _meets(drive_box, _bounds(inc_pts)):
                    continue                    # nowhere near this drive
                if not _runs_along(inc, pts, same_way=inc.control == "road_closure"):
                    continue
                mine = [p for p, _h in _samples(inc)] or [tuple(x) for x in json.loads(inc.points_json)]
                # The same works Street Manager already reports: keep its record.
                if any(_metres(a, b) <= DUPLICATE_M for a in mine for b in known):
                    continue
                twin = any(getattr(o, "source", "") == "tomtom" and o.street == inc.street
                           and o.control == inc.control
                           and any(_metres(a, b) <= SAME_WORK_M
                                   for a in mine for b, _h in _samples(o))
                           for o in found)
                if not twin:
                    found.append(inc)
        return found
    except Exception as e:  # noqa: BLE001 - roadworks never break a drive
        log.error("roadworks lookup failed (%s)", type(e).__name__)
        return []


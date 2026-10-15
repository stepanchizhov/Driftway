"""
Scotland's roadworks, from the Scottish Road Works Register's open data
(docs/ROADWORKS.md; founder, 13 to 15 Oct 2026: "What about Wales, Scotland
and NI?", then the register's own reply pointing to its Disruptions Export).

Each night around 2 am the register publishes a zip of CSVs under the Open
Government Licence v3 (no registration): `CurrentActivities.csv` holds every
work, event and permission overlapping a week ago to six months ahead, with
how traffic is controlled (`TrafficManagement`), its status, its actual
start and its location. Unlike TomTom's reports it says whether there are
portable traffic lights or stop/go boards, as Street Manager does for
England.

The register's own caveat (its manager, 15 Oct 2026; and the specification,
v1.1): it is good at where and when works took place, less so at what is
happening right now, and planned dates are uncertain under Scotland's
noticing rules. So only works "In Progress" or "Commenced" with an actual
start count, the snapshot is replaced whole each night, and cards say it's
the register's, updated nightly.

Kept as rows of the same table as Street Manager's (core/roadworks.py),
their references starting "srwr:". Imported by the daily retention run once
the night's file exists (and on demand by the founder); nothing is sent to
the register but a download request.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterator, Optional

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .roadworks import Roadwork, parse_location

log = logging.getLogger("driftway")

EXPORT_URL = "https://downloads.srwr.scot/export/disruptions-daily/"
USER_AGENT = "Driftway/0.8 (+https://github.com/stepanchizhov/Driftway; roadworks)"
PREFIX = "srwr:"
ATTRIBUTION = ("Roadworks in Scotland: Scottish Road Works Register, updated nightly. Contains public "
               "sector information licensed under the Open Government Licence v3.0.")
#: The register's traffic management, onto the controls Street Manager uses
#: (roadworks.STOPPING and CLOSURE). Lane closures, narrowing, contraflows and
#: works off the carriageway don't stop traffic and aren't kept.
CONTROL = {
    "Portable Traffic Lights (TTLS)": "two_way_signals",
    "Stop/Go Boards Traffic Control": "stop_go_boards",
    "Give and Take Traffic Control": "give_and_take",
    "Priority System Traffic Control": "priority_working",
    "Convoy Working": "convoy_workings",
    "Road Closure": "road_closure",
    # Under way, control not yet recorded: weighed as roadworks of unknown
    # control, like TomTom's.
    "Traffic Management Not Yet Known": "roadworks",
}
UNDER_WAY = {"In Progress", "Commenced"}
#: A refresh is due when the last import is older than this.
REFRESH_AFTER = timedelta(hours=20)
#: Geometry this long is thinned: a polygon of a whole estate's works can have
#: thousands of vertices.
MAX_POINTS = 200


def _when(raw: str) -> Optional[datetime]:
    raw = (raw or "").strip()
    if not raw or raw.upper() == "NULL":
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def current_rows(zip_bytes: bytes) -> Iterator[Dict[str, str]]:
    """The rows of CurrentActivities.csv, streamed from the zip."""
    csv.field_size_limit(10 ** 9)            # GeometryFull can be very long
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        with z.open("CurrentActivities.csv") as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""))


def to_work(row: Dict[str, str], now: datetime) -> Optional[Roadwork]:
    """A kept work, or None: not under way, not stopping or closing traffic,
    or with nowhere to put it."""
    control = CONTROL.get((row.get("TrafficManagement") or "").strip())
    started = _when(row.get("ActualStartDateTimeUTC", ""))
    if (control is None or (row.get("ActivityStatus") or "").strip() not in UNDER_WAY
            or started is None or started > now):
        return None
    pts = parse_location(row.get("GeometryFull") or "")
    if not pts:
        try:
            pts = [(round(float(row["Latitude"]), 6), round(float(row["Longitude"]), 6))]
        except (KeyError, ValueError):
            return None
    if len(pts) > MAX_POINTS:
        step = len(pts) / MAX_POINTS
        pts = [pts[int(i * step)] for i in range(MAX_POINTS)]
    ref = f"{PREFIX}{row.get('ActivityReference', '').strip()}-{row.get('PhaseNumber', '').strip()}"
    ends = _when(row.get("LatestPossibleEndDateTimeUTC", "")) or _when(row.get("EndDateTimeUTC", ""))
    street = (row.get("Street") or row.get("Location") or "").strip()
    return Roadwork(
        work_ref=ref[:64], street=street[:160], town=(row.get("Town") or "").strip()[:80],
        control=control, status="in_progress",
        starts=started.replace(tzinfo=None), ends=ends.replace(tzinfo=None) if ends else None,
        points_json=json.dumps([list(p) for p in pts]),
        south=min(p[0] for p in pts), north=max(p[0] for p in pts),
        west=min(p[1] for p in pts), east=max(p[1] for p in pts),
        updated_at=now.replace(tzinfo=None))


def import_snapshot(session: Session, zip_bytes: bytes, now: Optional[datetime] = None) -> Dict:
    """Replace Scotland's works with tonight's snapshot. Counts only."""
    now = now or datetime.now(timezone.utc)
    kept, seen, by_control = {}, 0, {}
    for row in current_rows(zip_bytes):
        seen += 1
        w = to_work(row, now)
        if w is not None and w.work_ref not in kept:
            kept[w.work_ref] = w
            by_control[w.control] = by_control.get(w.control, 0) + 1
    session.execute(delete(Roadwork).where(Roadwork.work_ref.like(f"{PREFIX}%")))
    session.add_all(kept.values())
    session.commit()
    log.info("Scottish roadworks imported: %d kept of %d", len(kept), seen)
    return {"rows": seen, "kept": len(kept), "by_control": by_control}


def last_import(session: Session) -> Optional[datetime]:
    t = session.execute(select(func.max(Roadwork.updated_at))
                        .where(Roadwork.work_ref.like(f"{PREFIX}%"))).scalar()
    return t.replace(tzinfo=timezone.utc) if t is not None and t.tzinfo is None else t


def due(session: Session, now: Optional[datetime] = None) -> bool:
    last = last_import(session)
    return last is None or (now or datetime.now(timezone.utc)) - last > REFRESH_AFTER


def refresh(session: Session, client: Optional[httpx.Client] = None) -> Dict:
    """Download tonight's export and import it. Raises on failure (the
    callers log it; drives never depend on this)."""
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0), follow_redirects=True,
                                    headers={"User-Agent": USER_AGENT})
    try:
        resp = client.get(EXPORT_URL)
        resp.raise_for_status()
        return import_snapshot(session, resp.content)
    finally:
        if own:
            client.close()

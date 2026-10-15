"""
Scotland's roadworks from the Scottish Road Works Register's nightly
Disruptions Export (core/srwr.py; founder, 15 Oct 2026). A synthetic export
in the register's documented format (specification v1.1); no network.
"""

import csv
import datetime as dt
import io
import json
import os
import sys
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

FIELDS = ["Version", "LocalReference", "ActivityReference", "PhaseNumber", "Category", "LicenceType",
          "TrafficManagement", "TrafficImpact", "ActivityStatus", "StartDateTimeUTC", "EndDateTimeUTC",
          "LatestPossibleEndDateTimeUTC", "ActualStartDateTimeUTC", "Street", "Town", "Latitude", "Longitude",
          "GeometryFull"]
NOW = dt.datetime.now(dt.timezone.utc)
AGO = (NOW - dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
LATER = (NOW + dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
# A street in central Edinburgh, roughly, in British National Grid metres.
LINE = '"LINESTRING (325900 673500, 326000 673550)"'


def row(ref, tm="Portable Traffic Lights (TTLS)", status="In Progress", started=AGO, geom=LINE, street="BANK STREET"):
    return {"Version": "00", "LocalReference": "1", "ActivityReference": ref, "PhaseNumber": "1",
            "Category": "Standard", "LicenceType": "NULL", "TrafficManagement": tm, "TrafficImpact": "High",
            "ActivityStatus": status, "StartDateTimeUTC": AGO, "EndDateTimeUTC": LATER,
            "LatestPossibleEndDateTimeUTC": LATER, "ActualStartDateTimeUTC": started, "Street": street,
            "Town": "EDINBURGH", "Latitude": "55.95", "Longitude": "-3.19", "GeometryFull": geom.strip('"')}


def export(rows):
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=FIELDS, quoting=csv.QUOTE_MINIMAL)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CurrentActivities.csv", out.getvalue())
        z.writestr("CompletedActivities.csv", "Version\n")
    return buf.getvalue()


class _Db(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from core.db import Base
        from core.roadworks import Roadwork
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine, tables=[Roadwork.__table__])
        self.s = Session(self.engine)

    def tearDown(self):
        self.s.close()


class ImportTests(_Db):
    def test_only_works_under_way_that_stop_or_close_traffic_are_kept(self):
        from core import srwr
        out = srwr.import_snapshot(self.s, export([
            row("A"), row("B", tm="Stop/Go Boards Traffic Control"), row("C", tm="Road Closure"),
            row("D", tm="Lane Closure"),                            # doesn't stop traffic
            row("E", status="Planned"),                             # not under way
            row("F", started="NULL"),                               # no actual start
            row("G", started=LATER),                                # starts later
        ]))
        self.assertEqual(out["kept"], 3)
        self.assertEqual(out["by_control"], {"two_way_signals": 1, "stop_go_boards": 1, "road_closure": 1})

    def test_grid_metres_become_edinburgh_and_the_source_is_the_register(self):
        from core import srwr
        from core.roadworks import Roadwork
        srwr.import_snapshot(self.s, export([row("A")]))
        w = self.s.query(Roadwork).one()
        lat, lng = json.loads(w.points_json)[0]
        self.assertAlmostEqual(lat, 55.95, places=1)
        self.assertAlmostEqual(lng, -3.19, places=1)
        self.assertEqual(w.source, "srwr")
        self.assertEqual(w.status, "in_progress")

    def test_each_night_replaces_the_last_and_leaves_england_alone(self):
        from core import srwr
        from core.roadworks import Roadwork
        self.s.add(Roadwork(work_ref="TSR1", control="two_way_signals", points_json="[[51.48, -0.6]]",
                            south=51.48, north=51.48, west=-0.6, east=-0.6))
        self.s.commit()
        srwr.import_snapshot(self.s, export([row("A"), row("B")]))
        srwr.import_snapshot(self.s, export([row("C")]))
        refs = sorted(r.work_ref for r in self.s.query(Roadwork))
        self.assertEqual(refs, ["TSR1", "srwr:C-1"])

    def test_a_refresh_is_due_only_after_a_night(self):
        from core import srwr
        self.assertTrue(srwr.due(self.s))
        srwr.import_snapshot(self.s, export([row("A")]))
        self.assertFalse(srwr.due(self.s))
        self.assertTrue(srwr.due(self.s, NOW + dt.timedelta(hours=21)))


class CardTests(_Db):
    def test_scotland_is_named_with_its_freshness(self):
        from core import roadworks, srwr
        srwr.import_snapshot(self.s, export([row("A")]))
        edinburgh = [(55.95, -3.19), (55.96, -3.19)]
        with roadworks.lookup_for_request(self.s):
            line = roadworks.status_line([], edinburgh)
        self.assertIn("Scotland's road works register (updated nightly)", line)
        self.assertNotIn("Street Manager", line)               # not an English drive

    def test_a_registers_closure_isnt_listed_on_a_live_drive_and_streets_come_once(self):
        from core import roadworks
        from core.roadworks import Roadwork
        closure = Roadwork(work_ref="srwr:X-1", street="Forrest Road", control="road_closure", points_json="[]")
        lights = [Roadwork(work_ref=f"srwr:L-{i}", street="Bank Street", control="two_way_signals",
                           points_json="[]") for i in (1, 2)]
        self.assertEqual(roadworks.on_card([closure, *lights], live_traffic=True), lights)
        self.assertIn(closure, roadworks.on_card([closure, *lights], live_traffic=False))
        self.assertEqual(roadworks.describe(lights), ["Bank Street: temporary traffic lights"])
        self.assertEqual(roadworks.describe([closure]), ["Forrest Road: road closure registered"])


class ScheduleTests(unittest.TestCase):
    def test_the_daily_retention_run_refreshes_scotland_after_answering(self):
        from test_identity_auth0 import _fresh
        client, _ = _fresh(configured=False)
        try:
            calls = []
            with mock.patch.dict(os.environ, {"RETENTION_TRIGGER_TOKEN": "t"}), \
                    mock.patch("core.srwr.refresh", lambda session, client=None: calls.append(1) or {}):
                r = client.post("/api/admin/retention/run", headers={"X-Retention-Token": "t"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(calls, [1])
        finally:
            client.close()

    def test_the_founder_can_import_now(self):
        from test_identity_auth0 import _fresh
        client, _ = _fresh(configured=False)
        try:
            with mock.patch.dict(os.environ, {"ADMIN_API_TOKEN": "founder"}), \
                    mock.patch("core.srwr.refresh", lambda session, client=None: {"kept": 2}):
                self.assertEqual(client.post("/api/admin/roadworks/scotland/refresh").status_code, 403)
                r = client.post("/api/admin/roadworks/scotland/refresh", headers={"X-Admin-Token": "founder"})
            self.assertEqual(r.json(), {"kept": 2})
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()

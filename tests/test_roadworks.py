"""
Roadworks that stop traffic, from Street Manager (core/rw().py; founder,
12 Oct 2026). Synthetic messages only: a test certificate signs them, and no
network is used.
"""

import base64
import datetime as dt
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

import importlib  # noqa: E402


def rw():
    """The roadworks module the running app uses. Imported late on purpose:
    the test app reloads core modules, and an early import here would leave
    the app holding a copy tied to the previous database."""
    return importlib.import_module("core.roadworks")

TOPIC = "arn:aws:sns:eu-west-2:287813576808:prod-permit-topic"
CERT_URL = "https://sns.eu-west-2.amazonaws.com/SimpleNotificationService-test.pem"
# Victoria Street, Windsor, roughly: a public street, in British National
# Grid metres as Street Manager sends it.
VICTORIA_ST = "LINESTRING(496700 176700, 496800 176750)"

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com")])
_cert = (x509.CertificateBuilder().subject_name(_name).issuer_name(_name)
         .public_key(_key.public_key()).serial_number(1)
         .not_valid_before(dt.datetime(2026, 1, 1)).not_valid_after(dt.datetime(2027, 1, 1))
         .sign(_key, hashes.SHA256()))


def signed(msg, version="2"):
    msg = {**msg, "SignatureVersion": version, "SigningCertURL": msg.get("SigningCertURL", CERT_URL)}
    algo = hashes.SHA256() if version == "2" else hashes.SHA1()
    sig = _key.sign(rw()._string_to_sign(msg), padding.PKCS1v15(), algo)
    return {**msg, "Signature": base64.b64encode(sig).decode()}


def notification(data, event="PERMIT_GRANTED"):
    payload = {"event_type": event, "object_type": "PERMIT", "object_data": data}
    return signed({"Type": "Notification", "MessageId": "m1", "TopicArn": TOPIC,
                   "Message": json.dumps(payload), "Timestamp": "2026-10-12T10:00:00Z"})


def permit(**over):
    today = dt.date.today()
    data = {"work_reference_number": "TSR1", "street_name": "VICTORIA STREET", "town": "WINDSOR",
            "works_location_coordinates": VICTORIA_ST,
            "traffic_management_type_ref": "two_way_signals",
            "proposed_start_date": (today - dt.timedelta(days=1)).isoformat(),
            "proposed_end_date": (today + dt.timedelta(days=2)).isoformat(),
            "work_status_ref": "in_progress", "permit_status": "granted"}
    data.update(over)
    return data


class SignatureTests(unittest.TestCase):
    def verify(self, msg):
        return rw().verify(msg, fetch_cert=lambda url: _cert)

    def test_a_signed_street_manager_message_is_accepted(self):
        self.assertTrue(self.verify(notification(permit())))
        self.assertTrue(self.verify(signed({"Type": "Notification", "MessageId": "m", "TopicArn": TOPIC,
                                            "Message": "{}", "Timestamp": "t"}, version="1")))

    def test_a_changed_message_is_refused(self):
        msg = notification(permit())
        msg["Message"] = msg["Message"].replace("two_way_signals", "no_carriageway_incursion")
        self.assertFalse(self.verify(msg))

    def test_another_topic_or_certificate_host_is_refused(self):
        self.assertFalse(self.verify(signed({"Type": "Notification", "TopicArn": "arn:aws:sns:x:1:other",
                                             "Message": "{}", "MessageId": "m", "Timestamp": "t"})))
        self.assertFalse(self.verify(signed({"Type": "Notification", "TopicArn": TOPIC, "Message": "{}",
                                             "MessageId": "m", "Timestamp": "t",
                                             "SigningCertURL": "https://evil.example.com/cert.pem"})))

    def test_only_amazons_own_confirmation_link_is_followed(self):
        self.assertFalse(rw().confirm_subscription({"SubscribeURL": "https://evil.example.com/x"}))


class PermitTests(unittest.TestCase):
    def setUp(self):
        from test_identity_auth0 import _fresh
        self.client, _ = _fresh(configured=False)
        from core.db import SessionLocal
        self.rw = rw()                            # the module the app now uses
        self.s = SessionLocal()

    def tearDown(self):
        self.s.close()
        self.client.close()

    def test_grid_metres_become_a_place_in_windsor(self):
        pts = self.rw.parse_location(VICTORIA_ST)
        self.assertEqual(len(pts), 2)
        self.assertAlmostEqual(pts[0][0], 51.48, places=1)
        self.assertAlmostEqual(pts[0][1], -0.61, places=1)

    def test_works_that_stop_traffic_are_kept_and_others_are_not(self):
        self.assertIsNotNone(self.rw.store_permit(self.s, permit()))
        self.assertIsNone(self.rw.store_permit(self.s, permit(work_reference_number="TSR2",
                          traffic_management_type_ref="no_carriageway_incursion")))
        # Changed later to something that doesn't stop traffic: forgotten.
        self.assertIsNone(self.rw.store_permit(self.s, permit(current_traffic_management_type_ref="lane_closure")))
        self.assertIsNone(self.s.get(self.rw.Roadwork, "TSR1"))

    def test_finished_or_cancelled_works_are_forgotten(self):
        self.rw.store_permit(self.s, permit())
        self.rw.handle_event(self.s, {"object_type": "PERMIT", "event_type": "WORK_STOP",
                                        "object_data": permit()})
        self.assertIsNone(self.s.get(self.rw.Roadwork, "TSR1"))

    def test_a_drive_down_the_street_finds_them_only_while_they_run(self):
        self.rw.store_permit(self.s, permit())
        street = self.rw.parse_location(VICTORIA_ST)
        drive = [(street[0][0] - 0.001, street[0][1]), street[0], street[1], (street[1][0] + 0.001, street[1][1])]
        found = self.rw.works_along(self.s, drive)
        self.assertEqual([w.work_ref for w in found], ["TSR1"])
        self.assertEqual(self.rw.describe(found), ["Victoria Street: temporary traffic lights"])
        later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=5)
        self.assertEqual(self.rw.works_along(self.s, drive, at=later), [])
        elsewhere = [(52.0, 13.0), (52.01, 13.0)]
        self.assertEqual(self.rw.works_along(self.s, elsewhere), [])

    def test_the_endpoint_refuses_unsigned_posts(self):
        r = self.client.post("/api/roadworks/street-manager", content=json.dumps({"Type": "Notification"}),
                             headers={"Content-Type": "text/plain"})
        self.assertEqual(r.status_code, 403)

    def test_a_signed_notification_is_stored(self):
        from unittest import mock
        with mock.patch("core.roadworks._fetch_cert", lambda url: _cert):
            r = self.client.post("/api/roadworks/street-manager", content=json.dumps(notification(permit())),
                                 headers={"Content-Type": "text/plain"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["kept"])

    def test_the_founder_sees_what_arrived(self):
        from unittest import mock
        with mock.patch("core.roadworks._fetch_cert", lambda url: _cert):
            self.client.post("/api/roadworks/street-manager", content=json.dumps(notification(permit())),
                             headers={"Content-Type": "text/plain"})
        with mock.patch.dict(os.environ, {"ADMIN_API_TOKEN": "founder"}):
            self.assertEqual(self.client.get("/api/admin/roadworks/summary").status_code, 403)
            self.assertEqual(self.client.get("/api/admin/roadworks/summary",
                                             headers={"X-Admin-Token": "wrong"}).status_code, 403)
            r = self.client.get("/api/admin/roadworks/summary", headers={"X-Admin-Token": "founder"})
        self.assertEqual(r.status_code, 200, r.text)
        s = r.json()
        self.assertGreaterEqual(s["events"].get("PERMIT PERMIT_GRANTED", 0), 1)
        self.assertGreaterEqual(s["controls"].get("traffic_management_type_ref=two_way_signals", 0), 1)
        self.assertGreaterEqual(s["coordinates"].get("grid metres", 0), 1)
        self.assertIn("works_location_coordinates", s["fields"])
        self.assertEqual(s["kept"]["by_control"], {"two_way_signals": 1})
        self.assertEqual(s["example_stopping_permit"]["street_name"], "VICTORIA STREET")


class RankingTests(unittest.TestCase):
    def test_a_drive_through_temporary_lights_ranks_lower(self):
        from core import scorer
        from core.models import Coord, RoadMix
        from core.router import EvaluatedRoute
        geom = [Coord(lat=52.0, lng=13.0), Coord(lat=52.01, lng=13.0)]
        clear = EvaluatedRoute(anchors=[], minutes=30, distance_km=20, road_mix=RoadMix(), geometry=geom)
        works = EvaluatedRoute(anchors=[], minutes=30, distance_km=20, road_mix=RoadMix(), geometry=geom)
        for r in (clear, works):
            r.bumps_checked = r.lights_checked = True
        clear.works = []
        works.works = [rw().Roadwork(work_ref="x", control="stop_go_boards")]
        self.assertGreater(scorer.score_route(clear, 30, "mixed"), scorer.score_route(works, 30, "mixed"))


if __name__ == "__main__":
    unittest.main()

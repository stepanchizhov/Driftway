"""
Navigation handoff: never silently change the drive.

The failure this guards against is quiet. Hand a shaped nap route to an app
that cannot express waypoints and nothing errors - the parent just gets a
different, shorter drive, and finds out when the child wakes up early. So the
rule under test is not "produce a URL" but "only offer an app that can carry
this route, and say so plainly when one cannot".

Provider facts verified against current documentation on 11 September 2026;
the sources are cited in core/navigation.py.
"""

import os
import sys
import unittest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from backend.core.models import Coord  # noqa: E402
from backend.core.navigation import (  # noqa: E402
    APPLE_MAPS,
    GOOGLE_MAPS,
    WAZE,
    build_options,
    provider_by_id,
)

START = Coord(lat=51.4857, lng=-0.6214)
FINISH = Coord(lat=51.5216, lng=-0.7205)
SHAPING = [Coord(lat=51.50, lng=-0.67), Coord(lat=51.51, lng=-0.70)]


def _by_id(options):
    return {o.provider_id: o for o in options}


class ProviderCapabilityTests(unittest.TestCase):
    def test_only_google_maps_carries_waypoints(self):
        """Verified: Waze deep links define no waypoint parameter, and the
        Apple Maps URL scheme has only saddr/daddr - the Maps app's multi-stop
        feature is not reachable from a link."""
        self.assertTrue(GOOGLE_MAPS.supports_waypoints())
        self.assertFalse(WAZE.supports_waypoints())
        self.assertFalse(APPLE_MAPS.supports_waypoints())

    def test_the_waypoint_cap_matches_the_documented_mobile_limit(self):
        self.assertEqual(GOOGLE_MAPS.max_waypoints, 3)

    def test_an_unknown_preference_falls_back_rather_than_failing(self):
        self.assertEqual(provider_by_id("not_an_app").id, GOOGLE_MAPS.id)
        self.assertEqual(provider_by_id(None).id, GOOGLE_MAPS.id)


class ShapedRouteTests(unittest.TestCase):
    def test_a_destination_only_app_is_offered_but_marked_not_faithful(self):
        options = _by_id(build_options(START, FINISH, SHAPING, is_loop=False))

        self.assertTrue(options["google_maps"].preserves_route)
        self.assertFalse(options["waze"].preserves_route)
        self.assertEqual(options["waze"].dropped_waypoints, 2)

    def test_the_notice_names_both_the_limitation_and_the_way_out(self):
        waze = _by_id(build_options(START, FINISH, SHAPING, is_loop=False))["waze"]
        self.assertIsNotNone(waze.notice)
        self.assertIn("cannot follow this shaped route", waze.notice)
        self.assertIn("Google Maps", waze.notice)

    def test_a_faithful_app_is_offered_first(self):
        options = build_options(START, FINISH, SHAPING, is_loop=False)
        self.assertTrue(options[0].preserves_route)
        self.assertEqual(options[0].provider_id, "google_maps")

    def test_a_preference_never_outranks_keeping_the_route_intact(self):
        """Preferring Waze must not put a route-destroying option first."""
        options = build_options(
            START, FINISH, SHAPING, is_loop=False, preferred_id="waze",
        )
        self.assertEqual(options[0].provider_id, "google_maps")
        self.assertTrue(options[0].preserves_route)

    def test_waypoints_are_never_silently_dropped_from_the_url(self):
        google = _by_id(build_options(START, FINISH, SHAPING, is_loop=False))["google_maps"]
        self.assertIn("waypoints=", google.url)
        self.assertEqual(google.url.count("|"), len(SHAPING) - 1)


class LoopTests(unittest.TestCase):
    def test_destination_only_apps_are_not_offered_for_a_loop(self):
        """A loop ends where it began. Without waypoints that is not a shorter
        drive, it is no drive at all - so offering it would be worse than
        offering nothing."""
        options = _by_id(build_options(START, START, SHAPING, is_loop=True))
        self.assertIn("google_maps", options)
        self.assertNotIn("waze", options)
        self.assertNotIn("apple_maps", options)

    def test_a_loop_keeps_its_shaping_points(self):
        google = _by_id(build_options(START, START, SHAPING, is_loop=True))["google_maps"]
        for point in SHAPING:
            self.assertIn(f"{point.lat:.6f},{point.lng:.6f}", google.url)


class PlainDestinationTests(unittest.TestCase):
    """A Meet Halfway venue has no shaping, so every app is faithful."""

    def test_every_provider_is_offered_and_faithful(self):
        options = build_options(START, FINISH, [], is_loop=False)
        self.assertEqual(len(options), 3)
        self.assertTrue(all(o.preserves_route for o in options))
        self.assertTrue(all(o.notice is None for o in options))

    def test_a_preference_is_honoured_when_nothing_is_at_stake(self):
        options = build_options(START, FINISH, [], is_loop=False, preferred_id="waze")
        self.assertEqual(options[0].provider_id, "waze")

    def test_each_url_matches_its_documented_scheme(self):
        options = _by_id(build_options(START, FINISH, [], is_loop=False))
        self.assertIn("waze.com/ul?ll=", options["waze"].url)
        self.assertIn("navigate=yes", options["waze"].url)
        self.assertIn("maps.apple.com/?saddr=", options["apple_maps"].url)
        self.assertIn("dirflg=d", options["apple_maps"].url)
        self.assertIn("google.com/maps/dir/?api=1", options["google_maps"].url)

    def test_apple_maps_is_marked_ios_only(self):
        options = _by_id(build_options(START, FINISH, [], is_loop=False))
        self.assertEqual(options["apple_maps"].platforms, ["ios"])
        # The others are unrestricted.
        self.assertEqual(options["google_maps"].platforms, [])


class SimulatedRouteTests(unittest.TestCase):
    def test_a_simulated_route_gets_no_handoff_at_all(self):
        """Load-bearing. Simulated geometry is a straight line between invented
        points; the app treats an empty handoff list as 'not drivable'. A
        capability layer that always produced a URL would undo that."""
        self.assertEqual(
            build_options(START, FINISH, SHAPING, is_loop=False, simulated=True),
            [],
        )
        self.assertEqual(
            build_options(START, START, SHAPING, is_loop=True, simulated=True),
            [],
        )


class GenerateResponseTests(unittest.TestCase):
    """The options reach the client alongside the existing maps_url."""

    def test_routes_carry_navigation_options(self):
        import asyncio

        from backend.core.generator import generate_routes
        from backend.core.models import (
            Direction, GenerateRequest, RoadProfile,
        )
        from backend.core.router import MockRouter

        req = GenerateRequest(
            start=START, finish=START, target_minutes=30,
            tolerance_minutes=10, road_profile=RoadProfile.MIXED,
            direction=Direction.SURPRISE,
        )
        res = asyncio.run(generate_routes(req, MockRouter()))
        self.assertTrue(res.routes)
        for route in res.routes:
            # MockRouter is simulated, so there is nothing to navigate.
            self.assertTrue(route.simulated)
            self.assertEqual(route.navigation, [])
            self.assertEqual(route.maps_url, "")


if __name__ == "__main__":
    unittest.main()

"""
Both route modes, end to end, against fake routers.

No network: every router here is a stub, so these run anywhere and prove the
pipeline's decisions rather than TomTom's. Live-provider findings are recorded
separately in the handoff, not asserted here - a test that needs a working API
key and a working road network is a test that fails for the wrong reasons.
"""

import asyncio
import unittest

from backend.core.generator import generate_routes, google_maps_url
from backend.core.geometry import haversine_km
from backend.core.models import (
    Coord,
    Direction,
    GenerateRequest,
    RoadMix,
    RoadProfile,
    RouteMode,
)
from backend.core.router import EvaluatedRoute, MockRouter
from backend.core.search import MockSearch, normalise_query

POOL = Coord(lat=51.4857, lng=-0.6214)     # "swimming pool"
HOME = Coord(lat=51.4720, lng=-0.6280)     # saved Home, elsewhere in town
FAR = Coord(lat=51.5216, lng=-0.7205)      # a genuine drive away

MIX = RoadMix(motorway=0.1, primary=0.4, secondary=0.3, residential=0.2)


def _geometry(start, finish, n=30):
    """A plausible polyline between two points."""
    return [
        Coord(
            lat=start.lat + (finish.lat - start.lat) * i / (n - 1),
            lng=start.lng + (finish.lng - start.lng) * i / (n - 1),
        )
        for i in range(n)
    ]


class ScaledRouter:
    """Duration grows with how far the anchors stray from the direct line.

    With no anchors it returns the direct drive, which is what the generator
    asks for when it needs the baseline.
    """

    name = "test-scaled"

    def __init__(self, direct_minutes=25.0):
        self.direct_minutes = direct_minutes
        self.calls = []

    async def evaluate(self, start, finish, anchors, profile):
        self.calls.append(len(anchors))
        base = haversine_km(start, finish)
        detour = 0.0
        for a in anchors:
            detour += haversine_km(start, a) + haversine_km(a, finish) - base
        total_km = base + detour
        per_km = self.direct_minutes / max(base, 0.01)
        pts = [start, *anchors, finish]
        geometry = []
        for i in range(len(pts) - 1):
            geometry.extend(_geometry(pts[i], pts[i + 1], 12))
        return EvaluatedRoute(
            anchors=anchors,
            minutes=round(total_km * per_km, 1),
            distance_km=round(total_km, 1),
            road_mix=MIX,
            geometry=geometry,
        )


class DeadRouter:
    """A live provider that answers nothing at all."""

    name = "tomtom"

    async def evaluate(self, start, finish, anchors, profile):
        return None


def _req(start, finish, minutes, tol=10, mode=None):
    return GenerateRequest(
        start=start, finish=finish, target_minutes=minutes,
        tolerance_minutes=tol, road_profile=RoadProfile.MIXED,
        direction=Direction.SURPRISE, mode=mode,
    )


# ---------------------------------------------------------------- modes

class RoundTripTests(unittest.TestCase):
    def test_round_trip_finishes_where_it_started_even_with_a_saved_home(self):
        """The regression that sent parents on a one-way drive to Home."""
        req = _req(POOL, POOL, 30, mode=RouteMode.LOOP)
        res = asyncio.run(generate_routes(req, ScaledRouter()))

        self.assertEqual(res.mode, RouteMode.LOOP)
        self.assertIsNone(res.direct_minutes, "a loop has no direct baseline")
        for route in res.routes:
            # HOME is nowhere in this request; assert the geometry proves it.
            self.assertLess(haversine_km(route.geometry[0], POOL) * 1000, 50)
            self.assertLess(haversine_km(route.geometry[-1], POOL) * 1000, 50)
            self.assertGreater(
                haversine_km(route.geometry[-1], HOME) * 1000, 100,
                "a round trip must not end at Home",
            )

    def test_a_destination_a_few_metres_away_is_treated_as_a_loop(self):
        """Coordinates decide the mode, not the client's label."""
        nearly = Coord(lat=POOL.lat + 0.0002, lng=POOL.lng)
        req = _req(POOL, nearly, 30, mode=RouteMode.DESTINATION)
        res = asyncio.run(generate_routes(req, ScaledRouter()))
        self.assertEqual(res.mode, RouteMode.LOOP)


class DestinationTests(unittest.TestCase):
    def test_two_manually_chosen_endpoints_are_both_honoured(self):
        req = _req(POOL, FAR, 60, mode=RouteMode.DESTINATION)
        res = asyncio.run(generate_routes(req, ScaledRouter(direct_minutes=25.0)))

        self.assertEqual(res.mode, RouteMode.DESTINATION)
        self.assertTrue(res.routes)
        for route in res.routes:
            self.assertLess(haversine_km(route.geometry[0], POOL) * 1000, 60)
            self.assertLess(haversine_km(route.geometry[-1], FAR) * 1000, 60)

    def test_current_location_to_home(self):
        """The swimming-pool-to-Home case: Home is an ordinary destination."""
        req = _req(POOL, HOME, 45, mode=RouteMode.DESTINATION)
        res = asyncio.run(generate_routes(req, ScaledRouter(direct_minutes=12.0)))

        self.assertEqual(res.mode, RouteMode.DESTINATION)
        self.assertTrue(res.routes)
        for route in res.routes:
            self.assertLess(haversine_km(route.geometry[-1], HOME) * 1000, 60)

    def test_requested_time_is_the_total_journey_not_added_time(self):
        """60 minutes means a 60-minute drive, not 25 + 60."""
        router = ScaledRouter(direct_minutes=25.0)
        req = _req(POOL, FAR, 60, tol=10, mode=RouteMode.DESTINATION)
        res = asyncio.run(generate_routes(req, router))

        self.assertAlmostEqual(res.direct_minutes, 25.0, delta=0.5)
        self.assertTrue(res.routes)
        best = res.routes[0]
        self.assertLessEqual(
            abs(best.predicted_minutes - 60), 10,
            f"{best.predicted_minutes} min should be near the 60-minute total",
        )
        # extra_minutes is the difference from the direct drive, not the target.
        self.assertAlmostEqual(
            best.extra_minutes, best.predicted_minutes - 25.0, delta=0.6
        )

    def test_the_direct_route_is_measured_before_anything_else(self):
        router = ScaledRouter(direct_minutes=25.0)
        asyncio.run(generate_routes(_req(POOL, FAR, 60), router))
        self.assertEqual(
            router.calls[0], 0,
            "the first routing call must be the no-anchor direct baseline",
        )


class ImpossibleRequestTests(unittest.TestCase):
    def test_a_target_below_the_direct_drive_returns_the_direct_route(self):
        router = ScaledRouter(direct_minutes=25.0)
        req = _req(POOL, FAR, 10, mode=RouteMode.DESTINATION)
        res = asyncio.run(generate_routes(req, router))

        self.assertEqual(len(res.routes), 1)
        route = res.routes[0]
        self.assertTrue(route.is_direct)
        self.assertAlmostEqual(route.predicted_minutes, 25.0, delta=0.5)
        self.assertIsNotNone(res.notice)
        self.assertIn("25", res.notice)
        self.assertIn("not possible", res.notice)
        # It still ends where it should, and it is still navigable.
        self.assertTrue(route.maps_url)

    def test_a_target_equal_to_the_direct_drive_is_not_called_impossible(self):
        """Asking for 25 when the drive takes 25 is not a mistake, and saying
        "not possible" to that would be nonsense."""
        req = _req(POOL, FAR, 25, mode=RouteMode.DESTINATION)
        res = asyncio.run(generate_routes(req, ScaledRouter(direct_minutes=25.0)))

        self.assertTrue(res.routes[0].is_direct)
        self.assertNotIn("not possible", res.notice)
        self.assertIn("nothing to add", res.notice)

    def test_the_direct_route_is_never_dressed_up_as_hitting_the_target(self):
        req = _req(POOL, FAR, 10, mode=RouteMode.DESTINATION)
        res = asyncio.run(generate_routes(req, ScaledRouter(direct_minutes=25.0)))
        self.assertNotEqual(res.routes[0].predicted_minutes, 10)


# ---------------------------------------------------------- result quality

class ResultQualityTests(unittest.TestCase):
    def test_no_suitable_route_says_so_rather_than_returning_nothing_quietly(self):
        req = _req(POOL, FAR, 60, mode=RouteMode.DESTINATION)
        res = asyncio.run(generate_routes(req, DeadRouter()))
        # DeadRouter yields nothing, so the simulator steps in - and says so.
        self.assertTrue(res.simulated)
        self.assertIsNotNone(res.notice)

    def test_results_are_not_padded_to_three_with_poor_routes(self):
        """Only genuinely distinct routes are returned."""
        # Every candidate comes back as the same road at the same length, so
        # dedupe should leave exactly one - and nothing should invent two more
        # to fill the card slots. (Same length but different anchors would be
        # genuinely different drives, and dedupe is right to keep those.)
        same_anchor = Coord(lat=51.49, lng=-0.64)

        class OneShapeRouter(ScaledRouter):
            name = "test-oneshape"

            async def evaluate(self, start, finish, anchors, profile):
                ev = await super().evaluate(start, finish, anchors, profile)
                ev.distance_km = 20.0
                ev.minutes = 30.0
                ev.anchors = [same_anchor]
                return ev

        req = _req(POOL, POOL, 30, mode=RouteMode.LOOP)
        res = asyncio.run(generate_routes(req, OneShapeRouter()))
        self.assertLess(len(res.routes), 3)
        self.assertIsNotNone(res.notice)
        self.assertIn("Only", res.notice)


# ------------------------------------------------------------- simulation

class SimulatedRouteTests(unittest.TestCase):
    def test_simulated_routes_carry_no_navigation_link(self):
        req = _req(POOL, POOL, 30, mode=RouteMode.LOOP)
        res = asyncio.run(generate_routes(req, DeadRouter()))

        self.assertTrue(res.simulated)
        self.assertTrue(res.routes, "a demo still shows what the app would do")
        for route in res.routes:
            self.assertTrue(route.simulated)
            self.assertEqual(
                route.maps_url, "",
                "a simulated route must never be handed to a navigation app",
            )
            self.assertEqual(route.confidence, "low")

    def test_the_notice_names_the_routes_as_simulated(self):
        res = asyncio.run(generate_routes(_req(POOL, POOL, 30), DeadRouter()))
        self.assertIn("simulated", res.notice.lower())

    def test_live_routes_keep_their_navigation_link(self):
        res = asyncio.run(generate_routes(_req(POOL, POOL, 30), ScaledRouter()))
        self.assertFalse(res.simulated)
        for route in res.routes:
            self.assertFalse(route.simulated)
            self.assertTrue(route.maps_url)

    def test_the_plain_mock_provider_is_still_marked_simulated(self):
        """Running with ROUTING_PROVIDER=mock is a demo too, not just the
        fallback path."""
        res = asyncio.run(generate_routes(_req(POOL, POOL, 30), MockRouter()))
        self.assertTrue(res.simulated)
        for route in res.routes:
            self.assertEqual(route.maps_url, "")


# ----------------------------------------------------------------- export

class NavigationExportTests(unittest.TestCase):
    def test_export_keeps_the_endpoints_and_the_waypoint_order(self):
        anchors = [
            Coord(lat=51.50, lng=-0.65),
            Coord(lat=51.51, lng=-0.68),
            Coord(lat=51.52, lng=-0.70),
        ]
        url = google_maps_url(POOL, FAR, anchors)

        self.assertIn(f"origin={POOL.lat:.6f},{POOL.lng:.6f}", url)
        self.assertIn(f"destination={FAR.lat:.6f},{FAR.lng:.6f}", url)
        waypoints = url.split("waypoints=")[1].split("&")[0]
        self.assertEqual(
            waypoints,
            "51.500000,-0.650000|51.510000,-0.680000|51.520000,-0.700000",
            "waypoints must keep the driving order",
        )

    def test_export_never_silently_drops_waypoints_within_the_supported_limit(self):
        anchors = [Coord(lat=51.50 + i / 100, lng=-0.65) for i in range(3)]
        url = google_maps_url(POOL, FAR, anchors)
        self.assertEqual(url.count("|"), 2, "all three waypoints must survive")

    def test_generated_routes_never_exceed_the_three_waypoint_limit(self):
        """Google Maps takes at most three; more would be dropped by the app
        itself, silently changing the route."""
        res = asyncio.run(generate_routes(_req(POOL, POOL, 30), ScaledRouter()))
        for route in res.routes:
            self.assertLessEqual(len(route.waypoints), 3)


# ----------------------------------------------------------------- search

class SearchTests(unittest.TestCase):
    def test_uk_postcodes_normalise_regardless_of_spacing_and_case(self):
        for raw in ("sl41nj", "SL4 1NJ", " sl4  1nj ", "Sl41Nj"):
            self.assertEqual(normalise_query(raw), "SL4 1NJ", f"failed on {raw!r}")

    def test_non_postcode_text_is_passed_through_untouched(self):
        self.assertEqual(normalise_query("  Windsor Leisure Centre "),
                         "Windsor Leisure Centre")

    def test_search_returns_resolved_coordinates(self):
        places = asyncio.run(MockSearch().search("windsor leisure", None, 5))
        self.assertTrue(places)
        self.assertTrue(all(p.coord.lat and p.coord.lng for p in places))

    def test_an_area_result_is_flagged_approximate(self):
        places = asyncio.run(MockSearch().search("datchet", None, 5))
        self.assertTrue(places)
        self.assertTrue(places[0].approximate,
                        "an area centroid must invite refinement")

    def test_no_matches_is_an_empty_list_not_an_error(self):
        places = asyncio.run(MockSearch().search("zzqqxx nowhere", None, 5))
        self.assertEqual(places, [])


if __name__ == "__main__":
    unittest.main()

import asyncio
import unittest

from backend.core.generator import generate_routes, snap_to_route
from backend.core.models import Coord, Direction, GenerateRequest, RoadProfile, RoadMix
from backend.core.geometry import haversine_km, nearest_point_on_path
from backend.core.router import EvaluatedRoute


class AlwaysBadRouter:
    name = "test"

    async def evaluate(self, start, finish, anchors, profile):
        geometry = [
            start,
            Coord(lat=start.lat + 0.001, lng=start.lng + 0.001),
            Coord(lat=start.lat + 0.002, lng=start.lng + 0.002),
            finish,
        ]
        return EvaluatedRoute(
            anchors=anchors,
            minutes=30.0,
            distance_km=4.0,
            road_mix=RoadMix(motorway=0.0, primary=0.0, secondary=0.1, residential=0.9),
            geometry=geometry,
            has_uturn=True,
        )


class GeneratorFallbackTests(unittest.TestCase):
    def test_generate_routes_returns_a_best_effort_route_when_every_candidate_is_invalid(self):
        req = GenerateRequest(
            start=Coord(lat=51.5, lng=-0.1),
            target_minutes=30,
            tolerance_minutes=10,
            road_profile=RoadProfile.MIXED,
            direction=Direction.SURPRISE,
        )

        response = asyncio.run(generate_routes(req, AlwaysBadRouter()))

        self.assertTrue(response.routes, "expected a best-effort route fallback")
        self.assertEqual(response.routes[0].predicted_minutes, 30.0)
        self.assertEqual(response.provider, "test")


class ShortLoopRouter:
    """A router whose drive time scales with loop size, and whose geometry
    always trips the self-overlap rule.

    Stands in for the real-world case that broke the alpha: near a town centre
    every short loop looks like it doubles back on itself, so the quality
    heuristics rejected all of them and the app fell back to whatever long
    route happened to survive.
    """

    name = "test-short"

    async def evaluate(self, start, finish, anchors, profile):
        radius_km = max(haversine_km(start, a) for a in anchors)
        minutes = radius_km * 12.0  # 12 min per km of anchor radius
        # A tight zigzag: many points within 150 m of each other, so
        # _self_overlap_ratio is high and validation rejects it.
        geometry = [start]
        for i in range(20):
            geometry.append(Coord(lat=start.lat + (i % 2) * 0.0002, lng=start.lng))
        geometry.append(finish)
        return EvaluatedRoute(
            anchors=anchors,
            minutes=round(minutes, 1),
            distance_km=round(radius_km * 3.0, 1),
            road_mix=RoadMix(motorway=0.1, primary=0.4, secondary=0.3, residential=0.2),
            geometry=geometry,
        )


class DurationBeatsHeuristicsTests(unittest.TestCase):
    def test_short_target_is_honoured_even_when_every_loop_trips_the_quality_rules(self):
        req = GenerateRequest(
            start=Coord(lat=53.279, lng=-2.897),
            finish=Coord(lat=53.279, lng=-2.897),
            target_minutes=10,
            tolerance_minutes=5,
            road_profile=RoadProfile.MIXED,
            direction=Direction.SURPRISE,
        )

        response = asyncio.run(generate_routes(req, ShortLoopRouter()))

        self.assertEqual(len(response.routes), 3, "expected three loops")
        for route in response.routes:
            self.assertLessEqual(
                abs(route.delta_minutes),
                req.tolerance_minutes,
                f"{route.predicted_minutes} min is outside the requested "
                f"{req.target_minutes} +/- {req.tolerance_minutes}",
            )


class OffRoadAnchorRouter:
    """Returns a route along a straight road, ignoring where the anchors are.

    Mimics the real failure: the anchor is a bearing-and-distance guess that
    can land in a field or across a river, while the road the car drives is
    somewhere else entirely.
    """

    name = "test-offroad"

    async def evaluate(self, start, finish, anchors, profile):
        # A due-east road through the start point.
        geometry = [Coord(lat=start.lat, lng=start.lng + 0.002 * i) for i in range(30)]
        return EvaluatedRoute(
            anchors=anchors,
            minutes=30.0,
            distance_km=20.0,
            road_mix=RoadMix(motorway=0.1, primary=0.4, secondary=0.3, residential=0.2),
            geometry=geometry,
        )


class AnchorSnappingTests(unittest.TestCase):
    def test_waypoints_are_moved_onto_the_road_that_is_actually_driven(self):
        start = Coord(lat=51.5, lng=-0.1)
        # Anchors well north of the east-west road the router will return.
        anchors = [Coord(lat=51.52, lng=-0.09), Coord(lat=51.53, lng=-0.07)]
        geometry = [Coord(lat=start.lat, lng=start.lng + 0.002 * i) for i in range(30)]

        snapped = snap_to_route(anchors, geometry)

        for original, moved in zip(anchors, snapped):
            self.assertGreater(
                haversine_km(original, geometry[0]), 1.0,
                "test setup: the anchor should start well off the road",
            )
            on_road = haversine_km(moved, nearest_point_on_path(moved, geometry))
            self.assertLess(
                on_road * 1000, 1.0,
                f"waypoint still {on_road * 1000:.0f} m from the road",
            )

    def test_returned_waypoints_sit_on_the_route(self):
        req = GenerateRequest(
            start=Coord(lat=51.5, lng=-0.1),
            finish=Coord(lat=51.5, lng=-0.1),
            target_minutes=30,
            tolerance_minutes=10,
            road_profile=RoadProfile.MIXED,
            direction=Direction.SURPRISE,
        )

        response = asyncio.run(generate_routes(req, OffRoadAnchorRouter()))

        self.assertTrue(response.routes)
        for route in response.routes:
            for wp in route.waypoints:
                # Distance to the polyline itself, not to its nearest vertex:
                # a point can sit exactly on the road and still be ~70 m from
                # the closest vertex when the provider samples coarsely.
                on_road = haversine_km(wp, nearest_point_on_path(wp, route.geometry))
                self.assertLess(on_road * 1000, 1.0)


if __name__ == "__main__":
    unittest.main()

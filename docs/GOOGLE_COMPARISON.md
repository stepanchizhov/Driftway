# Simulated drives against Google Maps (design, 12 Oct 2026)

Founder: simulate runs and check them against Google Maps, to learn where
to place checkpoints. Driftway plans a drive, then hands Google Maps the
start, up to three waypoints and the finish; between waypoints Google picks
its own roads. The question: **what does Google do between our waypoints,
and how should we place them so it drives the road we planned?**

## What each run measures

For one planned drive (ours: TomTom geometry, time and the waypoints we
hand over) and Google's route through the same points:

1. **Overlap:** share of our road within 30 m of Google's. The headline.
2. **Where they part:** for each leg between waypoints, overlap per leg, so
   we see which kind of leg goes wrong.
3. **Waypoint behaviour:** does Google reach each waypoint along the road we
   meant, or arrive from another side, turn round (a U-turn or a loop round
   a block), or leave it on a different road?
4. **Time and distance:** Google's traffic-aware time against ours, and
   the total distance, for the same drive.
5. **The waypoint's setting:** road class, one-way or dual carriageway,
   distance to the nearest junction, side of the road. These explain 1 to 3.

## Which runs (about 60, chosen to vary one thing at a time)

| Factor | Values | Why |
|---|---|---|
| Place | town centre (Windsor), suburb grid (Dedworth), village lanes (Holyport, Bray), next to a motorway (Datchet, M4), park roads (Great Park edge) | Junction density, one-way systems, dual carriageways |
| Length | 15, 30, 60, 90 min | Short loops stress turn-arounds; long ones stress waypoint spacing |
| Kind | round trip, go somewhere | The detour planner places waypoints differently |
| Road style | Quieter, Mixed | Quiet roads have more junctions and one-way streets |
| Time | off-peak, rush hour | Whether Google's choices change with traffic |

Not every combination: all five places at 30 min both kinds and both
styles (20 runs), plus Windsor and Holyport across all four lengths (16),
plus 12 at rush hour, plus 12 with deliberately "bad" waypoints (on a dual
carriageway, just before a junction, on a one-way street the wrong way) to
confirm what breaks. About 60 Google requests and 600 TomTom calls.

## Expected outcome

Placement rules, each with its evidence, for example (hypotheses until
measured): put a waypoint well past a junction in the direction of travel,
never on a dual carriageway, never on a one-way street, on the road the
drive is meant to stay on, with at most N km between waypoints. Then a
change to how `generator.snap_to_route` places them, and the same runs again
to show the overlap rose.

## How to get Google's routes: DECISION for the founder

1. **Google Maps Platform Routes API** (recommended). Needs a Google Cloud
   project with billing and an API key, kept as a secret like the others.
   Cost for ~60 requests is at most a few dollars and likely inside the
   monthly free usage. It returns Google's route, time and turn
   instructions for our exact waypoints. Terms to respect: results are not
   kept beyond the study (only our summary numbers are), never shown on a
   non-Google map, and not used to build a substitute for Google's
   routing. Read the current Google Maps Platform terms before agreeing.
2. **Your phone, supervised**: open each run's Google Maps link over USB,
   read the route from the screen. Free, but slow, and Google's consumer
   terms forbid automating the app, so only a handful of runs.

Option 1 gives the 60 runs in an afternoon; option 2 gives perhaps ten.

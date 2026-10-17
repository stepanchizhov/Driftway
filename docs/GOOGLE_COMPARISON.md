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

## The harness (15 Oct 2026)

IMPLEMENTED: `backend/tools/google_compare.py`, tests in
`tests/test_google_compare.py`. Two questions, kept apart:

- **A. API:** how does a Google Routes API calculation through Driftway's
  exported waypoints differ from Driftway's own final drive? The harness.
- **B. Handoff:** what does the Google Maps app or browser actually do with
  the link? Only a phone can say: the checklist below. A result for A is
  never a result for B.

**What Google is given:** exactly what the drive's Google Maps link holds:
start, finish and its waypoints (at most three: Maps URLs allow three on
mobile browsers and nine elsewhere, read 15 Oct 2026), in order. Sent to the
Routes API as **stopovers** (its default; `via: true` would make them
pass-through). Maps URLs don't say which their waypoints are; a stop is the
cautious reading. `TRAFFIC_AWARE`, `DRIVE`, high-quality polyline. Driftway's
internal shaping points are not sent.

**Measured per case:** share of Driftway's drive within 30 m of Google's line
and the reverse; minutes and km for both; mapped bumps, lights and
turn-arounds at the waypoints on both lines (roadworks left out: they change
by the hour). Results keep no key and no Google polyline.

**Cases** (`backend/data/google_compare/cases.json`, prepared 15 Oct 2026
with Driftway as in production, live TomTom, public starts only):

| Case | Built by | Waypoints | Driftway min | Google Maps link (for B) |
|---|---|---|---|---|
| `windsor-central-30-mixed` | plain | 3 | 30.2 | [open](https://www.google.com/maps/dir/?api=1&origin=51.483400,-0.610500&destination=51.483400,-0.610500&waypoints=51.495320,-0.610250|51.491900,-0.587870|51.477950,-0.594408&travelmode=driving) |
| `dedworth-30-mixed` | steered | 3 | 30.6 | [open](https://www.google.com/maps/dir/?api=1&origin=51.481500,-0.644000&destination=51.481500,-0.644000&waypoints=51.483610,-0.623050|51.459090,-0.647220|51.491018,-0.676861&travelmode=driving) |
| `eton-wick-30-quiet` | plain | 2 | 23.6 | [open](https://www.google.com/maps/dir/?api=1&origin=51.493000,-0.647000&destination=51.493000,-0.647000&waypoints=51.499272,-0.639117|51.495360,-0.633400&travelmode=driving) |
| `englefield-green-30-mixed` | plain | 3 | 29.4 | [open](https://www.google.com/maps/dir/?api=1&origin=51.430000,-0.570000&destination=51.430000,-0.570000&waypoints=51.423800,-0.586450|51.438181,-0.592862|51.443040,-0.571210&travelmode=driving) |
| `holyport-45-quiet` | plain | 3 | 44.5 | [open](https://www.google.com/maps/dir/?api=1&origin=51.496000,-0.704000&destination=51.496000,-0.704000&waypoints=51.499680,-0.718359|51.509310,-0.704390|51.500170,-0.689990&travelmode=driving) |
| `windsor-central-30-quiet` | turn_moved | 3 | 30.6 | [open](https://www.google.com/maps/dir/?api=1&origin=51.483400,-0.610500&destination=51.483400,-0.610500&waypoints=51.482252,-0.568842|51.474360,-0.579790|51.461671,-0.583201&travelmode=driving) |
| `great-park-30-mixed` | steered | 3 | 24.9 | [open](https://www.google.com/maps/dir/?api=1&origin=51.460000,-0.623000&destination=51.460000,-0.623000&waypoints=51.436303,-0.597154|51.436960,-0.632550|51.446880,-0.640360&travelmode=driving) |
| `windsor-to-maidenhead-35` | plain | 1 | 34.9 | [open](https://www.google.com/maps/dir/?api=1&origin=51.483400,-0.610500&destination=51.518800,-0.722500&waypoints=51.428452,-0.733120&travelmode=driving) |

**Founder: to run A** (the key is entered by you, never in chat):

1. https://console.cloud.google.com: a project (e.g. "driftway-research"),
   billing linked.
2. APIs & Services, Library: enable **Routes API**.
3. Credentials, Create credentials, API key; edit it: API restrictions,
   Restrict key, **Routes API** only.
4. Optional: Routes API, Quotas: cap requests per day at about 200.
5. Add `GOOGLE_ROUTES_API_KEY=...` to `backend/.env` yourself.
6. Then the developer runs `python -m tools.google_compare run --limit 5`
   (five requests), inspects them, and only then the rest of the eight.
   Expanding toward about 60 cases waits for that look.

**Real drives, recorded (17 Oct 2026).** The founder asked for drives
planned in the app to be kept for comparing with Google. Maintainers only
(`core/drive_records.py`): an account whose email is in `MAINTAINER_EMAILS`
on the server sees "Record my drives for analysis" in Settings, under
Account. With it on, each drive request is stored for 30 days: the request
(start, finish, minutes, road style, what wakes the child), per drive offered
its minutes, km, Google Maps link, waypoints, the route (300 points), mapped
stops, roadworks and what was checked, the trade-off note; and the provider
calls the request used. Anyone else asking to record is ignored by the
server, and their drives stay anonymous: the sign-in token goes with a drive
request only while recording is on.

The founder's copy: `GET /api/admin/drive-records?since=2026-10-17` with the
admin token, saved **outside the repository** (they hold the founder's own
places). Then

    python -m tools.google_compare records $HOME\driftway-records\drives.json --limit 5

compares each request's first drive with Google (question A, one request
each), from where it was planned; results go next to the file. Since
2e66353 the links carry no start (Google starts from the phone, so it offers
Start), which is why the start comes from the request.

**B: phone checklist** (OPEN, nobody has done it yet). For each link above,
on Android (and an iPhone when one is at hand): open it, and note

- whether Google Maps keeps all the waypoints, and in order;
- whether it treats them as stops (arrival announcements, "Waypoint 1");
- its route against the Driftway card's map: same roads? a turn-around
  where Driftway had none?
- its time against Driftway's minutes.

Record the phone, app version and time of day. A drive's real handoff is
only verified once someone has done this.


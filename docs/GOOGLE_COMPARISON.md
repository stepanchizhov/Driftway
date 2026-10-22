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
each), from where it was planned; results go next to the file. Since 0.8.18
a drive planned from the phone's location has links with no start (Google
starts from the phone, so it offers Start; a picked start is still
carried), which is why the start comes from the request.

**Pins (0.8.21, 22 Oct 2026).** Drive links now carry up to three points:
the anchors plus pins where the plain fastest way would leave Driftway's
roads (docs/ROUTE_MODES.md, "Pins"). Measured so far against TomTom's plain
fastest way only. Two field cases, both Google much shorter than Driftway:
a 45-minute Windsor-area loop Google put at 28 minutes (18 Oct, two points),
and a 71-minute Quieter drive west of London Google drove in 52 on the M4 and
M25 (21 Oct, one point). Prepared cases and recorded drives made after
0.8.21 carry the pins, so run A on them to see whether Google follows.

The eight prepared cases were pinned on 22 Oct 2026 (`python -m
tools.google_compare pin`, live TomTom, keeping each case's `anchors`):
three changed (Dedworth, Holyport, Windsor to Maidenhead). `run` asks Google
about both links of a changed case, "pinned" and "anchors", so `--limit 11`
covers every case: 8 links plus the 3 anchor-only ones. The report has a
`link` column.

**First run of A (22 Oct 2026, 11 Google requests).** Overlap is the
share of Driftway's drive within 30 m of Google's line (strict: a parallel
lane or the far side of a dual carriageway counts as off).

| Case | Link | Overlap | Turn-arounds ours/Google | km ours/Google |
|---|---|---|---|---|
| windsor-central-30-mixed | 3 points | 0.57 | 1/1 | 14.3/12.2 |
| dedworth-30-mixed | **pinned** (a point swapped) | **0.81** | 2/2 | 17.8/16.2 |
| dedworth-30-mixed | anchors | 0.50 | 2/2 | 17.8/14.9 |
| eton-wick-30-quiet | 2 points | 0.72 | 1/1 | 7.7/5.1 |
| englefield-green-30-mixed | 3 points | 0.88 | 2/2 | 9.9/9.6 |
| holyport-45-quiet | pinned (a point swapped) | 0.68 | 1/1 | 26.4/22.7 |
| holyport-45-quiet | anchors | **0.73** | 1/1 | 26.4/21.1 |
| windsor-central-30-quiet | 3 points (turn moved) | 0.80 | **0/2** | 13.2/11.7 |
| great-park-30-mixed | 3 points (steered) | 0.51 | **1/3** | 12.2/15.2 |
| windsor-to-maidenhead-35 | **pinned** (1 -> 3 points) | **0.94** | 0/1 | 25.5/25.4 |
| windsor-to-maidenhead-35 | anchors | 0.81 | 0/1 | 25.5/24.8 |

Read so far:

- **Pins:** better in two of three (Dedworth 0.50 -> 0.81, Windsor to
  Maidenhead 0.81 -> 0.94), slightly worse in one (Holyport 0.73 -> 0.68),
  where TomTom's stand-in had predicted better. The stand-in is a guide, not
  Google: worth checking the swap against Google on more drives (recorded
  ones) before trusting it further.
- **Turn-arounds Google adds:** where Driftway moved a turn-back to an easy
  place (windsor-central-30-quiet) Google turns round twice at the link's
  points, and on the steered Great Park loop three times against one. The
  link's points there are where Google has to turn; worth a look.
- **Minutes, timed at the same moment (22 Oct 2026, mid-morning).** Driftway's
  routes re-timed with live TomTom through the same points (the same route,
  89 to 100%), Google asked a minute later:

  | Case | Overlap | km ours/Google | min TomTom/Google |
  |---|---|---|---|
  | englefield-green-30-mixed | 0.88 | 9.8/9.6 | **29.4/20.6** |
  | windsor-central-30-quiet | 0.80 | 13.2/11.7 | 28.8/19.7 |
  | dedworth-30-mixed (pinned) | 0.81 | 17.8/16.2 | 29.4/24.7 |
  | holyport-45-quiet (pinned) | 0.68 | 25.4/22.7 | 42.0/27.9 |
  | windsor-to-maidenhead-35 (pinned) | 0.94 | 25.5/25.4 | **31.8/32.3** |

  On the same roads in and around Windsor, TomTom's time is 20 to 45% longer
  than Google's; on the A-road drive to Maidenhead they agree. Which is right
  only a drive can say: if Google is, a "30-minute" town loop takes about 21.
  The field cases point the same way (a 45-minute loop Google put at 28, 18
  Oct). Next: time a real drive that follows Driftway's route, against both
  estimates.

**B: phone checklist** (OPEN, nobody has done it yet). For each link above,
on Android (and an iPhone when one is at hand): open it, and note

- whether Google Maps keeps all the waypoints, and in order;
- whether it treats them as stops (arrival announcements, "Waypoint 1");
- its route against the Driftway card's map: same roads? a turn-around
  where Driftway had none?
- its time against Driftway's minutes.

Record the phone, app version and time of day. A drive's real handoff is
only verified once someone has done this.


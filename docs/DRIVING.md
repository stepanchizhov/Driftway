# Driving routes: measurements

What has been measured about the drives Driftway generates, and what changed
because of it. Numbers are from live TomTom calls; nothing here has been
driven to check it.

## 10 Oct 2026 — avoiding reused roads, and "thrilling" routes

**Question.** Can TomTom options reduce the two things that wake a baby on a
generated loop: turning around, and driving the same road twice? Does either
make the drive smoother?

**Variants.** All with `traffic=true`, `travelMode=car`, the "mixed" profile.

| | Request |
|---|---|
| A | `routeType=fastest` (what the app sent until now) |
| B | A + `avoid=alreadyUsedRoads` |
| C | `routeType=thrilling`, `windingness=low`, `hilliness=low` |
| D | C + `avoid=alreadyUsedRoads` |

**Starts.** Four public places around Windsor: the town centre, Eton Wick,
Datchet, Old Windsor.

**Measures.**
- *Turn-arounds*: the app's own `turnaround_count` (TomTom's U-turn
  instruction, plus waypoints where the route reverses by 150° or more).
- *Repeated road*: share of the drive within 20 m of road already driven at
  least 400 m earlier.
- *Jolts* and *stops* per 10 km: OpenStreetMap features within 12 m of the
  route, counted once per pass. Jolts are humps, tables, cushions, bumps and
  other calming. Stops are signals, signalled crossings, stop and give-way
  signs, mini-roundabouts and roundabouts. A junction mapped as several
  signal nodes, or a roundabout split into several ways, counts more than
  once, so the stop figures are inflated in absolute terms. They are only
  fair for comparing variants.

### 1. Same waypoints, four ways (256 calls)

For each start, the generator's 8 candidate waypoint sets for 30- and
45-minute loops (64 routes per variant). Each was sent unchanged under each
variant. Times are before the generator's refine step.

| | Turn-arounds (mean) | No turn-around | Repeated road | Loops ≥10% repeated | Time vs A | Jolts/10 km | Stops/10 km |
|---|---|---|---|---|---|---|---|
| A | 2.33 | 1 of 64 | 21% | 44 of 64 | — | 11.2 | 28.0 |
| B | 1.80 | 6 of 64 | 4% | 5 of 64 | +18% | 10.4 | 29.0 |
| C | 2.00 | 0 of 64 | 21% | 47 of 64 | +7% | 10.8 | 33.4 |
| D | 1.67 | 4 of 64 | 6% | 10 of 64 | +19% | 10.7 | 36.6 |

Paired against A on the same waypoints:
- B had fewer turn-arounds on 27 routes and more on 1. It repeated less
  road on 51 and more on none.
- C had fewer turn-arounds on 27 routes and more on 9, with no change in
  repeated road. It had about 5 more signals per 10 km.

### 2. The whole generator, 30-minute loops (174 calls)

Each variant ran through `generate_routes`, so the refine step re-fitted the
time. These are the routes it would show (11 or 12 per variant).

| | Within ±5 min | Within ±10 min | Turn-arounds (mean) | No turn-around | U-turn instructions | Loops ≥10% repeated | Calls per request |
|---|---|---|---|---|---|---|---|
| A | 6 of 11 | 11 of 11 | 2.09 | 0 of 11 | 9 | 6 | 12.6 |
| B | 8 of 11 | 11 of 11 | 1.00 | 5 of 11 | 5 | 0 | 15.7 |
| D | 6 of 12 | 12 of 12 | 1.17 | 3 of 12 | 8 | 0 | 15.3 |

With B, the top route had no turn-around from all four starts. With A, it
had one from all four.

### Decision

- **Adopted: `avoid=alreadyUsedRoads` on every route request**
  (`core/router.py`), alongside `avoid=motorways` for the quiet profile. It
  has the same time accuracy and costs about 3 more TomTom calls per
  request.
- **Not adopted: `routeType=thrilling`.** It does not reduce repeated road,
  routes through more signals, and does no better than B on turn-arounds.

### What it does not fix

- **Turn-arounds remain** on about half of routes. Most come from hard
  waypoints placed on roads where the only way on is back. Fewer, softer
  shaping points could reduce them; TomTom's `supportingPoints` is the
  likely tool.
- **Smoothness is unchanged.** Neither option touches it. Mapped jolts per
  route varied widely between the routes shown for one start: from 6 to 46
  among one start's three routes. Choosing between routes by mapped
  traffic calming could therefore matter more than any provider option.
  That needs OSM traffic-calming data on the server.
  - Windsor-area coverage (bbox 51.44,-0.70,51.52,-0.55): 637 mapped
    calming features, 175 signals, 35 mini-roundabouts.
  - Surface, speed limit and lane tags cover only 14–27% of roads.

### Limits

- One area, one afternoon, the mixed profile only, and loops only. Padded
  destination routes get the same parameter but were not measured.
- 11 or 12 routes per variant in part 2. The direction is clear; the exact
  rates are not.
- OSM shows only what is mapped. A missing hump is not a missing jolt.

The script that produced these numbers is not in the repository. It used
the app's own router and scorer, a variant parameter injected into the
query, and one Overpass download of the area.

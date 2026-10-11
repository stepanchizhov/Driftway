# Calmer drives: what the map data holds about speed bumps

Research only, 11 Oct 2026. No change to drives. Question from the roadmap:
can Driftway steer drives away from speed bumps around Windsor, and on what
evidence?

## Short answer

- **Neither route provider can avoid speed bumps.** TomTom's routing has no
  option for them; openrouteservice has none for driving. (Checked against
  their documentation today; details below.)
- **OpenStreetMap maps a fair number of them around Windsor, unevenly.** 665
  traffic-calming features, mostly humps, cushions and tables, on residential
  and tertiary roads. Some built-up areas have none mapped at all, and most
  were last edited in one burst in 2020, so the data cannot say whether a
  street is calm or simply unmapped.
- **Driftway can use the map data itself**, without any provider support:
  count mapped calming along each of the up to 8 candidate drives it already
  evaluates, and prefer the candidate with fewer. That is a ranking change,
  not a routing change, and fits the existing pipeline.
- **Measured on real drives (20 drives, 160 candidates; below):** the
  candidates for one drive differ a lot, from 1 to 50 mapped bumps. The
  drive Driftway offers today is often already among the calmest, but in
  about a third of drives an equally acceptable candidate has 4 to 29 fewer.
  So counting would change the drive offered, sometimes a lot.
- **Quieter is not bumpier than Mixed, at the level of whole drives.**
  Mapped calming is densest on the roads Quieter prefers (residential and
  tertiary about 1.3 per km, primary 0.07), so we expected it to be. On the
  20 drives it wasn't: 0.77 against 0.70 bumps per km, and Quieter had more
  in 5 of 10 starts and fewer in 4. The earlier HYPOTHESIS is not supported.

## What OpenStreetMap holds (Windsor area)

Area: 51.43 to 51.52 N, 0.72 to 0.55 W (Windsor, Eton, Old Windsor, Datchet,
the edge of Maidenhead). Data as of 2026-10-11T20:51Z, from the public
Overpass API (`lz4.overpass-api.de`; the main server and two mirrors were
too busy that evening, which is itself a finding: see "Using it").

| Traffic calming (`traffic_calming=*`) | Count |
|---|---|
| hump | 213 |
| cushion | 154 |
| table | 149 |
| island | 63 |
| bump | 52 |
| choker | 19 |
| chicane | 13 |
| dip, choked table | 2 |
| **total** (605 points, 60 lines) | **665** |

Islands and chokers narrow the road rather than lift it; for a sleeping
baby the vertical ones (hump, cushion, table, bump) are what matters: 568.

**Where they are**, matched to the road they sit on:

| Road class | Length | Calming points | Per km |
|---|---|---|---|
| residential | 278 km | 365 | 1.31 |
| tertiary | 59 km | 79 | 1.33 |
| secondary | 64 km | 58 | 0.91 |
| unclassified | 43 km | 15 | 0.35 |
| primary | 72 km | 5 | 0.07 |
| not on a mapped public road (service roads, car parks) | | 83 | |

**How complete.** Of 41 built-up 1 km squares (over 3 km of local roads
each), 7 have no calming mapped at all, and the spread is wide: from none to
about 7 per km of local road, median about 1.5. Edits by year: 413 of 665
were last touched in 2020, about 140 in 2024 to 2026. Speed limits tell
little either: a 20 mph limit is mapped on only 5 to 7% of local roads.

Squares with local roads and nothing mapped (approximate centres, a few
street names to recognise them). **For the founder:** do any of these have
humps you know of? A yes means the data is missing there, not that the
roads are calm.

- near Drift Road (51.466, -0.670)
- near Chestnut Drive, Woodland Avenue (51.466, -0.626)
- near Ham Lane, Church Road, Old Windsor (51.466, -0.554)
- near Aysgarth Park, Byland Drive, Holyport Road (51.493 to 51.502, -0.698)
- near Old Mill Lane, Ferry Road, Bray (51.511, -0.684)
- near St Mary's Road, Orchard Way, Datchet (51.511, -0.540)

Other things that slow a drive, also mapped: 640 crossings, 182 sets of
traffic signals, 77 give-way and 5 stop points, 39 mini roundabouts, 27
speed cameras.

## What the providers can do

- **TomTom Calculate Route** (docs.tomtom.com, read 11 Oct 2026): `avoid`
  takes `tollRoads`, `motorways`, `ferries`, `unpavedRoads`, `carpools`,
  `alreadyUsedRoads`, `borderCrossings`, `tunnels`, `carTrains`,
  `lowEmissionZones`. Nothing about speed bumps, traffic calming or road
  furniture. `avoidAreas` takes at most 10 rectangles: far too coarse to
  dodge individual humps, and it would close whole streets. `routeType=
  thrilling` with `windingness=low` exists, but optimises for "interesting
  or challenging roads", not smoothness.
- **openrouteservice** (giscience.github.io, read 11 Oct 2026): for
  `driving-car`, `avoid_features` is `highways`, `tollways`, `ferries`,
  `fords`; profile weightings are not available for driving. `avoid_polygons`
  exists without documented limits, with the same coarseness problem.

DECISION (proposed): don't try to make a provider avoid humps. Count them
on the candidates Driftway already has.

## Options for Driftway

1. **Count and rank** (recommended next slice). For each candidate drive
   (`generator._evaluate_all`, up to 8, each with full geometry), count
   mapped vertical calming within about 12 m of the route; add a penalty to
   `scorer.score_route`; show "about N speed bumps mapped along this drive"
   with the coverage caveat. No new provider calls.
2. **Shape away from clusters.** Feed dense clusters into candidate anchors
   so detours avoid them. More calls, more complexity; only if 1 shows real
   differences between candidates.
3. **Avoid areas.** TomTom's 10 rectangles: rejected, too coarse.

**Using it.** Not live Overpass per drive: three of four public servers
failed that evening, and their fair-use rules don't fit an app. Instead, a
small extract per area built ahead of time (a tool run, like the curated
walks), refreshed monthly: Windsor's whole set is 665 features, a few tens
of kilobytes. Licence: ODbL. Using it to rank drives is a produced work:
"© OpenStreetMap contributors" on the drive card, which the maps already
show. No new outside host is contacted by the app, so the privacy policy
doesn't change.

**Honesty rules for the card.** "Mapped" never becomes "none": an area with
nothing mapped says so. Islands and chokers are not counted as bumps.

## The measurement (11 Oct 2026, evening)

Ten public start points around Windsor (stations, village greens, a leisure
centre, a Great Park gate), a 30-minute loop each, Quieter and Mixed: the
same 8 candidates Driftway's generator builds (`_loop_candidates`,
`_evaluate_all`), from TomTom with live traffic (160 calls), and the drive
it would offer first (`_pick_top_three`, without the refinement step).
Mapped vertical calming (hump, bump, table, cushion, dip) within 12 m of
each candidate, each point counted once, from a wider extract (51.33 to
51.62 N, 0.88 to 0.40 W: 3,437 vertical points). "Calmest acceptable" is
the candidate with fewest bumps among those Driftway already treats as
best: on time (within 10 minutes) and passing validation.

| Start | Profile | Bumps on the 8 candidates | Offered | Calmest acceptable |
|---|---|---|---|---|
| Windsor & Eton Central | Quieter | 1, 4, 8, 14, 19, 29, 34, 50 | 8 | 8 |
| | Mixed | 7, 7, 14, 15, 17, 18, 24, 30 | 7 | 7 |
| Windsor Leisure Centre | Quieter | 19 to 62 | 19 | 19 |
| | Mixed | 8 to 69 | 8 | 8 |
| Dedworth Road | Quieter | 21 to 48 | 21 | 21 |
| | Mixed | 17 to 52 | 19 | 17 |
| Eton Wick | Quieter | 19 to 52 | 27 | none on time |
| | Mixed | 11 to 42 | 18 | 18 |
| Datchet | Quieter | 6 to 35 | 15 | **6** |
| | Mixed | 6 to 35 | 35 | **6** |
| Old Windsor | Quieter | 7 to 46 | 13 | **9** |
| | Mixed | 12 to 23 | 12 | 12 |
| Englefield Green | Quieter | 2 to 15 | 7 | **2** |
| | Mixed | 6 to 40 | 13 | **7** |
| Holyport | Quieter | 0 to 32 | 2 | 0 |
| | Mixed | 0 to 24 | 2 | 2 |
| Bray | Quieter | 7 to 45 | 7 | 7 |
| | Mixed | 0 to 21 | 8 | **0** |
| Great Park, Ranger's Gate | Quieter | 1 to 23 | 2 | 1 |
| | Mixed | 2 to 27 | 6 | 2 |

- Offered drives: median 10 to 10.5 mapped bumps, about 0.7 to 0.8 per km.
- Counting would offer a calmer, equally acceptable drive in 9 of the 19
  drives with an on-time candidate; by 4 or more bumps in 6 (Datchet both,
  Old Windsor and Englefield Green Quieter, Englefield Green and Bray
  Mixed); by 29 at most.
- The calmest acceptable candidate can be worse on what Driftway ranks by
  today (road mix, smoothness, closeness to the time), so the right change is
  a penalty in the score, not "fewest bumps wins".
- All counts are lower bounds: unmapped calming isn't counted (the founder
  confirmed Drift Road, Holyport Road and Woodland Avenue have none, which
  matches the data; the other empty areas are unknown).

DECISION (proposed): build option 1, count and rank, as the next driving
slice: an extract built ahead of time, a bump penalty in `score_route`
weighed against what it already ranks by, and "about N speed bumps mapped"
on the drive card with the coverage caveat. Measure it the same way after.

## Reproducing the survey

Overpass queries used (area `51.43,-0.72,51.52,-0.55`, send a User-Agent
naming the project; servers refuse requests without one):

```
[out:json][timeout:120];(node[traffic_calming](BBOX);way[traffic_calming](BBOX););out meta center;
[out:json][timeout:180];way[highway~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential|living_street)$"](BBOX);out tags geom;
[out:json][timeout:120];(node[highway=traffic_signals](BBOX);node[highway=crossing](BBOX);node[highway=mini_roundabout](BBOX);node[highway=give_way](BBOX);node[highway=stop](BBOX);node[highway=speed_camera](BBOX););out tags;
```

Calming points were matched to roads by shared vertex (rounded to about
1 m); squares are 0.009 degrees of latitude by 0.0144 of longitude, about
1 km by 1 km. The downloads were not committed. The measurement used the generator's own
functions with the routing provider configured in `backend/.env`, ran from
a developer machine, and printed counts only, never routes or keys.

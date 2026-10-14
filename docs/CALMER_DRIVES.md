# Calmer drives: what the map data holds about speed bumps

Research 11 Oct 2026; built the same evening (0.8.7, see the end). Question from the roadmap:
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

## Built (0.8.7, 11 Oct 2026)

IMPLEMENTED.

- **Data, ahead of time:** `backend/tools/build_calming.py` writes
  `backend/data/calming/<region>.json` from OpenStreetMap (vertical calming
  only; ODbL, attributed). `windsor.json`: 3,437 points, 51.33 to 51.62 N,
  0.88 to 0.40 W, data as of 2026-10-11T21:14Z. Refresh monthly; another
  area is one more run. Nothing is fetched while serving a drive.
- **Count:** `core/calming.py` counts mapped bumps within 12 m of a drive,
  each once, or gives no count when under 80% of the drive is inside
  prepared data. A simulated drive gets no count.
- **Ranking:** drives are ordered as before (time, smoothness, loop, road
  mix). Then `scorer.calmer_lead` may put a calmer drive first, but only
  one with **no more turn-arounds** than the drive it replaces and **at most
  3 minutes further** from the time asked for; among those the score with
  bumps decides (`W_BUMPS` 0.25, full at one mapped bump per km).
  Why the guard: a plain penalty, tried first, bought fewer bumps with an
  extra turn-around (Datchet, 1 to 3) or ten minutes over the time
  (Englefield Green), which is a worse drive for a sleeping baby.
- **Card:** "About N speed bumps mapped along this drive · there may be
  others nobody has mapped. Map data © OpenStreetMap contributors", or "No
  speed bumps mapped along this drive" with the same caveat; nothing outside
  the prepared area.

**After (same 160 candidates ranked both ways, no extra calls):** the drive
offered first changes in 2 of 20 (Datchet: Quieter 15 to 9 bumps, Mixed 37
to 14), 11% fewer mapped bumps across all 20, no added turn-arounds, median
time unchanged within half a minute. Modest by design: the larger savings
seen in the first measurement (Bray 8 to 0, Englefield Green 7 to 2) came
with a turn-around or a worse time, and the guard refuses those.

OPEN: does it feel calmer? Founder, on real drives from Datchet and
elsewhere. LATER, only if it helps: let calmer candidates into second and
third place too, and shape candidates away from dense clusters (option 2).

## Traffic lights (0.8.11, 12 Oct 2026)

IMPLEMENTED. Founder, after a real drive: one stop-go, three or four sets
of lights, one pedestrian-operated; a stop may wake a baby more than a bump.

- **What the map holds**, wider Windsor area (51.33 to 51.62 N, 0.88 to
  0.40 W, data 2026-10-12T14:37Z): 3,452 lights, grouped (lights within
  40 m are one junction or one crossing; a signalled crossing beside
  junction lights belongs to the junction) into **702 junctions** and **141
  pedestrian-operated crossings** (signal-controlled crossings, and lights
  tagged pelican, puffin, toucan or pegasus). OSM tells them apart well; an
  ambiguous light with no tags counts as a junction.
- **Counted** like bumps (`core/calming.lights_along`): each junction or
  crossing once, within 12 m of the drive; no count outside the data.
- **Ranked** with bumps under the same guard (`scorer.calmer_lead`: no extra
  turn-arounds, within 3 minutes): W_LIGHTS 0.3, full at one per km.
- **Card:** "Traffic lights at about N junctions and M pedestrian crossings
  mapped along this drive".

**Measured offline** on the same 160 real candidates (no new calls): one
start's candidates range from 3 to 29 junctions with lights; a median drive
meets about 8 junctions and 3 pedestrian lights. Ranking with bumps and
lights together changes the first drive in 1 of 20 (Englefield Green,
Quieter: bumps 7 to 5, junctions 10 to 5, pedestrian 2 to 0); across all
20, bumps 255 to 253, junctions 123 to 118, pedestrian lights 44 to 42, no
added turn-arounds, timing unchanged. Bumps alone had changed the two
Datchet drives, but their calmer candidates had more lights.

The guard is why the effect is small: the calmest candidates are mostly
the ones with a turn-around or off the time. NEXT (proposed): build calm
candidates on purpose, by placing waypoints to steer round dense clusters
of lights and bumps, then the same guard picks among better options.


## Steering round busy stretches (0.8.13, 13 Oct 2026)

IMPLEMENTED (`core/steering.py`), the "next" above. For the two leading
drives of a request:

1. find the densest 2 km of stops on the drive (bump 1, junction lights
   1.2, pedestrian lights 1, roadworks that stop traffic 4; at least 3),
   leaving alone the first and last 800 m: a parent's own street can't be
   avoided;
2. ask TomTom for the same drive kept out of a box round that stretch
   (`avoidAreas`, which only its POST form takes; one call);
3. take the point where that detour strays furthest from the drive (at
   least 200 m) as an extra waypoint, pulling the drive's own waypoints in
   to pay for the detour's extra minutes; Google Maps on a phone takes three
   waypoints, so with three already the nearest gives way;
4. route the waypoints again, plainly (one call), and keep the result only
   if a parent meets **fewer stops** on it (`scorer.stops_met`, at least 2
   less; not per km, since a longer drive with more lights is not calmer;
   turn-arounds included, see below).

Why waypoints: Google Maps, which most parents drive with, gets only our
waypoints and picks its own roads between them. An avoid-area exists only
inside TomTom, so a drive is offered only as the waypoints make it.
Steered drives then compete with the rest under the usual rules.

Cost: up to four extra TomTom calls a request (two per drive steered).
Simulated routing is never steered. The generate log line says
`steered=<chosen>/<built>`.

**Measured** on the 20 Windsor requests above (10 starts, Quieter and Mixed,
30 minutes; cached candidates, live steering calls):

- A detour around the busiest stretch usually meets as many stops
  elsewhere: of 29 avoid-area detours with an apex, the waypoint drive was
  calmer in 6 with the loop pulled in, 3 without. The avoid-area detour's
  own count says little: it is forced the long way round.
- The first drive changed in **4 of 20**. Two clear wins: Dedworth Road,
  Mixed (bumps 19 to 10, same lights, same turn-arounds, 2.4 min from the
  time); Eton Wick, Quieter (bumps 27 to 9, turn-arounds 3 to 1, 4 minutes
  further from the time). Two trade-offs the existing ranking made: Dedworth
  Road, Quieter (20 to 30 minutes, on time now, lights 6 to 0, but two
  turn-arounds where there were none) and Windsor & Eton Central, Mixed
  (one turn-around fewer, three more lights, 5.5 minutes longer).

The trade-offs are the ranking's own: a steered drive is always calmer
than the one it was built from, but may win first place on time.

## Turn-arounds on the same scale (0.8.13, 13 Oct 2026)

Founder, on the Dedworth case: "a turn-around is better than a red light
and especially better than a stop-go", though better still at a spot where
turning is easy. Until then a calmer drive could never add a turn-around,
which made one turn-around worth about seven sets of lights.

Now every stop is on one scale (`scorer.STOP_WEIGHT`, `TURN_WEIGHT`): a
bump or a turn-around 1, lights 1.2, roadworks that stop traffic 4,
counted as met on the drive. `calmer_lead`: a drive at most 3 minutes
further from the time than the first may replace it when it spares at
least 2 (`CALM_GAIN`). Steering keeps a drive on the same test.

Measured offline on the 20 requests (candidates plus the steered drives,
no calls): first drive changed in 7 of 20; across all 20, bumps 222 to
167, lights 157 to 141, turn-arounds 14 to 22, minutes off the time 82 to
78 in total. E.g. Bray, Mixed: 8 bumps and 16 lights to none and 1, for two
turn-arounds. With a turn-around at 3: 5 of 20 changed, bumps 169, lights
146, turn-arounds 19.

Per child: see "What wakes your little one?" below.

## Easy places to turn round (0.8.13, 13 Oct 2026)

IMPLEMENTED. The founder's own example (Slough): a drive's spike ended at a
loop round a small island at the end of a residential street, driven round
with no three-point turn. In OpenStreetMap that loop has no tag: the street
runs in, round the island and back to a point it has already passed.

- **Data** (`tools/build_calming.py`, `turns` in data/calming/windsor.json,
  OSM 2026-10-13T12:09Z): 3,152 easy places to turn round, as [lat, lng,
  kind, radius]: 1,631 turning circles or loops tagged at a street's end,
  616 roundabouts (pieces joined), 423 mini-roundabouts, 482 road loops
  found by shape (a road on residential to primary roads that rejoins
  itself within 300 m; service roads and car parks left out). The founder's
  example is found, radius 16 m.
- **Where a drive turns round:** at a waypoint (the geometry detector) or
  where TomTom's guidance says U-turn (its point, now kept). Within 30 m of
  an easy place's edge it is easy (`calming.easy_turn_at`).
- **Counted** at `EASY_TURN_WEIGHT` 0.3 of a hard turn-around, in the
  ranking's smoothness and on the stops scale. The card says "turns round
  once, at a roundabout" (or a mini-roundabout, a turning circle, round a
  loop at the end of a street) instead of "doubles back once".
- **Moved:** for the two leading drives, a waypoint the drive turns round at
  away from an easy place moves to the nearest one within 700 m, and the
  drive is routed again (one call), kept if better on the stops scale
  (`steering.easier_turn_candidates`).

**Measured** on the same 20 requests: of 134 waypoint turn-arounds on all
candidates, only 2 were at an easy place, so the weight alone changes
nothing; the move is what counts. Moves tried 12, all better; the first
drive changed in 8 of 20. First drives: turn-arounds 22 to 20, at an easy
place 0 to 12, and often fewer stops too (Englefield Green, Mixed: stop
weight 19 to 3.6; Windsor and Eton Central, Mixed: 12.6 to 7.6). The cost
is time: 16 more minutes off in total over 20 drives, and three drives 4
to 8 minutes further from the time (all within the 10-minute window), the
ranking preferring a smoother drive. Up to two more TomTom calls a request.
Measurement scripts: scratchpad `steer_measure.py`, `steer_diag.py`,
`steer_variants.py` (not in the repo; counts only).

## What wakes your little one? (0.8.15, 14 Oct 2026)

IMPLEMENTED. Founder: let parents "choose what types of obstacles are better
and worse for their kids. It easily can be different for each child."

- **Asked in Settings,** per kind of stop: speed bumps, stopping at traffic
  lights, turning round, roadworks (stop/go and temporary lights). Answers:
  Not at all / Sometimes (the usual) / Wakes them. Kept on the phone (one
  set per phone; one per child would come with account sync) and sent with
  every drive request as `stops`.
- **Weighed** (`scorer.stop_preferences`, for one request): Not at all
  keeps a quarter of the kind's weight on the stops scale, Wakes them two and
  a half times (`FEELING_FACTOR`, HYPOTHESIS). It applies to choosing the
  first drive (`stops_met`), to steering round the busiest stretch, and for
  turning round also to the smoothness every drive is ranked by.
- **Measured offline** on the 20 Windsor requests (cached candidates and
  steered drives): each answer changes the first drive in 1 to 3 of 20.
  "Lights wake them": lights 141 to 125 across the 20 first drives (bumps
  167 to 179); "turn-arounds wake them": turn-arounds 22 to 21 (bumps up 17);
  "bumps wake them, turning round is fine": minutes off the time 78 to 61.
  Modest, because a request has few candidates and a calmer drive may be at
  most 3 minutes further from the time; steering live uses the answers too.

Settings now have **Simple** and **All** (founder: settings "are getting
more and more"). Simple hides a drive's tolerance and direction and, for
walks, retracing, checkpoint reach and walks that need travel; each still
shows once changed from its default, so nothing in force is out of sight.

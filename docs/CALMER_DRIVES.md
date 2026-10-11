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
- **One finding matters for the product now:** mapped calming is densest on
  exactly the roads "Quieter" prefers. Residential and tertiary roads carry
  about 1.3 mapped features per km; primary roads 0.07. HYPOTHESIS: a
  "Quieter" drive meets *more* speed bumps than a "Mixed" one around
  Windsor, which works against the "smoothest for a sleeping baby" promise.
  Not yet measured on real drives.

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

## Before building: one measurement

OPEN: does counting actually change which drive is offered? Take about 20
drives in the founder's area (8 candidates each: about 160 TomTom calls,
within the free allowance), count mapped calming on every candidate, and
compare "Quieter" with "Mixed". If candidates differ by a few bumps or
less, option 1 isn't worth building; if "Quieter" carries clearly more, the
"Quieter" label and its promise need rethinking either way.

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
1 km by 1 km. The downloads were not committed.

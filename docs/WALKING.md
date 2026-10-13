# Walking with a pram or carrier — the experiment

Status, 9 Oct 2026: **IMPLEMENTED behind a flag, enabled on production, not
yet field-verified.** Four walks around Windsor, built from map data. The
founder has opened the screen on a phone; nobody has walked a route with it
yet, and the founder's own circuit is not in yet (see
[Adding your own walk](#adding-your-own-walk)).

It is the **Walk** tab, beside Still asleep, Plan a drive and Meet up - a
founder decision on 9 Oct, after a header button made the navigation grow in
two places. The tab exists only while the flag is on.

## What it does

Pick **Pram** or **Carrier**, optionally describe the pram (wheel type, width,
double) or the load (approximate weights, who carries the bag), and pick a
rough duration.

**Fitting the time.** A there-and-back walk turns back early to fit the time
asked for. Each stretch costs its length twice plus everything climbed on it
in either direction, so a hilly stretch uses the time faster than a flat one.
Obstacles beyond the turn no longer count; those before it still do. A loop
cannot be shortened, so its card says how far off it is. Every card states the
fit in one sentence - the first version only sorted by duration, so asking for
60 minutes quietly returned 20-minute walks.

Each walk comes back judged for that setup:

| Verdict | Means |
|---|---|
| Not suitable for your setup | A known incompatibility: steps with no ramp, a stile, a gap narrower than the pram. One is enough. |
| Possible, with harder stretches | Passable with effort or care, and each stretch says where it is. |
| No known problems, but parts aren't recorded | Nothing known against it, and some of it is unknown. |
| No known problems | Nothing known against it, and it is all recorded. |

A blocking obstacle is never averaged away by the pleasant stretch around it,
and an unknown is never shown as fine.

## Who is walking

**Pram**, **Carrier**, or **Just me** - the third added by founder decision on
9 Oct 2026, for people without children or parents walking alone. It goes
beyond the Bible's pram-and-carrier scope on purpose. For someone on foot,
steps and stiles are notes rather than obstacles, a climb counts as harder
going only above 15% (HYPOTHESIS), loose or soft ground is a footing note, and
an unrecorded surface does not make the verdict "unknown" - it does not decide
whether the walk is possible - though the coverage line still states it. Walks
made from your start use ordinary walking routing, steps allowed.

## Settings and updating

Changing a setting, the time or the start no longer recalculates anything by
itself: an **Update walks** bar appears while the settings differ from those the
walks were made with, and one tap recalculates the curated walks and re-makes
the made ones. Walks made from your start come first; if no curated walk starts
at your doorstep and fits the time, they are made as soon as your location is
known. Curated walks fold into their own section.

## Shapes, distance and preferences

Founder decisions, 9 Oct 2026, after using it:

- **Shape is measured, not declared.** The share of a walk that passes within
  20 m of ground already walked decides whether the card says *Loop*, *Loop,
  partly walked twice* or *There and back*. Castle Hill, curated as a loop,
  measures as there-and-back: it goes up and comes back down the same streets.
  Generated walks are called "Walk", not "Loop", for the same reason.
- **How much may be walked twice** (Walk preferences, kept on the device):
  don't mind / a little (up to about 15%, enough for a shared first and last
  stretch) / avoid. Founder feedback: a yes/no was too blunt. Anything but
  "don't mind" also stops a long loop being shortened by turning back.
- **Greener or quieter**, for walks made from your start: openrouteservice's
  documented `green` and `quiet` weightings, which exist for walking routing
  only. **Not offered for a pram** (DECISION, 0.8): until 0.8 a pram asking
  for either was switched to walking routing with only steps avoided, which
  is weaker than wheelchair routing - that also limits surface, smoothness,
  slope and kerb height - so it could admit paths a pram may not manage. A
  pram now always gets wheelchair routing. A request for a greener or quieter
  pram walk (an older app) is answered with an ordinary pram walk that says
  so, on loops and on both legs of a checkpoint walk; tested in
  `tests/test_walk_generation.py`. **Closed, 11 Oct 2026** (IMPLEMENTED in
  `be248b1`, rechecked): `generate.request_body` is the only place a routing
  profile is chosen; it returns `wheelchair` for a pram whatever the
  character asked for, and never adds a weighting for a pram
  (`pram_character` turns a stale client's request into an ordinary pram walk
  with a note). Loops, every checkpoint leg and routes of your own all build
  their requests with it. Tests: `test_a_pram_is_never_moved_off_pram_routing`,
  `test_an_older_app_asking_for_a_quieter_pram_walk_gets_pram_routing_and_a_note`,
  `test_a_pram_walk_via_a_checkpoint_keeps_pram_routing_on_both_legs`
  (`test_walk_generation.py`), `test_every_profile_keeps_its_access_rules_on_both_legs`
  (`test_walk_checkpoints.py`) and `PramTests` (`test_walk_trace.py`).
  Wheelchair routing's rules are the provider's; missing surface or slope
  data stays "not recorded" on the card, never a guarantee. Rivers, canals, seaside and
  "town" are not offered by the provider and are not pretended; waterside
  would need our own check against mapped water. Each generated walk shows its
  share along streets and roads, from the provider's way types. **What they do
  in practice is measured below** (Greener and quieter, 10 Oct): around
  Windsor, nothing.
- **From your doorstep versus needing travel.** A walk starting within 1 km of
  you is from your doorstep; further ones are listed separately with their
  distance, and can be hidden.
- **Nothing more than about an hour's drive away is shown.** Approximated as
  60 km in a straight line - roughly an hour's drive across most of the UK, not
  a measured drive time.
- Walks hidden by a preference are counted on screen, never silently dropped.
- **Time:** 20, 30, 45, 60 or 90 minutes, or any number from 10 to 240.

## Walks made from your start

With `ORS_API_KEY` set on the API (`/api/health` reports
`"walk_generation": true`), the Walk tab offers **Start from**: where you are,
or any place you search. It asks openrouteservice for three round trips of the
length your time allows - wheelchair routing with steps avoided for a pram,
walking routing for a carrier - and judges each with exactly the same rules,
findings and map as the curated walks.

What generated walks can and cannot say. Surfaces and path types come from
openrouteservice's per-stretch information; heights from its SRTM model, which
is coarser than the 25 m model the curated walks use. **Gates, stiles and kerbs
are not reported**, and every generated walk says so. Nobody has checked a
generated walk on foot.

Terms (openrouteservice Standard plan, reviewed by the founder 9 Oct 2026):
results are CC-BY-SA 4.0 with attribution shown under the walks.

**What openrouteservice receives, exactly.** From Driftway's server, never
the phone: the start point and, for a walk via a checkpoint, the checkpoint,
both as precise coordinates; the walk options (routing profile, length,
weighting, areas to avoid). No name, account, device id, label or search text
goes with them. A precise start can still be someone's home, so it is location
data about a person, and the earlier wording here ("personal data must not be
sent... the start point only") overstated the position. Driftway does not
store or log those points - provider error messages are logged with every
number blanked, and validation errors no longer echo submitted values - and
generated walks are not stored. What openrouteservice does with a request is
governed by its terms, not by Driftway. Usage is capped
at 10 generations a minute and 600 a day across everybody (three provider
calls each, against the plan's 40 a minute and 2000 a day), and 4 a minute and
30 an hour per account.

**Status:** round trips confirmed working on production for pram and carrier
by the founder, 9 Oct 2026 (founder-tested). "Just me" is implemented and
deployed, not founder-tested.

## Fitting the time, and spikes (0.8, 11 Oct 2026)

Founder feedback after using it: generated walks came back much longer than
asked and still came first, and some had spikes - out along a path and
straight back the same way. openrouteservice treats a round trip's length as
"a preferred value". Now, for loops made from a start (`generate.py`):

- **Spikes are cut out first.** A spike is up to 700 m out and back along
  the same path (at most 40% of the walk), after which the walk carries on
  somewhere new. The far end of a there-and-back walk also comes back on
  itself, but then the walk heads back the way it came, so it is not cut.
- **Measured** in walking minutes, as the card measures them (pace plus
  climb).
- **Asked for again** when a loop misses the time by more than 15%, with its
  length scaled by the miss. The closer of the two answers is kept. At most
  one extra call per loop.
- **Ordered**: walks within 20% of the time first, then by the smaller miss.
  Greener and Quieter re-order only among equals.

Live check, 11 Oct, from the Long Walk's Park Street end, best walk against
the time asked: 40 min for 45 (Just me), 64 for 60 (Carrier), 29 for 30 (Just
me), with 4 or 5 provider calls each. Loops that cross themselves are not yet
handled, pending the founder's examples. Several checkpoints: see
Checkpoints.

## Checkpoints

**Up to three** (founder request, 11 Oct 2026; IMPLEMENTED). Walks go through
them in the order they were added, then home another way, in one request
for the way out. "How close a walk must come" applies to every checkpoint:

- at the last, the way out is cut where it first comes that close, as
  before;
- at one in between, the walk is routed through it, then the stretch inside
  that distance is replaced by the direct path between where it enters and
  leaves, when that is shorter. That costs one extra call per checkpoint.

Later walks leave openings round every checkpoint in the paths they avoid.
Before any call, the chain is checked: the first checkpoint at the start,
two in the same place, and a time floor (straight legs, less twice the reach
per checkpoint). Each walk records every checkpoint, and the map numbers
them. Several checkpoints are not founder-tested yet, and the controls have
not been seen on a phone.

What follows was written for one checkpoint and holds for each of them.

A checkpoint means **"visit this point"**, not "follow this avenue". Founder
request, 9 Oct: a walk via the Long Walk went to the single midpoint the place
search returned, not the stretch along the treeline the founder meant. Since
10 Oct the checkpoint can be placed on the map. Multiple checkpoints, drawn
corridors and dragging the route itself are LATER.

**Choosing it** (IMPLEMENTED, `frontend/src/walking/checkpoint.ts`,
`CheckpointPicker.tsx`):

- "Drop a pin on the map" (until 0.8: "Choose on map") opens an explicit selection mode. Inside it a tap places
  the one draft marker and dragging moves it; panning and zooming never do
  (Leaflet reports a click only when the finger did not drag). The cross at
  the centre with "Place at centre" does the same without precise gestures,
  and from the keyboard.
- "Use this point" confirms it as "Point on map"; "Cancel" restores the
  checkpoint that was there before. "Remove checkpoint" clears it. Search
  and map edit the same checkpoint.
- The map is centred once, when it opens, and never re-fitted while choosing.
- No provider is called while choosing - no routing and no reverse geocoding.
  A confirmed or removed checkpoint is a changed setting: the Update bar
  appears, and walks are made only on "Update walks", with the profile,
  time and preferences unchanged.
- The checkpoint is not remembered on the device after the page closes.
- While settings are being edited, the walks on screen stay, marked as made
  for the previous settings. An answer arriving for older settings is dropped
  rather than shown.

**What the provider does with it, and the policy** (DECISION, 10 Oct;
`backend/core/walking/generate.py`):

- Coordinates are checked finite and in range on both sides, and sent as
  [lng, lat]. The provider snaps each point to the nearest way the profile may
  use - for a pram, wheelchair routing, so never onto steps - and both legs of
  the walk keep the profile's access options.
- Within **25 m** of the parent's marker, the walk visits the marker. The 25 m
  is a HYPOTHESIS: about a path's width plus a marker placed by finger.
- **How close is close enough is the parent's to set** (DECISION, founder,
  10 Oct): Walk preferences → "How close a walk must come to your
  checkpoint": to it (25 m, default), 100, 250 or 500 m. The founder's case is
  the King George III statue (OSM way 931857501) at the end of the Long Walk:
  the walk should pass it about 200 m away, not climb Snow Hill to it. Above
  25 m:
  - the way out is cut where it first comes that close, and the way back
    starts there;
  - the provider may search that far for a path;
  - the time floor counts only the distance beyond that circle;
  - a start already within reach is refused;
  - only a walk that cannot get that close needs the parent's acceptance;
  - each kept walk is checked to come within reach;
  - the card says how far from the checkpoint it turns.

  Live check: going "to it", a Just me walk from the Long Walk's Park Street
  end came within 18 m of the statue, with 89 m of climb. The 250 m
  comparison was cut short when openrouteservice began refusing requests
  with "Quota exceeded" although its dashboard showed the quota unused (see
  `DEPLOY.md`), and is still to be run.
- Snapped further, up to **150 m**, the walks are made but not shown until the
  parent has seen both points on the map and accepted the moved one, or moved
  their marker. Distance alone does not show two places are equivalent: the
  nearest path can be across a river, behind a fence or on the wrong side of a
  wall. Accepting needs no new request, because the walks already go there.
- Beyond 150 m, or with no route to the point, nothing is routed and the
  parent is told why and asked to move it. No connector is ever drawn across
  unmapped ground.
- Every walk kept passes within 25 m of the routed point; a variant that
  snapped elsewhere is dropped.
- A checkpoint whose straight-line distance there and back already exceeds
  the time (with the usual tolerance, 15% or 5 minutes) is refused before any
  provider call, with the minimum time. Walks that turn out longer than asked
  are shown with "longer than you asked for", plus an offer of a longer time
  or a nearer checkpoint. A walk via a checkpoint is never shortened before
  it gets there, and the time is never changed for the parent.
- The way back avoids a 25 m corridor along the way out, left open for 150 m
  at each end. If no wholly different way back exists - a single bridge, gate
  or path can force that - the walk goes over some ground twice and says so,
  with the share measured. If that is more than the retracing preference
  allows, the walk is hidden with a count and a "Show it anyway" button,
  never silently dropped.
- The provider's `alternative_routes` option is still not used: it is
  documented only in forum threads.

**Live check, 10 Oct 2026** (developer, public points: the Long Walk's Park
Street end to its midpoint, from the curated walk's own data; 15 calls):

| Case | Result |
|---|---|
| Pram, 60 min | 1 walk, visits the point (0 m), 82 min, flagged longer. There and back: no wheelchair way back avoiding the avenue, and it says so |
| Carrier, 60 min | 1 walk, 0 m, 78 min, a loop, flagged longer |
| Just me, 60 min | 1 walk, 0 m, 78 min, a loop, flagged longer |
| Just me, a marker about 80 m east of the avenue | Snapped 60 m: confirmation required |
| Pram, the middle of Queen Mother Reservoir | "No mapped way suitable for a pram within 150 m" - after fixing the parser for the live error wording, which differs from the older one in forum threads |
| Just me, 20 min | Refused before any call: "at least 57 minutes" |

Only one walk came back per profile here: further variants either found no
route avoiding the earlier ones or repeated them. Whether the founder's
treeline is reachable this way needs the founder's own point - not guessed
from a screenshot. Status: IMPLEMENTED, live-checked by the developer, **not
founder-tested**, not yet seen on a phone.

Map lines use saturated colours over a dark outline, chosen for a light map:
the app's dark-theme pastels vanished over parks and fields.

## Greener and quieter, measured (10 Oct 2026)

The founder saw "all three modes rotate the same three routes". A controlled
comparison, holding start, profile (carrier), length and seed constant
(about 60 calls, public points in Windsor, Heidelberg and Berlin):

- **The option reached the provider - in one form only.** `{"factor": 1.0}`
  is refused (400, code 2002) in all three cities; the integer form
  `{"green": 1}` is accepted. The integer form now goes first.
- **Around Windsor, the geometry did not change.** It was identical to the
  ordinary route in all four pairs tried: two point-to-point routes, one
  through the town centre, and two loops. The provider's own per-stretch green
  and noise values came back as one constant range along each Windsor route,
  even through town. In Berlin and Heidelberg they vary stretch by stretch,
  and the routes changed: Berlin greener shared 36% of its line with the
  ordinary route, quieter 63%; Heidelberg quieter 37%; Heidelberg greener was
  identical in the one pair tried.
- **Not shown: that any route is greener or quieter.** A changed line proves
  the weighting acted, not that the walk is better. The provider's values
  were not checked against anything on the ground.
- **Why the same three walks came back:** round-trip seeds (1, 2, 3) set the
  directions of the three loops whatever the character. With no data to weigh,
  the walks were the same, and greener or quieter re-sorted them by their
  share along roads.

So: no wiring or caching defect beyond the refused form. HYPOTHESIS: the
public service has no green or noise data for Great Britain. Weighted walks
now ask for that data and say when it does not vary along the walk, and the
preference explains that it depends on the provider's data. The smallest next
experiment, if the option is to mean something in the UK: score candidate
walks against mapped parks and main roads ourselves (OSM), rather than rely
on provider weighting.

## Access

- `WALKING_ENABLED` on the API, default **off**. Off means the endpoint answers
  404 and the app shows no entry point. Driving and meetups are unaffected
  either way (tested).
- Then `WALKS_ACCESS`, enforced on the server. Unset or `everyone` (the
  default since 11 Oct 2026, founder decision: the beta is small and found only
  through him) lets anyone in, signed in or not; making walks is rate-limited
  per account, or per network address for someone not signed in, inside the
  shared provider budget. `admitted` restores the 14 Sep policy: only accounts
  that redeemed an invitation.
- Equipment and load are sent with each request and never stored. A test checks
  that an assessment leaves every table unchanged.

To try it: set `WALKING_ENABLED=true` on the Render API, then **Walks** appears
in the header.

## Why it is curated rather than generated

The audit, run before any design work (central Windsor, 664 mapped paths,
OpenStreetMap as of 8 Oct 2026):

| Recorded on the map | Share of paths |
|---|---|
| Surface | 25% |
| Smoothness | 0.5% |
| Width | 0.6% |
| Incline | 2% |
| `stroller=` | 0 |
| Steps | well mapped (they are a path type) |

Automatic pram suitability is not possible from that. It also weakens the case
for openrouteservice: its wheelchair profile routes over the same OSM data, so
it cannot know what the tags do not say. Its quota and terms were not
verifiable without a sign-up (the official restrictions page lists none), and
are now not the deciding question.

So the founder's walks are the primary evidence, and the map supplements them.

## Evidence

Every claim carries a basis, strongest first:

| Basis | Shown as | What it is |
|---|---|---|
| `reported` | seen on foot | Someone walked it, on a stated date |
| `mapped` | from the map | An OpenStreetMap tag; says what a mapper recorded, not today's condition |
| `modelled` | from terrain data | Gradient from the EU-DEM 25 m height model |
| `unknown` | not recorded | Nothing. Never treated as fine |

Two inferences are labelled as such. A **road's** surface tag describes the
carriageway, so walking its pavement records "road surface; the pavement's own
surface is not mapped". And **unpaved** is its own class, because it says the
path is not sealed and nothing about how firm it is.

## Thresholds — HYPOTHESIS

In `backend/core/walking/profiles.py`, one place to change them:

- Pram: 5% is a noticeable slope; 8.3% (1:12) is hard to push up or hold back.
  Borrowed from UK wheelchair-ramp guidance. **Not a validated pram threshold.**
- Carrier: 10% is hard work with a child on you.
- Time: about 4 km/h, plus a minute per 10 m climbed (Naismith), no stops.
  Stated on every card.

Not modelled, deliberately: calories, heart rate, a "safe" carried weight.
Manufacturer limits are specific to the carrier model.

## The walks

| Walk | Direction | Shape | One way | Character |
|---|---|---|---|---|
| The Brocas riverside meadow | west, across the bridge | there and back | 0.6 km | Flat; gravel then unpaved |
| Castle Hill and the old town | the town | loop | 1.3 km round | Firm; about 19 m of climbing; setts |
| The Long Walk | south, into the Great Park | there and back | 3.7 km | Mapped asphalt; gentle until Snow Hill (about 11%) at the far end |
| Jubilee River Way | north-east | there and back | 1.4 km | Compacted gravel; level; about 560 m unrecorded |
| Snow Hill circuit | south-west, Great Park | circuit | 7.85 km round | **The founder's own walk**, recorded 9 Oct; field path, park roads, steep descent from Snow Hill; turn back early for shorter |
| Westward past Ostritzer Straße | Köpenick, Berlin | there and back | 2.0 km | Level; most of the far half mapped as soft ground |
| Through Alt-Köpenick | Köpenick, Berlin | there and back | 2.0 km | Firm; about 900 m of setts; bollards, one gate |
| To the Müggelsee shore | Köpenick, Berlin | one way | 4.3 km | Mostly sealed, a stretch of soft path; ends at the Seglergemeinschaft am Müggelsee |

Castle Hill is curated to **avoid steps**: the shortest path climbs four
flights, and no curator would offer that walk to someone with a pram. The Long
Walk starts where Park Street meets it; the stretch north of there, towards
the castle, is mapped private and is not part of the walk.

### Walks from someone's home

The three Berlin walks are routes testers walk regularly from home, built
between the home street and the furthest point they gave. **No walk may start
at anyone's door**: walk files are committed to a public repository and shown
to every beta tester. So such a walk is built from the real start and then has
its opening stretch cut away (`"start_after_m"` in the spec) before anything is
written; every published point of the Berlin walks is at least 432 m from the
home street, checked by distance rather than assumed. The specs naming the
home street live in `backend/data/walks/specs/private/`, which is git-ignored.
They were built from the map between two points, so the way the testers
actually walk may differ; a GPS recording would replace them.

## Adding your own walk

This is how the founder's circuit goes in. The Bible describes it as a 30–40
minute circuit with a gravel car park, asphalt, an aggregate path, a worn field
track, a climb at the field's end and a gate with flood and deep-water
warnings. The hand-drawn maps are not georeferenced, so they cannot be used to
place anything. What is needed instead:

**1. The GPS trace.** Record the walk in a fitness app with GPS on, then export
it as **GPX**. That is the minimum: it places the route without inventing
coordinates. The app's elevation figure is not needed (the earlier screenshot's
"0 m ascent" is exactly why); heights come from the terrain model.

**2. What you notice, roughly where.** "About ten minutes in", "at the gate by
the river", or a timestamp is plenty. Worth noting:

- where the **surface changes**, and what to: tarmac, gravel, compacted,
  grass, mud, setts, and how the pram or carrier actually coped
- **gates**: swing gate, kissing gate or stile; whether the pram fitted; the
  width if you can measure it (a tape, or a phone's measure app) — a photo of
  a gate does not give its width
- **steps or kerbs**, and whether there was a way round
- where a **climb or descent** felt steep
- **hazards**: flood or deep-water signs, slippery stretches, standing water
- the **date**, and whether it had rained in the last few days

Send the GPX and the notes; they become `reported` evidence with your date, and
they outrank the map.

**3. Building it.** For whoever runs the tool:

```text
backend/data/walks/specs/<id>.spec.json          what the walk is
backend/data/walks/specs/<id>.gpx                the trace, if from GPS
backend/data/walks/specs/<id>.observations.json  what was seen, and when
```

A spec uses `"gpx": "<id>.gpx"` instead of `"waypoints"`. Observations look
like this:

```json
{
  "observations": [
    {"at_m": 420, "attribute": "surface", "value": "worn grass track",
     "class": "soft", "observed_on": "2026-10-09",
     "note": "Fine when dry; ruts at the field edge"},
    {"at_m": 610, "attribute": "barrier", "value": "gate",
     "observed_on": "2026-10-09", "width_cm": 95},
    {"at_m": 615, "attribute": "hazard",
     "value": "Gate signs warn of flood defences, deep water and slippery surfaces",
     "observed_on": "2026-10-09"}
  ],
  "notes": ["Walked with a soft carrier after two dry days."]
}
```

Then, from `backend/`:

```powershell
..\.venv\Scripts\python.exe -m tools.build_walk data\walks\specs\<id>.spec.json
```

The tool is development-time only: the app never calls OpenStreetMap or the
elevation service while serving anyone. It caches every response in
`backend/tools/.cache/` (gitignored), backs off when the public Overpass
instance is busy (often), keeps to Open Topo Data's limit of one call per
second, and identifies itself by the public repository URL rather than by any
person.

## Sources and terms (checked 8 Oct 2026)

- **OpenStreetMap**, via the Overpass API. ODbL; attribution
  "© OpenStreetMap contributors" is on the Walks screen.
- **EU-DEM 25 m**, via the Open Topo Data public API. Free: up to 100
  locations per request, 1 call per second, 1000 calls per day. Copernicus
  attribution is on the screen. Tested at Windsor points and agrees with SRTM
  30 m within 3 m.
- **The Lullaby Trust**, slings and carriers: TICKS, quoted from the page,
  shown with its last-reviewed date (1 February 2025).

## Known limits

- **25 m terrain model.** It sees sustained slopes. It cannot see a ten-metre
  ramp or a kerb, and in town, buildings and trees can distort it. The open
  Environment Agency 1 m LIDAR is the upgrade path.
- **Ascent is summed per section**, with a 1 m threshold against model noise,
  so the total can differ by a few metres from a whole-route calculation.
  Within the model's own error.
- **GPX matching is nearest-path.** Each recorded point is matched to the
  closest mapped path within 15 m, and that evidence is labelled "matched to
  the nearest mapped path". At junctions it can pick the neighbouring way: a
  check with a sparse synthetic trace of the Brocas walk produced a few short
  mislabelled stretches (a 23 m "Street" between two pieces of Brocas Street).
  A filter for one-point blips is in place for dense real traces, but has not
  been tried on one yet. Expect to review a GPX-built walk by eye.
- **Sections are at most 300 m.** Long ways are split so a slope sits roughly
  where it is; the first Long Walk build charged Snow Hill's climb to walkers
  turning back long before it.
- **The map uses OpenStreetMap's own map images** (tile.openstreetmap.org).
  Its usage policy, checked 9 Oct 2026, allows light use with attribution on
  the map, a real Referer and honoured caching, and forbids bulk or offline
  download; access can be withdrawn without notice, "especially" for commercial
  services. Fine for the beta. Switch to a tile provider before wider use.
- **Google Maps can only approximate a walk.** Its links take at most three
  checkpoints on a phone, and it picks its own way between them. The in-app
  map is the way to follow a walk; the checkpoint link says so.
- **Navigation handoff.** "Directions to the start" opens Google Maps to the
  start point only. It will not follow the walk and the screen says so.
- **The checkpoint picker has not been seen on a phone.** Typechecked, built
  and its rules unit-tested; the founder's phone is the first look. The rest
  of the Walk tab has been used on the founder's phone since 9 Oct.

## Next

1. The founder places a checkpoint on the treeline route on a phone (see the
   checklist in the handover).
2. The two Windsor walks walked once and annotated, so at least one walk has
   `reported` evidence end to end.
3. Feedback from a few parents with different equipment, per the Bible's first
   experiment.

LATER: a map view, live rerouting, load-based timing models, crowdsourced
reports, mountain or technical terrain.

## Walking pace (11 Oct 2026)

Times assumed 4 km/h for everyone; the founder walks at about 5, so every
walk he was offered came out shorter than he asked for. Walk preferences now
have a pace, 3 to 6.5 km/h, kept on the device and sent with each request as
`pace_kmh` (never stored; the server accepts 2 to 7, and 4 when it is
missing). It sets every time on a card, where a long walk turns back, how
long a walk made from the start is asked to be, and the shortest possible
time through checkpoints. The climb allowance stays a minute per 10 m. The
card says which pace it used. On the server the pace is set once per request
(`catalogue.walking_pace`) and read wherever a time is worked out.

## My walks: routes of your own (11 Oct 2026)

Founder request: the walks Driftway makes are not always the ones a parent
walks; his own Long Walk loop never came up. Now:

- **Draw** a route by tapping the map in order (`RouteDrawer.tsx`), with
  "Finish where I started"; **import** a GPX file (track points, else route
  points; read as text, never as markup); or **save** a walk Driftway made
  (its way out, for a there-and-back walk).
- Kept on the device only (`myWalks.ts`, `driftway.mywalks.v1`), as at most
  40 points evenly spaced along the way. Privacy policy 1.5.
- **Show** sends the points to `POST /api/walks/trace`, which routes through
  them in order with the profile's own rules (one openrouteservice call,
  100 m snap radius, steps avoided for a pram) and judges the result like
  any other walk, at the parent's time and pace. A route whose end is within
  150 m of its start is a loop; otherwise it is walked there and back. Not
  logged or stored; same access and rate limits as making walks.
- Between two points the provider takes the shortest suitable way, which may
  not be the parent's; more points keep it closer, and the card says so.

**Later, not built** (founder, 11 Oct): recording a walk as you go (in the
web app only while it is open with the screen on; reliable recording needs a
native app, and a recorded track needs a privacy policy change), and walks
that learn from the ones taken - preferring paths walked before, avoiding
stretches always skipped.

### Fidelity of routes of your own (11 Oct 2026, 0.8.5)

IMPLEMENTED. A route of your own is recalculated along mapped paths, so the
walk shown can differ from what was drawn or recorded. The screen always says
it was recalculated, and the map draws the parent's own line, dotted purple,
over the walk. The server compares the two (`generate.trace_fidelity`, from
the final geometry the card is judged on) and the screen says where they
differ: points the walk passes more than 60 m from (by number), and a walk
more than 30% longer than the line through the points. The saved route is
never changed to match the provider's result.

- **Thinning.** A GPX track is kept as 40 points spread evenly by distance.
  With synthetic fixtures (a loop with a 270 m connector; a parallel path
  150 m away; a long way round) the connector keeps points and is followed,
  and the parallel path and the detour are flagged
  (`test_walk_trace.py`, `FidelityTests`). HYPOTHESIS: a route with several
  short connectors under about 1/40 of its length could lose one; the
  fidelity check would then flag it, and drawing points by hand at the turns
  fixes it.
- **Checkpoints are never cut.** Dead-end cleanup runs on round trips only
  (`test_dead_end_cleanup_never_touches_a_checkpoint_walk`); time fitting
  never turns a checkpoint walk back early (`catalogue._may_turn`,
  `test_walks_longer_than_asked_are_flagged_not_trimmed`); every checkpoint,
  its order and reach are checked in `test_walk_checkpoints.py`.
- **Figures** (distance, climb, time at the chosen pace, warnings) come from
  the final geometry shown
  (`test_figures_come_from_the_geometry_shown_at_the_pace_chosen`).
- OPEN: the founder's own Long Walk circuit, the real test. Not done by a
  developer fixture.

### Free sources for curated walks (founder question, 11 Oct 2026)

Curation by one person does not scale. Checked what exists, free and
reusable, around Windsor (51.40 to 51.55 N, 0.75 to 0.50 W):

- **OpenStreetMap walking route relations** (ODbL, the same terms as the
  map): 25 within that area, read 11 Oct 2026. 19 local, 3 regional, 1
  national (the Thames Path, a National Trail), 1 European (E2). Several are
  made for exactly Driftway's families: the National Trust's "Accessible
  Route, Runnymede" (1.5 km), Cliveden's Blue, Green, Gold and Woodland
  trails (2.6 to 5 km), Ankerwycke (1 km), Runnymede's Summer, Views and
  Memorial routes, plus the Jubilee River Path and Maidenhead's Millennium
  and Boundary walks. Each could be built into a curated walk with
  `tools/build_walk.py` and judged by the same rules, labelled "a mapped
  route, checked by the map, not on foot".
- **National Trails** open data (Natural England, Open Government Licence):
  the Thames Path line; the same route as the OSM relation, from its owner.
- **Not usable:** route sites (AllTrails, Komoot, OS Maps, Wikiloc, walking
  blogs). Their routes are their users' or their own copyright; link to
  them, never copy them.
- **Later, with consent:** parents' own My walks, shared deliberately.
  Needs a sharing step, a review step and a privacy change (a route often
  starts at a door), so it is not automatic.

**IMPLEMENTED, 0.8.8 (11 Oct 2026): trails from OpenStreetMap.**
`tools/import_osm_routes.py SOUTH WEST NORTH EAST` finds circular local
walking routes (network=lwn, roundtrip=yes, up to 8 km by their own mapped
paths), writes one spec each to `data/walks/specs/osm-*.spec.json`, and
builds them with `tools/build_walk.py`, which now takes `osm_relation`:

- **Followed along the trail's own paths**, in the order the route lists
  them, each turned round if mapped the other way. Members that aren't paths
  (car parks, a cafe, a pub: every National Trust trail here lists them) are
  not walked. Where paths don't join, or one can't be used on foot, the walk
  goes round on mapped paths and says so.
- **Starts where the trail says:** its `from` grid reference (converted from
  OSGB36, checked against the Ordnance Survey worked example to about 1 m),
  else its own car park. Within 17 to 78 m of the named start for every
  trail built.
- **Copied:** route line, name, operator, distance, suggested time, start
  and website (ODbL). **Not copied:** the `description` text, which repeats
  the operator's wording; summaries are written from the facts and each walk
  links to the operator's page.
- **Held back unless faithful:** more than 2 gaps, more than 15% + 200 m
  added by going round them, or less than 70% of the stated distance mapped
  means it isn't the trail. Held specs keep the reason in `review` and no
  walk is shipped.

Result for the Windsor area (51.40 to 51.55 N, 0.75 to 0.50 W):

| Trail | Built | Stated | Pram | Carrier | On foot |
|---|---|---|---|---|---|
| Cliveden Blue Walking Trail | 3.1 km | 2.6 | harder going | harder going | fine |
| Cliveden Gold Walking Trail | 4.4 km | 5.0 | harder going | harder going | fine |
| Cliveden Green Walking Trail | 3.5 km | 3.7 | harder going | harder going | harder going |
| Cookham Wetland and Wildlife Trail | 4.6 km | 4.8 | blocked: 5 mapped steps | surface not recorded in places | fine |
| Runnymede Summer Route | 3.1 km | 3.0 | harder going | surface not recorded in places | fine |
| Runnymede Views Route | 2.4 km | 2.5 | blocked: steps | fine | fine |
| St Ann's Hill circular route, Chertsey | 2.4 km | 2.5 | blocked: steps | harder going | fine |

Held, with the reason in each spec: Runnymede Accessible Route (only
0.8 km of its 1.5 km mapped), Cliveden Woodland (going round gaps adds
1.6 km), Egham to Runnymede circular (9 gaps), Runnymede Memorial Route (28
gaps), both Ankerwycke walks (4 gaps; 0.8 km of 1 mapped). Skipped:
Maidenhead Boundary Walk (24 km of paths, no distance tag).

OPEN: the held trails are incomplete or out of order **in OpenStreetMap**,
which anyone can fix. The Accessible Route is the one that matters most
for prams. Fixed in the map, a re-run of the importer picks it up.
LATER: order members by connection rather than by list, which would
rescue some out-of-order routes automatically.

## Walks anywhere (11 Oct 2026, 0.8.9)

IMPLEMENTED. Founder decisions: the developer-side job runs on a GitHub
Actions schedule; AI-written descriptions wait for the founder's approval.

1. **Right away, for anyone, no AI.** In the Walk tab, when no curated walk
   starts within 15 km, the app asks `POST /api/walks/areas` with the
   position. The server keeps only its grid square (0.1 degree, about 11 by
   7 km in Britain), queues it, and returns the walking routes mapped in it
   (looked up from OpenStreetMap's Overpass service once per square, with
   the square's edges only, kept 30 days): name, length, circular or not,
   operator, the operator's page. Shown as "Trails mapped near you, not
   checked yet". Walks made from the parent's start keep working as before.
2. **Within hours, the job, no AI.** `.github/workflows/walk-areas.yml`
   runs `tools/walk_area_job.py` every six hours: up to 3 queued squares per
   run, each built with `import_area(..., broad=True)` (any walking route
   whose own paths are 0.3 to 10 km; circular if it says so or its ends meet,
   otherwise walked there and back; the same faithfulness gate). Walks that
   pass are uploaded (`PUT /api/admin/curated-walks/{id}`, stored in the
   `curated_walks` table) and appear in Curated walks at once. Slopes come
   from EU-DEM in Europe and SRTM elsewhere; the walk names which.
3. **The job, AI.** For up to 20 walks without a description per run, the
   job sends the walk's own facts (no person's data) to Anthropic's Claude
   (`DESCRIPTION_MODEL`, default claude-sonnet-5-5) with instructions to use
   only those facts, then checks the text (length, plain text, no number the
   facts don't contain) and uploads it as **pending**.
4. **The founder approves.** `/review.html` lists pending descriptions with
   the walk's facts beside each; approve (optionally corrected) or reject.
   Only approved text is shown, labelled "Written with AI from this walk's
   map data, and checked by Driftway".

Access: anyone can ask for a square (20 an hour per address); the job's
`WALKS_JOB_TOKEN` can read the queue, upload walks and add pending
descriptions; only `ADMIN_API_TOKEN` approves. A walk in `data/walks/`
always wins over a stored one with the same id. Privacy policy 1.7.
Tests: `tests/test_walk_areas.py`.

**Long trails, in sections (12 Oct 2026, 0.8.10).** Founder idea: a trail
far longer than a walk still passes through somewhere a parent can walk.
In the job's broad mode, a trail longer than 10 km by its own paths is not
skipped: its usable paths inside the area are taken as connected runs
(`build_walk.trail_runs`; never joined across a gap or a path closed to
walkers), cut into pieces of about 4 km (`_cut`; a remainder under 1 km
joins the piece before), and each piece becomes a walk there and back named
after where it starts ("Tiergartenring: from Hiroshimasteg"), so the usual
time fitting turns back when the time is up. At most 3 sections per trail
and 9 per area per run, for the terrain service's daily allowance. Gates
and other barriers on the trail's paths come with the route itself.
Central Berlin (52.5 to 52.6 N, 13.3 to 13.4 E), which had no walk under
10 km, now gives 9 sections of the Tiergartenring, Heiligenseer Weg and
Lübarser Weg.

OPEN: the first real run, and Katya's area as the first test outside
Windsor. LATER: tell a parent when their area's walks are ready (it would
need a contact, so not without asking them).

## When openrouteservice struggles (0.8.13, 13 Oct 2026)

Founder: walks failed all afternoon, "This happens too often. We need a
proper fallback and messaging towards the user." Measured that afternoon on
api.heigit.org: foot-walking round trips timed out after 40 s, a simple
driving route took 33 s, wheelchair routing answered in 0.1 to 6 s; the
dashboard showed 13 errors in 14 requests with the quota almost unused.
Every walk waited 20 s and more, then said only "Couldn't make walks".

- **Fail fast** (`generate._post`): a walk call gives up after 10 s. One
  that times out, fails on the provider's side or takes over 8 s marks that
  ORS profile (foot-walking, wheelchair) as struggling for 5 minutes; walks
  for it then don't call it at all. Whether it has recovered is checked in
  the background, at most once a minute and only when someone asks.
- **Stand-in** (`core/walking/tomtom_walk.py`): loops other than pram walks
  are made with TomTom's walking routes (travelMode pedestrian, on the
  drives' key and rate limiter): a triangle of waypoints round the start,
  three directions, fitted to the length once. TomTom gives no surfaces, way
  types or heights, so these walks say "surfaces, steps, slopes and gates
  aren't known" and slopes are left unknown, never flat. Measured live while
  ORS was down: three 45-minute walks in 1.3 s (48 minutes long).
- **Never for a pram**: TomTom can't keep a pram's rules (surface, slope,
  kerbs, steps), and a stand-in must not weaken them (product rule, 10 Oct).
- **Said plainly**: the screen says openrouteservice is struggling, that
  it's on their side and not the parent's phone or connection, and what
  still works (their own walks, the checked walks near them), with "Try
  again" and "Show the checked walks". Walks from the stand-in carry a
  notice above them. The endpoint answers 503 with
  `{"code": "provider_slow" | "provider_refused", "message", "retry_after_s"}`.
- **Privacy**: TomTom then receives a walk's start (and two points its loop
  passes), as it already does for drives. Privacy policy 1.8.

Not covered yet: walks via checkpoints and "follow my route" (My walks) need
openrouteservice's avoid-areas and snapping; while it struggles they fail
fast with the same message instead of waiting.

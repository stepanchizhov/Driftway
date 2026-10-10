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
  only. A pram asking for either gets walking routing with steps still
  avoided, and the card says so - so for a pram, part of any difference comes
  from the change of routing, not the weighting. Rivers, canals, seaside and
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

## Checkpoints

A checkpoint means **"visit this point"**, not "follow this avenue". Founder
request, 9 Oct: a walk via the Long Walk went to the single midpoint the place
search returned, not the stretch along the treeline the founder meant. Since
10 Oct the checkpoint can be placed on the map. Multiple checkpoints, drawn
corridors and dragging the route itself are LATER.

**Choosing it** (IMPLEMENTED, `frontend/src/walking/checkpoint.ts`,
`CheckpointPicker.tsx`):

- "Choose on map" opens an explicit selection mode. Inside it a tap places
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
- Then **admitted beta accounts only**, enforced on the server. Signing in is
  not enough; an invitation must have been redeemed.
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

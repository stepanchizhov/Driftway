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

Castle Hill is curated to **avoid steps**: the shortest path climbs four
flights, and no curator would offer that walk to someone with a pram. The Long
Walk starts where Park Street meets it; the stretch north of there, towards
the castle, is mapped private and is not part of the walk.

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
- **No map view.** The strip shows where the hard stretches fall along the
  walk; there is no map yet.
- **Navigation handoff.** "Directions to the start" opens Google Maps to the
  start point only. It will not follow the walk and the screen says so.
- **Not yet seen rendered.** Typechecked and built; the founder's phone is the
  first look.

## Next

1. The founder's circuit, from GPX and notes.
2. The two Windsor walks walked once and annotated, so at least one walk has
   `reported` evidence end to end.
3. Feedback from a few parents with different equipment, per the Bible's first
   experiment.

LATER: a map view, live rerouting, load-based timing models, crowdsourced
reports, mountain or technical terrain.

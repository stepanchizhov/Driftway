# Route modes — Project Bible addendum

**Version 0.4 (working) · 9 September 2026 · supplements `Driftway_Project_Bible_v0_3.docx` §6 and §7**

The Bible's §7 already decided the behaviour this addendum implements
("Arrive in about X minutes, to a place", v0.3, DECIDED). This records what was
built, what was actually verified, and what is still not true.

---

## 1. The two modes

The app now asks a parent which of two questions they are answering.

### Round trip (`mode: "loop"`)

Start and finish are the same point. The start is the device location or a
searched place; the finish is **always** that same point.

> **DECIDED.** A saved Home must never become the finish of a round trip.
> This was a real defect: with a Home saved anywhere other than where the
> parent was parked, "Find three loops" silently produced a one-way drive to
> Home. Regression-tested in `tests/test_route_modes.py`.

### Go somewhere (`mode: "destination"`)

Start and finish are different places. Both are editable, so a parent can plan
a drive from the swimming pool while still sitting at home.

> **DECIDED.** The requested duration is the **total journey**, not extra time
> added to the direct route. Asking for 60 minutes when the direct drive is 25
> yields a ~60-minute drive, not an 85-minute one.

The server decides the mode from the coordinates, not the client's label: a
"destination" 20 m from the start is a loop in every way that matters to the
router. The client's `mode` is advisory and is logged when the two disagree.

### The hard floor

A padded route can only ever be longer than the direct one. The direct drive is
therefore measured first — one routing call, before any candidate generation —
and becomes a floor.

When the requested total is at or below that floor (plus 2 minutes' slack), the
app does **not** silently return something much longer. It says so and offers
the direct route:

> "That drive takes about 25 minutes even by the quickest route, so 10 minutes
> is not possible. Here is the direct way."

---

## 2. Address and place search

**DECIDED: search is proxied through the backend** (`GET /api/search`), not
called from the browser. A provider key shipped to a PWA is a key anyone can
lift out of devtools.

Provider: TomTom Fuzzy Search, `idxSet=PAD,Addr,Str,Geo,POI,EPP`, `countrySet=GB`,
`typeahead=true`, biased by the parent's location where known.

### Verified against the live UK dataset, 9 Sep 2026

| Behaviour | Finding |
|---|---|
| Postcode spacing and case | `SL4 1NJ`, `sl41nj`, `Sl41Nj` all resolve. Normalised anyway so the label reads properly. |
| Full postcode | Returns type `Extended Postal Point` — an exact point. |
| Postcode district | Returns type `Geography` with `entityType: PostalCodeArea`. **This is the signal that separates an area from an exact place.** |
| `address.postalCode` | Holds only the outward code (`SL4`), **not** the full postcode. The full one is inside `freeformAddress`. Do not build labels from `address.postalCode`. |
| Duplicates | One leisure centre came back four times, metres apart. Results are de-duplicated by label within 150 m. |
| No matches | HTTP 200 with `numResults: 0` — a normal empty answer, not an error. |

### Rules the picker enforces

- **Nothing routes until the user picks a result.** Typing "windsor" and
  pressing the button must not quietly drive to whatever ranked first.
- **Stale responses are dropped.** Each search carries a sequence number and an
  `AbortController`; a slow reply for an old query can never overwrite a newer
  one. Debounced at 250 ms, minimum 2 characters.
- **Area results are flagged.** An `approximate` result shows "This is an area,
  not an exact spot" and invites refinement.
- **No matches, provider failure and loading are three different messages.**
  A 503 from the provider says search is unavailable; an empty result says
  nothing was found.

### Not verified

UK **Point Address** (`PAD`) coverage. In testing, street-level queries came
back as `Street` or `POI` rather than `Point Address`. Do not assume every UK
house number resolves to its own point.

---

## 3. Current location and Home

- Location is requested on load and can be retried.
- **If location is denied, unavailable or times out, the parent can still
  plan** — the "From" picker is always present, so a manual start is a normal
  path rather than an error recovery.
- Home is **not** a silent fallback for the start. It is offered as a one-tap
  shortcut in both pickers, and nothing more.
- Changing the mode, either endpoint, the duration, tolerance, road style or
  direction **discards the routes on screen**. A stale card whose Google Maps
  link points at the previous destination is worse than no card.

---

## 4. Simulated routes

**DECIDED (changed in this version).** Simulated routes are demo-only and
carry **no navigation link at all**.

Previously, when live routing failed the app quietly substituted simulated
routes and still offered a Google Maps button. The geometry behind those routes
is a straight line between invented points; handing it to a navigation app
dresses a guess up as a drivable route.

Now:

- `GenerateResponse.simulated` and `RouteOption.simulated` mark them.
- `maps_url` is an empty string. The card renders a disabled "Simulated route —
  not drivable" slab instead of a start button.
- Confidence is forced to `low`.
- The results header carries: *"Live routing is unavailable, so these are
  simulated demo routes. They are not real roads and cannot be opened in
  Google Maps."*

**Consequence for local development:** running with `ROUTING_PROVIDER=mock`
exercises the whole pipeline but produces no navigation links, by design. Use a
TomTom key to test the export path.

---

## 5. Result quality

**DECIDED: up to three routes, never padded to three.** Previously the
generator backfilled the list to reach three, which meant a parent could be
sent down a route the app itself had rejected, purely to fill a card slot.

Now the list stops at however many are genuinely worth offering, and says so:

> "Only two routes worth offering here. The rest doubled back or missed your
> time window, so they were left out."

Genuine constraints are kept separate from quality preferences:

- **Constraints** — the endpoints, a drivable road — are never relaxed.
- **Preferences** — the time window, no doubling back, no repeated stretches —
  are relaxed only when nothing else exists, and the route then carries a
  `caveat` naming what it misses ("doubles back once"; "about 41 min, outside
  your 30 ± 10 min window").

---

## 6. Navigation export

Verified by test: the Google Maps URL preserves the chosen origin, the chosen
destination, and the waypoint order, capped at the three waypoints the mobile
app supports. Generated routes never carry more than three, so nothing is
silently dropped.

> **Honest limitation, unchanged.** Google Maps recalculates independently. It
> is given our origin, destination and waypoints — it is **not** given our
> route, and it will not reproduce our duration. Snapping waypoints onto the
> driven road (v0.3) makes divergence much less likely, but only a
> Maps-native handoff would remove it.

---

## 6a. Delayed arrival (the one-tap action)

**DECIDED.** Delayed arrival is *not* a third route mode. It is the fast lane
onto the existing destination routing — Bible §7 Branch B, "extend from an
arbitrary origin (needs route memory)".

### The situation it is built for

A brief stop. Engine running, baby has just gone under, the parent is about to
pull away and has seconds and one hand. Anything requiring two hands or three
screens is useless then. So the destination must already be known.

### How it works

- The app remembers **the last destination the parent chose**, on the device
  only (`driftway.recentDestination.v1`). It is recorded the moment a
  destination is *selected*, not when a route is started — the common case is
  that they looked up the pool, drove there, and the baby fell asleep on the
  way back out, having never launched a route.
- The main screen then offers that destination plus saved Home as a **switch,
  not a menu**: both are on screen at once, so choosing costs no navigation
  step.
- Four fixed durations. One tap generates and hands straight to Google Maps.
  No results screen, no comparison — removing in-car decisions is deliberate.

### Rules it inherits

- The duration is the **total journey**, and the card says so.
- The **direct-route floor** applies. Tapping "15 min" when the drive takes 15
  shows *"That drive already takes about 15 minutes, so there is nothing to
  add"* and opens the direct route.
- **Simulated routes never open.** If live routing is down the action reports
  it rather than launching anything, because there is no results screen here
  on which to show a demo.

### Safety framing

Bible §9 states the principle — *"Route setup happens while parked, or is done
by a passenger"* — but nothing in the UI had ever said it. This is the screen
most likely to be reached mid-journey, so it is the screen that has to.

The block carries: **"Set this up while parked, or hand it to a passenger."**

Calm and non-blocking, per §4 and §9: it offers the alternative rather than
only forbidding, it never shames, and it does not prevent the tap. It sits
above the duration buttons so it is read before acting, not after.

It is deliberately separate from the existing `SafetyNote`, which covers a
different subject (car seats as travel equipment rather than a sleep surface).
Merging them would bury a distraction warning inside a collapsed panel about
infant sleep.

### Hypotheses to tune from real use

- **Freshness window: 7 days** (`RECENT_MAX_AGE_MS`). Long enough to cover a
  weekly routine, short enough that the app is not still offering a holiday
  cottage in March. Re-choosing the same place refreshes the clock rather than
  creating a new entry.
- **Durations: 15 / 30 / 45 / 60.** Unlike the planner these do not start at 5,
  because the floor usually makes very short targets meaningless for a
  destination that is already minutes away.

### Not built

Live extension — "+15 on what's *remaining*" — still requires the app to own
the navigation session, and remains deferred exactly as §7 describes.

## 7. Still true from the 0.3 handoff

The structural finding stands: routing through exact waypoints produces
turn-arounds, measured at **24 of 24 candidates** across dense, suburban and
rural starts. Turn-arounds rank routes down and now surface as a visible
caveat, but they cannot be eliminated while the provider has no round-trip
mode. Provider alternatives (openrouteservice, GraphHopper) are **deferred
pending commercial review** — quotas, pricing and self-hosting licence terms
are all unconfirmed.

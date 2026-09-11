# NapLoop — Claude next-phase handover
**Date:** 11 September 2026  
**Canonical product document:** `NapLoop_Project_Bible_v0.4.docx`

I want to continue developing NapLoop, a mobile-first parent route planner. Treat **NapLoop Project Bible v0.4** as canonical and inspect the current repository before changing code.

The live routing primitives are **Loop Mode** and **Destination Mode**, with TomTom-backed search/routing and the existing delayed-arrival capability. Duration accuracy is reasonably good, but exact shaping waypoints can produce awkward turn-arounds and tiny out-and-back spurs.

The next phase has two parallel tracks. **Track A is the immediate implementation priority. Track B continues behind feature flags and must not block Track A.**

## TRACK A — Core driving UX and route quality

### A1. Reorganize the mobile shell
Use three top-level user jobs:

1. **Still Asleep** — default landing destination.
2. **Plan a drive** — contains the existing `Round trip / Go somewhere` segmented choice.
3. **Meet up** — collaborative playdate / Meet Halfway workflow.

Prefer persistent bottom navigation, or an equally clear mobile job switcher, rather than stacking every function on one scrolling page.

Do **not** split Round trip and Go somewhere into separate top-level tabs. They are distinct route primitives, but share enough controls and mental context to live inside Plan a drive.

Saved places and Settings remain secondary actions rather than additional top-level destinations.

Deep links into meetup sessions/results must open the relevant context directly.

### A2. Promote Still Asleep into an always-available primary mode
The current delayed-arrival card is too contextual and overcrowds Go somewhere. Promote the capability into the default top-level **Still Asleep** surface.

Requirements:

- It must work on a fresh launch, even when there was no recent route search.
- Candidate targets should include:
  - **Home** when explicitly saved;
  - other **saved places**;
  - a **recent route/search destination** only while genuinely recent;
  - **Choose destination** when no useful saved target exists.
- A recent destination is an *additional choice*, never a silent replacement for Home/saved places.
- Initial recency HYPOTHESIS: approximately **6 hours**, never beyond **24 hours** unless the destination was explicitly saved. Keep this configurable rather than burying it in UI logic.
- Still Asleep duration means **total remaining journey time from now**, not “extra minutes”.
- Respect the direct-route floor. If a target already takes longer than the selected time, explain that and offer the direct journey.
- Keep the urgent screen sparse:
  - target;
  - duration;
  - primary `Find route` action.
- Reuse remembered defaults for road style/tolerance where appropriate and place advanced options behind **Route preferences** rather than exposing the full planner control set.
- Remove the duplicate/contextual Still Asleep card from the main Plan a drive screen once the top-level mode is working.

Do not require account creation to use Still Asleep or to choose a destination.

### A3. Conservative short-spur cleanup
We have field examples of two superficially similar branches:

- one is an **integral part of the loop** and must stay;
- another is a tiny **out-and-back spur** created only because a shaping waypoint sits down a side road. Skipping it changes the drive by roughly a minute or less.

Implement a conservative post-generation route-quality pass.

#### Definition of a cleanup candidate
A route segment is a potential disposable spur only when its topology is approximately:

`through corridor/junction -> shaping waypoint -> same/nearly same corridor/junction`

It should show clear out-and-back/reverse-overlap behaviour.

Do **not** classify a segment as disposable merely because it is short, turns sharply, or visually sticks out. A short branch that continues onward and contributes to the loop topology is integral.

#### Cleanup process
For an eligible waypoint-induced short spur:

1. Identify the shaping waypoint responsible.
2. Try moving/softening the waypoint toward the through road or branch junction, or remove the shaping waypoint if safe.
3. Ask the routing provider to calculate the route again.
4. Never simply edit/smooth the displayed polyline. The drivable route and exported handoff points must agree.
5. Accept the cleaned route only when:
   - the short spur disappears or meaningfully shrinks;
   - start/finish and other hard constraints remain correct;
   - route topology is better;
   - requested duration remains inside tolerance;
   - no worse reversal/overlap problem is introduced.
6. If cleanup breaks tolerance, retain the original candidate or regenerate time elsewhere. Do not retain silly geometry solely to gain a few seconds if a better route can be generated within tolerance.

Initial threshold HYPOTHESIS:

- spur added time `<= 90 seconds`; **and**
- spur added time `<= 10%` of requested duration.

Topology is the primary criterion. Tune these thresholds from real field data.

#### Cost controls
Do not allow cleanup to multiply routing calls indefinitely.

- Cap cleanup retries per candidate.
- Log whether each candidate spur was:
  - detected;
  - cleanup attempted;
  - removed;
  - retained because duration would fall outside tolerance;
  - rejected as integral geometry.
- Include extra provider calls in the existing calls-per-generation telemetry.

#### Tests
Add sanitized fixtures for at least:

1. **Integral branch**: must not be removed.
2. **Short out-and-back spur**: should be eligible for cleanup.
3. Cleanup causes duration to leave tolerance: preserve/regenerate appropriately.
4. Cleanup introduces a worse reversal: reject cleaned variant.
5. Provider failure during cleanup: original valid candidate survives.

Do not put private/home addresses into fixtures or repo history.

### A4. Navigation-provider capability abstraction
Do not hard-code the product around one `Open in Google Maps` action.

Create a provider capability boundary/model that can represent, at minimum:

- direct-destination handoff;
- multi-waypoint handoff;
- exact-route / GPX-style import;
- Android Auto / CarPlay continuation where relevant.

Product behaviour:

- A user may later save a preferred navigation app.
- Use that provider when the selected NapLoop route is representable there.
- If it cannot preserve the route, explain why and offer a compatible provider rather than silently dropping shaping points.

Current working assumptions, which must be re-verified against current provider documentation before implementation details are frozen:

- **Google Maps** remains the current multi-waypoint baseline.
- **Waze** is suitable for direct destinations / Meet Halfway navigation, but should not be assumed to preserve arbitrary multi-anchor NapLoop routes.
- **Apple Maps** is a relevant multi-stop option on iOS.
- **GPX/exact-route export** for compatible apps such as Sygic/OsmAnd is LATER.

Example product state:

> Waze can navigate to this destination, but it cannot preserve this multi-stop nap route. Open in Google Maps instead.

Provider incompatibility is a normal product state, not a generic error.

## TRACK B — Meet Halfway staging
Continue the existing invite-only identity + Meet Halfway work from the existing Bible/addendum/brief behind feature flags.

Canonical points remain:

- invite-only beta registration;
- meetup invitees can participate as guests;
- exact origins private by default;
- preferred/max drive duration per participant;
- actual travel-time fairness rather than geometric midpoint;
- family-safe Explore taxonomy;
- structured voting;
- privacy-safe results links;
- optional Delayed Arrival / Still Asleep routing after a venue is selected.

Track B must not block Track A deployments.

## Engineering constraints

- **Inspect first.** Read project structure, `package.json`, backend entrypoints, route generation, API contracts, tests, current env/config, and current project docs before editing.
- Preserve existing working behaviour unless Bible v0.4 explicitly supersedes it.
- Keep routing/search available if optional persistence, account, analytics, or social storage fails.
- Do not build a home-grown password system.
- Exact locations do not belong in the core account record.
- Minimize retained route history and respect the project’s privacy boundaries.
- Complex planning is for parked/passenger interaction.
- Keep staging behind feature flags where appropriate.
- Mark new product proposals as **DECISION**, **HYPOTHESIS**, or **LATER**.
- Do not overbuild the first slice.

## First response before coding
Please first give me:

1. A concise map of the existing frontend/backend code paths affected by this phase.
2. The smallest implementation sequence that can ship safely to staging.
3. Proposed feature flags / migration strategy.
4. Tests that must exist before production behaviour changes.
5. Any contradictions between Bible v0.4 and the current code or existing docs.

Then implement the **first safe slice**, verify tests/builds, and tell me exactly:

- what changed;
- what remains unchanged;
- how to run it locally;
- how to test it on staging from a phone;
- what telemetry/logs to inspect during the next real drive.

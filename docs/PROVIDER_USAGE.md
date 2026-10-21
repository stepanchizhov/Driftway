# Provider usage: calls, ceilings and the founder's checks

Founder and Astra brief, 15 Oct 2026: make provider usage understandable
before Google Play. Each API is its own pool; adding allowances together
would be a fiction.

## Measured (15 Oct 2026, live, from this machine)

| Operation | Calls per request |
|---|---|
| Drive (loop or one-way, 15 to 60 min, Windsor, Edinburgh) | **16 to 24 TomTom routing**, median 18, plus **1 TomTom incidents** (roadworks). Includes the first candidates, refinement, steering (up to 4) and moved turn-backs (up to 2). One-way drives add one direct route |
| Pins in the drive links (0.8.21, `core/handoff.py`) | **1 to 6 more TomTom routing per drive offered**: one per set of link points tried, up to 3 sets, and up to 3 swaps for a full link that still strays. Measured 22 Oct 2026: a 30-min Windsor loop 23 -> 28 calls, a 70-min Quieter one-way drive 20 -> 35 |
| Ferry-free direct way (0.8.20) | 1 more TomTom routing, only when the direct way crosses on a ferry |
| Walk, openrouteservice | 5 openrouteservice directions (three round trips, two fitted again) |
| Walk, TomTom stand-in (openrouteservice struggling) | 3 TomTom routing (6 if the loops miss their length) |
| Walk via checkpoints, stand-in | 3 TomTom routing |
| Route of your own, stand-in | 1 TomTom routing |
| Place search | 1 TomTom search (openrouteservice's search when TomTom can't) |
| Meet Halfway | 1 TomTom matrix per venue check |
| Daily provider check (GitHub Actions) | 1 TomTom routing, 1 search, 3 openrouteservice |
| Google comparison (development only) | `prepare`: about 20 TomTom routing per case; `run`: 1 Google Routes per case |

Retries count: a TomTom routing request is tried up to 3 times on throttling
or a server error, each attempt counted. Nothing loops: refinement has 4
passes, steering 2 drives, moved turn-backs 2 drives, the walk stand-in one
refit.

**Free allowance against use** (public pricing page, read 13 Oct 2026, not
the founder's contract): Routing, 20,000 requests a month, about 650 a day,
which is about **30 to 40 drives a day** at 16 to 24 calls each; with the
pins (0.8.21, 25 to 35 calls) about **20 to 25 a day**. Other TomTom
APIs have their own allowances, not checked here.

## Driftway's own ceilings (IMPLEMENTED, `core/usage.py`)

Daily, per TomTom API, set by environment variable on Render:

| API | Variable | Default | At the ceiling |
|---|---|---|---|
| Routing (drives, walk stand-in) | `TOMTOM_ROUTING_PER_DAY` | 600 | Drives use openrouteservice (no live traffic, and the card says so); the walk stand-in says it can't help |
| Search | `TOMTOM_SEARCH_PER_DAY` | 600 | openrouteservice's place search |
| Incidents (roadworks) | `TOMTOM_INCIDENTS_PER_DAY` | 300 | Cards say roadworks couldn't be checked |
| Matrix (Meet Halfway) | `TOMTOM_MATRIX_PER_DAY` | 100 | openrouteservice's matrix |

HYPOTHESIS: the defaults come from the public free allowance, not from the
founder's plan. openrouteservice keeps its own budgets (`core/ors.py`).

Counts and ceilings live in one server process: they start again on every
deploy or restart, and assume one instance (as on Render today). Driftway
Next, when it exists, counts separately and draws on the same TomTom key:
give it lower ceilings.

**The founder's view:** `GET /api/admin/provider-usage` with the
`X-Admin-Token` header: calls per API and per operation since the server
started, calls per drive request (min, median, max over the last 100),
calls refused at a ceiling, and the ceilings. Counts only, nothing about
anyone.

```powershell
$t = Read-Host "Admin token"
Invoke-RestMethod https://driftway.onrender.com/api/admin/provider-usage -Headers @{"X-Admin-Token"=$t} | ConvertTo-Json -Depth 5
```

## Fixed on the way (15 Oct 2026)

Matching TomTom's roadworks to a drive compared every incident in the area
with every stretch of the drive: a 60-minute drive took 140 s to rank, past
the app's 60 s limit. Both are now narrowed by bounding box first: 6.5 s,
same works found. A test keeps it under a second for 2,000 incidents.

## Founder checks (OPEN)

1. **TomTom plan:** in the TomTom developer dashboard, which plan the key is
   on, the monthly allowance per API (Routing, Search, Traffic incidents,
   Matrix), and what happens past it: refused, or billed, and at what price.
2. **Spend limit:** if the plan bills overage, set a spend cap there.
   Driftway's ceilings are a second line, not a replacement.
3. **Set the ceilings** on Render to fit the plan, if the defaults don't.
4. Watch `/api/admin/provider-usage` after the first testers.

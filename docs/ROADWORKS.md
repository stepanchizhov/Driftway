# Roadworks that stop traffic

Founder, 12 Oct 2026, after a real drive: one stop-go and three or four sets
of lights; a stop-go may be the worst thing for a sleeping baby. Temporary
works are never on a map, so they need a live source.

## England: Street Manager (IMPLEMENTED 0.8.12; subscribed 13 Oct 2026)

Onboarded by the Street Manager team (request SPBS-20493); the endpoint
confirmed the permit topic subscription itself on 13 Oct 2026
(`arn:aws:sns:eu-west-2:287813576808:prod-permit-topic`, as documented).

**What has arrived:** `GET /api/admin/roadworks/summary` with the
`X-Admin-Token` header (founder only) counts, since the API last started,
the events, traffic-control values, coordinate kinds and field names
received, what is kept for drives, and one example stopping permit. That is
how the assumptions below get checked.

The Department for Transport's Street Manager is where councils and utility
companies in England record their works, including how traffic is
controlled. Its open data is pushed as Amazon SNS notifications to an
endpoint we host, under the Open Government Licence v3.0.

**What is built**

- `POST /api/roadworks/street-manager` (`routes/roadworks.py`): accepts
  only messages signed by Amazon SNS for Street Manager's topics (signature
  checked against Amazon's certificate, certificate host checked); confirms
  a subscription by following Amazon's own link; stores permit events.
- `core/roadworks.py` keeps only works that make traffic stop or close:
  `two_way_signals`, `multi_way_signals`, `stop_go_boards`,
  `convoy_workings`, `give_and_take`, `priority_working`, and
  `road_closure`, using the current traffic control when given, else the
  planned one. Works whose control changes to something else, that stop, or
  whose permit is cancelled are forgotten; ended works are purged a week
  after they end (the nightly retention run).
- Drives: candidates passing within 25 m of works running now get a
  penalty (W_WORKS 0.5 per stopping work, under the same guard as bumps and
  lights: no extra turn-arounds, within 3 minutes). Every drive card lists
  the works on it today: "Victoria Street: temporary traffic lights", with
  the OGL attribution.
- Tests: `tests/test_roadworks.py` (signatures genuine, tampered, wrong
  topic, foreign certificate host; grid conversion; what is kept and
  forgotten; timing; ranking; the endpoint).

**Assumptions, checked on real notifications 13 Oct 2026** (278 messages
in 90 minutes; 6,428 works that stop or close traffic kept across England
that first day):

- Coordinates: British National Grid metres in all 278 (`POINT(527809.792
  148101.294)`). CONFIRMED.
- Traffic control values seen: `some_carriageway_incursion` 71,
  `no_carriageway_incursion` 43, `multi_way_signals` 38, `two_way_signals`
  37, `road_closure` 29, `give_and_take` 28,
  `temp_obstruction_15_minute_delay` 13, `lane_closure` 12,
  `stop_go_boards` 6, `priority_working` 1; `convoy_workings` among those
  kept. `stop_go_boards` CONFIRMED. `current_traffic_management_type_ref`
  is present but often null, so the planned value is used then.
- Event types: upper case with underscores (`WORK_START`, `WORK_STOP`,
  `PERMIT_SUBMITTED`, `PERMIT_GRANTED`, `PERMIT_ALTERATION_GRANTED`,
  `PERMIT_REFUSED`, `PERMIT_CANCELLED`). CONFIRMED.
- Dates are full timestamps (`2026-10-13T19:21:18.000Z`), read as such.
- CHANGED: works count on a drive only while **in progress** (work status
  set by `WORK_START`), not because their proposed dates cover now: a third
  of messages were `PERMIT_SUBMITTED`, applications for works that may never
  happen on those dates. One still in progress after its proposed end
  counts for a day more, until its `WORK_STOP`.

**Founder: to switch it on**

1. Register at https://www.gov.uk/guidance/find-and-use-roadworks-data
   (Street Manager open data). Give this endpoint:
   `https://driftway.onrender.com/api/roadworks/street-manager`, and ask
   for the **permit** topic. Accept their terms.
2. Within 3 days of their reply, Amazon sends a confirmation; the endpoint
   confirms it automatically. The API's log then says "Street Manager
   subscription confirmed".
3. Tell me, and I'll check the first works stored and the assumptions above.

Scotland, Wales and Northern Ireland are not in Street Manager.

## Wales, Scotland, Northern Ireland: TomTom incidents (0.8.14, 14 Oct 2026)

Founder: "What about Wales, Scotland and NI?" Searched 13 Oct 2026: no open
feed like Street Manager. Scotland's Road Works Register (kept by the
Scottish Road Works Commissioner, public map at roadworks.scot) lists an open
data section that couldn't be reached; Wales's councils publish through
Elgin's roadworks.org on Traffic Wales (commercial); Northern Ireland's DfI
Roads publishes road assets on Open Data NI but no works register. An email
to the Scottish Commissioner asking about open access is drafted for the
founder.

IMPLEMENTED (`core/incidents.py`): TomTom's traffic incidents, everywhere,
on the drives' key.

- **Live, 13 Oct 2026:** Cardiff 17 roadworks and 15 closures, Edinburgh 36
  and 43, Belfast 8 and 5, Windsor 21 and 6. Descriptions are mostly just
  "Roadworks" or "Closed"; "Single alternate line traffic" (one direction at
  a time) is the only one that says traffic stops.
- **Kinds:** alternating traffic counts as stopping traffic (in `STOPPING`,
  like temporary signals); a closure (category 8) as a closure; plain
  roadworks as `roadworks`, traffic control not known: weight 1 on the stops
  scale (a bump), a quarter of a stopping work in the score. A lane closed
  with traffic flowing is not kept.
- **Asked once per drive request,** for a box round the start and finish
  (8 to 30 km margin, by the time asked), while the first candidates are
  routed; the answer is cached five minutes per area. Only with live
  routing; never from tests or the simulator.
- **On the drive** only if at least 30 m of it runs along the drive (a drive
  crossing a closed street at a junction is not on it), and for a closure
  only the way the drive goes (TomTom closes one direction at a time, and
  its own routes avoid closed roads). Both directions of the same works
  count once. In England a TomTom work within 60 m of a Street Manager one
  is dropped and Street Manager's record kept.
- **Card:** "B39: roadworks, traffic control not known", credited "Traffic
  incidents © TomTom". Privacy policy 1.9: TomTom receives the box.

Measured live after these rules: 30-minute drives from Edinburgh Waverley
listed 1 or 2 works each, Cardiff Central 0 or 1, Belfast 0 to 2; before the
crossing and direction rules, up to five each, mostly closed side streets
the drives only crossed.

## Other countries (planning, 12 Oct 2026)

Unverified unless marked. Each needs checking before any build.

| Where | Source | Format | Notes |
|---|---|---|---|
| Everywhere TomTom covers | **TomTom Traffic Incidents API** | JSON | Already on our key. Roadworks with location, delay, sometimes lane closures; not how traffic is controlled. The quickest worldwide baseline. |
| EU and EEA | **National Access Points** under the ITS Directive's real-time traffic rules | DATEX II (XML) | Each country publishes roadworks and closures, often with lane and traffic-control detail. One DATEX II reader covers many countries. |
| Germany | Mobilithek (national access point); Autobahn GmbH's public API for motorway works; cities such as Berlin (VIZ) | DATEX II, JSON | Motorway API is simple and public; urban works vary by city. |
| Netherlands | NDW open data | DATEX II | Detailed and open. |
| France | Bison Futé / transport.data.gouv.fr | DATEX II | |
| Scotland | Scottish Road Works Register | to check | Run by the Scottish Road Works Commissioner; open data access to check. |
| Northern Ireland | DfI Roads (TrafficwatchNI) | to check | |
| USA | **WZDx** (Work Zone Data Exchange) feeds from state DOTs, listed by the US DOT | GeoJSON | A national standard, with traffic control details in some feeds. |

**Proposed order:** TomTom incidents first (worldwide, no registration,
our existing key), then DATEX II (one reader, many European countries,
including Germany for Katya), then WZDx if there are users in the US.
Traffic lights and speed bumps already work anywhere OpenStreetMap maps
them: `tools/build_calming.py` builds any area.

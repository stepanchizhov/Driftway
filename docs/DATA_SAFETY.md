# Google Play Data safety: Driftway's answers

Reviewable answers for the Data safety form in Play Console, drawn from the
inventory behind `frontend/public/privacy.html` (version 1.3, 10 Oct 2026;
brought up to version 1.10, 17 Oct 2026: see the dated notes at the end).
That inventory was checked against the code: stored tables, device storage,
logs, and every outside host, which `tests/test_privacy_inventory.py` keeps
honest.

**Google's definitions** (Play Console Help, "Provide information for Google
Play's Data safety section", read 10 Oct 2026):

- **Collected** means "transmitting data from your app off a user's device".
  This includes data sent to a third party's server, even if never stored.
- **Shared** means "transferring user data collected from your app to a third
  party", except to a **service provider** that "processes it on behalf of
  the developer" and on its instructions. Such transfers are not sharing.
- **Processed ephemerally** means "accessing and using it while the data is
  only stored in memory", "retained for no longer than necessary to service
  the specific request in real-time". It must still be declared in the form,
  but is not shown on the store listing.
- Data **only processed on the device** is not collection.
- **Precise location:** "within an area less than 3 square kilometers".
  **Approximate location:** an area of 3 km² or more, including inferred
  location such as from an IP address.

The form's categories and wording change over time. Fill it in against the
form as it is on the day; these are the facts to answer with.

## Data types

| Play data type | Collected? | Shared? | Ephemeral? | Required or optional | Purposes | Driftway's facts |
|---|---|---|---|---|---|---|
| **Location: precise** | Yes | No (service providers) | Partly: drive, walk and search requests are processed in memory and discarded. Meetup starting points are stored | Optional for most features. Location access can be refused; a place can be searched instead | App functionality | Start points, checkpoints, destinations and the points of a route of your own (My walks, kept on the device) go to the server, then to TomTom or openrouteservice to route. Meetup origins are stored until the meetup expires (30 days after its date, or 60 days after creation), and never shown to the other parent |
| **Location: approximate** | Yes | No | No | Not avoidable | App functionality; security (rate limits) | IP addresses reach the server (rate limits, in memory for at most a day, not stored) and the hosting provider's request logs. The device fetches map images directly from OpenStreetMap. Fonts come with the app (0.8). Since 0.8.9, asking for walks where there are none stores a grid square about 10 km across with a request count, not linked to the person (the position itself is discarded). Since 0.8.14, TomTom receives a box round a drive's area, tens of kilometres across, to ask about roadworks |
| **Personal info: email address** | Yes | No (service provider: Auth0) | No | Optional (only to sign in) | Account management | Stored on the account only if Auth0 has verified it |
| **Personal info: name** | Yes | No | No | Optional | Account management; app functionality (meetups) | An optional display name for the account or a meetup |
| **Personal info: user IDs** | Yes | No | No | Optional (only to sign in) | Account management | The sign-in id from Auth0; a random device id for things saved without an account |
| **App activity: other user-generated content** | Yes | No | No | Optional | App functionality; analytics in the plain sense (improving the app) | Feedback messages, route feedback notes, meetup votes and comments. Feedback sent without an account is deleted after 365 days |
| **App activity: other actions** | Yes | No | No | Optional | App functionality | Saved drives, including the navigation link with its points |
| **App info and performance** | No | | | | | No crash or diagnostics reporting. The Feedback button sends only the app version and build with the message |

Not collected: financial information, health information, messages, photos
or videos, audio, files, calendar, contacts, web browsing, device or other
IDs (no advertising id). Pram and carrier details, and a child's weight,
stay on the device; they are sent with a walk request only to judge the walk,
and are not stored. Likewise the answers to "What wakes your little one?"
(0.8.15): kept on the device, sent with a drive request only to choose the
drive, not stored.

**Service providers** (not "sharing"): Render (hosting), Auth0 (sign-in),
TomTom (search, routes, travel times, and openrouteservice's stand-in for
walks), openrouteservice by HeiGIT (walks, and TomTom's stand-in). Each
receives only what its job needs.

**Opened by the user's choice**: Google Maps, Waze, Apple Maps. When the
parent opens a route there, the route's points travel in the link. Under
the definitions above that is the user's own action, not Driftway sharing,
but the privacy policy says so plainly.

## Security practices

- **Data encrypted in transit:** yes. HTTPS only (Render; providers over
  HTTPS).
- **Users can request deletion:** yes.
  - In the app: Settings, then Delete my account. This also works for a
    disabled account, with no invitation needed.
  - On the web, without the app:
    `https://driftway.stepan.chizhov.com/delete-account.html`. It works on
    the current origin too: `/delete-account.html`.
  - By email: stepan@ibookbinding.com.
- **What is kept after deletion**, and why (listed on that page):
  - the invitation record, unlinked from the person;
  - things saved on a device before signing in, which are not linked to any
    account;
  - the Auth0 sign-in, deleted on request;
  - the hosting provider's request logs, kept on its own schedule.
- **Independent security review:** no.
- **Families policy:** not applicable. The audience is adults (parents);
  the app is not designed for children.

## Account deletion declaration

- **App lets users create an account:** yes. Open to anyone since 11 Oct 2026 (`REGISTRATION_MODE=open`); invitations remain possible.
- **Delete-account web link:**
  `https://driftway.stepan.chizhov.com/delete-account.html`. It names the
  app and the developer (iBookBinding Ltd) as on the listing, and puts the
  deletion route first.

The domain went live on 10 Oct 2026: both URLs answer over HTTPS. The same
pages remain on `driftway-front.onrender.com`.

**0.8.19 (18 Oct 2026), logs:** found while making the tour video: the
HTTP client logged every outside request's full address at INFO, so the
hosting provider's logs held the points of drives, walks and searches sent to
TomTom and openrouteservice (and TomTom's key, sent in the address). It now
logs warnings only (`main.py`; `tests/test_beta_readiness.py`). The policy's
"these records never include ... positions" is true again from this release;
Render keeps logs for a limited time, so the older lines age out.

**0.8.18 (17 Oct 2026), maintainers' recorded drives:** accounts whose
email is in the server's MAINTAINER_EMAILS (the founder; later, anyone
maintaining Driftway) can turn on "Record my drives for analysis": each
drive request is stored for 30 days with its start and finish, the drives
offered and their routes. Not offered to other users, so it changes no
answer in the form; if it is ever offered beyond the team, declare it
(Location: precise, stored; App activity). In the export, erased with the
account. Also fixed: an account's email is stored only when Auth0 has
verified it, as this document already said; account creation had stored the
sign-in's address unverified. Privacy policy 1.10.

**0.8.14 (14 Oct 2026), roadworks outside England:** TomTom (already a
processor for drives) is asked for the roadworks in a box round a drive's
area, tens of kilometres across, once per request; nothing is stored beyond
a five-minute in-memory cache of the answer. Privacy policy 1.9.

**0.8.13 (13 Oct 2026), walks when openrouteservice struggles:** a walk's
start (and two points its loop passes) can go to TomTom instead, already a
processor for drives; nothing new is collected or stored. Pram walks never
use the stand-in. Privacy policy 1.8.

**0.8.9 (11 Oct 2026), walks for new areas:** a grid square about 10 km
across is stored when a parent asks for walks where there are none, with a
request count and nothing linking it to them; their position is used to
find the square and discarded. This is approximate location at most, and
not linked to an identity. Walk descriptions are written with AI by a
developer-side job from public map data only; no user data goes to it.


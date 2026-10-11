# Saved places

**IMPLEMENTED, 11 Oct 2026 (0.8.5).** Founder request: more places than Home.

## What a saved place is

Somewhere the parent deliberately keeps: Home, Swimming, Workshop. It is not
a saved drive (`Favourites`, server-side, account-owned), a meetup venue, a
walk in My walks, or the recent destination. None of those is converted into
a place, and places never expire: the six-hour recent-destination window and
its 24-hour ceiling (`lib/stillAsleepConfig.ts`) apply only to the recent
destination.

## Behaviour

- **Saved screen (★ Saved), Places:** add a place with a name and a location
  (address or postcode search, or "Where I am now"), edit its name or
  location, make it Home, remove it. Saving only keeps the place: nothing is
  routed and nothing opens.
- **Home:** at most one place is Home. Removing Home asks first and leaves no
  Home: no other place is promoted, so Still asleep and the quick drive home
  never send a parent somewhere they did not choose as home. "Save as Home"
  on Plan a drive moves Home, or adds it.
- **Where places appear:** Still asleep's targets (Home first, then the
  others, then a recent search while fresh); one-tap choices in every place
  search that picks the parent's own points: Plan a drive (start and
  destination), Still asleep's "Where are you now?", Walk (start and
  checkpoints) and Meet up (your own start only). Never offered as a meetup
  venue, which the other parent sees.
- **States:** an empty list says so; every change says whether it was kept on
  this device or, when the browser refuses storage, for this visit only.
  Never "saved" when it was not. An unreadable store is reported and left
  untouched until the parent saves.

## Storage and scope

- **This device, this web address only.** `localStorage`, key
  `driftway.places.v1` (the same key Home always used: an existing Home
  survives the upgrade unchanged). Not in the account: places do not appear
  on another phone, in another browser, or on Driftway Next, and signing in
  does not move them anywhere.
- **Why not the account:** the server's `saved_places` table exists from
  v0.2 but has never been read or written by the app, so there was no working
  account mechanism to reuse. Syncing places to an account is LATER; it would
  need export, deletion and an explicit move-to-account step like saved
  drives have.
- Names are trimmed and capped at 40 characters and shown as text, never as
  markup. Positions must be finite and on the globe. Nothing about places is
  logged; a place is sent to the server only as part of a route request,
  like any start or destination.
- Two saves with the same name within 25 m are one place (a double tap).
  Renaming or moving keeps the place's identity.

## Code

`frontend/src/lib/places.ts` (rules, tested in `places.test.ts`),
`hooks/usePlaces.ts` (storage, persistence result),
`components/PlacesManager.tsx` (the screen), `components/PlaceSearch.tsx`
(`saved` shortcuts), `hooks/useStillAsleepTargets.ts` (targets).

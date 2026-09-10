# NapLoop Claude Implementation Brief

## Meet Halfway / Playdate Finder - staging branch

**Date:** 10 September 2026  
**Revision:** 2 - add minimal user registry, invite-only beta registration, and scoped invitation capabilities  
**Priority:** Near-term staging experiment  
**Do not merge to production until founder test passes**

---

## 0. Read this first

Before changing code:

1. Read the repository’s current `CLAUDE.md`, `PROJECT_BIBLE.md`, environment/setup docs, and relevant API/router/provider modules.
2. Read the latest Route Modes handoff if present.
3. Confirm the deployed/current behaviour of Loop Mode, Destination Mode, address/place search, and Delayed Arrival.
4. Do not regress the existing routing modes while building Meet Halfway.
5. Prefer a feature flag and a staging-only entry point until this slice is usable.
6. Public registration must remain disabled during founder/alpha testing; stage the account/invitation architecture in `invite_only` mode.

### Current integration assumptions from the latest handoff

Treat these as facts to verify against the repo, not excuses to rewrite working code:

- Loop and Destination are explicit current route modes.
- Address/place search is proxied through the backend so the routing/search provider key stays out of the browser.
- Delayed Arrival already exists as a one-tap action rather than a third route mode.
- Routing/search are intended to remain usable even if persistence/storage is unhealthy.
- A prior production incident was caused by database initialization failing at import/startup time. Do **not** reintroduce that coupling.
- Meetup participation and ordinary routing should not require a registered account. Accounts add identity, persistence, entitlements, and convenience; they are not permission to expose location data.

If the repository differs, document the difference before modifying architecture.

---

## 1. Feature goal

Build the first staging version of **Meet Halfway / Playdate Finder**.

Two parents should be able to provide private starting locations and a meetup time, optionally express preferred/max drive times, discover 3–5 family-suitable meetup venues, compare real travel times, vote on the options, and share the results.

This is **destination discovery**, not a new route-generation mode.

In the same staging cycle, establish a minimal **user registry and invitation architecture**. Public signup remains closed. Founder/admin-issued beta invitations can create accounts, while meetup participant links continue to work for guests.

Once a venue is selected, each participant can use normal navigation. A participant may optionally invoke existing Delayed Arrival to make their own journey longer for a nap.

---

## 2. MVP product flow

### Organiser

1. Open **Meet Halfway** from staging.
2. Choose date/time.
3. Choose either:
   - one or more activity categories, or
   - **Explore ideas**.
4. Enter/select own start location.
5. Optionally enter:
   - preferred drive minutes;
   - tolerance;
   - maximum drive minutes.
6. Create meetup.
7. Receive a private participant invitation link.

### Invited parent

1. Open participant link.
2. Enter/select start location.
3. Set privacy:
   - `Hide my exact starting location from other participants` default **ON**.
4. Optionally enter preferred/tolerance/max drive values.
5. Submit.

### Results

Once enough participants exist:

1. Discover venue candidates.
2. Calculate actual journey time from every participant to every candidate.
3. Apply hard filters and rank candidates.
4. Display 3–5 options.
5. Allow each participant to vote:
   - Works for me
   - Could work
   - Too far
   - Not this venue
6. Re-rank or visibly update group fit.
7. Provide a separate **results share link**.
8. Allow normal navigation to the chosen venue.
9. If available, expose `Make my drive X minutes` using existing Delayed Arrival.

---

## 3. Do not overbuild chat

Do **not** build full messaging for this slice.

Implement structured voting. Optional short comments are acceptable only if they are trivial to add after voting works.

Add a share-to-system / copy-link action so parents can discuss the shortlist in WhatsApp, Messenger, etc.

Full chat is deferred because it creates unrelated moderation and notification work.

---

## 4. Data model

Use names that fit the existing project conventions. The shapes below are conceptual, not mandatory ORM syntax.

### UserAccount

Keep account identity separate from travel/location records.

```ts
interface UserAccount {
  id: string
  authProvider?: string | null
  authSubject?: string | null
  email?: string | null // private; never group-facing
  displayName?: string | null
  status: 'active' | 'disabled'
  createdAt: string
  lastActiveAt?: string | null
  planKey?: string | null
  defaultHideExactOrigin: boolean
}
```

Do **not** add exact home coordinates, child identity fields, or meetup origin history to this record.

### BetaAccessInvite

```ts
interface BetaAccessInvite {
  id: string
  tokenHash: string
  createdByUserId?: string | null
  createdByAdmin: boolean
  createdAt: string
  expiresAt: string
  acceptedAt?: string | null
  acceptedByUserId?: string | null
  revokedAt?: string | null
  boundEmail?: string | null
}
```

The raw token is shown only when created/accepted; store a hash where practical.

### SavedPlace (later / optional)

If the repo already has saved Home/location support, keep it separate from `UserAccount` and preserve existing semantics. Any new account-linked saved place must be explicitly opted in.

```ts
interface SavedPlace {
  id: string
  userId: string
  label: string
  lat: number
  lng: number
  createdAt: string
  updatedAt: string
}
```

Do not automatically create SavedPlace rows from meetup origins.

### MeetupSession

```ts
interface MeetupSession {
  id: string
  publicResultsSlug: string
  createdAt: string
  updatedAt: string
  scheduledAt: string | null
  mode: 'filtered' | 'explore'
  requestedCategories: string[]
  status: 'collecting' | 'ready' | 'decided' | 'expired'
  selectedVenueId?: string | null
  regionCode: string
  ownerParticipantId: string
  ownerUserId?: string | null
}
```

### Participant

```ts
interface MeetupParticipant {
  id: string
  meetupId: string
  joinToken: string
  userId?: string | null
  displayName?: string | null

  // Exact coordinate is server-side routing input.
  startLat: number
  startLng: number

  // Safe display fields shown to other participants.
  localityLabel?: string | null
  displayLat?: number | null
  displayLng?: number | null
  hideExactOrigin: boolean

  preferredMinutes?: number | null
  toleranceMinutes?: number | null
  maxMinutes?: number | null

  createdAt: string
  updatedAt: string
}
```

### VenueCandidate

```ts
interface MeetupVenueCandidate {
  id: string
  meetupId: string
  provider: string
  providerVenueId: string
  name: string
  lat: number
  lng: number
  addressLabel?: string | null
  canonicalCategories: string[]
  providerRating?: number | null
  providerReviewCount?: number | null
  openingStatus: 'open' | 'closed' | 'unknown'
  suitability: 'allowed' | 'conditional'

  // Calculated by NapLoop.
  participantTravel: ParticipantTravel[]
  fairnessSpreadMinutes: number
  totalTravelMinutes: number
  maxTravelMinutes: number
  score: number
  scoreBreakdown: Record<string, number | string | boolean>
}
```

### ParticipantTravel

```ts
interface ParticipantTravel {
  participantId: string
  directMinutes: number
  preferredDeltaMinutes?: number | null
  exceedsMaximum: boolean
}
```

### VenueVote

```ts
type VoteValue = 'works' | 'maybe' | 'too_far' | 'not_this_venue'

interface MeetupVote {
  meetupId: string
  venueCandidateId: string
  participantId: string
  value: VoteValue
  comment?: string | null
  createdAt: string
  updatedAt: string
}
```

### Entitlements

Do not scatter paywall conditionals through components.

Create or extend a single entitlement layer, e.g.:

```ts
interface FeatureEntitlements {
  meetHalfway: boolean
  maxMeetupParticipants: number
  maxVenueCandidates: number
  advancedMeetupFilters: boolean
  advancedExplore: boolean
  savedMeetupGroups: boolean
  popularityInsights: boolean
}
```

For staging, enable the feature and keep restrictions generous/unlocked unless existing billing architecture requires otherwise.

---

## 5. Identity, registration gate, and invitation architecture

This section is part of the near-term staging work, not a distant account-system redesign.

### 5.1 Registration modes

Add one server-authoritative registration setting/feature flag, adapting naming to project conventions:

```ts
type RegistrationMode = 'closed' | 'invite_only' | 'open'
```

For staging/founder testing use:

```txt
REGISTRATION_MODE=invite_only
```

Requirements:

- `closed`: no account creation, even with an invite;
- `invite_only`: account creation requires a valid unused beta-access invitation;
- `open`: normal registration can be enabled later;
- hiding/showing frontend buttons is not sufficient; enforce this server-side.

### 5.2 Do not build password auth

First inspect the repository for an existing auth/session provider.

- If one exists, integrate the account registry and invite gate with it.
- If none exists, do **not** invent a password database or password-reset system.
- Introduce a small provider-agnostic auth/session boundary and report the viable managed-auth choices before selecting a production provider.
- It is acceptable for the first staging slice to generate/administer beta-access links before email delivery exists. The founder can share the link manually.

If a temporary staging session mechanism is required, keep it explicitly staging-only, use secure HttpOnly cookies, and document how it will be replaced by the production auth provider.

### 5.3 Separate capability types

Implement/prepare three distinct capability classes. Do not reuse one token/slug for multiple scopes.

1. **Beta access invite**
   - allows account activation/creation only;
   - single-use by default;
   - expiring and revocable;
   - high entropy;
   - optionally email-bound later.

2. **Meetup participant invite**
   - allows guest participation in one meetup;
   - does not require account creation;
   - scoped to the participant’s allowed writes (origin/preferences/votes), not organiser/admin actions.

3. **Results link**
   - read-only;
   - privacy-safe serialization only;
   - cannot edit participant or meetup state.

Never place email, exact coordinates, or meaningful sequential IDs inside these raw tokens.

### 5.4 Guest participation and account claiming

`MeetupParticipant.userId` must be nullable.

A person opening a meetup invitation may participate as a guest. Do not force a signup wall into the collaboration funnel.

Later/next increment, support linking/claiming a guest participant to a registered account after authentication. Linking must not change that participant’s existing per-meetup `hideExactOrigin` choice.

### 5.5 Account privacy/data minimization

The registry is for identity, security, entitlements, and explicit saved preferences.

Do not:

- copy meetup origins into the user table;
- infer/save Home from repeated meetup starts;
- expose login email to other meetup members;
- include exact locations in analytics;
- make registration consent equivalent to location-sharing consent.

If location history or saved places are added later, they need an explicit user action and independent deletion controls.

### 5.6 Admin/founder invitation controls for staging

Provide the smallest workable admin path to:

- create a beta-access invite;
- set expiry;
- copy/share the invite URL;
- list minimal invite status (unused/accepted/expired/revoked);
- revoke an unused invite.

This may initially be a protected CLI/admin endpoint rather than a polished admin UI. Do not delay founder testing for admin chrome.

### 5.7 Account invitations are not the meetup invitations

UI copy must distinguish them clearly. Suggested concepts:

- `Invite to NapLoop beta`
- `Invite parent to this meetup`
- `Share results`

Do not label all three merely `Invite`.

### 5.8 Entitlement relationship

Account identity should be the stable anchor for future plan/entitlement checks, but do not introduce a production paywall now.

Basic meetup joining, privacy controls, voting, and read-only result sharing must continue to work without Premium. During invite-only testing, beta access itself is not a paid entitlement.

---

## 6. Persistence and outage isolation

Meet Halfway share links and votes require persistence. However, **storage failure must not take routing/search down**.

### Required rule

- Existing `/api/generate`, `/api/search`, and health/routing endpoints must continue working if meetup storage fails.
- Meetup endpoints that require storage may return a clear `503 meetup_storage_unavailable`.
- Never initialize a required DB connection at module import time in a way that can prevent the API app from starting.
- Health output should report meetup storage separately.

If the current repository already has a storage abstraction, use it. Otherwise, introduce the smallest provider-independent repository interface necessary for meetup sessions, participants, votes, and cached candidates.

Do not choose a new hosted DB provider in this task unless the current staging environment genuinely cannot persist meetup data. If provider choice is needed, stop and present options before adding infrastructure.

---

## 7. Privacy rules

These are product requirements, not polish.

### Exact origins

- Registered account status does not change origin privacy.
- Store/use exact origin only for routing.
- Do not send another participant’s exact start coordinate to the browser.
- Default `hideExactOrigin = true`.
- Results responses should expose `localityLabel` plus coarse display coordinates when hidden.
- Do not embed exact origins in share URLs.
- Do not derive a displayed route polyline from a hidden home point if another participant can inspect it.

### Coarse convergence display

For hidden origins, use one of:

- provider locality centroid;
- geohash/grid centroid at an agreed coarse precision;
- deterministic coarse jitter inside the locality.

Do not implement the convergence map in the first slice unless candidate planning already works. Prepare the response model so it can be added without exposing exact coordinates.

### Results sharing

Create two capabilities:

1. `joinToken`: private write capability for a participant.
2. `publicResultsSlug` or equivalent: read-only results capability.

Do not use one universal token for both.

---

## 8. Internal activity taxonomy and family-safe filtering

Do not depend on raw provider category names throughout the app.

Create a canonical category registry such as:

```ts
type PlaydateSuitability = 'allowed' | 'conditional' | 'blocked' | 'unknown'

interface CanonicalActivityCategory {
  id: string
  label: string
  suitability: PlaydateSuitability
  exploreEligible: boolean
  providerMappings: Record<string, string[]>
}
```

Seed a small UK-focused taxonomy for staging.

### Initial allowed categories

Examples:

- play_cafe
- soft_play
- playground
- park
- childrens_farm
- swimming
- leisure_centre
- library
- museum_family
- discovery_centre
- family_cafe
- garden_attraction

### Conditional categories

Examples:

- restaurant_family
- pub_family
- general_cafe
- attraction_general

Only include conditional categories when family suitability can be positively inferred or the user explicitly chose them.

### Blocked categories

Map provider categories representing clearly age-restricted or inappropriate playdate destinations to blocked. Include adult entertainment, adult-only nightlife, gambling-led venues, substance/smoking-led venues, and other clearly age-restricted categories.

**Unknown categories must not enter Explore automatically.**

Use a positive allowlist plus explicit blocks. Do not rely on substring filtering alone.

---

## 9. Candidate discovery

Implement the simplest method that works with the current provider abstraction.

### Stage A: define a practical search region

For two participants:

1. obtain participant origins;
2. estimate direct travel-time relation between them if useful;
3. choose one or more search centres around the time-weighted corridor / midpoint region;
4. expand search radius if too few safe candidates are found.

Do not use geometric midpoint as the final ranking criterion. It is merely a candidate-discovery hint.

For >2 participants later, use centroid/isochrone overlap or sampled search centres.

### Stage B: discover POIs

Use the provider’s POI/category search through the backend.

- Filtered mode: search only mapped requested categories.
- Explore mode: query several allowlisted category groups and deliberately diversify the returned set.
- Deduplicate provider duplicates by provider ID and spatial/name similarity.
- Apply opening-time filtering if the provider supplies sufficiently reliable data.

If the current `/api/search` endpoint cannot efficiently support category/nearby discovery, add a meetup-specific backend search method behind the same provider abstraction rather than hacking the UI to issue many fuzzy text queries.

### Stage C: calculate actual travel times

For every participant × venue candidate, obtain traffic-aware direct journey minutes using the routing provider.

Use a matrix API if the current provider supports it economically and the abstraction is clean. Otherwise batch ordinary route calls carefully.

Log provider-call counts for each meetup generation. API cost is part of the experiment.

---

## 10. Ranking algorithm v0

Do not pretend the first score is mathematically final. Make the score breakdown inspectable.

### Hard constraints

For each venue:

- if any participant has `maxMinutes` and the route exceeds it, mark a hard violation;
- closed venue at scheduled time -> reject when opening data is confident;
- blocked/unknown Explore category -> reject;
- required filter failure -> reject.

If every venue violates a maximum, do not silently ignore it. Return a structured fallback state and let the UI ask whether the group wants to widen/relax constraints.

### Derived values

```txt
spread = max(directMinutes) - min(directMinutes)
maxBurden = max(directMinutes)
totalBurden = sum(directMinutes)
preferredPenalty = sum(abs(directMinutes - preferredMinutes) / toleranceScale)
```

Do not use percentage fairness as the primary metric.

### Suggested score ordering

Prefer lexicographic/gated ranking in v0 over one magical weighted number:

1. zero hard-max violations;
2. lowest count/amount of hard violations if fallback is explicitly allowed;
3. best preferred-duration fit;
4. lower maximum burden;
5. lower absolute spread;
6. lower total burden;
7. category/suitability quality;
8. opening-hours confidence;
9. provider rating confidence;
10. community/popularity signal when available;
11. current group votes.

This ordering should be configurable and logged.

### Important UX rule

Always show absolute minutes per participant. Never show only a fairness label.

Example:

```txt
Play Cafe A
Stepan: 27 min
Sam:    31 min
Spread: 4 min
Group fit: Very even
```

For longer trips:

```txt
Venue B
Parent A: 90 min
Parent B: 120 min
Spread: 30 min
Group fit: Significant difference
```

Do not hide the burden behind “67% similar” or equivalent.

---

## 11. Voting and collaborative re-ranking

Implement one vote per participant per venue.

Values:

- `works`
- `maybe`
- `too_far`
- `not_this_venue`

### Initial vote effect

- `works`: positive group-fit signal.
- `maybe`: small/neutral signal.
- `too_far`: strong negative for that participant.
- `not_this_venue`: strong negative independent of journey time.

Do not permanently mutate the participant’s max/preferred settings when they vote `too_far`.

Optional later affordance:

> “Would you like to set a maximum drive time so we avoid similar options?”

### No forced consensus

If every candidate has a blocker, offer:

- widen search;
- relax venue category;
- relax fairness target;
- change max-drive limits;
- Explore different activities.

---

## 12. Explore mode v0

Explore is part of staging, not deferred.

Its job is to return **different kinds of plausible activities**.

### Diversity rule

Do not let one provider category dominate all result slots.

For 5 candidates, aim for category diversity where supply exists. Example:

- 1 soft play
- 1 park
- 1 play/family cafe
- 1 museum/discovery venue
- 1 farm/garden/activity attraction

If supply is limited, repeat categories rather than returning low-quality or unsafe options.

### Premium architecture

Basic Explore should be implemented behind an entitlement flag even if unlocked in staging.

Do not build Premium-only exploration logic yet. Leave room for future themes/advanced filters.

---

## 13. Popularity and NapLoop signals

Prepare event instrumentation now, but do not build a complex recommendation system yet.

### Suggested anonymous/aggregate events

- meetup_candidate_impression
- meetup_candidate_selected
- meetup_navigation_started
- meetup_vote_submitted
- meetup_result_shared
- meetup_category_selected
- meetup_explore_used
- meetup_completed_feedback (later)

Never include exact home coordinates in analytics payloads.

### Popularity data model

If the current analytics/storage architecture makes this easy, store enough to aggregate by venue/provider ID and locality:

- impressions;
- shortlist appearances;
- selections;
- navigation starts;
- works/maybe/negative votes;
- distinct meetup-group count;
- last-seen timestamp.

### Display rules for later

Do not modify the provider’s star rating.

Future card signals should remain separate, e.g.:

```txt
4.6 ★ provider rating
Popular on NapLoop
86% group approval
```

Do not expose popularity until a minimum distinct-group threshold exists. Use a configurable threshold, starting experimentally around 5–10 groups.

Account for ranking/impression bias before treating raw selection count as quality.

---

## 14. Free vs Premium implementation posture

Do not finalize the commercial split in code.

### Must remain free/non-paywalled

- account privacy/security controls;
- guest acceptance of a basic meetup invitation;
- beta access while the product is explicitly running a closed invite-only test;
- privacy controls;
- family-safe category filtering;
- basic invitation link;
- basic results link;
- participant journey-time visibility;
- basic voting.

### Staging entitlement hypotheses

Create flags/caps for:

- max participant count;
- max candidate count;
- advanced filters;
- advanced Explore;
- saved groups;
- recurring meetups;
- popularity insights;
- additional re-planning / expensive API operations.

Keep staging permissive so founder tests are not blocked by artificial plan limits.

Instrument feature usage so product decisions can be evidence-based later.

---

## 15. API surface proposal

Adapt paths to current conventions.

### Beta access / registration

Adapt paths to existing auth conventions, but keep semantics distinct.

```http
POST /api/admin/beta-invites
GET  /api/admin/beta-invites
POST /api/admin/beta-invites/{inviteId}/revoke
POST /api/auth/accept-beta-invite
GET  /api/auth/me
POST /api/auth/logout
```

Admin endpoints must be protected. `accept-beta-invite` must enforce `REGISTRATION_MODE` and invite validity server-side.

If a managed auth provider is not yet selected, the staging implementation may stop at a provider-independent account/invite service plus documented integration seam rather than inventing password auth.

### Create meetup

```http
POST /api/meetups
```

Request:

```json
{
  "scheduled_at": "2026-09-12T10:30:00+01:00",
  "mode": "explore",
  "categories": [],
  "organiser": {
    "start": {"lat": 51.48, "lng": -0.61},
    "hide_exact_origin": true,
    "preferred_minutes": 35,
    "tolerance_minutes": 10,
    "max_minutes": 50
  }
}
```

Response should include organiser capability plus participant invitation link/token and results slug, without returning sensitive tokens to unrelated clients.

### Join/update participant

```http
POST /api/meetups/{meetupId}/participants/{joinToken}
```

### Generate candidates

```http
POST /api/meetups/{meetupId}/candidates
```

Return candidates with participant travel times, score breakdown, opening/suitability metadata, and privacy-safe participant labels.

### Vote

```http
PUT /api/meetups/{meetupId}/votes/{candidateId}
```

Authenticated/capability-scoped by participant token.

### Public results

```http
GET /api/meetups/results/{publicResultsSlug}
```

Read-only, privacy-safe. Never include exact origins or join tokens.

### Select venue

```http
POST /api/meetups/{meetupId}/selection
```

Owner or group rule TBD. For staging, organiser can make the final selection after votes.

---

## 16. Frontend staging screens

Keep the number of screens small.

### Beta access / account entry

For staging:

- no public Sign up CTA;
- a valid beta-access URL can enter the account activation flow;
- signed-in users can see minimal account state;
- meetup guest links bypass the account activation requirement.

### Screen 1: Create meetup

- date/time
- Filtered / Explore segmented control
- category chips when Filtered
- own start picker
- preferred / max drive optional controls
- Create & invite

### Screen 2: Join meetup

- meetup summary
- start picker
- hide exact location checkbox ON
- optional preferred / max drive
- Join

### Screen 3: Candidate results

Each card:

- venue name/type
- provider rating if present
- opening status
- every participant’s journey minutes
- absolute spread
- simple group-fit label
- votes
- Works / Maybe / Too far / Not this venue controls for the current participant
- map/navigation action

Top-level controls:

- Share results
- Show more / widen search when needed
- Change activity type / Explore

### Screen 4: Selected venue

- agreed destination
- participant journey times
- normal Navigate button
- if Delayed Arrival is available: `Make my drive…`

Do not build the convergence map until these screens work.

---

## 17. Delayed Arrival integration

After a venue is chosen, use the existing Destination/Delayed Arrival flow rather than duplicating detour logic.

Pass the selected venue as the destination and let the participant choose a desired total travel time.

Do not calculate group fairness using padded routes by default.

Later, an advanced participant preference may ask Meet Halfway to optimize against a desired drive duration from the outset. The data model above already supports `preferredMinutes` for that purpose.

---

## 18. Test plan

Add unit and integration tests without weakening existing route-mode tests.

### Registry / beta invitations

- `invite_only` rejects account creation without a valid beta invite;
- valid invite can create/activate exactly one account;
- used, expired, and revoked invites are rejected;
- registration gate is enforced server-side;
- public signup path is absent/disabled in staging;
- login email never appears in meetup/results payloads;
- meetup participant can remain `userId = null`;
- guest participation still works when account registration is closed/invite-only;
- linking a guest to an account does not alter location-sharing consent;
- beta access token, meetup join token, and results capability are not interchangeable.

### Privacy

- hidden participant exact coordinate never appears in public results JSON;
- join token never appears in public results;
- public results link cannot edit participant data;
- locality/coarse coordinate is returned when exact origin is hidden.

### Fairness

- 25 vs 28 ranks as more even than 25 vs 40, all else equal;
- 90 vs 120 is labelled/treated as a 30-minute spread, not a small relative difference;
- explicit `maxMinutes=30` rejects a 35-minute candidate;
- preferred 40 with max 55 can rank 43 minutes above 25 minutes when other constraints permit;
- no max -> candidate remains possible and is shown transparently.

### Fallback

- if no candidate fits all maxima, return a structured no-fit state;
- widening search or relaxing constraints produces alternatives rather than a generic failure.

### Categories

- blocked category cannot appear in Explore;
- unknown category cannot appear in Explore;
- conditional family-pub category requires positive suitability signal or explicit user selection;
- Explore diversity does not fill all cards with one category when diverse supply exists.

### Voting

- `too_far` lowers candidate group fit;
- `not_this_venue` is distinguished from travel-time rejection;
- votes from one meetup cannot affect another;
- vote update is idempotent/upserted per participant/candidate.

### Storage isolation

- failed meetup storage returns 503 for persistence-dependent meetup endpoints;
- existing routing/search endpoints remain healthy;
- app startup does not fail because meetup storage is unavailable.

### Existing product regression

Run all current tests for Loop, Destination, search, and Delayed Arrival.

---

## 19. Logging / observability

For every candidate-generation request log, without exact origins in ordinary logs:

- meetup ID;
- participant count;
- activity mode/categories;
- number of raw POIs;
- number rejected by safety taxonomy;
- number rejected by opening status;
- route/matrix provider call count;
- candidate count before/after hard constraints;
- final spread / max burden / total burden per result;
- generation latency;
- fallback reason if fewer than requested candidates.

Avoid logging addresses, exact lat/lng, emails, auth session secrets, beta-access raw tokens, join tokens, or results capability tokens.

For beta-access events, log only invite ID/status and account ID where appropriate, never the raw token.

---

## 20. Recommended implementation sequence

### Milestone 1 - identity + architecture skeleton

- registration-mode setting (`invite_only` in staging)
- minimal user/account domain model
- beta-access invite model/service
- protected founder/admin invite create/list/revoke path
- no public signup
- auth-provider boundary; do not build password auth
- meetup feature flag / staging entry
- meetup domain types
- repository interface
- create/join/read endpoints
- privacy-safe serializers
- storage outage isolation tests

### Milestone 2 - two-parent planner without sharing polish

- two participant origins
- guest participant support (`userId` nullable)
- filtered category mode
- POI discovery
- participant × candidate travel times
- fairness scoring
- 3–5 candidate cards

Founder can test this before share links are beautiful.

### Milestone 3 - collaboration capabilities

- meetup participant invitation link
- read-only results link
- strict capability separation
- structured voting
- re-ranking / group-fit display

### Milestone 4 - Explore

- canonical taxonomy
- provider mapping
- family-safe allowlist/block rules
- category-diverse Explore results

### Milestone 5 - selected venue + Delayed Arrival handoff

- final selection
- normal navigation
- `Make my drive X minutes` integration

### Milestone 6 - account convenience + instrumentation groundwork

- optional guest-to-account claim/link seam
- aggregate events
- venue popularity counters
- account-linked saved preferences only where explicitly opted in
- no public popularity badge until minimum sample threshold is reached

### Deferred

- open public registration
- polished admin/invitation dashboard
- automated invitation email delivery if not already available
- convergence map
- full comments/chat
- saved/recurring groups
- 3+ participant UX polish
- production paywall
- sophisticated community recommendation model
- additional countries

---

## 21. Definition of done for staging alpha

Do not call the feature ready merely because endpoints exist.

It is ready for founder testing when:

1. Staging registration is server-side `invite_only`; public account creation without an invite fails.
2. Founder/admin can create, copy, inspect status, and revoke a beta-access invitation.
3. A valid beta-access invite can create/activate a minimal account without exposing private account identity to meetup peers.
4. A meetup invitee can still participate as a guest without creating an account.
5. Two real parents can join the same meetup from separate devices.
6. Neither needs to reveal an exact address to the other.
7. At least 2 plausible safe venues are returned in a realistic UK test area when provider data allows.
8. Each candidate clearly shows both journey times.
9. A stated maximum drive time is respected.
10. A preferred drive time can influence ranking without becoming a hard ban.
11. Explore returns genuinely different activity types when supply permits.
12. Both parents can vote and see the group result.
13. A read-only results link can be shared.
14. Existing Loop/Destination/Delayed Arrival behaviour and tests still pass.
15. Meetup-storage failure does not break ordinary route generation or search.
16. The selected venue can be opened in navigation and, when available, passed to Delayed Arrival.

---

## 22. What to report back after implementation

When the staging slice is complete, report:

1. files changed;
2. account/auth approach and whether a managed provider was already present;
3. registration-mode implementation and current staging value;
4. beta-access invite lifecycle and admin workflow;
5. migrations/storage changes;
6. API endpoints added;
7. category mappings added;
8. scoring algorithm and configurable values;
9. privacy decisions and how exact coordinates are prevented from leaking;
10. provider call count for a typical 2-parent search;
11. new tests and full test results;
12. staging URL and exact founder test steps;
13. known limitations;
14. open decisions that need a product call rather than an engineering guess.

Do not silently choose a production auth provider, a production paywall split, a new paid infrastructure provider, or a full-chat architecture. Surface those decisions explicitly.

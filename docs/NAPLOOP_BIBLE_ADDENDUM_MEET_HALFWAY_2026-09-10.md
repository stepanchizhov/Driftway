# NapLoop Project Bible Addendum

## Meet Halfway / Playdate Finder

**Status:** Near-term staging feature  
**Date:** 10 September 2026  
**Revision:** 2 - identity registry, closed-beta access invitations, and account/privacy architecture  
**Target Bible version:** v0.3 candidate  
**Relationship to current product:** Destination discovery + collaborative planning, not a third route mode

---

## 1. Product decision

**DECISION:** Move **Meet Halfway / Playdate Finder** forward from the distant roadmap into a near-term staging feature. It can be developed and tested in parallel while Loop Mode, Destination Mode, and Delayed Arrival continue to be exercised.

Meet Halfway solves a different question from the existing route modes:

> “Where should several parents meet so that the journey is practical and reasonably fair for everyone?”

The output is a **destination first**, followed by ordinary navigation or NapLoop’s existing Delayed Arrival logic for each participant.

The feature must not be reduced to finding a geometric midpoint. The core optimization variable is **travel time**, because equal physical distance can produce very unequal journeys.

---

## 2. Core use case

Two or more parents want to arrange a playdate. Each parent supplies a starting location, either directly in the initiating parent’s planner or privately through an invitation link.

The group can:

- choose a type of venue, such as a play cafe, soft play, park, children’s farm, swimming/leisure centre, library, museum, cafe with a play area, or another family-suitable activity;
- choose **Explore** instead of a fixed venue type and let NapLoop suggest different kinds of activities available within the practical overlap of the group;
- optionally specify a preferred drive duration;
- optionally specify a maximum acceptable drive duration;
- review several destination candidates with journey times for every participant;
- vote on whether each destination and journey works for them;
- share the current results through a separate results link;
- use Delayed Arrival individually if a suitable venue is too close for one child’s desired nap window.

Example:

- Parent A prefers about 40 minutes of driving because the child needs a nap.
- Parent B prefers no more than 25 minutes.
- Parent C has no preferred duration but sets a hard maximum of 45 minutes.

The best venue is not necessarily equidistant. The best venue is the one that produces the strongest overall fit to the participants’ **individual practical constraints**.

---

## 3. Fairness is not symmetry

**DECISION:** Do not rank candidates using relative percentage difference alone.

A five-minute difference is often negligible. A thirty-minute difference may be acceptable to one parent and a dealbreaker to another. Likewise, 90 vs 120 minutes should not be described as “fair enough” merely because both journeys are long.

The ranking system should therefore distinguish:

1. **Hard practicality**: Does any participant exceed a stated maximum travel time?
2. **Personal fit**: How far is each journey from that participant’s preferred drive duration, if one exists?
3. **Absolute fairness**: What is the largest minute difference between participants?
4. **Total burden**: How much combined driving does the group do?
5. **Venue quality and suitability**: Is the destination actually worth meeting at?

### Participant travel preferences

Each participant may optionally specify:

- **Preferred drive:** e.g. around 40 minutes.
- **Comfort tolerance:** e.g. ±10 minutes.
- **Maximum drive:** e.g. 55 minutes.

**DECISION:** A stated maximum is a hard constraint unless the participant later changes it. Preferred duration is a soft constraint.

If no maximum is supplied, NapLoop should not invent one. Instead, it should show the trade-off clearly and allow the participant to vote.

### Graceful fallback

If no good candidates satisfy the initial fairness target, NapLoop should widen the search and explain the compromise rather than returning nothing.

Example:

> No suitable places keep everyone within 5 minutes of each other. Here are the best options with a 10–15 minute spread.

The interface should show absolute journey times prominently so the group can judge whether the difference matters to them.

---

## 4. Collaborative decision-making

**DECISION:** Collaboration is part of the value proposition, not an optional social layer to bolt on much later.

For each candidate, participants should be able to express a structured response such as:

- **Works for me**
- **Could work**
- **Too far**
- **Not this venue**

A participant who selects **Too far** may optionally adjust their maximum drive time or explain the constraint in a short note.

### Discussion

**HYPOTHESIS:** Do not build a full in-app chat initially. Full chat creates moderation, notification, abuse-reporting, retention, and privacy work that does not improve the route algorithm.

The first social layer should use structured voting plus an optional short comment. A share-to-WhatsApp/Messenger action can cover free-form conversation externally.

If repeated testing shows parents need discussion inside NapLoop, threaded comments can be evaluated later.

### Re-ranking after votes

Votes should be capable of changing the ranking:

- a candidate marked **Too far** by one participant should fall sharply;
- a candidate marked **Not this venue** by one participant should be treated as unsuitable for consensus unless the group explicitly overrides it;
- candidates with broad **Works for me** approval should rise;
- if all current candidates fail, NapLoop should offer to widen the search rather than forcing agreement.

---

## 5. Two kinds of share link

**DECISION:** Meet Halfway needs two distinct share flows.

### A. Participant input link

The organiser sends a private invitation link. The recipient can enter:

- starting location;
- optional display name;
- preferred drive duration;
- optional comfort tolerance;
- optional maximum drive duration;
- relevant activity preferences;
- location-sharing privacy choice.

The organiser does not need to know the exact address for routing to work.

### B. Results link

A separate link presents the current candidate venues, journey times, votes, and group trade-offs.

The results link must never expose a participant’s exact origin unless that participant explicitly chose to share it.

**DECISION:** Results sharing is a core collaborative feature and should not be paywalled.

---

## 6. User registry, closed-beta access, and invitations

**DECISION:** Introduce a minimal user/account registry sooner rather than later, but design it as an **identity and entitlement layer**, not as a repository of family/location history.

NapLoop needs stable users for saved preferences, future subscriptions, reusable groups, moderation/account controls, and community features. That can coexist with the privacy principles above if identity data and sensitive travel/location data are kept deliberately separate.

### Registration posture during testing

**DECISION:** Public self-registration should remain closed while the product is in founder/alpha testing. The staged system should support an explicit registration mode such as:

- `closed` - no new accounts;
- `invite_only` - only valid beta-access invitations can create an account;
- `open` - normal registration, for a later launch phase.

Staging should run in `invite_only` mode. The restriction must be enforced server-side, not merely by hiding a Sign up button.

**DECISION:** Invite-only beta access is an operational/testing gate, not a Premium feature or a permanent social hierarchy.

### Minimal account record

The registry should contain only what NapLoop actually needs, for example:

- stable internal user ID;
- private authentication identity (provider subject and, if required, email);
- optional display name;
- account creation / last-active timestamps;
- account status;
- current entitlement/plan flags;
- beta-invite provenance for abuse/debugging;
- optional default privacy/preferences chosen by the user.

**DECISION:** Do not put exact home coordinates, routine origins, children’s names, children’s dates of birth, or meetup travel history into the core user record.

If a user later chooses **Save Home** or another saved place, treat that as a separate, explicitly opted-in data object with its own retention/deletion rules. A user account must not silently become a location dossier.

### Authentication posture

**DECISION:** Do not build or store NapLoop-specific passwords ourselves. Prefer a managed identity mechanism such as passwordless email/magic link, passkey, OAuth, or another established authentication provider once the implementation stack is chosen.

If the current repository has no authentication provider, the engineering task should first create a provider-agnostic auth/account boundary and surface the provider choice rather than quietly inventing a password system.

Email, if used for login, is private account data. It must never become the participant display name by default and must never appear in meetup/result payloads for other users.

### Three different invitation/share capabilities

NapLoop now has three conceptually separate links. They must remain separate in UX, permissions, token scope, and analytics:

1. **Beta access invitation** - allows a person to create/activate a NapLoop account while registration is invite-only.
2. **Meetup participant invitation** - allows a person to contribute a private start point/preferences and participate in that meetup.
3. **Results link** - read-only access to the privacy-safe shortlist/results.

A future referral link may exist, but it should not be conflated with any of these.

### Beta access invitations

For testing, founder/admin users should be able to create a shareable beta-access invitation without requiring an email-sending system.

The invitation should be:

- high-entropy and unguessable;
- single-use by default;
- expiring;
- revocable before acceptance;
- recorded as accepted/expired/revoked rather than deleted without trace;
- optionally bound to an email later, but not dependent on email for the first staging implementation.

Later, trusted users may receive a limited number of beta invitations, but invitation quotas are an experiment, not a launch decision.

### Meetup participation must remain low-friction

**DECISION:** A person receiving a **meetup participant invitation should not be forced to create a full NapLoop account** merely to submit their location/preferences or vote in one playdate.

For the initial collaborative feature, a participant may remain a capability-scoped guest. If they later register, NapLoop may offer to claim/link that guest participation to their account.

This preserves virality and privacy while still allowing registered users to gain convenience features such as saved preferences, recurring groups, favourites, and history.

### Token/capability rules

All invitation/share links should use separate high-entropy tokens with the minimum necessary scope.

- beta-access token: account creation only;
- meetup join token: write only to the invited participant’s allowed meetup actions;
- results token/slug: read-only privacy-safe results;
- authenticated account session: normal user-owned actions.

Tokens must not contain email addresses, exact coordinates, account IDs that reveal sequence, or other sensitive data in clear text. Prefer storing only token hashes server-side where practical. Tokens should be revocable independently.

### User-facing privacy controls

Account registration does not change the existing meetup privacy default:

> Hide my exact starting location from other participants

should remain ON by default and should be evaluated **per meetup**, even if a user has a saved default preference.

**DECISION:** Registration must never imply consent to expose saved/home locations to other parents.

### Personalization and community signals

Registered users make useful personalization possible, but this should be progressive and transparent.

NapLoop may remember, with appropriate settings/consent:

- preferred activity categories;
- commonly chosen meetup areas at coarse locality level;
- favourite venues;
- typical preferred/max drive settings;
- groups the user explicitly saves.

Do not require user-level tracking merely to produce aggregate NapLoop popularity. Venue/category popularity can be aggregated without exposing individual behaviour, and exact home coordinates must never enter analytics payloads.

**LATER:** Provide account controls for reviewing/deleting saved places, saved groups, preferences, and history separately.

### Monetization relationship

**DECISION:** Privacy protections, receiving/accepting a basic meetup invitation, and basic results sharing must not be Premium-only.

A registered account can be the anchor for future entitlements, but registration itself should not be used to cripple the free collaborative loop. Premium may reasonably cover persistence/convenience around identity, for example richer saved groups/history, advanced personalization, larger recurring groups, and other power features already listed below.

---

## 7. Location privacy and the convergence map

**DECISION:** Exact participant starting locations are private by default in group-facing views.

The invitation form should include a clear control such as:

> ☑ Hide my exact starting location from other participants (recommended)

When enabled, NapLoop may still use the exact coordinate internally for routing, but other participants see only a coarse locality such as:

- Windsor area
- Wokingham
- North Slough

### Fun convergence view

**LATER / NEAR-TERM EXPERIMENT:** Show a map of participants converging on the chosen destination.

If a participant hides their exact start, their displayed origin must use a locality centroid, coarse area, or deliberately imprecise marker. The visual may be playful, but it must not leak a home address through map placement, route geometry, metadata, or URL parameters.

Exact-origin visibility must never be required for the feature to work.

**DECISION:** Privacy controls are never premium features.

---

## 8. Activity discovery and Explore mode

Meet Halfway should support two discovery paths.

### Filtered mode

The group chooses one or more activity categories before search.

Examples:

- play cafe / cafe with play area
- soft play / indoor play
- playground / park
- children’s farm / petting farm
- swimming / leisure centre
- library / story-time venue
- museum / discovery centre
- garden / outdoor attraction
- family-friendly restaurant or cafe
- toddler class / activity venue where source data supports it

### Explore mode

**DECISION:** Include a basic Explore mode in the initial staging feature.

Explore searches across several family-appropriate categories and returns a deliberately varied set rather than five versions of the same venue type.

Example output:

- indoor soft play
- riverside park
- children’s farm
- museum activity space
- play cafe

The goal is discovery, not randomness. Every suggestion must still satisfy opening-time, travel, safety-category, and basic suitability requirements.

---

## 9. Family-safe venue taxonomy

**DECISION:** Do not pass raw map-provider category results directly into Playdate Finder or Explore.

NapLoop should maintain an internal **canonical activity taxonomy** and map each provider’s categories into it.

Every mapped category should have a playdate-suitability state:

- `allowed`
- `conditional`
- `blocked`
- `unknown`

### Default behaviour

- `allowed`: eligible for Explore and filtered search.
- `conditional`: eligible only when supporting metadata indicates family suitability or the user explicitly selected the category.
- `blocked`: never surfaced in Playdate Finder.
- `unknown`: excluded from Explore until mapped or reviewed; may be considered only for an explicit named-place search after a suitability check.

### Categories to block by default

Examples include:

- adult entertainment and sexual-content venues;
- nightclubs and adult-only nightlife;
- gambling-led venues;
- cannabis / smoking / nicotine-led venues where present in source data;
- alcohol-led venues without a positive family-suitability signal;
- other clearly age-restricted destinations.

A family pub or restaurant with a play area can be treated as `conditional`, rather than losing useful family destinations simply because the provider’s broad category contains “pub” or “bar”.

**DECISION:** Use a positive family-suitable allowlist plus explicit blocks. A blacklist alone is too easy to evade through inconsistent provider taxonomies.

---

## 10. Provider rating, NapLoop popularity, and group fit

**DECISION:** Do not mathematically alter or relabel a map provider’s star rating.

Provider rating and NapLoop signals are different facts and should remain visually distinct.

A venue card may eventually show:

> 4.6 ★ provider rating · Popular on NapLoop · 86% group approval

or a separate NapLoop **Match** score that combines the app’s own signals while leaving the provider rating untouched.

### Signals NapLoop may learn from

Subject to consent, retention policy, and privacy thresholds, the product may aggregate:

- category impressions;
- candidate shortlists;
- venue selections;
- navigation starts;
- structured votes;
- optional post-visit ratings;
- repeat selections;
- saved favourites;
- locality-level popularity;
- time-of-day / day-of-week popularity where sample size supports it.

### Popularity is not quality

A frequently selected venue may simply be convenient or frequently ranked first. Therefore:

- do not call selection count a “rating”;
- distinguish **popular** from **highly rated**;
- account for impressions and ranking position before treating selection frequency as a strong signal;
- apply recency weighting so a once-popular venue does not remain permanently dominant;
- require a minimum number of distinct groups before displaying community popularity.

**HYPOTHESIS:** Start with a simple badge only after at least 5–10 distinct meetup groups have generated a meaningful signal for that venue/locality. Increase this threshold if privacy or statistical noise is a concern.

### Privacy rule for community signals

Never expose individual participants, home areas, exact origins, or identifiable visit histories through popularity statistics. Small-sample segmentation should be suppressed.

---

## 11. Suggested candidate score

The score is intentionally multi-part. It should not collapse every concern into one opaque number during early testing.

### Hard gates

Reject or heavily penalize candidates that:

- exceed a participant’s explicit maximum drive time;
- are closed at the intended meetup time;
- are in a blocked activity category;
- have an unusable/uncertain location;
- violate a required filter such as accessibility when marked mandatory.

### Ranking layers

For remaining candidates, consider:

1. maximum participant burden;
2. preferred-duration fit per participant;
3. largest absolute journey-time spread;
4. total group driving time;
5. venue category match;
6. opening-hours confidence;
7. provider rating adjusted for review-count confidence;
8. NapLoop popularity signal when sufficiently mature;
9. current group voting/approval;
10. optional practical attributes such as parking, indoor/outdoor, price, accessibility, baby-changing facilities, and age suitability.

**HYPOTHESIS:** Do not lock weights before staging tests. Expose enough of the ingredients in logs to compare ranking strategies.

---

## 12. Integration with Delayed Arrival

Meet Halfway chooses **where** the group should meet. Delayed Arrival can then choose **how an individual participant reaches that venue**.

Example:

- The selected play cafe is 22 minutes from Parent A.
- Parent A wants a 40-minute nap drive.
- Parent B wants the direct 27-minute route.

Parent A can tap:

> Make my drive 40 minutes

NapLoop then uses the existing Destination Mode / Delayed Arrival machinery to produce an individual route ending at the same agreed venue.

**DECISION:** Meetup fairness should be calculated using the normal/direct journey unless a participant explicitly opts to have a nap-duration preference included in the meetup calculation. Do not silently assume that everyone wants a padded route.

---

## 13. Monetization principles

The paywall must not damage the collaborative loop that makes Meet Halfway useful and shareable.

### Never paywall

- basic account privacy/security controls;
- accepting a basic meetup participant invitation as a guest;
- accepting/using beta access while the closed beta is running;
- basic privacy controls;
- hiding exact starting locations;
- safety/category filtering;
- basic participant invitation links;
- basic results sharing;
- the ability to see one’s own journey time;
- basic structured voting needed to reach agreement.

### Strong candidates for the free core

**HYPOTHESIS:** Keep enough functionality free that a real two-parent playdate can be planned end-to-end.

Likely free:

- 2–4 participants;
- basic Meet Halfway search;
- 3 candidate venues;
- common activity-category filters;
- basic Explore mode with a mixed set of family-suitable activities;
- one preferred drive duration and optional maximum per participant;
- basic voting;
- participant and results share links;
- direct navigation handoff;
- basic Delayed Arrival handoff for the chosen venue if that feature remains free in the core product.

### Good premium candidates

These add power, convenience, history, or extra API consumption without making the free collaboration feel broken:

- larger groups beyond the free participant allowance;
- more candidate venues / wider search radius / repeated “show me more” searches;
- advanced venue filters and mandatory-vs-preferred filter logic;
- saved playdate groups and reusable participant preferences;
- richer cross-device account history and personalization;
- recurring meetups;
- richer future-time traffic planning;
- automatic re-planning when one participant changes availability or limits;
- personalized venue/category recommendations from history;
- detailed NapLoop popularity and trend insights;
- favourite places, group history, and saved shortlists;
- advanced exploration themes such as “something outdoors”, “rainy-day surprise”, or “new place none of us has tried”;
- richer per-parent nap/travel profiles and multiple preference windows;
- premium-only convenience features that materially increase provider/API usage.

### Features that should be tested before deciding whether to charge

- preferred/max drive duration per participant;
- basic Explore;
- participant count above two;
- live collaborative re-ranking;
- short comments.

These are strategically important to differentiation and virality. Paywall decisions should be made from observed usage, not assumed willingness to pay.

### Monetization architecture decision

**DECISION:** Implement entitlements/feature flags from the beginning, but launch staging with the feature effectively unlocked. This lets later tests move features between Free and Premium without rewriting core logic.

**DECISION:** Never sell ranking position inside the fairness algorithm without explicit labelling. Sponsored venues, if ever introduced, must not masquerade as the objectively best meetup.

---

## 14. Staging scope

**DECISION:** Build this on staging while the current Loop/Destination/Delayed Arrival product continues to be tested.

### First testable slice

- UK only;
- minimal user registry present;
- server-side registration mode set to `invite_only`;
- founder/admin can generate a revocable, expiring beta-access link;
- no public signup path;
- meetup invitees may participate as guests without creating an account;
- 2 parents initially in the UI, data model capable of more;
- organiser creates a meetup;
- second parent joins by private link;
- both supply exact origins privately;
- exact origins hidden from each other by default;
- optional preferred and maximum drive times;
- date/time for the meetup;
- filtered activity mode plus basic Explore;
- 3–5 venue candidates;
- actual route-time calculation from both origins;
- clear absolute travel times and fairness spread;
- graceful widening when no close-to-equal candidates exist;
- Works / Maybe / Too far / Not this venue voting;
- shareable results link;
- handoff to normal navigation;
- optional “Make my drive X minutes” handoff to Delayed Arrival.

### Next staging increments

- optional guest-to-account claiming/linking;
- auth-provider-backed cross-device login if not already implemented;
- 3+ participant UI;
- masked convergence map;
- richer venue filters;
- saved/recurring groups;
- popularity aggregation;
- post-meetup feedback;
- entitlement/paywall experiments;
- additional countries/provider-category mappings.

---

## 15. Success criteria for the first real test

A real group should be able to:

1. create a meetup in under one minute;
2. add a second participant through a link without exchanging home addresses;
3. receive at least two genuinely plausible venue choices;
4. immediately understand each person’s travel time;
5. reject an unfair option and see useful alternatives;
6. agree on a venue through structured voting;
7. share the result without leaking precise origins;
8. navigate there;
9. optionally pad one participant’s journey using Delayed Arrival.

The founder test question is not “Did the algorithm find the mathematical midpoint?” It is:

> “Would two real parents actually use these results to choose where to meet?”

---

## 16. Open decisions to learn from staging

1. How much absolute time difference do users tolerate before they describe a meetup as unfair?
2. Do users understand preferred drive vs maximum drive without explanation?
3. Does Explore increase successful plans, or add decision fatigue?
4. How many candidate venues are useful before choice becomes noisy?
5. Should voting re-rank candidates instantly or only after every participant responds?
6. Are structured votes enough, or do users repeatedly ask for comments/chat?
7. Is the convergence map delightful enough to justify the privacy and implementation work?
8. Which filters are actually used often enough to justify Premium placement?
9. Does NapLoop popularity change venue choice once it has enough data?
10. Which collaborative features create enough value to monetize without weakening sharing and organic growth?
11. Do guest meetup participants convert naturally into registered users, or does account prompting create friction?
12. Should trusted beta users receive invitations, and if so how many before abuse/spam risk rises?
13. Which saved-account conveniences are valuable enough for Premium without turning privacy or basic collaboration into a paywall?

---

## 17. Canonical product summary

**Meet Halfway / Playdate Finder** is a near-term collaborative destination-discovery feature. NapLoop also gains a minimal invite-only user registry during testing, with public registration closed, low-friction guest meetup participation, and strictly separated beta-access, participant-invite, and read-only results capabilities. It finds family-suitable activities that are practically reachable for multiple parents, ranks them using real travel times and individual limits rather than geometric midpoint logic, lets participants privately contribute origins and travel preferences, and supports group voting and result sharing. Basic exploration, privacy, safety filtering, and collaboration should remain useful without payment. Premium should primarily sell power, convenience, history, advanced discovery, and higher-cost computation rather than withholding the ability to arrange a normal playdate.

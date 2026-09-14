# NapLoop invitation framework and walking expansion

Use this prompt with NapLoop Project Bible v0.6.0. Stepan owns product decisions; ChatGPT is the product/technical co-pilot; you are the repository coding agent.

## Objective and sequence

Complete the smallest reliable invitation/user framework before implementing the walking expansion. Reuse what exists. After that gate, introduce only necessary internal module boundaries and a bounded pram/carrier walking experiment in the same NapLoop package.

This prompt specifies the full direction, but **the current implementation slice is Phase A: invitation/user framework**. Complete that slice and report its acceptance evidence. Phases B and C are the agreed follow-on scope for the next iteration, not a request to build everything in one run. Do not turn a missing live auth configuration into a claim that the gate passed.

## Source hierarchy and initial reconciliation

Read the current repository instructions, including AGENTS.md/CLAUDE.md where present, README files, architecture notes, deployment guidance, API contracts and tests. Read Bible v0.6.0 before making product changes.

- Product truth: Bible v0.6.0 and subsequent explicit user decisions.
- Implementation truth: current repository and newest Claude implementation report. Distinguish implemented, locally tested, deployed and field-tested.
- Continuity: the Astra handover. It is not current implementation evidence.
- Surface conflicts explicitly. Do not silently change product requirements to match old code or rebuild features because the Bible contains historic status.

Report a compact IMPLEMENTED / STAGED / PLANNED / OPEN / SUPERSEDED reconciliation with concrete paths and commit identifiers. Then proceed with the bounded work; do not stop merely to ask permission for routine reversible implementation choices. If a material product/security choice is unresolved, finish the independent safe work and identify that specific decision.

### Dated baseline to check against the repository

The last supplied Three Jobs report is 11 September 2026, main a0f3410, reportedly deployed with 134 passing tests (120 backend, 14 frontend). These are historical claims, not tests run for this task.

- Three-job shell: Still Asleep default; Plan a drive containing Round trip / Go somewhere; flagged Meet up, reportedly enabled in production.
- Loop and Destination routing, TomTom backend search, total-duration semantics and direct-route floor.
- Home/recent targets; explicitly saved places never expire. Recent search window about six hours, at most 24 hours. Additional saved-place management remains incomplete in that snapshot.
- Shared navigation layer keeps shaping waypoints, not exact geometry/duration. Meetup cards reportedly bypass it. Simulated routes have no navigation handoff.
- Optional database failures no longer prevent ordinary routing/search from starting.
- DEPLOY.md documents beta invite mint/list/revoke, token hashes, ADMIN_API_TOKEN and invite_only registration. Full account/auth/session behaviour is not established by that evidence.
- The supplied deployment guide says there is no migration tool and create_all does not alter existing columns. Check whether newer work has changed this.
- No new live NapLoop testing results were supplied during the walking discussion. Photos and a fitness recording are product observations, not app validation.

## Non-negotiable invariants

1. Privacy by design. Identity is not a location dossier. Exact meetup origins remain private from other participants and results viewers.
2. Ordinary route generation/search must not depend on writing an account, favourite, observation or analytics event. Optional storage/auth/social failures cannot take those operations down.
3. Protected account/admin/meetup operations fail closed if authorization cannot be verified. Resilience never means bypassing permissions.
4. Beta access, meetup participation and read-only results are distinct capabilities. A guest can participate in an invited meetup without a beta account.
5. No home-grown passwords or production mock authentication. Keep managed identity behind a small internal boundary.
6. One app/codebase/package, initially deployed together. No microservices, general plugin engine, speculative transport framework or repository fork.
7. Keep existing route semantics, saved-place non-expiry, hard participant maxima, simulated-route behaviour and navigation limitations intact.
8. DECISION means accepted intent; HYPOTHESIS needs testing; LATER is deferred; IMPLEMENTED requires evidence. Mocked tests do not prove a production integration.
9. Verify current provider/platform/pricing/safety facts from official sources before a decision depends on them. Record links and check dates. No vendor is selected by this prompt.

## Phase A invitation and user framework

### A1 Inspect and define the minimum gap

Inventory current account tables, identity integrations, registration modes, invite models/endpoints, sessions, admin protection, entitlements, guest links and result capabilities. Trace which frontend paths use them. Identify dead code and incomplete routes without treating all existing infrastructure as disposable.

Document a concise ownership map. The identity/access module owns account IDs, verified identities, sessions, account status and authorization. Meet-up owns its participant records and private origins. Saved places remain separate and optional. This boundary work belongs in Phase A; wholesale routing refactoring does not.

Separate registration policy, authentication and entitlements. Account-creation policy must not accidentally become a global mandatory-login gate for stateless planning. An intentional access gate, if found in current code, needs reconciliation rather than silent removal.

### A2 Account and session lifecycle

Use a stable internal user ID and a unique mapping to the managed provider's verified identity. Store only necessary private identity fields, optional display name, timestamps, account status, invite provenance and simple entitlements. Do not add child names, birthdays, health records, Home coordinates or automatic travel history.

Reuse a valid existing managed identity integration. Validate identities server-side using the provider's supported mechanism, including applicable issuer/audience/expiry checks; never trust a client-supplied email, user ID or entitlement. Do not auto-link accounts by an unverified email address.

If no provider is configured, inspect the deployed stack and propose the smallest suitable managed option using current official documentation. Complete the provider-neutral seam, development fixtures and reproducible configuration instructions without building a password system. Explicitly report any external provisioning dependency; keep live authentication STAGED until a real configured flow is verified. Do not purchase services or send real invitations automatically.

Implement/verify session status, sign-in return handling, sign-out and disabled-account denial. Document expiry/revocation semantics, including what sign-out invalidates. Use the chosen provider's supported session pattern; protect applicable cookie flows against CSRF, unsafe cross-origin configuration and open redirects. Keep secrets server-side and raw credentials/tokens out of logs and analytics. Do not redesign the frontend solely to accommodate an auth library.

Document how an account can be disabled and how deletion/anonymisation affects linked records. Deliver a minimal protected administrative operation/runbook if suitable; a polished self-service deletion UI is not a prerequisite. Do not silently erase other participants' records or keep personal identity indefinitely without a stated policy.

### A3 Registration and beta invitations

Enforce closed / invite_only / open on the server, with invite_only for the testing environment. Closed prevents new account activation; already active users retain normal access unless disabled. Open is a supported future policy, not a production switch to flip now.

Reuse admin invite mint/list/revoke. Missing/invalid admin credentials must deny access. A minimal API/CLI runbook is sufficient; do not build a large admin dashboard.

Use high-entropy scoped beta tokens; store hashes, reveal raw values only when issued, apply expiry and revocation, and make redemption transactional. Define first-use behaviour explicitly: one successful activation per invite, with safe idempotent retry for the same completed operation where appropriate, and no second account through replay or concurrent redemption. For an existing active account, handle a beta link without creating a duplicate or granting extra privileges.

An invite is admission authorization, not a permanent sign-in credential. Validate both the beta capability and verified identity before account activation. Avoid consuming invitations merely because a link preview or unauthenticated GET loads the page. Avoid leaking raw tokens through application telemetry or third-party resources on redemption pages.

Provide clear UI states for invitation ready, sign-in required, success, already used, expired, revoked and temporarily unavailable without disclosing another person's identity. Retain intended app context after completion using validated return destinations.

### A4 Guest and results compatibility

Verify independent scopes for beta, meetup participant, organiser and results access. Do not let a results link submit votes, a participant link administer another participant, or a beta token read meetup origins.

Preserve the fresh-browser guest journey: open participant link, supply private origin/preferences, vote and view permitted results without account creation. Exact origins must not leak in shared payloads or map pins. Optional later guest-to-account claiming requires proof of both identities/capabilities and explicit consent; do not implement broad claiming in this slice unless needed to preserve an existing flow.

Keep account authentication separate from guest bearer capabilities. Do not assume all anonymous users are interchangeable or that a valid user can access every meetup.

### A5 Durability and failure isolation

Account/invite state requires durable storage before real beta invitations. Check actual deployment configuration without printing secrets. Do not use an ephemeral fallback as proof of durable identity.

Use the repository's existing migration approach if sound. If none exists and changes are necessary, introduce the smallest explicit, versioned non-destructive migration process suitable for this stack. Test upgrades from the current schema and existing records; document backup, deployment order and rollback/forward recovery. Do not drop production tables or follow old test-table reset instructions for real users.

Exercise missing/unreachable optional DB, unavailable auth provider and failed local storage. Core health/search/routing should remain available as designed. Account/admin/meetup operations that require unavailable state should return a clear scoped failure with no privilege escalation. Do not misreport degraded features as healthy.

### A6 Required verification

Use meaningful tests around these contracts, reusing current coverage where adequate:

- Registration mode matrix for new and existing accounts.
- Expired/revoked/invalid beta invites; failed authentication; retries; replay and concurrent redemption.
- Missing/incorrect admin credentials and unauthorized invite management.
- Beta/participant/organiser/results cross-scope attempts, cross-user access and private-origin payload checks.
- Session verification, expired session, sign-out and disabled-account behaviour.
- Fresh-browser guest participation independent of registration.
- Schema upgrade with existing records and preserved relationships.
- Required-state outages deny protected operations; ordinary search/routing survive optional failures.
- Existing Loop/Destination/Still Asleep and inert simulated-route regression checks affected by the changes.

Run a real configured identity-provider smoke test where available. Mark provider stubs, local tests, deployment checks and user field tests separately. No real messages to testers are needed: return a founder-run invitation/test procedure. Avoid expanding into unrelated test cleanup once the relevant gates are satisfied.

### Phase A completion report

Return changed files, commit/branch state, tests with actual outcomes, migrations, environment-variable names (no values), configuration still needed, deployment/rollback instructions and a short founder test checklist. Include the updated reconciliation and every material conflict resolved or still open.

State explicitly whether the framework gate passed. If not, identify the smallest remaining dependency and what was completed despite it. End this implementation slice after that report; do not automatically start the walking build.

## Phase B incremental module boundaries after acceptance

Map current modules to these responsibilities, preserving public behaviour:

| Shared capability | Independent logic |
|---|---|
| Location selection and optional saved places | Road access versus pedestrian entrances |
| Journey orchestration and route result shape | Candidate generation and evaluation per travel profile |
| Route geometry, segments, maps and evidence metadata | Driving traffic; walking terrain and equipment constraints |
| Walking path evidence | Pram clearance/rolling resistance; carrier footing/load preferences |
| Provider and navigation interfaces | Actual capabilities and source-specific limitations |
| Identity/access | Verified accounts, sessions and scopes; no routine location history |
| Meet-up workflow | Participants, private origins, fairness, voting and results lifecycle |
| Guidance, optional reports and observability | Profile-specific advice and non-blocking writes |

Distinguish journey job (round trip, destination, extension, meetup) from travel profile (driving, pram, carrier). Do not introduce a universal route-quality score. Evaluate eligibility first, preferences second and confidence separately. Unknown does not mean zero, safe or suitable.

Select only the extraction needed by the walking experiment. Keep driving reversal/spur rules inside driving evaluation: a comfortable out-and-back walk can be better than a rough loop. Mixed-transport meetups, full live navigation and permanent shell redesign are later.

## Phase C bounded walking experiment after the framework

Build behind a disabled-by-default flag. Begin with the Windsor circuit described in the Bible and two nearby alternatives, subject to data availability and field verification. If precise traces are absent, label annotations approximate and request the minimum survey input; do not invent georeferenced sections from sketches.

### Product behaviour

- Distinct pram and carrier profiles in one app. Do not commit to a permanent fourth tab or rename Plan a drive without a tested design.
- Pram capability and width are separate inputs. Carrier setup may include position/type and approximate child + carrier + additional carried luggage weight; assign luggage to the correct adult or pram. Keep inputs optional and local first.
- Show surface, firmness/roughness, meaningful slopes, gates/steps/stiles and unknowns. Explain hillier firm paths versus flatter rough ground when both are viable.
- Preserve observations with source, date and measured/reported/inferred status. Map tags and photographs alone do not establish complete access or current conditions.
- A single blocking obstacle must not disappear inside an average suitability score. Hard constraints remain hard. Unknown sections are clearly unverified.
- Shortening/return alternatives must respect the same equipment and access requirements. Generic navigation handoff or recalculation is not assumed to preserve them.
- Use approximate time/effort with explicit pace/stop assumptions. Load-based timing and physiological/calorie models are hypotheses, not validated features.
- Gate and hazard information belongs at the affected route section. Begin with ordinary paths and modest countryside walks. Exposed mountains, scrambling and awkward climbing are excluded from this experiment; generic disclaimers do not make them suitable.
- Source carrier guidance by equipment type and outdoor guidance from official/recognized bodies; show calm relevant notices. No sleep or universal safe-load guarantees.

The supplied fitness screenshot shows 33 minutes, 2.11 km and 0 m ascent despite a reported climb. Treat the ascent as unresolved/inadequate evidence; do not import zero as flat terrain. Heart-rate changes are not georeferenced proof of a path effect. Do not add wearable integration or store this family health record as a fixture.

Audit local data coverage before selecting an API. OSM attributes and openrouteservice wheelchair restrictions are research starting points, not selected services or pram guarantees. Verify official commercial terms, permitted caching/storage/display, quotas and call budgets. Compare the proposed experience with PramTrails/Komoot; do not assume an empty market.

The first success criterion is that parents can anticipate difficult sections and choose a preferable route for their equipment. Verify disabled-flag isolation, constraint handling, clear uncertainty, bounded calls and non-fatal report/save failures. Defer crowdsourcing platforms, health-device integration, automatic photo certification and national unrestricted routing.

## Retained work and explicit supersession

The immediate-next-task wording for bounded spur repair in v0.5.1 is superseded by the framework-first sequence. Spur repair itself remains agreed backlog: reuse detection, protect integral branches, measure saved time, reroute through the provider, cap calls, check tolerance and retain the original on uncertainty. Do not apply visual polyline trimming or mark repair delivered without evidence.

Also retain live driving tests, the full two-parent meetup test, additional device-local saved places and meetup adoption of the navigation capability layer. Their exact interleaving after Phase A can follow concrete results. GPX, dedicated Android Auto/CarPlay, account-based location sync and broad mountain walking remain later.

## Documentation and handoff discipline

Update the actual repository documentation with what changed, what was tested and what remains incomplete. Keep the Bible as product canon; do not change it merely to hide implementation gaps. Identify any outdated source instructions explicitly, especially destructive schema reset advice or expiry rules that conflict with saved-place non-expiry.

Follow the repository's existing workflow for reversible coding and reviewable commits. Do not silently deploy a schema/auth change to production, open public registration, purchase/provision services or send invitations to real people. Prepare concrete setup/deployment instructions and identify any action requiring the owner's participation. Continue independent authorized work when one external step is unavailable.

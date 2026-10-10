# Deploying Driftway to Render

Written 10 September 2026, after the backend crash-looped on an expired
Postgres instance. Follow in order — later steps need URLs the earlier ones
produce.

Three pieces: a **database**, a **backend web service**, and a **frontend
static site**. They must all be in the **same region** (yours is Oregon).

---

## Before you start: two facts that will bite you

**Free Postgres expires 30 days after creation.** Render then gives you 14
days to upgrade before deleting it permanently. That is exactly what broke the
service — the old instance's hostname (`dpg-d8vep4rsq97s738999kg-a`) stopped
resolving. **A new free database will expire the same way in 30 days.**

**A new Postgres is reachable from anywhere by default.** Render sets the
inbound allowlist to `0.0.0.0/0`, so the connection string alone is enough for
anyone who obtains it. The backend uses the *internal* URL over Render's
private network, so clearing the external allowlist costs nothing and closes
this off. Do it when you create the database.

**Free web services** (not the current backend, which is on Starter) spin down
after 15 minutes idle and take about a minute to wake. The app's request
timeout is 60 seconds, so on a Free plan the first request after a quiet spell
can time out. Starter has no spin-down.

---

## Step 1 — Create the database

You are on this screen already.

| Field | Value |
|---|---|
| **Name** | `driftway-db` |
| **Project** | Driftway / Production (optional, tidy) |
| **Database** | leave blank |
| **User** | leave blank |
| **Region** | **Oregon (US West)** — must match the backend |
| **PostgreSQL Version** | 18 (default is fine) |
| **Plan** | scroll down and pick **Free** |

Create it, then open the database page and:

1. Copy the **Internal Database URL**.
2. Open **Access Control** and remove the default `0.0.0.0/0` entry, so the
   database refuses connections from outside Render.

> Use the **Internal** URL, not the External one. Internal stays on Render's
> private network — faster, and it doesn't count against bandwidth. It only
> works because the backend is in the same region, which is why region matters.

---

## Step 2 — Point the backend at it

Backend service (**Driftway**) → **Environment**. Set these four:

| Key | Value |
|---|---|
| `DATABASE_URL` | the Internal Database URL from step 1 |
| `ROUTING_PROVIDER` | `tomtom` |
| `TOMTOM_API_KEY` | your key |
| `ALLOWED_ORIGINS` | `https://driftway-front.onrender.com,http://localhost:5173` |

**`ROUTING_PROVIDER` must be `tomtom`.** On `mock` the API returns simulated
demo routes with no Google Maps link, and every card reads "Simulated route —
not drivable". That is deliberate (never hand invented geometry to a
navigation app) but it looks like a total failure if it happens by accident.

Save. The service redeploys.

### If you would rather skip Postgres entirely

**Delete the `DATABASE_URL` variable.** The backend falls back to a local
SQLite file and boots normally. Routes, search and navigation all work;
favourites and feedback are lost on every restart, because free web services
have ephemeral disks.

That is a legitimate alpha choice — the Project Bible is explicit that loops
and detours must work with zero stored travel data. What you must *not* do is
leave `DATABASE_URL` pointing at a database that no longer exists.

---

## Step 3 — Create the frontend static site

Render → **New** → **Static Site** → same repo.

| Setting | Value |
|---|---|
| **Name** | `Driftway-Front` |
| **Region** | Oregon |
| **Root Directory** | `frontend` |
| **Build Command** | `npm ci && npm run build` |
| **Publish Directory** | `dist` |

Add one environment variable **before the first build** — Vite bakes it into
the bundle at build time, so setting it later needs a rebuild:

| Key | Value |
|---|---|
| `VITE_API_BASE` | the backend URL, `https://driftway.onrender.com` — **no trailing slash** |

> Without `VITE_API_BASE` the bundle calls same-origin `/api`, which on a
> static site is nothing at all. The Vite dev proxy only exists locally.

No rewrite rule is needed: the app has no client-side router, so there are no
deep links to redirect.

---

## Step 4 — Close the CORS loop

Copy the static site's URL (`https://driftway-front.onrender.com`).

Backend service → **Environment** → set `ALLOWED_ORIGINS` to it, with **no
trailing slash**. Keep localhost too so local dev against the deployed API
keeps working:

```
https://driftway-front.onrender.com,http://localhost:5173
```

Save and let the backend redeploy. This is a genuine chicken-and-egg: the
backend cannot know the frontend's URL until the frontend exists.

---

## Step 4a — Meet Halfway (optional, staging experiment)

Off by default. Every meetup endpoint returns 404 until it is switched on, so
deploying the code does not deploy the feature.

Backend service (**Driftway**) → **Environment**:

| Key | Value |
|---|---|
| `MEET_HALFWAY_ENABLED` | `true` |
| `REGISTRATION_MODE` | `invite_only` |
| `ADMIN_API_TOKEN` | a long random string you keep private |

`ADMIN_API_TOKEN` guards beta-invite creation and account disabling. **Leave it
unset and the admin endpoints refuse everything** — a missing secret is not
permission.

Run this locally and paste **the output** into Render — not the command itself.
Pasting the line below verbatim has happened, and it sets the admin token to a
string published in this repository, which anyone can read:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

It should look like `kJ3n...` — 43 random characters, no spaces, no quotes. If
the value in Render contains a space, it is wrong.

### Retention — the scheduled purge

Meetups are kept for 30 days after the event (60 from creation if never
scheduled), and accounts for 365 days of inactivity. Those rules live in
`backend/core/retention.py` and have been tested since 14 September. **They do
nothing until something calls them on a schedule.**

The work itself is `python -m jobs.run_retention`. It is safe to run twice —
selection is by age, so a second run finds nothing left — and bounded to 200
records of each kind per pass, draining any backlog across runs rather than in
one long transaction. It logs counts and meetup ids only, never a coordinate,
an address or a token.

**Chosen schedule: GitHub Actions (free).** Decided 8 Oct 2026.
`.github/workflows/retention.yml` calls the API daily at 03:15 UTC. It is free
because the repository is public, and it runs whether or not anyone's computer
is on. It uses a **retention-only token**, not the admin token: that token can
run the purge and nothing else, and since the purge selects by age, a leaked
copy only lets someone run early a job that was going to run anyway.

Setting it up is three steps. **Generating a value and entering it are separate
steps** - the command below prints a secret; what you paste is the printed
output (43 random characters, no spaces), never the command.

1. Generate the token, in PowerShell on your own machine:
   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Enter the **output** in two places, identically:
   - Render → Driftway (API) → Environment → `RETENTION_TRIGGER_TOKEN`
   - GitHub → the repository → Settings → Secrets and variables →
     Actions → New repository secret → `RETENTION_TRIGGER_TOKEN`
3. GitHub → Actions → Retention → **Run workflow**, then check that
   `/api/health` shows a non-null `retention` field.

Known limits, from GitHub's own documentation (checked 10 Oct 2026): scheduled
workflows in a public repository are switched off after 60 days with no
repository activity; the schedule "can be delayed during periods of high loads",
and "if the load is sufficiently high enough, some queued jobs may be dropped".
A late or dropped run catches up at the next run, because selection is by age.
It is not free of consequence: until then, records past their retention period
are kept longer than the policy says.

**First scheduled run, 10 Oct 2026: late, then successful.** Diagnosed from
GitHub's run history (public API) and `/api/health`, not assumed:

| Check | Evidence |
|---|---|
| Workflow on the default branch | `.github/workflows/retention.yml` on `main` since `645e71e` |
| Enabled | Workflow state `active` |
| Triggered by the schedule | Run 38042742327, event `schedule`, created 09:49:21 UTC - 6 h 34 min after the 03:15 slot |
| Reached the service and purged | Run concluded `success` in 5 s; `/api/health` `retention.last_run` = 2026-10-10T09:49:24, 0 purged, no backlog |

So the schedule did fire, late, which is GitHub's documented behaviour under
load; the workflow, token and endpoint all worked. Nothing was changed: 03:15
is already away from the top of the hour, which is GitHub's only advice. The
9 Oct run was a manual `workflow_dispatch`, which proves the token and endpoint
but not the schedule. **To check a run was scheduled rather than manual**, look
at its event on the Actions tab (`schedule` versus `workflow_dispatch`);
`/api/health` records when a purge ran, not what started it.

*Alternatives, not in use.* `backend/render.yaml` still carries a Render cron
service, which Render bills separately. And the endpoint can be called from a
local Windows scheduled task if GitHub is ever unsuitable:

```powershell
$action  = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
  '-NoProfile -Command "Invoke-RestMethod -Method Post ' +
  '-Uri https://driftway.onrender.com/api/admin/retention/run ' +
  '-Headers @{''X-Retention-Token''=$env:RETENTION_TRIGGER_TOKEN}"')
$trigger = New-ScheduledTaskTrigger -Daily -At 4am
Register-ScheduledTask -TaskName 'Driftway retention' -Action $action -Trigger $trigger
```

That only runs while the machine is on, which is why it is the fallback.

**Verifying it rather than assuming it.** `/api/health` carries a `retention`
field. It is `null` until a run completes against that database, and then
reports the timestamp, the counts, and whether a backlog remained:

```json
"retention": {"last_run": "2026-09-15T03:15:02", "meetups_purged": 0,
              "accounts_purged": 0, "backlog": false}
```

Until that field is non-null on production, retention is implemented and
scheduled but **not verified**, and should not be described as operational.

**If a run is missed**, nothing needs repairing. The next ordinary run takes
whatever the missed one would have, because selection is by age rather than by
a cursor; in the meantime expired records stay longer than they should. To catch up immediately, call the admin endpoint once. If `backlog`
comes back `true` repeatedly, the schedule is too infrequent for the volume.

**Retention is not erasure.** A person deleting their account gets that
immediately from the account screen; retention is the separate promise that
data nobody asked about does not accumulate. Both have to work.

### Incident note — admin token, 14 Sep 2026

`ADMIN_API_TOKEN` on the production API had been set to the literal text of the
generator command above, rather than to its output. That string is published in
this repository, so for an unknown period the admin endpoints were guarded by a
value anyone could read.

**The exposed token was rotated; no invitations were found at inspection.
Historical misuse has not been established.** An empty invite list at one
moment does not prove the token was never used — an invite could have been
minted and revoked, and nothing else the admin endpoints do leaves a record
that would survive. Treat the exposure window as unaudited.

### Walking experiment

`WALKING_ENABLED=true` on the API turns on the pram and carrier walks. Off by
default; off means the endpoint answers 404 and the app shows no **Walks**
button. When on, only admitted beta accounts can use it - enforced on the
server. It makes no provider calls at request time and stores nothing about
equipment or load. Details in [WALKING.md](WALKING.md).

### Rate limits and the provider bill

`/api/generate` is the only endpoint an anonymous stranger can use to spend
money: one generation costs many routing calls. It is limited per caller and
capped across the service.

| Variable | Default | What it does |
|---|---|---|
| `GENERATE_PER_MINUTE` | `6` | Per caller, sliding window |
| `GENERATE_PER_HOUR` | `40` | Per caller, sliding window |
| `GENERATE_GLOBAL_PER_HOUR` | `600` | Everybody combined — the provider-budget backstop |
| `TRUSTED_PROXY_COUNT` | `0` | How many proxies in front may be believed |

**Set `TRUSTED_PROXY_COUNT=1` on Render.** Render puts exactly one proxy in
front of the service, so the caller's real address arrives only in
`X-Forwarded-For`. Left at `0` that header is ignored entirely — the safe
default, because an unproxied deployment that trusted it would let anyone mint
a fresh allowance per request. The cost of leaving it at `0` behind Render is
the opposite problem: every caller is keyed to the proxy's address and shares
one bucket.

Honest limits of this implementation: the counters live in the worker's memory.
They reset when the service restarts, and they are not shared between
instances — so on a multi-instance deployment the effective limit is the
configured number times the instance count. A single-instance service, which is
what this is, behaves exactly as configured. A shared store is the upgrade path
and needs infrastructure that does not exist yet.

Refusals return `429` with a `Retry-After` header, and the message distinguishes
"you personally are going too fast" from "the whole service is at its limit".

### Search engines

`frontend/index.html` carries `<meta name="robots" content="noindex, nofollow">`
and `frontend/public/robots.txt` disallows everything. Both are requests that
well-behaved crawlers honour. **Neither restricts access**: anyone with the URL
can still open the app. The controls that actually restrict things are
server-side — `REGISTRATION_MODE=invite_only` for admission, and the rate
limits above for usage. Remove both when the alpha opens.

No frontend change is needed. The app asks `/api/health` whether the feature is
on and only then shows the entry point.

### Minting a beta invite

There is no admin UI yet, by design — §5.6 of the brief says not to delay
founder testing for admin chrome. Use the API:

```bash
curl -X POST "https://driftway.onrender.com/api/admin/beta-invites?ttl_days=14" \
  -H "X-Admin-Token: <your ADMIN_API_TOKEN>"
```

The raw token comes back **once**, in that response, and is never retrievable
again — only its hash is stored. Listing invites shows status, never tokens.

To revoke: `POST /api/admin/beta-invites/{id}/revoke` with the same header.

### Schema changes

**This section previously told you to drop the meetup tables on a schema
change. Do not do that.** It was safe only while those tables held nothing but
throwaway test rows. Once a real tester has an account and an invitation,
dropping them destroys exactly the records Phase A exists to protect.

`create_all()` still adds missing *tables* but never missing *columns*. That is
now handled by ordered, forward-only migration steps in
`backend/core/migrations.py`, applied at startup. They are additive and
idempotent, so redeploys and restarts are safe, and a failing step is logged
loudly without taking routing or search down.

To add a column, append a step to `STEPS` — never edit or reorder an applied
one, because a database that has already run it will not run it again.

`/api/health` reports `schema_pending`. Non-empty means a step has not been
applied and some feature will fail even though storage answers.

Rollback is "deploy the previous code": every step is additive, so older code
still reads the older columns. See `docs/IDENTITY.md`.

---

## Step 5 — Verify

**Backend health** — open `https://driftway.onrender.com/api/health`:

```json
{"status":"ok","provider":"tomtom","search":"tomtom","storage":"ok"}
```

Check all four:

- `provider: tomtom` — not `mock`, or every route is a non-navigable demo
- `search: tomtom` — otherwise the pickers only find five sample places
- `storage: ok` — `unavailable` means the database is unreachable. **The API
  keeps serving routes either way**; favourites and feedback return 503 until
  it is fixed.
- `meet_halfway` — `true` only if you completed step 4a. The app hides the
  entry point when this is false.
- `schema_pending` — must be `[]`. Anything listed means a migration step has
  not been applied and the feature needing it will fail.

**Search** — `https://driftway.onrender.com/api/search?q=SL4%201NJ` should
return one Windsor result. This is the most reliable check that a deploy
actually took: the endpoint does not exist in older builds, so 404 means the
service is still serving a previous version.

**End to end** — open the static site, allow location, request a round trip.
Then switch to **Go somewhere**, pick a destination, and confirm the results
name both endpoints and show the direct-drive baseline.

---

## Troubleshooting

**`failed to resolve host 'dpg-...'`** — the database is gone or is in another
region. Recreate it (step 1) and update `DATABASE_URL`, or delete the variable
to fall back to SQLite. Since the resilience fix the API no longer crash-loops
on this; it logs the fault and keeps serving routes.

**Every route says "Simulated route — not drivable"** — `ROUTING_PROVIDER` is
not `tomtom`, or `TOMTOM_API_KEY` is empty or rejected. Check `/api/health`.

**Browser console shows CORS errors** — `ALLOWED_ORIGINS` does not exactly
match the site's origin. Scheme, host, no trailing slash.

**The app loads but nothing happens on the button** — `VITE_API_BASE` was
missing or wrong at build time. Fix it and **trigger a fresh deploy**; the
value is compiled into the bundle.

**Meet Halfway 404s everywhere** — `MEET_HALFWAY_ENABLED` is not `true` on the
backend. Check `/api/health`.

**Minting an invite returns 503** — `ADMIN_API_TOKEN` is unset. That is the
deliberate refusal, not a bug.

**A meetup endpoint 500s with `no such column`** — a migration step is
missing for that column. Check `schema_pending` on `/api/health` and add a step
to `backend/core/migrations.py`. Do not drop the table.

**The frontend won't build** — check Root Directory is `frontend` and Publish
Directory is `dist`. If the build log shows TypeScript errors about `path` or
`url`, `@types/node` is missing from devDependencies.

---

## When the 30 days are up

You get one free Postgres per workspace, and it expires. Options, in the order
I would consider them for this alpha:

1. **Drop `DATABASE_URL`** and run on SQLite until there are real users whose
   favourites you would be sorry to lose. Zero cost, zero maintenance, and the
   core product is unaffected.
2. **Recreate a free instance** every 30 days. Fine while testing alone;
   favourites and feedback reset each time.
3. **Move to a paid instance** before any closed beta. The Bible already flags
   this as the pre-beta migration.

## Versions and builds

Founder request, 10 Oct 2026: testers must be able to tell which Driftway they
are using.

- **The release number** is the newest entry in `frontend/src/version.ts`,
  which is also the history under Settings → "What's new?". The API's own
  copy is `backend/core/version.py`; `tests/test_version.py` fails if they
  differ. A release bumps both and adds a history entry in plain words.
- **The build** is the commit. The app takes it at build time from Render's
  `RENDER_GIT_COMMIT` (or `git` locally; "dev" without either). The API
  reads the same variable at run time. Settings shows both, and says when
  they differ. That is normal for a few minutes after a push, because the
  static site and the API deploy separately; if it lasts, the phone is
  holding an old copy of the app.
- `/api/health` carries `"version": {"app": ..., "build": ...}`.
- Versions before 0.7.0 were numbered afterwards from the project history.
  Project Bible document versions are a separate numbering.

## openrouteservice refusing requests (10 Oct 2026) - OPEN

From about 14:30 UTC every request to Directions V2 was answered
`403 {"error": "Quota exceeded"}`, with no rate-limit headers, and was still
refused at 14:56. **It was not the quota.** The HeiGIT dashboard (founder
screenshot, same afternoon) showed Directions V2 at 2000/2000 left and
40 a minute, and 86 requests that day (41 successes, 45 errors). The 86 match
the developer's live checks plus a few probes, so production and the test
suite used almost none.

The same symptom - 403 "Quota exceeded" on Directions V2 with the dashboard at
full quota, no rate-limit headers, for about a day - was reported on the
openrouteservice forum on 27 Jul 2026, with no staff answer. So this is most
likely on the provider's side (HYPOTHESIS). The key is shared with
production, so walk generation there is affected for as long as it lasts.

Until this release the app reported it as "couldn't find a walking route".
It now says the provider isn't making walks and gives the provider's stated
reason as the provider's claim.

If it lasts beyond a day: write to HeiGIT support (support@account.heigit.org)
with the organisation id, the endpoint (`POST /v2/directions/{profile}/geojson`),
the times, and the response body. Never post the key itself. A separate
developer key would still be good hygiene, but this incident was not caused
by quota use.

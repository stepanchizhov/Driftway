# Two channels: Driftway and Driftway Next

Founder decision, 11 Oct 2026: one app for public testing that stays steady,
and one with the latest build for closed testing. An Android app made with
Bubblewrap shows whatever its website serves, so two apps need two websites.
Each website has its own server, so the Next app never runs on a server
that stable isn't ready for.

| | **Driftway** (stable) | **Driftway Next** (latest) |
|---|---|---|
| Branch | `main` | `next` |
| Website | `driftway.stepan.chizhov.com` (Render: `Driftway-Front`) | `next.driftway.stepan.chizhov.com` (Render: `Driftway-Front-Next`) |
| Server | `driftway.onrender.com` (Render: `Driftway`) | Render: `Driftway-Next` |
| Database | shared | shared |
| Android app | `com.ibookbinding.driftway`, "Driftway" | `com.ibookbinding.driftway.next`, "Driftway Next" |
| Twa manifest | `android/twa-manifest.json` | `android/next/twa-manifest.json` |
| Who | public testers | the family, closed testing |

Both apps can be installed on one phone at the same time. Settings shows
which one you are in ("Driftway Next 0.8.0 · build …"), and feedback from
Next arrives marked `0.8.0-next`.

## Everyday flow

- New work is committed to `next`. Pushing `next` redeploys the Next
  website and server; stable is untouched.
- When Next has been tried and is good, promote it to stable:

  ```powershell
  git checkout main
  git merge --ff-only next
  git push origin main
  git checkout next
  ```

- An urgent fix for stable goes on `main`, then into `next`:
  `git checkout next; git merge main; git push origin next`.

**One database, two servers.** Accounts, saved drives and meetups are the
same in both apps. The rule that makes this safe: a change on `next` may
**add** tables and columns, never rename or remove them, until stable runs
code that no longer needs them. That is already how `core/migrations.py`
works (see "Schema changes" in `DEPLOY.md`).

**One set of provider keys.** See "Readiness, checked 11 Oct 2026" below
for the numbers. In short: each server counts its own openrouteservice use,
so the two shares must add up to less than the plan; set stable to `0.8`
and Next to `0.1` when Next starts.

**Scheduled jobs stay on stable.** The nightly retention purge and the
morning provider check call the stable server only. Both servers share the
database, so the purge covers Next too.

## Readiness, checked 11 Oct 2026

Next is prepared, not running. What has to hold before it runs, and what was
checked:

**Shared database: behaviour, not only schema.** IMPLEMENTED,
`tests/test_shared_database.py`, on a disposable SQLite file. After a newer
version adds a column to tables stable uses, adds a table and records a
migration step stable does not know, stable code still: ignores the unknown
step and re-runs nothing; reads rows Next wrote and writes its own; keeps
one account's saved drives from another; exports an account and erases it
completely, rows written by Next included, leaving other accounts alone.
OPEN: the same check against real Postgres happens only when Next first
deploys; do it with a test account, never real users' records.

**Who changes the schema.** Each server runs `create_all()` and
`core/migrations.py` when it starts. A step is recorded in
`schema_migrations`, so whichever server starts first with a new step
applies it once; the other skips it. If both start at the same moment, one
`ALTER` fails, is logged and is retried at the next start: not fatal. A
change on `next` that renames, drops or narrows anything stable uses is
forbidden until stable runs code that no longer needs it.

**Scheduled jobs: one of each.** The retention purge is triggered by
`.github/workflows/retention.yml` against the stable server, with
`RETENTION_TRIGGER_TOKEN`; Next has no such token, so it cannot run there
even by mistake. If the Render cron in `render.yaml` is ever applied, it is
one more trigger, not one per channel: use it or the GitHub workflow, not
both. Never add either to Next.

**Deleting an account** in either app deletes the one shared account and
everything kept with it, as the privacy policy and the deletion page say.
What is on the phone (places, My walks, settings) belongs to each app's own
address and stays until that app's data is cleared.

**openrouteservice budget.** The plan (Standard, read 10 Oct 2026):
directions 2000 a day and 40 a minute, matrix 500 and 40, geocoding 3000
and 100. Driftway's own ceilings (`core/ors.py`, `WINDOWS`) are just under
those, scaled by each server's `ORS_BUDGET_SHARE`. Everything that calls
openrouteservice counts against them: walks, the driving and search
stand-ins, and the provider check (at most one call per endpoint per six
hours per server).

| Endpoint | Plan, a day | Stable `1` (today) | Stable `0.8` + Next `0.1` | Headroom |
|---|---|---|---|---|
| Directions | 2000 | 1800 | 1440 + 180 = 1620 | 380 |
| Matrix | 500 | 450 | 360 + 45 = 405 | 95 |
| Geocoding | 3000 | 2700 | 2160 + 270 = 2430 | 570 |
| Directions, a minute | 40 | 35 | 28 + 3 = 31 | 9 |

DECISION (proposed for this small beta): **stable `0.8`, Next `0.1`** from
the day Next starts. Until then stable stays at `1`. Why the headroom:

- **Counters are per process and in memory.** A restart, which every deploy
  is, forgets the day's count. Next deploys often. The headroom absorbs
  that; it does not make it impossible to go over.
- **One instance each is assumed.** Two instances of one service would each
  count from zero: halve its share if it is ever scaled out.
- **The provider's own limit is the backstop.** When openrouteservice
  refuses, Driftway says the provider isn't making walks just now (never
  "unreachable"), drives and search stay on TomTom, and curated walks still
  work.

A shared counter (in the database) would remove these caveats. LATER, only
if the logs ever show the plan's limit reached.

**TomTom** has no Driftway-side daily count. Both servers share its free
allowance; at beta usage that is far from the limit.

**Other limits.** Both servers use the same Postgres; each keeps a small
connection pool, well inside the database plan's connection limit.

## One-time setup (founder)

### 1. Push both branches

```powershell
git push origin main next
```

### 2. The Next server

Render, **New**, **Web Service**, the same repository.

| Setting | Value |
|---|---|
| Name | `Driftway-Next` |
| Branch | `next` |
| Region | Oregon (same as the database) |
| Root Directory | `backend` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/api/health` |
| Instance | Free works, but it sleeps after 15 minutes without use, and the first request afterwards waits about a minute. The smallest paid instance avoids that |

**Environment.** Copy each of these from `Driftway`, Environment, with the
same value. Only the ones that are set there are needed:

`DATABASE_URL`, `TOMTOM_API_KEY`, `ORS_API_KEY`, `ORS_BASE_URL`,
`PELIAS_BASE_URL`, `ORS_FALLBACK_BASE_URL`, `ORS_FALLBACK_API_KEY`,
`AUTH0_DOMAIN`, `AUTH0_AUDIENCE`, `ROUTING_PROVIDER`, `SEARCH_PROVIDER`,
`SEARCH_DEFAULT_COUNTRIES`, `WALKING_ENABLED`, `MEET_HALFWAY_ENABLED`,
`REGISTRATION_MODE`, `WALKS_ACCESS`, `TRUSTED_PROXY_COUNT`,
`PYTHON_VERSION`.

Then set these, which differ:

| Key | Value | Why |
|---|---|---|
| `ALLOWED_ORIGINS` | `https://next.driftway.stepan.chizhov.com,http://localhost:5173` | Only the Next website may call it |
| `ORS_BUDGET_SHARE` | `0.1` | Its share of the openrouteservice plan |

And on the **stable** server, `Driftway`, at the same time: set
`ORS_BUDGET_SHARE` to `0.8`, so the two shares leave headroom (see
"Readiness" above).

Leave `ADMIN_API_TOKEN` and `RETENTION_TRIGGER_TOKEN` **unset** on Next.
Its admin endpoints then refuse everything; invitations, disabling accounts
and the purge go through stable only, so there is one door to guard.

Copy values between the two Render pages directly. Don't paste them into a
chat or a file.

### 3. The Next website

Render, **New**, **Static Site**, the same repository.

| Setting | Value |
|---|---|
| Name | `Driftway-Front-Next` |
| Branch | `next` |
| Root Directory | `frontend` |
| Build Command | `npm ci && npm run build` |
| Publish Directory | `dist` |

Environment, **before the first build** (they are baked in at build time):

| Key | Value |
|---|---|
| `VITE_API_BASE` | the Next server's address from step 2, e.g. `https://driftway-next.onrender.com`, no trailing slash |
| `VITE_CHANNEL` | `next` |
| `VITE_AUTH0_DOMAIN`, `VITE_AUTH0_CLIENT_ID`, `VITE_AUTH0_AUDIENCE` | the same as on `Driftway-Front` |

**Don't set `VITE_CANONICAL_ORIGIN`** on Next. It would tell testers that
Driftway has moved.

### 4. The address

As for the stable address (`ANDROID.md`, section 1):

1. `Driftway-Front-Next`, Settings, Custom Domains: add
   `next.driftway.stepan.chizhov.com`. Render shows the record to create.
2. At the DNS host for `stepan.chizhov.com`: that record, name
   `next.driftway`, normally a CNAME to the site's `onrender.com` address.
   No AAAA record; "DNS only" if it is Cloudflare.
3. Back in Render, **Verify**.

### 5. Sign-in

Auth0, Applications, the Driftway single-page app: add
`https://next.driftway.stepan.chizhov.com` to Allowed Callback URLs, Allowed
Logout URLs and Allowed Web Origins. Keep the existing entries.

### 6. Check

On `https://next.driftway.stepan.chizhov.com`:

- Settings says **Driftway Next**, and the server's build matches the app's;
- sign in, plan a drive, make a walk;
- `/.well-known/assetlinks.json` lists both `com.ibookbinding.driftway` and
  `com.ibookbinding.driftway.next`.

### 7. The Next Android app

Not built yet: in a new folder Bubblewrap asks questions first, so it is
easiest once the Next website answers (step 6). Then follow
`android/README.md` with `android/next/twa-manifest.json` in
`C:\Users\stepa\driftway-android-next`, signed with the local test key;
`assetlinks.json` already lists the Next package with it.

On Play: Play Console, **Create app**, "Driftway Next", package
`com.ibookbinding.driftway.next`, then a closed testing track with the
family's emails. It is a separate listing with its own store entry, Data
safety form and app signing key. The Data safety answers are the same as
stable's (`DATA_SAFETY.md`). Once Play shows its app signing key's SHA-256,
add it to the `com.ibookbinding.driftway.next` entry in `assetlinks.json`
on both branches.

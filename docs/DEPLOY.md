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

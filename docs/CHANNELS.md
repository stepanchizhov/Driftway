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

**One set of provider keys.** Each server counts its own openrouteservice
use, so Next takes a tenth of the plan (`ORS_BUDGET_SHARE=0.1`: 180 routes
a day, about 60 walks) and stable keeps the rest. TomTom's free daily
allowance is shared without a separate count; at beta usage that is far
from the limit.

**Scheduled jobs stay on stable.** The nightly retention purge and the
morning provider check call the stable server only. Both servers share the
database, so the purge covers Next too.

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

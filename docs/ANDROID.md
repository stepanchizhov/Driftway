# Driftway on Android: the beta app

Founder decisions, 10 Oct 2026:

- The closed beta reaches testers as an Android app built with **Bubblewrap**:
  the web app in a Trusted Web Activity, installed from Google Play. It is a
  way to deliver roadmap phase 2 ("closed beta: learn from several
  families"). It is not phase 3, native Android: a Trusted Web Activity
  cannot record trips in the background or send notifications.
- Domain: **`driftway.stepan.chizhov.com`**. `driftway.app` belongs to someone
  else. The Auth0 API audience `https://api.driftway.app` is only an
  identifier, never fetched, and stays as it is.
- Published by **iBookBinding Ltd**'s Play developer account. It is an
  organisation account, so the rule that new personal accounts must run a
  closed test with 12 testers for 14 days does not apply.
- The Render API is on the Pro plan, so it does not sleep when idle.

A Trusted Web Activity is tied to one web origin. The app proves it owns the
site through `/.well-known/assetlinks.json`, which lists the app's package
name and signing-key fingerprint. **So the domain must be final before the
first build.** Moving it later means a new build, an Auth0 change and a
reinstall for every tester.

## 1. Domain (founder)

1. At the DNS host for `stepan.chizhov.com`, add a CNAME record: name
   `driftway`, value `driftway-front.onrender.com`.
2. Render, Driftway-Front, Settings, Custom Domains: add
   `driftway.stepan.chizhov.com`, and wait until its certificate shows as
   issued.
3. Render, Driftway (API), Environment: add
   `https://driftway.stepan.chizhov.com` to `ALLOWED_ORIGINS`. It is
   comma-separated; keep the existing entries.
4. Auth0, Applications, the Driftway single-page app: add
   `https://driftway.stepan.chizhov.com` to Allowed Callback URLs, Allowed
   Logout URLs and Allowed Web Origins. Keep the onrender.com entries until
   everyone has moved.
5. Open `https://driftway.stepan.chizhov.com` and sign in. Check that
   `/privacy.html` and `/beta.html` load.

## 2. Play Console (founder)

1. Create the app "Driftway" in iBookBinding Ltd's developer account.
2. Choose the **package name**. It is permanent once an app is uploaded.
   Proposed: `com.ibookbinding.driftway`. DECISION pending.
3. Turn on Play App Signing (the default), then copy the **SHA-256
   certificate fingerprint** of the app signing key: Test and release,
   App integrity, App signing.
4. Send the package name and fingerprint. The developer adds
   `frontend/public/.well-known/assetlinks.json`; Vite copies that folder into
   the build (checked 10 Oct 2026). Once it is live, check that
   `https://driftway.stepan.chizhov.com/.well-known/assetlinks.json` answers
   with that JSON.

The file will look like this, with the real values:

```json
[{
  "relation": ["delegate_permission/common.handle_all_urls"],
  "target": {
    "namespace": "android_app",
    "package_name": "com.ibookbinding.driftway",
    "sha256_cert_fingerprints": ["AA:BB:...:FF"]
  }
}]
```

If the app ever opens with a browser address bar across the top, this
verification has failed. The usual cause is a fingerprint that does not match
the key that signed the installed build.

## 3. Build with Bubblewrap (founder's machine)

Bubblewrap is Google Chrome Labs' command-line tool. It can download the Java
and Android tools it needs on first run.

```powershell
npm install -g @bubblewrap/cli
mkdir driftway-android; cd driftway-android
bubblewrap init --manifest https://driftway.stepan.chizhov.com/manifest.webmanifest
bubblewrap build
```

During `init`:

- package name: the one chosen above;
- **location delegation: yes**. Every tab uses location, and Android then
  shows its own permission prompt, as for a native app;
- signing key: create one and keep it safe outside the repository. With
  Play App Signing it is the upload key; Google holds the app signing key.

`build` produces `app-release-bundle.aab`. Upload it to **Internal testing**
first.

When the web manifest changes, run `bubblewrap merge`, then
`bubblewrap update`, then `bubblewrap build`. Web app changes themselves need
no new build: the app shows the live site.

## 4. Store listing and Data safety (founder, with these answers)

- **Privacy policy URL:** `https://driftway.stepan.chizhov.com/privacy.html`
- **App access:** the beta needs an invitation. Give the reviewers a working
  invitation link and sign-in method.
- **Target audience:** adults (parents). Not designed for children.
- **Ads:** none.
- **Data safety**, from `frontend/public/privacy.html` (version 1, 10 Oct
  2026), which was checked against the code:
  - *Location, precise:* collected, to provide the app's features. Drive
    and walk requests are processed and not stored. Meetup starting points
    are stored until the meetup expires. Sent to service providers (TomTom,
    openrouteservice).
  - *Personal info:* email address (account, if verified by the sign-in
    provider), name (optional display name). For account management.
  - *App activity / user-generated content:* feedback messages and route
    feedback.
  - Encrypted in transit: yes (HTTPS only).
  - Deletion: in the app (Settings, Account, Delete), or by emailing
    stepan@ibookbinding.com.
  - No data sold, no advertising, no analytics.
  Check the current Play form's wording against these when filling it in.
  The categories are Google's and change from time to time.

## 5. Testers

- **Internal testing** (up to 100 people, no review wait): the founder and
  family first. Check install, sign-in, location prompts, and opening Google
  Maps from a drive.
- **Closed testing:** the beta proper, 12–20 families. Mint one invitation
  per family with the admin tools (`docs/IDENTITY.md`) and send it with the
  Play opt-in link and `https://driftway.stepan.chizhov.com/beta.html`.

## State, 10 Oct 2026

| Item | State |
|---|---|
| Privacy policy page, guide for testers, Feedback on every tab | IMPLEMENTED (0.8.0, in progress) |
| Maskable app icon, manifest describing walks and meetups | IMPLEMENTED |
| No search text, positions or link tokens in server logs | IMPLEMENTED |
| Domain `driftway.stepan.chizhov.com` | OPEN: founder, section 1 |
| Package name, Play App Signing fingerprint | OPEN: founder, section 2 |
| `assetlinks.json` | Waiting on section 2 |
| Bubblewrap build, internal test | Waiting on sections 1–3 |

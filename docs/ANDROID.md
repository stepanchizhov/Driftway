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
- Published by **iBookBinding Ltd**'s Play developer account, which already
  runs another app's test. Google's rule on closed testing before production
  (Play Console Help 14151465, read 10 Oct 2026) is worded for "developers
  with personal accounts created after November 13, 2023": 12 testers opted
  in for 14 days. It does not mention organisation accounts, so by its own
  wording it does not apply here. Play Console's dashboard shows any
  requirement that does apply. Internal testing has no review and no access
  requirement, and builds reach testers "within seconds".
- The Render API is on the Pro plan, so it does not sleep when idle.

A Trusted Web Activity is tied to one web origin. The app proves it owns the
site through `/.well-known/assetlinks.json`, which lists the app's package
name and signing-key fingerprint. **So the domain must be final before the
first build.** Moving it later means a new build, an Auth0 change and a
reinstall for every tester.

## 1. Domain (founder)

Checked against Render's custom-domain documentation, 10 Oct 2026. Render
shows the exact DNS record only after the domain is added, so add it there
first.

1. Render, Driftway-Front, Settings, Custom Domains: **+ Add Custom Domain**,
   then enter `driftway.stepan.chizhov.com`. Render then shows the record to
   create. For a subdomain this is normally a CNAME to the site's own
   address, `driftway-front.onrender.com`. Use what Render shows.
2. At the DNS host for `stepan.chizhov.com`, create that record (name
   `driftway`). Render's own notes:
   - remove any AAAA record for that name, because Render uses IPv4;
   - if the domain has CAA records, allow `letsencrypt.org` and `pki.goog`;
   - with Cloudflare, use "DNS only" (grey cloud) for this record.
3. Back in Render, press **Verify**. Render then issues the certificate, and
   all HTTP is redirected to HTTPS. The `onrender.com` address keeps working
   unless you switch it off. Don't switch it off: testers' links use it.
4. Render, Driftway (API), Environment: add
   `https://driftway.stepan.chizhov.com` to `ALLOWED_ORIGINS`. It is
   comma-separated; keep the existing entries. The API's own address,
   `driftway.onrender.com`, does not change.
5. Auth0, Applications, the Driftway single-page app: add
   `https://driftway.stepan.chizhov.com` to Allowed Callback URLs, Allowed
   Logout URLs and Allowed Web Origins. Keep the onrender.com entries. The
   app sends its current address as the callback, so nothing else changes.
   The API audience `https://api.driftway.app` stays as it is: it is an
   identifier, never fetched.
6. Check `https://driftway.stepan.chizhov.com` yourself:
   - signing in and out;
   - a route;
   - a meetup link;
   - `/privacy.html`, `/delete-account.html` and `/beta.html`.
7. Only then, Render, Driftway-Front, Environment: set
   `VITE_CANONICAL_ORIGIN=https://driftway.stepan.chizhov.com` and redeploy.
   The old address then shows "Driftway has a new address".

**What does not move with the address** (browser storage belongs to an
address):

- Home, settings, walk preferences and the recent destination, on each
  device;
- the sign-in session (sign in again; the account and everything on it are
  unaffected);
- drives saved without signing in, which are tied to a device id kept
  there.

The banner says this. It suggests signing in first on the old address and
moving those drives to the account (Saved), which then brings them along.
Nothing is carried automatically: the device id acts like a password, and
must not travel in a link. The banner's link keeps the page, so a meetup
link opened on the old address continues on the new one.

## 2. Play Console (founder)

1. Create the app "Driftway" in iBookBinding Ltd's developer account.
2. Package name: **`com.ibookbinding.driftway`** (DECISION, founder, 10 Oct).
   Permanent once an app is uploaded.
3. Keep Play App Signing on (the default). Create an **upload key**
   deliberately: see `android/README.md`, "Keys: three different things".
   Do not upload a build signed with the local test key.
4. Copy the **SHA-256 fingerprint of the app signing key**: Test and
   release, App integrity, App signing. The developer adds it to
   `frontend/public/.well-known/assetlinks.json`, next to the local test
   key's fingerprint that is already there. Vite copies `.well-known` into
   the build (checked 10 Oct 2026). Once deployed, check that
   `https://<address>/.well-known/assetlinks.json` returns that JSON.

## 3. Build with Bubblewrap

`android/twa-manifest.json` is the app's source, and `android/README.md` has
the PowerShell build steps. The developer built it on 10 Oct 2026 on the
founder's machine, with the Bubblewrap install already there (1.25.0, JDK 17,
Android SDK in `C:\Users\stepa\.bubblewrap`), for the **current** address,
signed with the **local test key**. See the state table at the end for what
that build has and has not been checked for.

For the Play build:

1. Once the domain move is verified, set `host`, the icon URLs,
   `webManifestUrl` and `fullScopeUrl` in `android/twa-manifest.json` to
   `driftway.stepan.chizhov.com`.
2. Point `signingKey` at the upload key.
3. Raise `appVersionCode` by one for every upload.
4. Run `bubblewrap update`, then `bubblewrap build`.
5. Upload `app-release-bundle.aab` to **Internal testing**.

When the web manifest changes, run `bubblewrap merge`, then `update`, then
`build`. Changes to the web app itself need no new build: the app shows the
live site.

**On a phone, before anyone else gets it.** None of these has been checked
on a device yet:

- [ ] It opens full-screen, with no address bar (asset links verified).
- [ ] Sign in goes to Auth0 (shown with an address bar, because it is a
  different site) and comes back signed in.
- [ ] Location: allow, deny, then allow again from settings. The prompt
  is Android's own (location delegation). Each tab copes with refusal.
- [ ] An invitation link and a meetup link, tapped in an email, open in
  the app.
- [ ] Opening a drive in Google Maps, then coming back.
- [ ] Back button: within the app, and at the first screen.
- [ ] Settings links: privacy, deleting your account, the guide for testers.
- [ ] Feedback sends.
- [ ] After a web deploy, the app shows the new version (Settings).

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
| Privacy policy 1.1, deleting your account without the app, guide for testers, Feedback on every tab | IMPLEMENTED (0.8.0, in progress) |
| Maskable app icon, site icon, iPhone icon, manifest describing walks and meetups | IMPLEMENTED |
| No search text, positions or link tokens in server logs | IMPLEMENTED |
| Data safety answers | IMPLEMENTED as `docs/DATA_SAFETY.md`; to be entered in Play Console by the founder |
| `android/twa-manifest.json`, package `com.ibookbinding.driftway`, location delegation on | IMPLEMENTED, for the current address |
| Local test build (APK and AAB, local test key) | Built on the founder's machine by the developer; **not yet installed on a phone** |
| `assetlinks.json` | Local test key only. The Play app signing key: OPEN, founder, section 2 |
| Domain `driftway.stepan.chizhov.com` | OPEN: founder, section 1 |
| Upload key | OPEN: founder, `android/README.md` |
| On-phone checks (section 3) | OPEN: nobody has done them yet |

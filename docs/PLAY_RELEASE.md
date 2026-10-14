# Google Play: first release (internal testing)

Prepared 14 Oct 2026 for the founder's first upload. Each step says who does
it. The details behind the steps are in `docs/ANDROID.md` (build and keys),
`android/README.md` (PowerShell build) and `docs/DATA_SAFETY.md` (the form's
answers).

## Checklist

| # | Step | Who | State |
|---|---|---|---|
| 1 | Check the TomTom plan and its overage price: drives now make up to about 7 more calls each (steering, moved turn-backs, roadworks). The free plan is 20,000 routing requests a month | Founder | OPEN |
| 2 | Create the **upload key** (`android/README.md`, "Keys"). Never the local test key | Founder | OPEN |
| 3 | Create the app in Play Console: package `com.ibookbinding.driftway`, Play App Signing on | Founder | OPEN |
| 4 | Copy the **app signing key's SHA-256** (Test and release, App integrity) and send it to the developer, who adds it to `frontend/public/.well-known/assetlinks.json` next to the test key's; push and check `https://driftway.stepan.chizhov.com/.well-known/assetlinks.json` | Founder, then developer | OPEN |
| 5 | Point `signingKey` in `android/twa-manifest.json` at the upload key, then build with `.\android\build.ps1` (never prints the password) | Founder | OPEN. Version already set: 0.8.15, code 3 |
| 6 | Store listing: the text below, the icon, a feature graphic, at least two phone screenshots | Founder, with the developer's drafts | Text DRAFTED below; graphics OPEN |
| 7 | Data safety form, from `docs/DATA_SAFETY.md` (updated 14 Oct for privacy policy 1.9) | Founder | Answers READY |
| 8 | Content rating questionnaire: no violence, no user-to-user chat (meetup comments are between two invited parents), no gambling, location shared only with service providers | Founder | OPEN |
| 9 | Target audience: adults (parents), not designed for children. Ads: none. App access: everything works without signing in; no test login needed | Founder | Answers READY |
| 10 | Upload `app-release-bundle.aab` to **Internal testing**; add testers (founder and family first) | Founder | OPEN |
| 11 | On a phone from Play: the checks in `docs/ANDROID.md` section 3 (full screen, sign-in, location, meetup link, Google Maps and back, Back button, Settings links, Feedback, update after a web deploy) | Founder, developer over USB | OPEN |

Later, for **closed testing** (12 to 20 families): the Play opt-in link and
`https://driftway.stepan.chizhov.com/beta.html`.

## Store listing text (draft)

**App name** (30 characters at most): `Driftway: nap drives & walks`

**Short description** (80 at most):

> Drives and walks of the length you choose, so your little one keeps sleeping.

**Full description:**

> When a little one sleeps best on the move, Driftway plans the drive or the
> walk around the nap.
>
> **Drives that bring you home.** Choose how long, and Driftway makes a loop
> of about that length, or a longer way to where you're going. It avoids
> turning round where it can, prefers quieter roads, and counts the speed
> bumps, traffic lights and roadworks mapped along each drive. Tell it what
> wakes your little one, and those are avoided more. Each drive opens in
> Google Maps.
>
> **Still asleep?** Already driving and the nap isn't done: one tap for a
> longer way home.
>
> **Walks checked for your pram or carrier.** Loops from where you are, or
> through places you choose, judged against your pram's wheels or your
> carrier and your pace. What's known about each path is shown with where it
> comes from, and what isn't known is said.
>
> **Meet halfway.** Find a fair place to meet another parent, with travel
> times for both of you.
>
> **Honest about what it knows.** Speed bumps and lights are counted where
> they're mapped; roadworks come from official data in England and from
> traffic reports elsewhere. When a map service is down, Driftway says so
> rather than guessing.
>
> Driftway is in beta, made in the UK, with the most detail around Windsor
> for now. No ads. No account needed to plan a drive or a walk.
>
> Car seats are designed for safe travel rather than routine sleep. Take
> regular breaks and follow your child seat maker's instructions.

**Category:** Parenting. **Tags/contact:** stepan@ibookbinding.com, the
privacy policy URL `https://driftway.stepan.chizhov.com/privacy.html`.

**What's new (0.8.15):** use the first line or two of the latest release in
Settings, What's new.

## Graphics (OPEN)

- **Icon** 512 × 512: from `frontend/public` (the maskable icon), exported
  at that size.
- **Feature graphic** 1024 × 500.
- **Phone screenshots** (2 to 8, 16:9 or 9:16): the developer can make them
  from the live app at phone size in a headless browser, with made-up places
  only, never the founder's own: Still asleep, a drive's cards, What wakes
  your little one, a walk card, Meet halfway.

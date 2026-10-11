# Driftway Android app (Trusted Web Activity)

`twa-manifest.json` is the source of the Android app. It is Bubblewrap's
config, generated on 10 Oct 2026 with Bubblewrap's own library
(`TwaManifest.fromWebManifestJson`) from the live web manifest, then set to
Driftway's choices. Everything else is generated from it. The full plan, with
Play Console and domain steps, is in `docs/ANDROID.md`.

| Setting | Value | Why |
|---|---|---|
| `packageId` | `com.ibookbinding.driftway` | Founder decision, 10 Oct. Permanent once uploaded to Play |
| `host` | `driftway.stepan.chizhov.com` | The final address. It went live on 10 Oct 2026: HTTPS, asset links and the API's CORS were checked from outside |
| `features.locationDelegation` | on | Every tab uses location. Android then asks for it as it would for a native app. Foreground only: no background location |
| `enableNotifications` | **on** (11 Oct) | Needed for location, not for notifications. It switches on the app's service, nothing on the phone: the notification permission stays off, and no one is asked to allow notifications. Checked on the founder's phone, 11 Oct: notification permission not granted, location granted, a location fix in the page within a second. Bubblewrap switches its background service on only with notifications, and the location permission prompt lives in that service. With it off, the app never asked for location: with permission not yet granted, the page waited forever (founder's phone, 11 Oct). Driftway never asks to send notifications, so none appear; the app does declare Android's notification permission |
| `appVersionCode` | 2 | 1 was the first local build, without the location prompt |
| `signingKey` | `C:\Users\stepa\.driftway\driftway-localtest.jks`, alias `driftway-localtest` | A **local test key** for builds you install by hand. Never use it as the Play upload key; see below |

Tooling used on 10 Oct 2026:

- `@bubblewrap/cli` 1.25.0 (npm's latest was 1.27.0), with its JDK 17 and
  Android SDK in `C:\Users\stepa\.bubblewrap`;
- the generated project: compileSdk/targetSdk 36, minSdk 21,
  `androidbrowserhelper` 2.6.2, `locationdelegation` 1.1.2.

## Building (Windows, PowerShell)

Build outside the repository, so generated files and outputs stay out of
it. A plain ASCII folder is the safe choice; a path with `Документы` in it
was not tested. If the build stops with `'gradlew.bat' is not recognized`,
the environment has `NoDefaultCurrentDirectoryInExePath` set. Some tool
sandboxes set it, and that was the cause here on 10 Oct. Clear it for the
build: `Remove-Item Env:NoDefaultCurrentDirectoryInExePath`.

```powershell
.\android\build.ps1          # Driftway, built in $HOME\driftway-android
.\android\build.ps1 -Next    # Driftway Next, in $HOME\driftway-android-next
```

`build.ps1` sets up Bubblewrap's JDK, checks that `jarsigner` is there
**before** anything is signed, and replaces the test key's password with
`***` in everything Bubblewrap and Gradle print. It clears the password from
the session when it finishes. Use it rather than setting the password
variables by hand.

Why: on 11 Oct 2026, with `jarsigner` missing from PATH, Bubblewrap printed
the failed signing command, `-storepass` and `-keypass` included, and the
test key's password appeared in tool output (the second time). Checked
after the fix: a stand-in Bubblewrap failing in exactly that way prints
`-storepass "***"`; a missing JDK stops before anything runs; a real build
of the stable app succeeded with the password nowhere in its output.

The first build of **Driftway Next** in a new folder needs Bubblewrap's
interactive `init` once (it asks questions); after that the script works
for it too.

This produces `app-release-signed.apk`, which you can install by hand, and
`app-release-bundle.aab`, which Play takes.

## Driftway Next

The latest-build app for closed testing (`docs/CHANNELS.md`) is built the
same way from `android/next/twa-manifest.json`, in its own folder:

```powershell
mkdir $HOME\driftway-android-next -Force
Copy-Item .\android\next\twa-manifest.json $HOME\driftway-android-next\
cd $HOME\driftway-android-next
```

then `bubblewrap update` and `bubblewrap build` as above. Same local test
key; `assetlinks.json` lists both packages with it.

## Keys: three different things

1. **Local test key** (`driftway-localtest.jks`). It exists now and is only
   for builds you install by hand. Its password is in the file next to it,
   and that is acceptable only because it is a test key. Its SHA-256
   fingerprint is in `frontend/public/.well-known/assetlinks.json`, so a
   build signed with it opens full-screen on the current address.
2. **Upload key.** It signs what you upload to Play. Create it deliberately:
   with `keytool`, or by answering Bubblewrap's prompts in a fresh `init`.
   Use a strong password, kept in a password manager, and keep a backup of
   the `.jks` file somewhere other than this computer. If it is lost, Play
   can reset it, but that takes time.
3. **App signing key.** Google holds it, with Play App Signing on by
   default. It signs what testers actually install from Play, so **its**
   fingerprint must be in `assetlinks.json` for the Play build to open
   full-screen. Play Console, Test and release, App integrity, App signing.

If the Play build opens with an address bar across the top, the asset-links
check failed. The usual cause is a fingerprint in `assetlinks.json` that
doesn't match the key that signed the installed build.

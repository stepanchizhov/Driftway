# Driftway Android app (Trusted Web Activity)

`twa-manifest.json` is the source of the Android app. It is Bubblewrap's
config, generated on 10 Oct 2026 with Bubblewrap's own library
(`TwaManifest.fromWebManifestJson`) from the live web manifest, then set to
Driftway's choices. Everything else is generated from it. The full plan, with
Play Console and domain steps, is in `docs/ANDROID.md`.

| Setting | Value | Why |
|---|---|---|
| `packageId` | `com.ibookbinding.driftway` | Founder decision, 10 Oct. Permanent once uploaded to Play |
| `host` | `driftway-front.onrender.com` **for now** | The final address, `driftway.stepan.chizhov.com`, is not live yet. Change this, the icon URLs, `webManifestUrl` and `fullScopeUrl` together, then run `bubblewrap update` |
| `features.locationDelegation` | on | Every tab uses location. Android then asks for it as it would for a native app. Foreground only: no background location |
| `enableNotifications` | off | Not used in the beta. Not impossible, just not needed |
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
mkdir $HOME\driftway-android -Force
Copy-Item .\android\twa-manifest.json $HOME\driftway-android\
cd $HOME\driftway-android
bubblewrap update --skipVersionUpgrade
$env:BUBBLEWRAP_KEYSTORE_PASSWORD = Get-Content $HOME\.driftway\driftway-localtest.password
$env:BUBBLEWRAP_KEY_PASSWORD = $env:BUBBLEWRAP_KEYSTORE_PASSWORD
bubblewrap build --skipPwaValidation
```

This produces `app-release-signed.apk`, which you can install by hand, and
`app-release-bundle.aab`, which Play takes.

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

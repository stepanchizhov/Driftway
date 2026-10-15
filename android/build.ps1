# Builds a Driftway Android app without ever printing a key's password.
#
#   .\android\build.ps1                       # Driftway, LOCAL TEST key, in $HOME\driftway-android
#   .\android\build.ps1 -Next                 # Driftway Next, LOCAL TEST key, in $HOME\driftway-android-next
#   .\android\build.ps1 -Upload -UploadKey C:\path\upload.jks -UploadAlias upload
#                                             # Driftway for Google Play, signed with the UPLOAD key
#   ... -DryRun                               # show what would be built; no password, no build
#
# Why this exists (11 Oct 2026): with jarsigner missing from PATH, Bubblewrap
# printed the failed signing command, passwords included. So this script
# checks for jarsigner before anything is signed, removes the password from
# every line Bubblewrap prints, and clears it from the session afterwards.
#
# The two keys are different things (android/README.md, "Keys"):
#   - the local test key: its password sits in a file next to it, for builds
#     installed by hand. Never uploaded.
#   - the Play upload key (15 Oct 2026, -Upload): its password is typed at the
#     prompt, hidden, and never written anywhere. Play re-signs the app with
#     its own app signing key; that key's SHA-256 is what assetlinks.json needs.

param(
    [switch]$Next,
    [switch]$Upload,
    [string]$UploadKey,
    [string]$UploadAlias,
    [switch]$DryRun,
    [string]$Project,
    [string]$PasswordFile = "$HOME\.driftway\driftway-localtest.password",
    [string]$JdkRoot = "$HOME\.bubblewrap\jdk"
)

$ErrorActionPreference = "Stop"
if ($Upload -and $Next) { throw "Driftway Next isn't uploaded to Play: build it with the test key (-Next)." }
if ($Upload -and (-not $UploadKey -or -not $UploadAlias)) {
    throw "With -Upload, give -UploadKey (the upload key's .jks file) and -UploadAlias."
}
$manifest = if ($Next) { Join-Path $PSScriptRoot "next\twa-manifest.json" } else { Join-Path $PSScriptRoot "twa-manifest.json" }
if (-not $Project) {
    $Project = if ($Next) { "$HOME\driftway-android-next" } elseif ($Upload) { "$HOME\driftway-android-play" } else { "$HOME\driftway-android" }
}

# The JDK Bubblewrap installed, and its jarsigner, first.
$jdk = Get-ChildItem $JdkRoot -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $jdk -and -not $DryRun) {
    throw "Bubblewrap's JDK was not found in $JdkRoot. Run 'bubblewrap doctor' first."
}
if ($jdk) {
    $env:JAVA_HOME = $jdk.FullName
    $env:Path = "$($jdk.FullName)\bin;$env:Path"
}
if (-not $DryRun -and -not (Get-Command jarsigner -ErrorAction SilentlyContinue)) {
    throw "jarsigner was not found in $($jdk.FullName)\bin. Not building: a failed signing step would print the password."
}
if ($Upload) {
    if (-not (Test-Path $UploadKey)) { throw "The upload key was not found: $UploadKey" }
} elseif (-not $DryRun -and -not (Test-Path $PasswordFile)) {
    throw "The local test key's password file was not found: $PasswordFile"
}
# Some tool sandboxes set this, and then gradlew.bat is "not recognized".
Remove-Item Env:NoDefaultCurrentDirectoryInExePath -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Force $Project | Out-Null
$target = Join-Path $Project "twa-manifest.json"
if ($Upload) {
    # The project's copy of the manifest signs with the upload key; the one in
    # the repository keeps pointing at the test key.
    $m = Get-Content $manifest -Raw | ConvertFrom-Json
    $m.signingKey.path = (Resolve-Path $UploadKey).Path
    $m.signingKey.alias = $UploadAlias
    $m | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 $target
} else {
    Copy-Item $manifest $target -Force
}
$built = Get-Content $target -Raw | ConvertFrom-Json
Write-Output ("Building {0} {1} (version code {2}), signed with {3} [{4}], in {5}" -f `
    $built.packageId, $built.appVersionName, $built.appVersionCode, $built.signingKey.path, $built.signingKey.alias, $Project)
if ($DryRun) {
    Write-Output "Dry run: nothing built, no password asked for."
    return
}

if ($Upload) {
    $secure = Read-Host "Upload key password (hidden; it is not stored)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $secret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
} else {
    $secret = (Get-Content $PasswordFile -Raw).Trim()
}
if (-not $secret) { throw "No password given: not building." }
$env:BUBBLEWRAP_KEYSTORE_PASSWORD = $secret
$env:BUBBLEWRAP_KEY_PASSWORD = $secret

function Run-Hidden([string[]]$arguments) {
    # Native output goes through PowerShell as text, with the password
    # replaced, whatever Bubblewrap or Gradle decide to print.
    $ErrorActionPreference = "Continue"
    & bubblewrap @arguments 2>&1 | ForEach-Object { Write-Host ("$_".Replace($secret, "***")) }
    return $LASTEXITCODE
}

Push-Location $Project
try {
    if ((Run-Hidden @("update", "--skipVersionUpgrade")) -ne 0) { throw "bubblewrap update failed (output above, password hidden)." }
    if ((Run-Hidden @("build", "--skipPwaValidation")) -ne 0) { throw "bubblewrap build failed (output above, password hidden)." }
    if ($Upload) {
        Write-Output "Built in $Project : app-release-bundle.aab, to upload to Internal testing."
    } else {
        Write-Output "Built in $Project : app-release-signed.apk (install by hand), app-release-bundle.aab."
    }
}
finally {
    Pop-Location
    Remove-Item Env:BUBBLEWRAP_KEYSTORE_PASSWORD, Env:BUBBLEWRAP_KEY_PASSWORD -ErrorAction SilentlyContinue
    $secret = $null
    $secure = $null
}

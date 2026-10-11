# Builds a Driftway Android app signed with the LOCAL TEST key, without
# ever printing the key's password.
#
#   .\android\build.ps1                       # Driftway, in $HOME\driftway-android
#   .\android\build.ps1 -Next                 # Driftway Next, in $HOME\driftway-android-next
#
# Why this exists (11 Oct 2026): with jarsigner missing from PATH, Bubblewrap
# printed the failed signing command, passwords included. So this script
# checks for jarsigner before anything is signed, removes the password from
# every line Bubblewrap prints, and clears it from the session afterwards.
#
# Never use it for the Play upload key: that key gets its own strong password,
# kept in a password manager, and is never written to a file next to it.

param(
    [switch]$Next,
    [string]$Project,
    [string]$PasswordFile = "$HOME\.driftway\driftway-localtest.password",
    [string]$JdkRoot = "$HOME\.bubblewrap\jdk"
)

$ErrorActionPreference = "Stop"
$manifest = if ($Next) { Join-Path $PSScriptRoot "next\twa-manifest.json" } else { Join-Path $PSScriptRoot "twa-manifest.json" }
if (-not $Project) {
    $Project = if ($Next) { "$HOME\driftway-android-next" } else { "$HOME\driftway-android" }
}

# The JDK Bubblewrap installed, and its jarsigner, first.
$jdk = Get-ChildItem $JdkRoot -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $jdk) {
    throw "Bubblewrap's JDK was not found in $JdkRoot. Run 'bubblewrap doctor' first."
}
$env:JAVA_HOME = $jdk.FullName
$env:Path = "$($jdk.FullName)\bin;$env:Path"
if (-not (Get-Command jarsigner -ErrorAction SilentlyContinue)) {
    throw "jarsigner was not found in $($jdk.FullName)\bin. Not building: a failed signing step would print the password."
}
if (-not (Test-Path $PasswordFile)) {
    throw "The local test key's password file was not found: $PasswordFile"
}
# Some tool sandboxes set this, and then gradlew.bat is "not recognized".
Remove-Item Env:NoDefaultCurrentDirectoryInExePath -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Force $Project | Out-Null
Copy-Item $manifest (Join-Path $Project "twa-manifest.json") -Force

$secret = (Get-Content $PasswordFile -Raw).Trim()
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
    Write-Output "Built in $Project : app-release-signed.apk (install by hand), app-release-bundle.aab."
}
finally {
    Pop-Location
    Remove-Item Env:BUBBLEWRAP_KEYSTORE_PASSWORD, Env:BUBBLEWRAP_KEY_PASSWORD -ErrorAction SilentlyContinue
    $secret = $null
}

param(
    [string]$Tag = ""
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

$tauriConfig = Get-Content -Raw -LiteralPath (Join-Path $repositoryRoot "desktop\src-tauri\tauri.conf.json") | ConvertFrom-Json
$desktopPackage = Get-Content -Raw -LiteralPath (Join-Path $repositoryRoot "desktop\package.json") | ConvertFrom-Json
$cargoContent = Get-Content -Raw -LiteralPath (Join-Path $repositoryRoot "desktop\src-tauri\Cargo.toml")

if ($cargoContent -notmatch '(?ms)^\[package\]\s*.*?^version\s*=\s*"([^"]+)"') {
    throw "Could not read the desktop package version from Cargo.toml."
}

$versions = [ordered]@{
    "tauri.conf.json" = [string]$tauriConfig.version
    "desktop/package.json" = [string]$desktopPackage.version
    "Cargo.toml" = [string]$Matches[1]
}
$version = $versions["tauri.conf.json"]

if ($version -notmatch '^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$') {
    throw "Desktop version '$version' is not valid SemVer."
}

$mismatches = $versions.GetEnumerator() | Where-Object { $_.Value -ne $version }
if ($mismatches) {
    $details = ($versions.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ", "
    throw "Desktop version files disagree: $details"
}

if ($Tag -and $Tag -ne "desktop-v$version") {
    throw "Release tag '$Tag' must exactly match desktop-v$version."
}

if ($env:GITHUB_OUTPUT) {
    Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "version=$version"
}
Write-Output "InternTrack desktop version $version is consistent."

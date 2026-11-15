$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

if ($env:GITHUB_ACTIONS -ne "true" -or $env:RUNNER_ENVIRONMENT -ne "github-hosted" -or $env:RUNNER_OS -ne "Windows") {
    throw "WebView2 driver setup requires a GitHub-hosted Windows runner."
}

# The WebView2 runtime can differ from the full Edge browser on the runner.
$runtimeKeys = @(
    "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
)
$runtimeVersion = $null
foreach ($key in $runtimeKeys) {
    $value = (Get-ItemProperty -LiteralPath $key -Name pv -ErrorAction SilentlyContinue).pv
    if ($value -match '^\d+\.\d+\.\d+\.\d+$' -and [version]$value -gt [version]"0.0.0.0") {
        $runtimeVersion = [string]$value
        break
    }
}
if (-not $runtimeVersion) { throw "Could not detect the installed WebView2 runtime." }
Write-Host "Installed WebView2 runtime: $runtimeVersion"
$runtimeBuild = ($runtimeVersion.Split('.')[0..2]) -join '.'

function Test-MatchingDriver {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $driverOutput = & $Path --version
    if ($driverOutput -notmatch '(\d+\.\d+\.\d+)\.\d+') { return $false }
    return $Matches[1] -eq $runtimeBuild
}

$bundledDriver = Join-Path $env:EDGEWEBDRIVER "msedgedriver.exe"
if (Test-MatchingDriver -Path $bundledDriver) { return $bundledDriver }

$runnerTemp = (Resolve-Path -LiteralPath $env:RUNNER_TEMP).Path
$downloadDirectory = Join-Path $runnerTemp ("interntrack-webdriver-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $downloadDirectory | Out-Null
$archive = Join-Path $downloadDirectory "edgedriver.zip"
Invoke-WebRequest -Uri "https://msedgedriver.microsoft.com/$runtimeVersion/edgedriver_win64.zip" -OutFile $archive -TimeoutSec 60
Expand-Archive -LiteralPath $archive -DestinationPath $downloadDirectory
$driver = Join-Path $downloadDirectory "msedgedriver.exe"
if (-not (Test-MatchingDriver -Path $driver)) { throw "Downloaded Edge WebDriver does not match WebView2 $runtimeVersion." }
Write-Host "Using Microsoft Edge WebDriver matching WebView2 $runtimeVersion"
return $driver

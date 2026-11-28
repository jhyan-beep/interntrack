param(
    [Parameter(Mandatory)][string]$InstallerPath,
    [Parameter(Mandatory)][string]$OutputDirectory,
    [Parameter(Mandatory)][ValidatePattern('^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$')][string]$Version,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$SourceCommit,
    [Parameter(Mandatory)][ValidatePattern('^https://github\.com/[\w.-]+/[\w.-]+/actions/runs/[0-9]+$')][string]$BuildUrl
)

$ErrorActionPreference = "Stop"
$installer = Get-Item -LiteralPath $InstallerPath
$expectedName = "InternTrack_$($Version)_x64-setup.exe"
if ($installer.PSIsContainer -or $installer.Name -cne $expectedName -or $installer.Length -eq 0) {
    throw "Expected a nonempty Windows x64 installer named $expectedName."
}
if (Test-Path -LiteralPath $OutputDirectory) {
    throw "Choose a new output directory so that files from an older build cannot be included."
}

$repoRoot = Join-Path $PSScriptRoot "../.."
$package = New-Item -ItemType Directory -Path $OutputDirectory
$stagedInstaller = Join-Path $package.FullName $expectedName
Copy-Item -LiteralPath $installer.FullName -Destination $stagedInstaller
Copy-Item -LiteralPath (Join-Path $repoRoot "docs/user-guide.md") -Destination (Join-Path $package.FullName "TESTER-GUIDE.md")
Copy-Item -LiteralPath (Join-Path $repoRoot "LICENSE") -Destination (Join-Path $package.FullName "LICENSE.txt")

$digest = (Get-FileHash -LiteralPath $stagedInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath (Join-Path $package.FullName "SHA256SUMS.txt") -Value "$digest  $expectedName" -Encoding ascii

$instructions = @(
    "InternTrack $Version | Windows x64 beta",
    "Build: $BuildUrl",
    "Source commit: $SourceCommit",
    "",
    "This is an unsigned test installer.",
    "",
    "1. Extract the ZIP into a folder. Open PowerShell in that folder.",
    "2. Run: Get-FileHash -Algorithm SHA256 -LiteralPath '.\$expectedName'",
    "   Compare the Hash value with SHA256SUMS.txt. If the values differ, redownload",
    "   the package from the GitHub build above before installing.",
    "3. If upgrading, export a portable backup and choose Quit from the InternTrack",
    "   tray menu. Run $expectedName and keep the existing installation location.",
    "   If Windows blocks the installer, report the exact message to the maintainer.",
    "4. Open InternTrack, sign in, and create or edit a sample application.",
    "   Under Account settings > Local reminders, select Send test notification.",
    "   Check for InternTrack test notification in Windows Notification Center.",
    "",
    "See TESTER-GUIDE.md for the full test steps. Use Account settings > About &",
    "support > Report an issue to send feedback. Include the version and what",
    "you expected to happen, and remove any private information from attachments."
)
Set-Content -LiteralPath (Join-Path $package.FullName "START-HERE.txt") -Value $instructions -Encoding ascii
Write-Output "Prepared $Version beta package with installer SHA-256 $digest"

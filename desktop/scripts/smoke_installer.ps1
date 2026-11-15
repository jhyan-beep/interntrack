param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion,
    [string]$PythonExecutable = "python"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

# Installing changes registry/shortcuts. Keep this check on disposable hosted CI.
if ($env:GITHUB_ACTIONS -ne "true" -or $env:RUNNER_ENVIRONMENT -ne "github-hosted" -or $env:RUNNER_OS -ne "Windows") {
    throw "Installer verification requires a GitHub-hosted Windows runner."
}

$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$runnerTemp = (Resolve-Path -LiteralPath $env:RUNNER_TEMP).Path
$testRoot = [IO.Path]::GetFullPath((Join-Path $runnerTemp ("interntrack-installer-" + [guid]::NewGuid().ToString("N"))))
$tempPrefix = $runnerTemp.TrimEnd('\') + '\'
if (-not $testRoot.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Installer test directory must be inside RUNNER_TEMP."
}
$installDirectory = Join-Path $testRoot "installed"
New-Item -ItemType Directory -Path $testRoot | Out-Null

function Invoke-InstallerProcess {
    param([string]$Executable, [string[]]$Arguments)
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(120000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Installer process timed out."
    }
    if ($process.ExitCode -ne 0) {
        throw "Installer process returned exit code $($process.ExitCode)."
    }
}

try {
    # NSIS requires /D= and _?= to be last, with their paths unquoted.
    Invoke-InstallerProcess -Executable $installer -Arguments @("/S", "/D=$installDirectory")
    $sidecar = Join-Path $installDirectory "interntrack-api.exe"
    if (-not (Test-Path -LiteralPath $sidecar -PathType Leaf)) {
        throw "Installed API executable is missing from $installDirectory."
    }
    $uninstaller = @(Get-ChildItem -LiteralPath $installDirectory -Filter "*uninstall*.exe" -File)
    if ($uninstaller.Count -ne 1) {
        throw "Expected exactly one uninstaller in the isolated install directory."
    }
    $launchers = @(Get-ChildItem -LiteralPath $installDirectory -Filter "*.exe" -File | Where-Object {
        $_.Name -ne "interntrack-api.exe" -and $_.Name -notlike "*uninstall*"
    })
    if ($launchers.Count -ne 1) {
        throw "Expected exactly one desktop launcher in the installed payload."
    }
    Write-Output "PASS: NSIS installs the launcher, API, and uninstaller in the requested directory"
    & $PythonExecutable (Join-Path $PSScriptRoot "smoke_sidecar.py") --binary $sidecar --expected-version $ExpectedVersion
    if ($LASTEXITCODE -ne 0) { throw "Installed API smoke test failed." }
    & $PythonExecutable (Join-Path $PSScriptRoot "smoke_recovery.py") --binary $sidecar --expected-version $ExpectedVersion
    if ($LASTEXITCODE -ne 0) { throw "Installed recovery smoke test failed." }
    $edgeDriver = & (Join-Path $PSScriptRoot "resolve_webview_driver.ps1")
    $diagnosticsDirectory = Join-Path $runnerTemp "interntrack-desktop-smoke"
    & $PythonExecutable (Join-Path $PSScriptRoot "smoke_desktop.py") --launcher $launchers[0].FullName --edge-driver $edgeDriver --expected-version $ExpectedVersion --output-directory $diagnosticsDirectory
    if ($LASTEXITCODE -ne 0) { throw "Installed desktop window smoke test failed. See the desktop smoke diagnostics artifact." }
}
finally {
    $uninstaller = @(Get-ChildItem -LiteralPath $installDirectory -Filter "*uninstall*.exe" -File -ErrorAction SilentlyContinue)
    if ($uninstaller.Count -eq 1) {
        Invoke-InstallerProcess -Executable $uninstaller[0].FullName -Arguments @("/S", "_?=$installDirectory")
        $remaining = @(Get-ChildItem -LiteralPath $installDirectory -Filter "*.exe" -File -ErrorAction SilentlyContinue | Where-Object {
            $_.Name -notlike "*uninstall*"
        })
        if ($remaining.Count) {
            throw "Uninstall left application executables behind."
        }
        Write-Output "PASS: NSIS uninstall removes the installed application payload"
    }
    # The validated per-test directory contains only this check's generated files.
    $cleanupPath = (Resolve-Path -LiteralPath $testRoot).Path
    if (-not $cleanupPath.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase) -or $cleanupPath -ne $testRoot) {
        throw "Refusing cleanup outside the validated per-test directory."
    }
    Remove-Item -LiteralPath $cleanupPath -Recurse -Force
}

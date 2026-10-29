param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [string]$PythonExecutable = "python",
    [switch]$SkipFrontendInstall
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$binaryDirectory = Join-Path $repositoryRoot "desktop\src-tauri\binaries"
$sidecarSource = Join-Path $repositoryRoot "dist\interntrack-api.exe"
$sidecarTarget = Join-Path $binaryDirectory "interntrack-api-$TargetTriple.exe"

Push-Location $repositoryRoot
try {
    if (-not $SkipFrontendInstall) {
        pnpm --dir frontend install --frozen-lockfile
    }
    pnpm --dir frontend run build
    & $PythonExecutable -m PyInstaller --noconfirm --clean desktop\interntrack_api.spec

    New-Item -ItemType Directory -Force -Path $binaryDirectory | Out-Null
    Copy-Item -Force -LiteralPath $sidecarSource -Destination $sidecarTarget
    Write-Output "Desktop sidecar ready: $sidecarTarget"
}
finally {
    Pop-Location
}

param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [string]$PythonExecutable = "python",
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

Push-Location $repositoryRoot
try {
    if (-not $SkipDependencyInstall) {
        & $PythonExecutable -m pip install -r requirements.txt -r requirements-desktop.txt
        pnpm --dir frontend install --frozen-lockfile
        pnpm --dir desktop install --frozen-lockfile
    }

    & (Join-Path $PSScriptRoot "build_sidecar.ps1") -TargetTriple $TargetTriple -PythonExecutable $PythonExecutable -SkipFrontendInstall
    pnpm --dir desktop exec tauri build --target $TargetTriple
}
finally {
    Pop-Location
}

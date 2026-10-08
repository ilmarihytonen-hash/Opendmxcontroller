$ErrorActionPreference = "Stop"
if (-not (Test-Path ".git")) {
    throw "Run this updater from a LumenDesk Git checkout."
}
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw "Git update failed; resolve repository changes before rebuilding." }
& (Join-Path $PSScriptRoot "build_windows.ps1")

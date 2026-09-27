<#
.SYNOPSIS
    Run local quality gates for the NAGP app + Lambda sources. NO AWS calls.
.DESCRIPTION
    Uses the project-local .venv Python to run byte-compile checks and pytest.
    Exits non-zero on any failure.
#>
$ErrorActionPreference = 'Stop'
$repo   = Split-Path $PSScriptRoot -Parent
$venvPy = Join-Path $repo '.venv\Scripts\python.exe'

if (-not (Test-Path $venvPy)) {
    Write-Error "Project venv not found at $venvPy. Create it first: py -3.14 -m venv .venv; .\.venv\Scripts\python -m pip install -r requirements-dev.txt"
    exit 1
}

Push-Location $repo
try {
    Write-Host '== compileall (syntax check) ==' -ForegroundColor Cyan
    & $venvPy -m compileall -q app lambda_src conftest.py tests
    if ($LASTEXITCODE -ne 0) { Write-Error 'compileall failed'; exit 1 }

    Write-Host '== pytest ==' -ForegroundColor Cyan
    & $venvPy -m pytest -q
    if ($LASTEXITCODE -ne 0) { Write-Error 'pytest failed'; exit 1 }

    Write-Host 'Local tests PASSED.' -ForegroundColor Green
}
finally {
    Pop-Location
}

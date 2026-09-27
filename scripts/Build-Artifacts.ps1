<#
.SYNOPSIS
    Run local tests, then build both artifacts. NO AWS interaction.
.DESCRIPTION
    1. Test-Local.ps1 (stops on failure)
    2. Build-AppArtifact.ps1
    3. Build-LambdaArtifact.ps1
    4. Summary of paths, sizes, and SHA-256 hashes.
#>
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent

Write-Host '===== 1/3 local tests =====' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'Test-Local.ps1')
if ($LASTEXITCODE -ne 0) { Write-Error 'Tests failed; aborting build.'; exit 1 }

Write-Host '===== 2/3 app artifact =====' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'Build-AppArtifact.ps1')
if ($LASTEXITCODE -ne 0) { Write-Error 'App artifact build failed.'; exit 1 }

Write-Host '===== 3/3 lambda artifact =====' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'Build-LambdaArtifact.ps1')
if ($LASTEXITCODE -ne 0) { Write-Error 'Lambda artifact build failed.'; exit 1 }

Write-Host '===== summary =====' -ForegroundColor Green
foreach ($p in @((Join-Path $repo 'dist\app\app.zip'), (Join-Path $repo 'dist\lambda\lambda.zip'))) {
    if (Test-Path $p) {
        $size = (Get-Item $p).Length
        $hash = (Get-FileHash $p -Algorithm SHA256).Hash
        Write-Host ("{0}`n  size   : {1} bytes`n  sha256 : {2}" -f $p, $size, $hash)
    }
}

<#
.SYNOPSIS
    Build the Lambda deployment zip dist\lambda\lambda.zip (Python 3.14 runtime).
.DESCRIPTION
    ZIP root contains handler.py plus PyMySQL (pure Python) and its metadata.
    boto3/botocore are NOT bundled (provided by the managed Lambda runtime).
    Excludes tests, .venv, caches, docs, credentials, and VCS metadata. NO AWS calls.
#>
$ErrorActionPreference = 'Stop'

function New-ZipFromDir([string]$SourceDir, [string]$ZipPath) {
    # Build a zip with FORWARD-SLASH entry names (Compress-Archive on Windows
    # PowerShell writes backslashes, which breaks imports on the Linux Lambda runtime).
    Add-Type -AssemblyName System.IO.Compression | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null
    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
    $base = (Resolve-Path $SourceDir).Path.TrimEnd('\')
    $fs = [System.IO.File]::Open($ZipPath, [System.IO.FileMode]::CreateNew)
    try {
        $zip = New-Object System.IO.Compression.ZipArchive($fs, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            Get-ChildItem -Path $SourceDir -Recurse -File | ForEach-Object {
                $rel = $_.FullName.Substring($base.Length + 1).Replace('\', '/')
                $entry = $zip.CreateEntry($rel, [System.IO.Compression.CompressionLevel]::Optimal)
                $es = $entry.Open()
                try {
                    $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
                    $es.Write($bytes, 0, $bytes.Length)
                } finally { $es.Dispose() }
            }
        } finally { $zip.Dispose() }
    } finally { $fs.Dispose() }
}

$repo    = Split-Path $PSScriptRoot -Parent
$venvPy  = Join-Path $repo '.venv\Scripts\python.exe'
$stage   = Join-Path $repo '.build\lambda-stage'
$outDir  = Join-Path $repo 'dist\lambda'
$zipPath = Join-Path $outDir 'lambda.zip'

if (-not (Test-Path $venvPy)) { Write-Error "Project venv not found at $venvPy"; exit 1 }

# Clean staging + previous output
if (Test-Path $stage)   { Remove-Item $stage -Recurse -Force }
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
New-Item -ItemType Directory -Path $stage  -Force | Out-Null
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

# handler.py at ZIP root
Copy-Item (Join-Path $repo 'lambda_src\handler.py') (Join-Path $stage 'handler.py') -Force

# Install ONLY lambda deps (PyMySQL) into the staging dir
$reqs = Join-Path $repo 'lambda_src\requirements.txt'
& $venvPy -m pip install --no-compile --target $stage -r $reqs
if ($LASTEXITCODE -ne 0) { Write-Error 'pip install for Lambda deps failed'; exit 1 }

# Defensive cleanup: never ship SDK/tests/caches
foreach ($junk in 'boto3','botocore','bin','tests','__pycache__') {
    Get-ChildItem $stage -Recurse -Force -Filter $junk -ErrorAction SilentlyContinue |
        Where-Object { $_.PSIsContainer } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
Get-ChildItem $stage -Recurse -Include '*.pyc' -File -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

# Validate BEFORE zipping
if (-not (Test-Path (Join-Path $stage 'handler.py'))) { Write-Error 'handler.py missing at zip root'; exit 1 }
if (-not (Test-Path (Join-Path $stage 'pymysql')))    { Write-Error 'pymysql package missing'; exit 1 }
if (Test-Path (Join-Path $stage 'boto3'))  { Write-Error 'boto3 must NOT be bundled'; exit 1 }

# Package (forward-slash entry names)
New-ZipFromDir -SourceDir $stage -ZipPath $zipPath

# Report + validation
$size = (Get-Item $zipPath).Length
$hash = (Get-FileHash $zipPath -Algorithm SHA256).Hash
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $entries    = $zip.Entries
    $hasHandler = @($entries | Where-Object { $_.FullName -eq 'handler.py' }).Count -eq 1
    $hasPyMySQL = @($entries | Where-Object { $_.FullName -like 'pymysql/*' }).Count -gt 0
    $hasBoto    = @($entries | Where-Object { $_.FullName -like 'boto3/*' -or $_.FullName -like 'botocore/*' }).Count -gt 0
    $count      = $entries.Count
    Write-Host "lambda.zip : $zipPath" -ForegroundColor Green
    Write-Host ("size       : {0} bytes" -f $size)
    Write-Host ("sha256     : {0}" -f $hash)
    Write-Host ("entries    : {0}" -f $count)
    Write-Host ("handler.py at root : {0}" -f $hasHandler)
    Write-Host ("pymysql bundled    : {0}" -f $hasPyMySQL)
    Write-Host ("boto3/botocore     : {0} (must be False)" -f $hasBoto)
    Write-Host '== top-level entries ==' -ForegroundColor Cyan
    $entries | Where-Object { $_.FullName -notmatch '/.+/' } |
        ForEach-Object { Write-Host ("  {0}" -f $_.FullName) } | Select-Object -First 40
    if (-not $hasHandler) { Write-Error 'validation: handler.py not at root'; exit 1 }
    if (-not $hasPyMySQL) { Write-Error 'validation: pymysql not bundled'; exit 1 }
    if ($hasBoto)         { Write-Error 'validation: boto3/botocore bundled'; exit 1 }
}
finally { $zip.Dispose() }

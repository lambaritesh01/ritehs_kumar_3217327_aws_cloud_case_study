<#
.SYNOPSIS
    Build the EC2 application artifact dist\app\app.zip (source only, NO vendored deps).
.DESCRIPTION
    The AMI builder later downloads this zip from private S3 (artifacts/app/), creates
    its own venv, and pip-installs app\requirements.txt. So this archive contains only
    app.py, templates\, and requirements.txt. No tests, venv, caches, docs, or secrets.
    NO AWS calls.
#>
$ErrorActionPreference = 'Stop'

function New-ZipFromDir([string]$SourceDir, [string]$ZipPath) {
    # Build a zip with FORWARD-SLASH entry names (Compress-Archive on Windows
    # PowerShell writes backslashes, which breaks unzip/imports on Linux/Lambda).
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
$stage   = Join-Path $repo '.build\app-stage'
$outDir  = Join-Path $repo 'dist\app'
$zipPath = Join-Path $outDir 'app.zip'

# Clean staging + previous output
if (Test-Path $stage)   { Remove-Item $stage -Recurse -Force }
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
New-Item -ItemType Directory -Path $stage  -Force | Out-Null
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

# Copy only the runtime application material
$appSrc = Join-Path $repo 'app'
Copy-Item (Join-Path $appSrc 'app.py')          (Join-Path $stage 'app.py')          -Force
Copy-Item (Join-Path $appSrc 'requirements.txt')(Join-Path $stage 'requirements.txt')-Force
Copy-Item (Join-Path $appSrc 'templates')       (Join-Path $stage 'templates') -Recurse -Force

# Defensive: strip any caches that might have been copied
Get-ChildItem $stage -Recurse -Include '__pycache__' -Directory -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $stage -Recurse -Include '*.pyc' -File -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

# Package (forward-slash entry names)
New-ZipFromDir -SourceDir $stage -ZipPath $zipPath

# Report
$size = (Get-Item $zipPath).Length
$hash = (Get-FileHash $zipPath -Algorithm SHA256).Hash
Write-Host "app.zip : $zipPath" -ForegroundColor Green
Write-Host ("size    : {0} bytes" -f $size)
Write-Host ("sha256  : {0}" -f $hash)
Write-Host '== contents ==' -ForegroundColor Cyan
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try { $zip.Entries | ForEach-Object { Write-Host ("  {0}" -f $_.FullName) } }
finally { $zip.Dispose() }

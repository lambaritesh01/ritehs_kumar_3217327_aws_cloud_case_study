<#
.SYNOPSIS
    Build the reviewer submission ZIP from an explicit allowlist. NO AWS calls.
.DESCRIPTION
    Stages only reviewer-facing sources/docs/scripts (never the whole repo), writes a
    SUBMISSION_MANIFEST.txt (commit, build time, per-file SHA-256), and produces
    dist\submission\nagp-aws-cloud-case-study.zip with forward-slash entry names.
    Internal tooling, secrets, local state, build output, and VCS data are excluded by
    virtue of not being on the allowlist.
#>
$ErrorActionPreference = 'Stop'

function New-ZipFromDir([string]$SourceDir, [string]$ZipPath) {
    Add-Type -AssemblyName System.IO.Compression | Out-Null
    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
    $base = (Resolve-Path $SourceDir).Path.TrimEnd('\')
    $fs = [System.IO.File]::Open($ZipPath, [System.IO.FileMode]::CreateNew)
    try {
        $zip = New-Object System.IO.Compression.ZipArchive($fs, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            Get-ChildItem -Path $SourceDir -Recurse -File | Sort-Object FullName | ForEach-Object {
                $rel = $_.FullName.Substring($base.Length + 1).Replace('\', '/')
                $entry = $zip.CreateEntry($rel, [System.IO.Compression.CompressionLevel]::Optimal)
                $es = $entry.Open()
                try { $bytes = [System.IO.File]::ReadAllBytes($_.FullName); $es.Write($bytes, 0, $bytes.Length) }
                finally { $es.Dispose() }
            }
        } finally { $zip.Dispose() }
    } finally { $fs.Dispose() }
}

$repo  = Split-Path $PSScriptRoot -Parent
$stage = Join-Path $repo '.build\submission-stage'
$out   = Join-Path $repo 'dist\submission'
$zip   = Join-Path $out 'nagp-aws-cloud-case-study.zip'

# --- Explicit allowlist (relative paths) ---
$allow = @(
    'README.md', 'requirements-dev.txt', 'conftest.py',
    'app/app.py', 'app/requirements.txt', 'app/templates/index.html',
    'lambda_src/__init__.py', 'lambda_src/handler.py', 'lambda_src/requirements.txt',
    'infra/foundation.yaml', 'infra/builder.yaml', 'infra/application.yaml', 'infra/README.md',
    'tests/test_app.py', 'tests/test_lambda_handler.py',
    'scripts/Build-AppArtifact.ps1', 'scripts/Build-LambdaArtifact.ps1', 'scripts/Build-Artifacts.ps1',
    'scripts/Test-Local.ps1', 'scripts/Test-Infrastructure.ps1', 'scripts/Build-Submission.ps1',
    'docs/ASSIGNMENT.md', 'docs/ARCHITECTURE.md', 'docs/architecture.mmd', 'docs/architecture.svg',
    'docs/COMPONENTS.md', 'docs/SCOPE_AND_ASSUMPTIONS.md', 'docs/DEPLOYMENT.md', 'docs/SECURITY_DESIGN.md',
    'docs/VALIDATION.md', 'docs/REQUIREMENTS_TRACEABILITY.md', 'docs/DEMO_PLAN.md',
    'docs/IMPLEMENTATION_PLAN.md', 'docs/COST_AND_CLEANUP.md', 'docs/DECISIONS.md'
)

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage -Force | Out-Null
New-Item -ItemType Directory -Path $out   -Force | Out-Null

$missing = @()
foreach ($rel in $allow) {
    $src = Join-Path $repo $rel
    if (-not (Test-Path $src)) { $missing += $rel; continue }
    $dst = Join-Path $stage $rel
    New-Item -ItemType Directory -Path (Split-Path $dst -Parent) -Force | Out-Null
    Copy-Item $src $dst -Force
}
if ($missing.Count -gt 0) { Write-Error ("Allowlisted files missing: " + ($missing -join ', ')); exit 1 }

# --- Manifest ---
try { $sha = (git -C $repo rev-parse HEAD).Trim() } catch { $sha = 'unknown' }
$built = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$staged = Get-ChildItem -Path $stage -Recurse -File | Sort-Object { $_.FullName.Substring($stage.Length + 1).Replace('\','/') }
$lines = @()
$lines += 'NAGP AWS Cloud Case Study - Submission Manifest'
$lines += "Source commit: $sha"
$lines += "Built (UTC): $built"
$lines += ("Files: " + ($staged.Count + 1))
$lines += ''
foreach ($f in $staged) {
    $rel = $f.FullName.Substring($stage.Length + 1).Replace('\','/')
    $h = (Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower()
    $lines += ('{0}  {1}' -f $h, $rel)
}
$manifestPath = Join-Path $stage 'SUBMISSION_MANIFEST.txt'
Set-Content -Path $manifestPath -Value $lines -Encoding ascii

# --- Package ---
New-ZipFromDir -SourceDir $stage -ZipPath $zip

# --- Report ---
$size = (Get-Item $zip).Length
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash
Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null
$z = [System.IO.Compression.ZipFile]::OpenRead($zip)
try { $count = $z.Entries.Count } finally { $z.Dispose() }
Write-Host "submission : $zip" -ForegroundColor Green
Write-Host ("size       : {0} bytes" -f $size)
Write-Host ("sha256     : {0}" -f $hash)
Write-Host ("files      : {0}" -f $count)

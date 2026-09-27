<#
.SYNOPSIS
    Lint and safety-check the CloudFormation templates. NO AWS API calls.
.DESCRIPTION
    Runs cfn-lint from the project .venv against infra/*.yaml and applies repository
    safety checks (no NAT gateway, no public RDS, no Multi-AZ, no access keys, no SSH
    key pair, no hardcoded 12-digit account id). Exits non-zero on any failure.
#>
$ErrorActionPreference = 'Stop'
$repo    = Split-Path $PSScriptRoot -Parent
$venvPy  = Join-Path $repo '.venv\Scripts\python.exe'
$cfnLint = Join-Path $repo '.venv\Scripts\cfn-lint.exe'
$infra   = Join-Path $repo 'infra'

if (-not (Test-Path $venvPy))  { Write-Error "Project venv not found at $venvPy"; exit 1 }
if (-not (Test-Path $cfnLint)) { Write-Error "cfn-lint not found; run: .\.venv\Scripts\python -m pip install -r requirements-dev.txt"; exit 1 }

$templates = 'foundation.yaml', 'builder.yaml', 'application.yaml'
foreach ($t in $templates) {
    if (-not (Test-Path (Join-Path $infra $t))) { Write-Error "Missing template: infra/$t"; exit 1 }
}

Write-Host '== cfn-lint ==' -ForegroundColor Cyan
& $cfnLint (Join-Path $infra 'foundation.yaml') (Join-Path $infra 'builder.yaml') (Join-Path $infra 'application.yaml')
if ($LASTEXITCODE -ne 0) { Write-Error 'cfn-lint reported findings'; exit 1 }

Write-Host '== safety checks ==' -ForegroundColor Cyan
$all = (Get-ChildItem $infra -Filter '*.yaml' | Get-Content -Raw) -join "`n"
$fail = $false
function Deny($label, $pattern) {
    if ($script:all -match $pattern) { Write-Host "FAIL: $label" -ForegroundColor Red; $script:fail = $true }
    else { Write-Host "ok  : $label" }
}
function Require($label, $pattern) {
    if ($script:all -match $pattern) { Write-Host "ok  : $label" }
    else { Write-Host "FAIL: $label" -ForegroundColor Red; $script:fail = $true }
}
Deny 'no NAT gateway'          'AWS::EC2::NatGateway'
Deny 'no Elastic IP'           'AWS::EC2::EIP'
Deny 'no IAM access keys'      'AWS::IAM::AccessKey'
Deny 'RDS not public'          'PubliclyAccessible:\s*true'
Deny 'RDS not Multi-AZ'        'MultiAZ:\s*true'
Deny 'no SSH KeyName'          'KeyName:'
Deny 'no 12-digit account id'  '\b\d{12}\b'
Deny 'no t2.micro (not Free-plan eligible)' 't2\.micro'

# Positive assertions
Require 'DeletionPolicy: Delete present'        'DeletionPolicy:\s*Delete'
Require 'RDS-managed master password'           'ManageMasterUserPassword:\s*true'
Require 'EC2 instances use t3.micro'            'InstanceType:\s*t3\.micro'
Require 'EC2 CPU credits standard (builder)'    'CPUCredits:\s*standard'
Require 'EC2 CPU credits standard (app LT)'     'CpuCredits:\s*standard'
Require 'ASG MinSize 2'                          "MinSize:\s*'2'"
Require 'ASG DesiredCapacity 2'                  "DesiredCapacity:\s*'2'"
Require 'ASG MaxSize uses AsgMaxSize parameter'  'MaxSize:\s*!Ref AsgMaxSize'
Require 'AsgMaxSize default 2'                   'AsgMaxSize:[\s\S]*?Default:\s*2'
Require 'AsgMaxSize allows 2 and 4'             'AllowedValues:\s*\[2,\s*4\]'
Require 'target-tracking CPU 50'                'TargetValue:\s*50'
Require 'builder phase-aware failure signal'    'Builder bootstrap failed during'
Require 'builder verifies AWS CLI preflight'    'verify-aws-cli'
Require 'builder health-check before success'   'health-check'
Require 'builder installs Python 3.11 runtime'  'python3\.11-pip'
Require 'app venv built with python3.11'         'python3\.11 -m venv'
Deny    'no external unzip dependency'          '\bunzip\b'
Deny    'no pip self-upgrade in builder'        'upgrade pip'
Deny    'no system python3 symlink change'      'ln -s|alternatives'
Require 'app LT writes runtime env file'        '/etc/nagp-app\.env'
Require 'app LT restarts service after config'  'systemctl restart nagp-app\.service'
Deny    'no enable --now (must restart)'        'enable --now'

if ($fail) { Write-Error 'Infrastructure safety checks failed'; exit 1 }
Write-Host 'Infrastructure checks PASSED.' -ForegroundColor Green

#!/usr/bin/env pwsh

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Info([string]$msg) { Write-Host "[launcher] $msg" -ForegroundColor Cyan }
function Ok([string]$msg) { Write-Host "[launcher] $msg" -ForegroundColor Green }
function Fail([string]$msg) { Write-Host "[launcher] $msg" -ForegroundColor Red; exit 1 }

function Get-ManualInstallHint() {
  return @"
Run these commands from this folder first:
1) uv venv .venv
2) .\.venv\Scripts\Activate.ps1
3) uv pip install langflow -U

Then run .\installer.ps1 once to apply the patch.
"@
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Installer = Join-Path $Root "installer.ps1"
$LangflowExe = Join-Path $Root ".venv\Scripts\langflow.exe"

if (-not (Test-Path $Installer)) {
  Fail "Missing installer script: $Installer"
}

if (-not (Test-Path $LangflowExe)) {
  Fail ("Missing Langflow executable: $LangflowExe`n`n" + (Get-ManualInstallHint))
}

Info "Ensuring LangPatcher is applied"
& $Installer
if ($LASTEXITCODE -ne 0) {
  Fail "Installer failed"
}

$launchArgs = @()
if ($args.Count -eq 0) {
  $launchArgs = @("run")
} else {
  $launchArgs = $args
}

Info "Launching Langflow from $Root"
Push-Location $Root
try {
  & $LangflowExe @launchArgs
  $exitCode = $LASTEXITCODE
} finally {
  Pop-Location
}

if ($exitCode -ne 0) {
  Fail "Langflow exited with code $exitCode"
}

Ok "Langflow exited cleanly"

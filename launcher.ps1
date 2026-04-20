#!/usr/bin/env pwsh

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Info([string]$msg) { Write-Host "[launcher] $msg" -ForegroundColor Cyan }
function Ok([string]$msg) { Write-Host "[launcher] $msg" -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "[launcher] $msg" -ForegroundColor Yellow }
function Fail([string]$msg) { Write-Host "[launcher] $msg" -ForegroundColor Red; exit 1 }

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Installer = Join-Path $Root "installer.ps1"
$TargetRoot = Join-Path $Root "langflow"
$LangflowExe = Join-Path $Root ".venv\Scripts\langflow.exe"

if (-not (Test-Path $Installer)) {
  Fail "Missing installer script: $Installer"
}

if (-not (Test-Path $TargetRoot) -or -not (Test-Path $LangflowExe)) {
  Warn "Local Langflow install not found. Running installer first."
  & $Installer
  if ($LASTEXITCODE -ne 0) {
    Fail "Installer failed"
  }
}

if (-not (Test-Path $TargetRoot)) {
  Fail "Missing Langflow checkout: $TargetRoot"
}

if (-not (Test-Path $LangflowExe)) {
  Fail "Missing Langflow launcher executable: $LangflowExe"
}

$launchArgs = @()
if ($args.Count -eq 0) {
  $launchArgs = @("run")
} else {
  $launchArgs = $args
}

Info "Launching Langflow from $TargetRoot"
Push-Location $TargetRoot
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

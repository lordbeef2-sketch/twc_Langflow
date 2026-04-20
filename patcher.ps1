#!/usr/bin/env pwsh

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Installer = Join-Path $Root "installer.ps1"

if (-not (Test-Path $Installer)) {
  Write-Host "[patcher] Missing installer script: $Installer" -ForegroundColor Red
  exit 1
}

Write-Host "[patcher] patcher.ps1 has been replaced by installer.ps1. Forwarding..." -ForegroundColor Yellow
& $Installer @args
exit $LASTEXITCODE

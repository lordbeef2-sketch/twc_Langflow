#!/usr/bin/env pwsh

param(
  [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Info([string]$msg) { Write-Host "[installer] $msg" -ForegroundColor Cyan }
function Ok([string]$msg) { Write-Host "[installer] $msg" -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "[installer] $msg" -ForegroundColor Yellow }
function Fail([string]$msg) { Write-Host "[installer] $msg" -ForegroundColor Red; exit 1 }

function Test-IsWindows() {
  return [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
}

function Get-ManualInstallHint() {
  return @"
Run these commands from this folder first:
1) uv venv .venv
2) .\.venv\Scripts\Activate.ps1
3) uv pip install langflow -U

Then rerun .\installer.ps1.
"@
}

function Get-RelativePath([string]$root, [string]$path) {
  $resolvedRoot = [System.IO.Path]::GetFullPath($root)
  $resolvedPath = [System.IO.Path]::GetFullPath($path)

  if (
    -not $resolvedRoot.EndsWith([System.IO.Path]::DirectorySeparatorChar) -and
    -not $resolvedRoot.EndsWith([System.IO.Path]::AltDirectorySeparatorChar)
  ) {
    $resolvedRoot = $resolvedRoot + [System.IO.Path]::DirectorySeparatorChar
  }

  $rootUri = [System.Uri]::new($resolvedRoot)
  $pathUri = [System.Uri]::new($resolvedPath)
  $relativeUri = $rootUri.MakeRelativeUri($pathUri)
  return [System.Uri]::UnescapeDataString($relativeUri.ToString()).Replace("/", [System.IO.Path]::DirectorySeparatorChar)
}

function Assert-PathWithinRoot([string]$path, [string]$root) {
  $resolvedPath = [System.IO.Path]::GetFullPath($path)
  $resolvedRoot = [System.IO.Path]::GetFullPath($root)
  if (-not $resolvedPath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    Fail "Refusing to modify path outside target root: $resolvedPath"
  }
}

function Get-FileSha256([string]$path) {
  return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-DirectoryFingerprint([string]$root) {
  if (-not (Test-Path $root)) {
    return ""
  }

  $entries = New-Object System.Collections.Generic.List[string]
  foreach ($file in Get-ChildItem -Path $root -Recurse -File | Sort-Object FullName) {
    if ($file.Extension -eq ".pyc" -or $file.DirectoryName -match "(^|\\)__pycache__(\\|$)") {
      continue
    }
    $relativePath = (Get-RelativePath -root $root -path $file.FullName).Replace("\", "/")
    $fileHash = Get-FileSha256 $file.FullName
    $entries.Add("$relativePath|$fileHash")
  }

  $combined = [string]::Join("`n", $entries)
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($combined)
  $stream = [System.IO.MemoryStream]::new($bytes)
  try {
    return (Get-FileHash -InputStream $stream -Algorithm SHA256).Hash.ToLowerInvariant()
  } finally {
    $stream.Dispose()
  }
}

function Read-InstallState([string]$path) {
  if (-not (Test-Path $path)) {
    return $null
  }

  try {
    return Get-Content -Path $path -Raw | ConvertFrom-Json
  } catch {
    Warn "Install state file is invalid at $path. Reapplying patch."
    return $null
  }
}

function Write-InstallState(
  [string]$path,
  [string]$pythonVersion,
  [string]$langflowVersion,
  [string]$langflowRoot,
  [string]$lfxRoot,
  [string]$payloadFingerprint,
  [string]$installerFingerprint
) {
  $stateDir = Split-Path -Parent $path
  if (-not (Test-Path $stateDir)) {
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
  }

  $state = [ordered]@{
    stateVersion = 2
    pythonVersion = $pythonVersion
    langflowVersion = $langflowVersion
    langflowRoot = $langflowRoot
    lfxRoot = $lfxRoot
    payloadFingerprint = $payloadFingerprint
    installerFingerprint = $installerFingerprint
    updatedAt = (Get-Date).ToString("o")
  }

  $state | ConvertTo-Json | Set-Content -Path $path -NoNewline
}

function Use-ExistingLocalVenv([string]$venvPath) {
  if (-not (Test-Path $venvPath)) {
    Fail ("Missing local .venv.`n`n" + (Get-ManualInstallHint))
  }

  $activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
  if (-not (Test-Path $activateScript)) {
    Fail ("Missing activation script: $activateScript`n`n" + (Get-ManualInstallHint))
  }

  Info "Reusing local Python environment at $venvPath"
  . $activateScript
}

function Assert-SupportedPython() {
  $pythonVersionOutput = & python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
  if ($LASTEXITCODE -ne 0 -or $null -eq $pythonVersionOutput) {
    Fail "Unable to determine the Python version in the local environment"
  }

  $pythonVersion = ([string]::Join("`n", @($pythonVersionOutput))).Trim()
  if ([string]::IsNullOrWhiteSpace($pythonVersion)) {
    Fail "Unable to determine the Python version in the local environment"
  }

  Ok "Using Python $pythonVersion in the local environment"
  return $pythonVersion
}

function Get-InstalledPackageLayout() {
  $script = @'
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path

payload = {"installed": False}

if importlib.util.find_spec("langflow") is not None and importlib.util.find_spec("lfx") is not None:
    import langflow
    import lfx

    payload = {
        "installed": True,
        "langflowVersion": metadata.version("langflow"),
        "langflowRoot": str(Path(langflow.__file__).resolve().parent),
        "lfxRoot": str(Path(lfx.__file__).resolve().parent),
    }

print(json.dumps(payload))
'@

  $layoutOutput = $script | & python -
  if ($LASTEXITCODE -ne 0 -or $null -eq $layoutOutput) {
    Fail ("Unable to inspect the installed Langflow package.`n`n" + (Get-ManualInstallHint))
  }

  $layoutJson = ([string]::Join("`n", @($layoutOutput))).Trim()
  if ([string]::IsNullOrWhiteSpace($layoutJson)) {
    Fail ("Unable to inspect the installed Langflow package.`n`n" + (Get-ManualInstallHint))
  }

  $layout = $layoutJson | ConvertFrom-Json
  if (-not $layout.installed) {
    Fail ("Langflow is not installed in this local environment.`n`n" + (Get-ManualInstallHint))
  }

  return $layout
}

function Copy-Tree([string]$sourceRoot, [string]$destinationRoot) {
  if (-not (Test-Path $sourceRoot)) {
    Fail "Missing payload directory: $sourceRoot"
  }

  if (-not (Test-Path $destinationRoot)) {
    New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null
  }

  $copied = 0
  foreach ($file in Get-ChildItem -Path $sourceRoot -Recurse -File | Sort-Object FullName) {
    if ($file.Extension -eq ".pyc" -or $file.DirectoryName -match "(^|\\)__pycache__(\\|$)") {
      continue
    }
    $relativePath = Get-RelativePath -root $sourceRoot -path $file.FullName
    $destinationPath = Join-Path $destinationRoot $relativePath
    $destinationDir = Split-Path -Parent $destinationPath

    Assert-PathWithinRoot -path $destinationPath -root $destinationRoot

    if (-not (Test-Path $destinationDir)) {
      New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
    }

    Copy-Item -Path $file.FullName -Destination $destinationPath -Force
    $copied++
  }

  return $copied
}

function Install-FrontendBundle([string]$bundlePath, [string]$destinationRoot) {
  if (-not (Test-Path $bundlePath)) {
    Fail "Missing built frontend bundle: $bundlePath"
  }

  if (-not (Test-Path $destinationRoot)) {
    New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null
  }

  $extractRoot = Join-Path $env:TEMP ("langpatcher-frontend-" + [guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null

  try {
    Expand-Archive -LiteralPath $bundlePath -DestinationPath $extractRoot -Force

    Assert-PathWithinRoot -path $destinationRoot -root $destinationRoot
    Get-ChildItem -Path $destinationRoot -Force | Remove-Item -Recurse -Force
    Copy-Item -Path (Join-Path $extractRoot "*") -Destination $destinationRoot -Recurse -Force
  } finally {
    if (Test-Path $extractRoot) {
      Remove-Item -Recurse -Force $extractRoot
    }
  }

  return (Get-ChildItem -Path $destinationRoot -Recurse -File | Measure-Object).Count
}

function Ensure-EnvSetting([string]$envFile, [string]$key, [string]$value) {
  $line = "$key=$value"

  if (Test-Path $envFile) {
    $envContent = Get-Content -Path $envFile -Raw
    if ($envContent -match "(?m)^\s*$key\s*=") {
      $updated = [regex]::Replace(
        $envContent,
        "(?m)^\s*$key\s*=.*$",
        $line
      )
      Set-Content -Path $envFile -Value $updated -NoNewline
      return
    }

    $trimmed = $envContent.TrimEnd("`r", "`n")
    if ($trimmed.Length -gt 0) {
      $trimmed = $trimmed + "`r`n"
    }
    Set-Content -Path $envFile -Value ($trimmed + $line + "`r`n") -NoNewline
    return
  }

  Set-Content -Path $envFile -Value ($line + "`r`n") -NoNewline
}

$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $PackageRoot

$PayloadRoot = Join-Path $PackageRoot "patcher_payload"
$BackendPayloadRoot = Join-Path $PayloadRoot "src\backend\base\langflow"
$LfxPayloadRoot = Join-Path $PayloadRoot "src\lfx\src\lfx"
$FrontendBundlePath = Join-Path $PayloadRoot "frontend_build.zip"
$VenvPath = Join-Path $PackageRoot ".venv"
$StateFile = Join-Path $VenvPath "langpatcher-state.json"
$EnvFile = Join-Path $PackageRoot ".env"

if (-not (Test-Path $PayloadRoot)) {
  Fail "Missing payload directory: $PayloadRoot"
}

Use-ExistingLocalVenv -venvPath $VenvPath
$PythonVersion = Assert-SupportedPython
$Layout = Get-InstalledPackageLayout
$InstalledLangflowVersion = [string]$Layout.langflowVersion
$LangflowRoot = [string]$Layout.langflowRoot
$LfxRoot = [string]$Layout.lfxRoot
$PayloadFingerprint = Get-DirectoryFingerprint $PayloadRoot
$InstallerFingerprint = Get-FileSha256 $MyInvocation.MyCommand.Path
$InstallState = Read-InstallState $StateFile

if ($Force) {
  Warn "Force mode enabled. LangPatcher will reapply all patch files."
}

$HasMatchingPatchedInstall = (
  -not $Force -and
  $null -ne $InstallState -and
  $InstallState.pythonVersion -eq $PythonVersion -and
  $InstallState.langflowVersion -eq $InstalledLangflowVersion -and
  $InstallState.langflowRoot -eq $LangflowRoot -and
  $InstallState.lfxRoot -eq $LfxRoot -and
  $InstallState.payloadFingerprint -eq $PayloadFingerprint -and
  $InstallState.installerFingerprint -eq $InstallerFingerprint -and
  (Test-Path $LangflowRoot) -and
  (Test-Path $LfxRoot)
)

if ($HasMatchingPatchedInstall) {
  Ok "LangPatcher is already applied for Langflow $InstalledLangflowVersion. Skipping patch."
  Write-Host "Run: .\launcher.ps1" -ForegroundColor White
  exit 0
}

Info "Applying backend patch files to $LangflowRoot"
$backendCopied = Copy-Tree -sourceRoot $BackendPayloadRoot -destinationRoot $LangflowRoot
Ok "Copied $backendCopied backend files"

Info "Applying LFX patch files to $LfxRoot"
$lfxCopied = Copy-Tree -sourceRoot $LfxPayloadRoot -destinationRoot $LfxRoot
Ok "Copied $lfxCopied LFX files"

$InstalledFrontendRoot = Join-Path $LangflowRoot "frontend"
Info "Replacing built frontend assets in $InstalledFrontendRoot"
$frontendFiles = Install-FrontendBundle -bundlePath $FrontendBundlePath -destinationRoot $InstalledFrontendRoot
Ok "Installed $frontendFiles frontend files"

Info "Ensuring LANGFLOW_AUTO_LOGIN=false in $EnvFile"
Ensure-EnvSetting -envFile $EnvFile -key "LANGFLOW_AUTO_LOGIN" -value "false"
Info "Ensuring TWC_AUTO_LOGIN=true in $EnvFile"
Ensure-EnvSetting -envFile $EnvFile -key "TWC_AUTO_LOGIN" -value "true"
Ok "Configured .env with LANGFLOW_AUTO_LOGIN=false and TWC_AUTO_LOGIN=true"

Write-InstallState `
  -path $StateFile `
  -pythonVersion $PythonVersion `
  -langflowVersion $InstalledLangflowVersion `
  -langflowRoot $LangflowRoot `
  -lfxRoot $LfxRoot `
  -payloadFingerprint $PayloadFingerprint `
  -installerFingerprint $InstallerFingerprint

Ok "Patch completed."
Write-Host "Run: .\launcher.ps1" -ForegroundColor White

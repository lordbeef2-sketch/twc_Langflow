#!/usr/bin/env pwsh

param(
  [string]$PythonSpec = "3.11",
  [string]$OutputRoot = "",
  [switch]$Clean,
  [switch]$SkipFrontendBuild,
  [bool]$CreateZip = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Info([string]$msg) { Write-Host "[offline-bundle] $msg" -ForegroundColor Cyan }
function Ok([string]$msg) { Write-Host "[offline-bundle] $msg" -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "[offline-bundle] $msg" -ForegroundColor Yellow }
function Fail([string]$msg) { Write-Host "[offline-bundle] $msg" -ForegroundColor Red; exit 1 }

function Test-IsWindows() {
  return [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
}

function Ensure-Command([string]$name, [string]$installHint) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    Fail "Missing required command '$name'. $installHint"
  }
}

function Get-NpmCommand() {
  if ((Test-IsWindows) -and (Get-Command "npm.cmd" -ErrorAction SilentlyContinue)) {
    return "npm.cmd"
  }

  return "npm"
}

function Assert-PathWithinRoot([string]$path, [string]$root) {
  $resolvedPath = [System.IO.Path]::GetFullPath($path)
  $resolvedRoot = [System.IO.Path]::GetFullPath($root)
  if (-not $resolvedPath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    Fail "Refusing to modify path outside package root: $resolvedPath"
  }
}

function Remove-DirectoryInsideRoot([string]$path, [string]$root) {
  if (-not (Test-Path $path)) {
    return
  }

  Assert-PathWithinRoot -path $path -root $root
  Remove-Item -LiteralPath $path -Recurse -Force
}

function Get-InstalledLangflowVersion([string]$pythonExe) {
  $version = (& $pythonExe -c "import importlib.metadata as metadata; print(metadata.version('langflow'))").Trim()
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
    Fail "Unable to determine the installed Langflow version"
  }
  return $version
}

function Resolve-LangflowGitRef([string]$version) {
  $repoUrl = "https://github.com/langflow-ai/langflow.git"
  $candidates = @(
    "release-$version",
    "v$version",
    $version,
    "main"
  )

  foreach ($candidate in $candidates) {
    $matches = (& git ls-remote --heads --tags $repoUrl $candidate)
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace(($matches -join ""))) {
      if ($candidate -eq "main") {
        Warn "Could not find a release ref for Langflow $version. Falling back to '$candidate'."
      } else {
        Ok "Matched Langflow source ref '$candidate'"
      }
      return $candidate
    }
  }

  Fail "Could not resolve a Langflow source ref for version $version"
}

function Copy-PatcherPayload([string]$payloadRoot, [string]$sourceRoot) {
  $payloadSrcRoot = Join-Path $payloadRoot "src"
  if (-not (Test-Path $payloadSrcRoot)) {
    Fail "Missing payload source directory: $payloadSrcRoot"
  }

  Copy-Item -Path $payloadSrcRoot -Destination $sourceRoot -Recurse -Force
}

$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $PackageRoot

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
  $OutputRoot = Join-Path $PackageRoot "offline_bundle"
} elseif (-not [System.IO.Path]::IsPathRooted($OutputRoot)) {
  $OutputRoot = Join-Path $PackageRoot $OutputRoot
}

$PayloadRoot = Join-Path $PackageRoot "patcher_payload"
$BuildRoot = Join-Path $PackageRoot ".offline-build"
$BuildVenv = Join-Path $BuildRoot ".venv"
$BuildSource = Join-Path $BuildRoot "langflow-source"
$Wheelhouse = Join-Path $OutputRoot "python-wheels"
$RequirementsFile = Join-Path $OutputRoot "requirements-frozen.txt"
$SourceArchive = Join-Path $OutputRoot "langflow-source.zip"
$FrontendBuildArchive = Join-Path $OutputRoot "frontend-build.zip"
$ManifestPath = Join-Path $OutputRoot "manifest.json"
$BundleZip = "$OutputRoot.zip"

Ensure-Command "uv" "Install uv, then rerun this script."
Ensure-Command "git" "Install Git, then rerun this script."
$NpmCommand = Get-NpmCommand
if (-not $SkipFrontendBuild) {
  Ensure-Command $NpmCommand "Install Node.js and npm, then rerun this script."
}

if (-not (Test-IsWindows)) {
  Warn "Build this bundle on Windows x64 for the best match with Windows Server 2022."
}

if ($Clean) {
  Info "Cleaning existing offline build artifacts"
  Remove-DirectoryInsideRoot -path $BuildRoot -root $PackageRoot
  Remove-DirectoryInsideRoot -path $OutputRoot -root $PackageRoot
  if (Test-Path $BundleZip) {
    Assert-PathWithinRoot -path $BundleZip -root $PackageRoot
    Remove-Item -LiteralPath $BundleZip -Force
  }
}

New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
New-Item -ItemType Directory -Path $Wheelhouse -Force | Out-Null

Info "Creating build environment with Python $PythonSpec"
uv venv $BuildVenv --python $PythonSpec --seed
if ($LASTEXITCODE -ne 0) {
  Fail "uv venv failed. Install Python $PythonSpec with 'uv python install $PythonSpec', then rerun this script."
}

$PythonExe = Join-Path $BuildVenv "Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
  Fail "Missing build Python executable: $PythonExe"
}

$ActivateScript = Join-Path $BuildVenv "Scripts\Activate.ps1"
if (-not (Test-Path $ActivateScript)) {
  Fail "Missing build activation script: $ActivateScript"
}
. $ActivateScript

Info "Installing Langflow into the build environment to resolve its version"
uv pip install --python $PythonExe langflow -U --torch-backend cpu --only-binary torch --only-binary torchvision
if ($LASTEXITCODE -ne 0) {
  Fail "Failed to install Langflow in the build environment."
}

$LangflowVersion = Get-InstalledLangflowVersion -pythonExe $PythonExe
Ok "Resolved Langflow $LangflowVersion"

$SourceRef = Resolve-LangflowGitRef $LangflowVersion
if (-not (Test-Path $BuildSource)) {
  Info "Cloning Langflow source ref '$SourceRef'"
  git -c core.longpaths=true clone --depth 1 --branch $SourceRef https://github.com/langflow-ai/langflow.git $BuildSource
  if ($LASTEXITCODE -ne 0) {
    Fail "git clone failed"
  }
} else {
  Warn "Reusing existing build source at $BuildSource"
}

Info "Applying patcher payload to build source"
Copy-PatcherPayload -payloadRoot $PayloadRoot -sourceRoot $BuildSource

Info "Syncing Langflow dependencies into the build environment"
$env:UV_TORCH_BACKEND = "cpu"
Push-Location $BuildSource
try {
  uv sync --active --no-dev
  if ($LASTEXITCODE -ne 0) {
    Fail "uv sync --active --no-dev failed"
  }

  Info "Freezing resolved Python packages"
  $frozen = (& uv pip freeze --exclude-editable)
  if ($LASTEXITCODE -ne 0) {
    Fail "uv pip freeze failed"
  }
  $frozen |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    Where-Object { $_ -notmatch " @ file:" } |
    Set-Content -Path $RequirementsFile
} finally {
  Pop-Location
}

Info "Downloading Python wheels into $Wheelhouse"
& $PythonExe -m pip download --dest $Wheelhouse --only-binary=:all: --extra-index-url https://download.pytorch.org/whl/cpu -r $RequirementsFile
if ($LASTEXITCODE -ne 0) {
  Fail "pip download failed. The offline bundle needs wheels for every frozen dependency."
}

Info "Ensuring CPU torch and torchvision wheels are in the wheelhouse"
$torchPins = Get-Content -Path $RequirementsFile | Where-Object { $_ -match "^(torch|torchvision)==" }
if ($torchPins.Count -eq 0) {
  $torchPins = @("torch", "torchvision")
}
& $PythonExe -m pip download --dest $Wheelhouse --only-binary=:all: --index-url https://download.pytorch.org/whl/cpu @torchPins
if ($LASTEXITCODE -ne 0) {
  Fail "Failed to download CPU torch/torchvision wheels."
}

Info "Adding Langflow distribution wheel to wheelhouse"
& $PythonExe -m pip download --dest $Wheelhouse --only-binary=:all: --extra-index-url https://download.pytorch.org/whl/cpu langflow==$LangflowVersion
if ($LASTEXITCODE -ne 0) {
  Warn "Could not download the langflow distribution wheel. Offline install can still use the bundled source checkout."
}

Info "Packaging Langflow source archive"
Push-Location $BuildSource
try {
  if (Test-Path $SourceArchive) {
    Remove-Item -LiteralPath $SourceArchive -Force
  }
  git archive --format=zip --output=$SourceArchive HEAD
  if ($LASTEXITCODE -ne 0) {
    Fail "git archive failed"
  }
} finally {
  Pop-Location
}

if (-not $SkipFrontendBuild) {
  Info "Building patched frontend for offline install"
  Push-Location (Join-Path $BuildSource "src/frontend")
  try {
    & $NpmCommand install
    if ($LASTEXITCODE -ne 0) {
      Fail "npm install failed"
    }

    & $NpmCommand run build
    if ($LASTEXITCODE -ne 0) {
      Fail "npm run build failed"
    }
  } finally {
    Pop-Location
  }

  $frontendBuild = Join-Path $BuildSource "src/frontend/build"
  if (-not (Test-Path $frontendBuild)) {
    Fail "Frontend build output was not created: $frontendBuild"
  }

  if (Test-Path $FrontendBuildArchive) {
    Remove-Item -LiteralPath $FrontendBuildArchive -Force
  }
  Compress-Archive -Path (Join-Path $frontendBuild "*") -DestinationPath $FrontendBuildArchive -Force
  Ok "Packaged frontend build"
} else {
  Warn "Skipped frontend build. Offline server install will require npm access unless frontend-build.zip is added later."
}

$manifest = [ordered]@{
  bundle_version = 1
  created_utc = (Get-Date).ToUniversalTime().ToString("o")
  python = $PythonSpec
  platform = "windows-x64"
  langflow_version = $LangflowVersion
  source_ref = $SourceRef
  contains = [ordered]@{
    python_wheels = $true
    langflow_source_zip = $true
    frontend_build_zip = -not $SkipFrontendBuild
  }
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $ManifestPath

if ($CreateZip) {
  if (Test-Path $BundleZip) {
    Remove-Item -LiteralPath $BundleZip -Force
  }
  Info "Creating transferable archive $BundleZip"
  Compress-Archive -Path (Join-Path $OutputRoot "*") -DestinationPath $BundleZip -Force
}

Ok "Offline bundle completed at $OutputRoot"
if ($CreateZip) {
  Ok "Transfer this file to the server and extract it next to installer.ps1: $BundleZip"
}

#!/usr/bin/env pwsh

param(
  [string]$InstallRoot = "",
  [Alias('Host')]
  [string]$ListenHost = "",
  [int]$Port = 0,
  [switch]$ValidateOnly,
  [switch]$NonInteractive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Info([string]$msg) { Write-Host "[launcher] $msg" -ForegroundColor Cyan }
function Ok([string]$msg) { Write-Host "[launcher] $msg" -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "[launcher] $msg" -ForegroundColor Yellow }
function Fail([string]$msg) { Write-Host "[launcher] $msg" -ForegroundColor Red; exit 1 }

function Get-PatcherConfigPath([string]$Root) {
  return Join-Path $Root "local.settings.json"
}

function Load-PatcherConfig([string]$Root) {
  $configPath = Get-PatcherConfigPath -Root $Root
  if (-not (Test-Path $configPath)) {
    return [pscustomobject]@{}
  }

  try {
    $raw = Get-Content -Path $configPath -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) {
      return [pscustomobject]@{}
    }
    return ($raw | ConvertFrom-Json)
  } catch {
    Warn ("Ignoring unreadable config file: {0}" -f $configPath)
    return [pscustomobject]@{}
  }
}

function Save-PatcherConfig([string]$Root, [hashtable]$Updates) {
  $configPath = Get-PatcherConfigPath -Root $Root
  $merged = [ordered]@{}
  $existing = Load-PatcherConfig -Root $Root

  foreach ($prop in $existing.PSObject.Properties) {
    $merged[$prop.Name] = $prop.Value
  }

  foreach ($key in $Updates.Keys) {
    $value = $Updates[$key]
    if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
      $merged.Remove($key) | Out-Null
      continue
    }
    $merged[$key] = $value
  }

  $merged["updated_at"] = (Get-Date).ToString("o")
  $merged | ConvertTo-Json | Set-Content -Path $configPath -Encoding UTF8
  return $configPath
}

function Get-DefaultLangflowRoot([string]$PatcherRoot) {
  $leaf = Split-Path -Leaf $PatcherRoot
  if ($leaf -ieq "patcher") {
    return (Split-Path -Parent $PatcherRoot)
  }
  return $PatcherRoot
}

function Test-SamePath([string]$Left, [string]$Right) {
  if ([string]::IsNullOrWhiteSpace($Left) -or [string]::IsNullOrWhiteSpace($Right)) {
    return $false
  }

  $leftFull = [System.IO.Path]::GetFullPath($Left).TrimEnd('\', '/')
  $rightFull = [System.IO.Path]::GetFullPath($Right).TrimEnd('\', '/')
  return $leftFull.Equals($rightFull, [System.StringComparison]::OrdinalIgnoreCase)
}

function Resolve-RequestedLangflowRoot([string]$RequestedRoot, [string]$SavedRoot, [string]$PatcherRoot) {
  $defaultRoot = Get-DefaultLangflowRoot -PatcherRoot $PatcherRoot
  $candidate = $RequestedRoot

  if ([string]::IsNullOrWhiteSpace($candidate) -and -not [string]::IsNullOrWhiteSpace($SavedRoot)) {
    $candidate = $SavedRoot
  }

  if (-not [string]::IsNullOrWhiteSpace($candidate)) {
    $expanded = [Environment]::ExpandEnvironmentVariables($candidate.Trim())
    if (-not [System.IO.Path]::IsPathRooted($expanded)) {
      $expanded = Join-Path (Get-Location).Path $expanded
    }

    if (Test-SamePath -Left $expanded -Right $PatcherRoot) {
      Warn ("Langflow target points at the patcher folder ({0}); using parent folder instead: {1}" -f $PatcherRoot, $defaultRoot)
      return $defaultRoot
    }

    return $candidate
  }

  return $defaultRoot
}

function Get-ConfigValue($Config, [string]$Name) {
  if ($null -eq $Config) {
    return $null
  }

  $property = $Config.PSObject.Properties[$Name]
  if ($null -eq $property) {
    return $null
  }

  return $property.Value
}

function Resolve-InstallRoot([string]$RequestedRoot, [string]$DefaultRoot) {
  if ([string]::IsNullOrWhiteSpace($RequestedRoot)) {
    return (Resolve-Path -LiteralPath $DefaultRoot).Path
  }

  $expanded = [Environment]::ExpandEnvironmentVariables($RequestedRoot.Trim())
  if (-not [System.IO.Path]::IsPathRooted($expanded)) {
    $expanded = Join-Path (Get-Location).Path $expanded
  }

  if (-not (Test-Path $expanded)) {
    Fail ("Install root was not found: {0}" -f $expanded)
  }

  return (Resolve-Path -LiteralPath $expanded).Path
}

function Get-LocalVenvPython([string]$Root) {
  $candidate = Join-Path $Root ".venv\Scripts\python.exe"
  if (Test-Path $candidate) {
    return (Resolve-Path -LiteralPath $candidate).Path
  }
  return ""
}

function Use-PythonRuntimePath([string]$PythonPath) {
  $script = @'
import json
import pathlib
import sys

paths = []
for value in [pathlib.Path(sys.executable).resolve().parent, pathlib.Path(sys.base_prefix).resolve(), pathlib.Path(sys.base_prefix).resolve() / "DLLs"]:
    if value.exists():
        paths.append(str(value))
print(json.dumps(paths))
'@

  try {
    $json = $script | & $PythonPath -
    if ($LASTEXITCODE -ne 0 -or -not $json) {
      return
    }
    $paths = (($json -join "`n") | ConvertFrom-Json)
  } catch {
    return
  }

  $existing = @($env:PATH -split ';' | Where-Object {
      if ([string]::IsNullOrWhiteSpace($_)) {
        return $false
      }
      $normalized = ([string]$_).TrimEnd('\', '/')
      $isGitOpenSslPath = $normalized.EndsWith("\Git\mingw64\bin", [System.StringComparison]::OrdinalIgnoreCase) -or $normalized.EndsWith("\Git\usr\bin", [System.StringComparison]::OrdinalIgnoreCase)
      if ($isGitOpenSslPath -and ((Test-Path (Join-Path $normalized "libcrypto-3-x64.dll")) -or (Test-Path (Join-Path $normalized "openssl.exe")))) {
        return $false
      }
      return $true
    })
  $ordered = [System.Collections.Generic.List[string]]::new()
  foreach ($path in @($paths)) {
    if (-not [string]::IsNullOrWhiteSpace([string]$path) -and (Test-Path ([string]$path))) {
      $ordered.Add([string]$path) | Out-Null
    }
  }
  foreach ($path in $existing) {
    $alreadyAdded = $false
    foreach ($prefix in $ordered) {
      if ($prefix -ieq $path) {
        $alreadyAdded = $true
        break
      }
    }
    if (-not $alreadyAdded) {
      $ordered.Add($path) | Out-Null
    }
  }

  $env:PATH = [string]::Join(';', $ordered)
}

function Get-LangflowInfo([string]$PythonPath) {
  $script = @'
import importlib.metadata as metadata
import importlib.util
import json
import sys

payload = {"installed": False}
spec = importlib.util.find_spec("langflow")
if spec is not None:
    payload = {
        "installed": True,
        "python": sys.executable,
        "version": metadata.version("langflow"),
        "package_root": spec.submodule_search_locations[0],
    }
print(json.dumps(payload))
'@

  $json = $script | & $PythonPath -
  if ($LASTEXITCODE -ne 0 -or -not $json) {
    Fail ("Failed to inspect Langflow using {0}" -f $PythonPath)
  }

  try {
    return (($json -join "`n") | ConvertFrom-Json)
  } catch {
    Fail ("Langflow inspection returned unreadable data for {0}" -f $PythonPath)
  }
}

function Import-DotEnv([string]$EnvFile) {
  if (-not (Test-Path $EnvFile)) {
    return
  }

  foreach ($line in Get-Content -Path $EnvFile) {
    $trimmed = $line.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith("#")) {
      continue
    }

    $index = $trimmed.IndexOf("=")
    if ($index -le 0) {
      continue
    }

    $key = $trimmed.Substring(0, $index).Trim()
    $value = $trimmed.Substring($index + 1).Trim()
    if (
      ($value.StartsWith('"') -and $value.EndsWith('"')) -or
      ($value.StartsWith("'") -and $value.EndsWith("'"))
    ) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    [Environment]::SetEnvironmentVariable($key, $value, "Process")
  }
}

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigRoot = $ScriptRoot
$SavedConfig = Load-PatcherConfig -Root $ConfigRoot
$SavedLangflowTarget = Get-ConfigValue -Config $SavedConfig -Name "langflow_target"
$ResolvedRequestedRoot = Resolve-RequestedLangflowRoot -RequestedRoot $InstallRoot -SavedRoot $SavedLangflowTarget -PatcherRoot $ScriptRoot
$Root = Resolve-InstallRoot -RequestedRoot $ResolvedRequestedRoot -DefaultRoot (Get-DefaultLangflowRoot -PatcherRoot $ScriptRoot)
$SavedHost = Get-ConfigValue -Config $SavedConfig -Name "host"
$SavedPort = Get-ConfigValue -Config $SavedConfig -Name "port"
$PythonPath = Get-LocalVenvPython -Root $Root

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
  Fail ("Missing local .venv at {0}. Run .\installer.ps1 first or use the GUI Install button." -f $Root)
}

Use-PythonRuntimePath -PythonPath $PythonPath

$Info = Get-LangflowInfo -PythonPath $PythonPath
if (-not $Info.installed) {
  Fail ("Langflow is not installed in {0}. Run .\installer.ps1 first." -f $PythonPath)
}

$ResolvedHost = if (-not [string]::IsNullOrWhiteSpace($ListenHost)) {
  $ListenHost
} elseif (-not [string]::IsNullOrWhiteSpace([string]$SavedHost)) {
  [string]$SavedHost
} else {
  "127.0.0.1"
}

$ResolvedPort = if ($Port -gt 0) {
  $Port
} elseif ($null -ne $SavedPort -and [int]$SavedPort -gt 0) {
  [int]$SavedPort
} else {
  7860
}

if ($ValidateOnly) {
  Write-Host "VALIDATION_OK"
  Write-Host ("Patcher root: {0}" -f $ConfigRoot)
  Write-Host ("Langflow target: {0}" -f $Root)
  Write-Host ("Python: {0}" -f $PythonPath)
  Write-Host ("Langflow package root: {0}" -f $Info.package_root)
  Write-Host ("Langflow version: {0}" -f $Info.version)
  Write-Host ("Host: {0}" -f $ResolvedHost)
  Write-Host ("Port: {0}" -f $ResolvedPort)
  exit 0
}

$configPath = Save-PatcherConfig -Root $ConfigRoot -Updates @{
  langflow_target = $Root
  python_exe = $PythonPath
  host = $ResolvedHost
  port = $ResolvedPort
}

Import-DotEnv -EnvFile (Join-Path $Root ".env")

Info ("Using local patcher settings: {0}" -f $configPath)
Info ("Starting patched Langflow on {0}:{1}" -f $ResolvedHost, $ResolvedPort)

Push-Location $Root
try {
  & $PythonPath -m langflow run --host $ResolvedHost --port $ResolvedPort @args
  $exitCode = $LASTEXITCODE
} finally {
  Pop-Location
}

if ($exitCode -ne 0) {
  Fail "Langflow exited with code $exitCode"
}

Ok "Langflow exited cleanly"

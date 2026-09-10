#!/usr/bin/env pwsh

param(
  [string]$InstallRoot = "",
  [string]$PythonExe = "",
  [switch]$PatchOnly,
  [switch]$InstallOnly,
  [switch]$Force,
  [switch]$ValidateOnly,
  [switch]$SkipAuthAddition,
  [switch]$NonInteractive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# The package keeps Langflow's native authentication, authorization, and
# sharing, then adds the single GUI-managed TWC OpenID lane below. Keep the
# switch for backwards-compatible command lines; it only controls legacy
# overlay files and never removes the TWC OpenID GUI/backend.
$SkipAuthAddition = $true

function Info([string]$msg) { Write-Host "[installer] $msg" -ForegroundColor Cyan }
function Ok([string]$msg) { Write-Host "[installer] $msg" -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "[installer] $msg" -ForegroundColor Yellow }
function Fail([string]$msg) { Write-Host "[installer] $msg" -ForegroundColor Red; exit 1 }

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

function Resolve-InstallRoot([string]$RequestedRoot, [string]$DefaultRoot) {
  if ([string]::IsNullOrWhiteSpace($RequestedRoot)) {
    return (Resolve-Path -LiteralPath $DefaultRoot).Path
  }

  $expanded = [Environment]::ExpandEnvironmentVariables($RequestedRoot.Trim())
  if (-not [System.IO.Path]::IsPathRooted($expanded)) {
    $expanded = Join-Path (Get-Location).Path $expanded
  }

  if (-not (Test-Path $expanded)) {
    New-Item -ItemType Directory -Path $expanded -Force | Out-Null
  }

  return (Resolve-Path -LiteralPath $expanded).Path
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
  [string]$installRoot,
  [string]$pythonPath,
  [string]$pythonVersion,
  [string]$langflowVersion,
  [string]$langflowRoot,
  [string]$lfxRoot,
  [string]$payloadFingerprint,
  [string]$installerFingerprint
) {
  $state = [ordered]@{
    stateVersion = 4
    installRoot = $installRoot
    pythonPath = $pythonPath
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

function Resolve-UvCommand {
  $uvCmd = Get-Command uv -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($uvCmd -and -not [string]::IsNullOrWhiteSpace([string]$uvCmd.Source)) {
    return [string]$uvCmd.Source
  }

  Fail "uv is required for LangPatcher install. Install uv or place uv.exe on PATH, then rerun."
}

function Get-LocalVenvPython([string]$Root) {
  $candidate = Join-Path $Root ".venv\Scripts\python.exe"
  if (Test-Path $candidate) {
    return (Resolve-Path -LiteralPath $candidate).Path
  }
  return ""
}

function Test-LangflowInstalled([string]$PythonPath) {
  if ([string]::IsNullOrWhiteSpace($PythonPath) -or -not (Test-Path $PythonPath)) {
    return $false
  }

  $script = @'
import importlib.util
raise SystemExit(0 if importlib.util.find_spec("langflow") and importlib.util.find_spec("lfx") else 1)
'@

  $script | & $PythonPath - 1>$null 2>$null
  return ($LASTEXITCODE -eq 0)
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

function Get-PythonVersion([string]$PythonPath) {
  $pythonVersionOutput = & $PythonPath -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
  if ($LASTEXITCODE -ne 0 -or $null -eq $pythonVersionOutput) {
    return ""
  }

  return ([string]::Join("`n", @($pythonVersionOutput))).Trim()
}

function Ensure-CompatibleRuntimePackages([string]$PythonPath) {
  $uvPath = Resolve-UvCommand
  Info "Ensuring Windows-compatible aiohttp runtime"
  & $uvPath --native-tls pip install --python $PythonPath "aiohttp>=3.11,<4"
  if ($LASTEXITCODE -ne 0) {
    Fail "Failed to install Windows-compatible aiohttp runtime package."
  }

  $requirementsPath = Join-Path $ScriptRoot "requirements.txt"
  if (Test-Path -LiteralPath $requirementsPath) {
    Info "Installing packages listed in $requirementsPath"
    & $uvPath --native-tls pip install --python $PythonPath --requirement $requirementsPath
    if ($LASTEXITCODE -ne 0) {
      Fail "Failed to install packages listed in $requirementsPath."
    }
  }
}

function Get-InstalledPackageLayout([string]$PythonPath) {
  $script = @'
import importlib.metadata as metadata
import importlib.util
import json

payload = {"installed": False}

langflow_spec = importlib.util.find_spec("langflow")
lfx_spec = importlib.util.find_spec("lfx")

if langflow_spec is not None and lfx_spec is not None:
    payload = {
        "installed": True,
        "langflowVersion": metadata.version("langflow"),
        "langflowRoot": langflow_spec.submodule_search_locations[0],
        "lfxRoot": lfx_spec.submodule_search_locations[0],
    }

print(json.dumps(payload))
'@

  $layoutOutput = $script | & $PythonPath -
  if ($LASTEXITCODE -ne 0 -or $null -eq $layoutOutput) {
    Fail ("Unable to inspect the installed Langflow package using {0}." -f $PythonPath)
  }

  try {
    $layout = (([string]::Join("`n", @($layoutOutput))).Trim()) | ConvertFrom-Json
  } catch {
    Fail ("Langflow inspection returned unreadable data for {0}." -f $PythonPath)
  }

  if (-not $layout.installed) {
    Fail ("Langflow is not installed in the local environment: {0}" -f $PythonPath)
  }

  return $layout
}

function Ensure-LocalLangflowEnvironment([string]$Root, [string]$RequestedPython, [switch]$ForceInstall) {
  $uvPath = Resolve-UvCommand
  $venvPython = Get-LocalVenvPython -Root $Root
  $venvPath = Join-Path $Root ".venv"

  if ([string]::IsNullOrWhiteSpace($venvPython)) {
    Info ("Creating folder-local Python environment at {0} with Python 3.11" -f $venvPath)
    $venvArgs = @("--native-tls", "venv", $venvPath, "--python")
    if ([string]::IsNullOrWhiteSpace($RequestedPython)) {
      $venvArgs += "3.11"
    } else {
      $venvArgs += $RequestedPython
    }
    & $uvPath @venvArgs
    if ($LASTEXITCODE -ne 0) {
      Fail "Failed to create local .venv with uv."
    }

    $venvPython = Get-LocalVenvPython -Root $Root
    if ([string]::IsNullOrWhiteSpace($venvPython)) {
      Fail "uv completed, but .venv\Scripts\python.exe was not found."
    }
  } else {
    Info ("Reusing local Python environment at {0}" -f $venvPath)
  }

  if ((-not $ForceInstall) -and (Test-LangflowInstalled -PythonPath $venvPython)) {
    Ok "Langflow is already installed in the local environment. Skipping install."
    return $venvPython
  }

  Info "Installing Langflow into the local environment"
  & $uvPath --native-tls pip install --python $venvPython langflow -U
  if ($LASTEXITCODE -ne 0) {
    Fail "Langflow installation failed."
  }

  if (-not (Test-LangflowInstalled -PythonPath $venvPython)) {
    Fail "Langflow install completed, but langflow/lfx are not importable from the local environment."
  }

  Ok "Langflow is installed in the local environment"
  return $venvPython
}

function Test-SkipAuthAdditionPath([string]$relativePath) {
  $normalized = $relativePath.Replace('/', '\').ToLowerInvariant()

  # Langflow 1.12 already ships its own auth/authz and sharing implementation.
  # Do not overlay the older mixed SAML/flow-sharing files from this payload.
  return (
    $normalized -match '(^|\\)(main\.py|api\\router\.py|api\\v1\\__init__\.py)$' -or
    $normalized -match '(^|\\)api\\v1\\(admin_settings|users|flows|flows_helpers)\.py$' -or
    $normalized -match '(^|\\)api\\v1\\schemas\\__init__\.py$' -or
    $normalized -match '(^|\\)services\\database\\models\\(__init__|flow\\model|user\\model)\.py$' -or
    $normalized -match '(^|\\)services\\database\\models\\flow_share\\' -or
    $normalized -match '(^|\\)alembic\\versions\\(a7c9d4e1f0b2|c8f2a9d0e1b3|f4a1c2d3e4b5)' -or
    $normalized -match '(^|\\)services\\settings\\base\.py$'
  )
}

function Patch-StockRouterForTWCOpenId([string]$langflowRoot) {
  $routerPath = Join-Path $langflowRoot "api\router.py"
  Assert-PathWithinRoot -path $routerPath -root $langflowRoot
  if (-not (Test-Path -LiteralPath $routerPath)) { Fail "Missing stock Langflow API router: $routerPath" }
  $content = Get-Content -LiteralPath $routerPath -Raw
  if ($content -notmatch 'langflow\.api\.v1\.sso') {
    $content = $content.Replace(
      'from langflow.api.v1.voice_mode import router as voice_mode_router',
      "from langflow.api.v1.voice_mode import router as voice_mode_router`r`nfrom langflow.api.v1.sso import admin_router as twc_sso_admin_router, router as twc_sso_router"
    )
    $content = $content.Replace(
      'router_v1.include_router(login_router)',
      "router_v1.include_router(login_router)`r`nrouter_v1.include_router(twc_sso_router)`r`nrouter_v1.include_router(twc_sso_admin_router)"
    )
    Set-Content -LiteralPath $routerPath -Value $content -Encoding UTF8
  }
  Ok "Mounted TWC OpenID routes in Langflow's stock API router"
}

function Patch-StockLoginForTWCOpenId([string]$langflowRoot) {
  $loginPath = Join-Path $langflowRoot "api\v1\login.py"
  Assert-PathWithinRoot -path $loginPath -root $langflowRoot
  if (-not (Test-Path -LiteralPath $loginPath)) { Fail "Missing stock Langflow login router: $loginPath" }
  $content = Get-Content -LiteralPath $loginPath -Raw
  $changed = $false
  $desiredGuard = '    if auth_settings.AUTO_LOGIN and not await _twc_sso_enabled(db):'
  foreach ($oldGuard in @(
      '    if auth_settings.AUTO_LOGIN:',
      '    if auth_settings.AUTO_LOGIN and not await _twc_sso_enabled(db):'
    )) {
    if ($content.Contains($oldGuard) -and -not $content.Contains($desiredGuard)) {
      $content = $content.Replace($oldGuard, $desiredGuard)
      $changed = $true
    }
  }
  if ($content -notmatch '(?m)^import os$') {
    $content = [regex]::Replace($content, 'from __future__ import annotations\r?\n', { param($match) $match.Groups[0].Value + 'import os' + "`r`n" }, 1)
    $changed = $true
  }
  if ($content -notmatch 'from langflow\.api\.v1\.sso import is_sso_enabled') {
    $content = $content.Replace(
      'from langflow.services.auth.exceptions import AuthenticationError',
      "from langflow.api.v1.sso import is_sso_enabled as _twc_sso_enabled`r`nfrom langflow.services.auth.exceptions import AuthenticationError"
    )
    $changed = $true
  }
  $passwordGuard = '    if await _twc_sso_enabled(db):' + "`r`n" + '        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="TWC OpenID sign-in is required")' + "`r`n"
  if ($content -notmatch 'TWC OpenID sign-in is required') {
    $content = $content.Replace('    check_rate_limit(request)' + "`r`n", '    check_rate_limit(request)' + "`r`n" + $passwordGuard)
    $changed = $true
  }
  if ($content -notmatch 'def _langpatcher_local_only\(\)') {
    $helperBlock = 'def _langpatcher_local_only() -> bool:' + "`r`n" + '    return os.getenv("LANGPATCHER_LOCAL_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}' + "`r`n`r`n"
    $headerPattern = 'router = APIRouter\(tags=\["Login"\]\)\r?\n'
    $content = [regex]::Replace($content, $headerPattern, { param($match) $match.Groups[0].Value + $helperBlock }, 1)
    $changed = $true
  }
  if ($changed) {
    Set-Content -LiteralPath $loginPath -Value $content -Encoding UTF8
  }
  Ok "Guarded stock auto-login when TWC OpenID is not enabled"
}

function Install-TwcOpenIdUi([string]$payloadRoot, [string]$frontendRoot) {
  $uiSource = Join-Path $payloadRoot "twc-openid-ui.js"
  $uiTarget = Join-Path $frontendRoot "twc-openid-ui-v4.js"
  if (-not (Test-Path -LiteralPath $uiSource)) { Fail "Missing TWC OpenID UI asset: $uiSource" }
  Copy-Item -LiteralPath $uiSource -Destination $uiTarget -Force
  $indexPath = Join-Path $frontendRoot "index.html"
  $index = Get-Content -LiteralPath $indexPath -Raw
  $scriptTag = '    <script src="./twc-openid-ui-v4.js"></script>'
  if ($index -match 'twc-openid-ui(?:-v[0-9]+)?\.js') {
    $index = [regex]::Replace($index, '\s*<script src="\.\/twc-openid-ui(?:-v[0-9]+)?\.js(?:\?v=\d+)?"></script>', "`r`n$scriptTag", 1)
  } else {
    $index = $index.Replace('</head>', "$scriptTag`r`n  </head>")
  }
  Set-Content -LiteralPath $indexPath -Value $index -Encoding UTF8
  Patch-FrontendAdminSettingsGuard -frontendRoot $frontendRoot
  Ok "Installed GUI-only TWC OpenID sign-in control"
}

function Patch-FrontendAdminSettingsGuard([string]$frontendRoot) {
  # Langflow's stock wrapper treats AUTO_LOGIN as a reason to redirect every
  # settings route, even after the auto-login session has resolved to the
  # superuser. The backend still enforces get_current_active_superuser for
  # settings APIs; the UI guard only needs the authenticated user's admin flag.
  $old = 'const NG=({children:e})=>{const{userData:t}=I.useContext(AE),r=wl(l=>l.isAuthenticated),o=wl(l=>l.autoLogin),s=wl(l=>l.isAdmin);return r?t&&!s||o?v.jsx(F6,{to:"/",replace:!0}):e:v.jsx(Tmt,{})}'
  $new = 'const NG=({children:e})=>{const{userData:t}=I.useContext(AE),r=wl(l=>l.isAuthenticated),s=wl(l=>l.isAdmin);return r?t&&!s?v.jsx(F6,{to:"/",replace:!0}):e:v.jsx(Tmt,{})}'
  $assets = Get-ChildItem -LiteralPath (Join-Path $frontendRoot "assets") -Filter "index-*.js" -File
  if ($assets.Count -eq 0) { Fail "Missing Langflow frontend JavaScript bundle" }
  $patched = $false
  foreach ($asset in $assets) {
    # The Vite bundle is UTF-8 and contains non-ASCII literals.  PowerShell 5's
    # Get-Content defaults to the active ANSI code page, which silently
    # mojibakes the bundle and leaves Chromium with a syntax error.  Read and
    # write the bytes with an explicit UTF-8 encoding instead.
    $content = [IO.File]::ReadAllText($asset.FullName, [Text.UTF8Encoding]::new($false, $true))
    if ($content.Contains($old)) {
      $content = $content.Replace($old, $new)
      [IO.File]::WriteAllText($asset.FullName, $content, [Text.UTF8Encoding]::new($false))
      $patched = $true
      break
    }
    if ($content.Contains($new)) { $patched = $true; break }
  }
  if ($patched) {
    Ok "Allowed authenticated superusers to open bundled settings routes"
  } else {
    Fail "The bundled Langflow settings guard did not match the expected build"
  }
}

function Copy-Tree([string]$sourceRoot, [string]$destinationRoot, [switch]$SkipAuthOverlay) {
  if (-not (Test-Path $sourceRoot)) {
    Fail "Missing payload directory: $sourceRoot"
  }

  if (-not (Test-Path $destinationRoot)) {
    New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null
  }

  $copied = 0
  foreach ($file in Get-ChildItem -Path $sourceRoot -Recurse -File | Sort-Object FullName) {
    $relativePath = Get-RelativePath -root $sourceRoot -path $file.FullName
    if ($SkipAuthOverlay -and (Test-SkipAuthAdditionPath -relativePath $relativePath)) {
      continue
    }
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
      $updated = [regex]::Replace($envContent, "(?m)^\s*$key\s*=.*$", $line)
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

function Patch-LangflowCliLocalOnlyVersionCheck([string]$LangflowRoot) {
  $mainPath = Join-Path $LangflowRoot "__main__.py"
  if (-not (Test-Path -LiteralPath $mainPath)) {
    Warn "Unable to patch Langflow CLI version check; __main__.py was not found."
    return
  }

  Assert-PathWithinRoot -path $mainPath -root $LangflowRoot
  $content = Get-Content -LiteralPath $mainPath -Raw
  $guard = '    if os.getenv("LANGPATCHER_LOCAL_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}:'
  if ($content.Contains($guard)) {
    return
  }

  $needle = @'
    Example:
        >>> build_version_notice("1.0.0", "langflow")
        'A new version of langflow is available: 1.1.0'
    """
'@
  $replacement = @'
    Example:
        >>> build_version_notice("1.0.0", "langflow")
        'A new version of langflow is available: 1.1.0'
    """
    if os.getenv("LANGPATCHER_LOCAL_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}:
        return ""
'@
  if (-not $content.Contains($needle)) {
    Warn "Unable to patch Langflow CLI version check; expected marker was not found."
    return
  }

  $content = $content.Replace($needle, $replacement)
  Set-Content -LiteralPath $mainPath -Value $content -NoNewline
  Ok "Patched Langflow CLI version check for local-only mode"
}

function Patch-LangflowLoginLocalOnlyVariableInit([string]$LangflowRoot) {
  $loginPath = Join-Path $LangflowRoot "api\v1\login.py"
  if (-not (Test-Path -LiteralPath $loginPath)) {
    Warn "Unable to patch Langflow login local-only guard; api\v1\login.py was not found."
    return
  }

  Assert-PathWithinRoot -path $loginPath -root $LangflowRoot
  $content = Get-Content -LiteralPath $loginPath -Raw
  $changed = $false

  if (-not $content.Contains("`nimport os`n")) {
    $needle = "from __future__ import annotations`r`n`r`nfrom typing import Annotated"
    $replacement = "from __future__ import annotations`r`n`r`nimport os`r`nfrom typing import Annotated"
    if ($content.Contains($needle)) {
      $content = $content.Replace($needle, $replacement)
      $changed = $true
    } else {
      Warn "Unable to patch Langflow login local-only guard; import marker was not found."
    }
  }

  if (-not $content.Contains("def _langpatcher_local_only() -> bool:")) {
    $needle = @'
router = APIRouter(tags=["Login"])


def get_limiter_from_app(request: Request):
'@
    $replacement = @'
router = APIRouter(tags=["Login"])


def _langpatcher_local_only() -> bool:
    return os.getenv("LANGPATCHER_LOCAL_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}


def get_limiter_from_app(request: Request):
'@
    if ($content.Contains($needle)) {
      $content = $content.Replace($needle, $replacement)
      $changed = $true
    } else {
      Warn "Unable to patch Langflow login local-only guard; router marker was not found."
    }
  }

  $duplicatePattern = "(?m)^        if not _langpatcher_local_only\(\):\s*\r?\n            if not _langpatcher_local_only\(\):\s*\r?\n            await get_variable_service\(\)\.initialize_user_variables\(user\.id, db\)\s*$"
  $desiredBlock = "        if not _langpatcher_local_only():`r`n            await get_variable_service().initialize_user_variables(user.id, db)"
  if ([regex]::IsMatch($content, $duplicatePattern)) {
    $content = [regex]::Replace($content, $duplicatePattern, $desiredBlock)
    $changed = $true
  }

  $oldLine = "        await get_variable_service().initialize_user_variables(user.id, db)"
  $guardedPattern = "(?m)^        if not _langpatcher_local_only\(\):\s*\r?\n            await get_variable_service\(\)\.initialize_user_variables\(user\.id, db\)\s*$"
  $newBlock = @'
        if not _langpatcher_local_only():
            await get_variable_service().initialize_user_variables(user.id, db)
'@
  if ((-not [regex]::IsMatch($content, $guardedPattern)) -and $content.Contains($oldLine)) {
    $content = $content.Replace($oldLine, $newBlock.TrimEnd("`r", "`n"))
    $changed = $true
  }

  if ($changed) {
    Set-Content -LiteralPath $loginPath -Value $content -NoNewline
    Ok "Patched Langflow login to skip environment variable import in local-only mode"
  }
}

function Install-PythonStartupGuard([string]$LangflowRoot) {
  $sitePackagesRoot = Split-Path -Parent $LangflowRoot
  if (-not (Test-Path -LiteralPath $sitePackagesRoot)) {
    Warn "Unable to install Python startup guard; site-packages root was not found."
    return
  }

  $siteCustomizePath = Join-Path $sitePackagesRoot "sitecustomize.py"
  Assert-PathWithinRoot -path $siteCustomizePath -root $sitePackagesRoot

  $content = @'
"""LangPatcher local runtime guard.

This module is imported automatically by Python during startup.  Keep it tiny:
it removes Windows Git/OpenSSL DLL directories from PATH before auth libraries
load OpenSSL, preventing the fatal "OPENSSL_Uplink ... no OPENSSL_Applink"
abort that can happen outside the LangPatcher launcher.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _python_runtime_paths() -> list[str]:
    candidates = [
        Path(sys.executable).resolve().parent,
        Path(sys.base_prefix).resolve(),
        Path(sys.base_prefix).resolve() / "DLLs",
    ]
    return [str(path) for path in candidates if path.exists()]


def _prefer_python_runtime_dlls() -> None:
    runtime_paths = _python_runtime_paths()
    for path in runtime_paths:
        add_dll_directory = getattr(os, "add_dll_directory", None)
        if add_dll_directory is not None:
            try:
                add_dll_directory(path)
            except OSError:
                pass

    raw_path = os.environ.get("PATH", "")
    existing = [entry for entry in raw_path.split(os.pathsep) if entry]
    ordered = []
    for entry in runtime_paths + existing:
        if entry and entry.lower() not in {item.lower() for item in ordered}:
            ordered.append(entry)
    os.environ["PATH"] = os.pathsep.join(ordered)


def _is_git_openssl_path(value: str) -> bool:
    normalized = value.rstrip("\\/")
    lowered = normalized.lower()
    if not (lowered.endswith("\\git\\mingw64\\bin") or lowered.endswith("\\git\\usr\\bin")):
        return False
    path = Path(normalized)
    return (path / "libcrypto-3-x64.dll").exists() or (path / "openssl.exe").exists()


def _sanitize_path() -> None:
    raw_path = os.environ.get("PATH", "")
    if not raw_path:
        return
    kept = []
    for entry in raw_path.split(os.pathsep):
        if entry and not _is_git_openssl_path(entry):
            kept.append(entry)
    os.environ["PATH"] = os.pathsep.join(kept)


_prefer_python_runtime_dlls()
_sanitize_path()

os.environ.setdefault("LANGPATCHER_LOCAL_ONLY", "true")
os.environ.setdefault("LANGFLOW_TELEMETRY_WRITER_ENABLED", "false")
os.environ.setdefault("LANGFLOW_DEACTIVATE_TRACING", "true")
os.environ.setdefault("LANGFLOW_DO_NOT_TRACK", "true")
os.environ.setdefault("DO_NOT_TRACK", "true")
'@

  $existing = if (Test-Path -LiteralPath $siteCustomizePath) { Get-Content -LiteralPath $siteCustomizePath -Raw } else { "" }
  if ($existing -eq $content) {
    Ok "Python startup guard is already installed"
    return
  }

  if (-not [string]::IsNullOrWhiteSpace($existing) -and -not $existing.Contains("LangPatcher local runtime guard")) {
    $backupPath = $siteCustomizePath + ".langpatcher.bak"
    Copy-Item -LiteralPath $siteCustomizePath -Destination $backupPath -Force
    Warn ("Existing sitecustomize.py was backed up to {0}" -f $backupPath)
  }

  Set-Content -LiteralPath $siteCustomizePath -Value $content -NoNewline
  Ok "Installed Python startup guard for Windows OpenSSL DLL safety"
}

function Patch-StockAlembicLegacyColumns([string]$LangflowRoot) {
  $envPath = Join-Path $LangflowRoot "alembic\env.py"
  Assert-PathWithinRoot -path $envPath -root $LangflowRoot
  if (-not (Test-Path -LiteralPath $envPath)) {
    Warn "Unable to install legacy database compatibility guard; Alembic env.py was not found."
    return
  }

  $content = Get-Content -LiteralPath $envPath -Raw
  if ($content -match 'TWC_LEGACY_COLUMNS') {
    Ok "Legacy v4 database compatibility guard is already installed"
    return
  }

  $marker = "def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:`n"
  if (-not $content.Contains($marker)) {
    Warn "Unable to install legacy database compatibility guard; Alembic include_name marker was not found."
    return
  }

  $compatibility = @'
_TWC_LEGACY_COLUMNS = {
    ("user", "can_view_all_flows"),
    ("sso_config", "provider"),
    ("sso_config", "provider_name"),
    ("sso_config", "enforce_sso"),
    ("sso_config", "client_id"),
    ("sso_config", "discovery_url"),
    ("sso_config", "redirect_uri"),
    ("sso_config", "scopes"),
    ("sso_config", "token_endpoint"),
    ("sso_config", "authorization_endpoint"),
    ("sso_config", "jwks_uri"),
    ("sso_config", "issuer"),
}


def include_object(object_, name: str | None, type_: str, reflected: bool, compare_to) -> bool:
    """Keep databases created by the retired v4 overlay readable.

    Those installs retained compatibility columns while the current native
    Langflow models no longer expose them.  They are harmless legacy storage;
    treating them as migration drift would abort startup before the GUI can be
    used.  This filter applies only to reflected legacy columns and does not
    suppress changes to current Langflow tables.
    """
    if type_ == "column" and reflected and name:
        table = getattr(getattr(object_, "table", None), "name", None)
        if (table, name) in _TWC_LEGACY_COLUMNS:
            return False
    return True


'@
  $content = $content.Replace($marker, $compatibility + $marker)
  $content = $content.Replace(
    '"include_name": include_name,',
    "`"include_name`": include_name,`r`n        `"include_object`": include_object,"
  )
  Set-Content -LiteralPath $envPath -Value $content -Encoding UTF8
  Ok "Installed legacy v4 database compatibility guard"
}

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigRoot = $ScriptRoot
$SavedConfig = Load-PatcherConfig -Root $ConfigRoot
$SavedLangflowTarget = Get-ConfigValue -Config $SavedConfig -Name "langflow_target"
$ResolvedRequestedRoot = Resolve-RequestedLangflowRoot -RequestedRoot $InstallRoot -SavedRoot $SavedLangflowTarget -PatcherRoot $ScriptRoot
$Root = Resolve-InstallRoot -RequestedRoot $ResolvedRequestedRoot -DefaultRoot (Get-DefaultLangflowRoot -PatcherRoot $ScriptRoot)
$PayloadRoot = Join-Path $ScriptRoot "patcher_payload"
$BackendPayloadRoot = Join-Path $PayloadRoot "src\backend\base\langflow"
$LfxPayloadRoot = Join-Path $PayloadRoot "src\lfx\src\lfx"
$FrontendBundlePath = Join-Path $PayloadRoot "frontend_build.zip"
$StateFile = Join-Path $Root "langpatcher-state.json"
$EnvFile = Join-Path $Root ".env"

if (-not (Test-Path $PayloadRoot)) {
  Fail "Missing payload directory: $PayloadRoot"
}

$PayloadFingerprint = Get-DirectoryFingerprint $PayloadRoot
$InstallerFingerprint = Get-FileSha256 $MyInvocation.MyCommand.Path
$localPython = Get-LocalVenvPython -Root $Root

if ($ValidateOnly) {
  Write-Host "VALIDATION_OK"
  Write-Host ("Patcher root: {0}" -f $ConfigRoot)
  Write-Host ("Langflow target: {0}" -f $Root)
  Write-Host ("Local Python: {0}" -f $(if ($localPython) { $localPython } else { "<missing>" }))
  Write-Host ("Langflow installed: {0}" -f $(if ($localPython -and (Test-LangflowInstalled -PythonPath $localPython)) { "yes" } else { "no" }))
  exit 0
}

if ($PatchOnly) {
  if ([string]::IsNullOrWhiteSpace($localPython)) {
    Fail ("Missing local .venv at {0}. Run Install first." -f $Root)
  }
  $PythonPath = $localPython
} else {
  $PythonPath = Ensure-LocalLangflowEnvironment -Root $Root -RequestedPython $PythonExe -ForceInstall:$Force
}

Use-PythonRuntimePath -PythonPath $PythonPath
Ensure-CompatibleRuntimePackages -PythonPath $PythonPath

if ($InstallOnly) {
  Save-PatcherConfig -Root $ConfigRoot -Updates @{
    langflow_target = $Root
    python_exe = $PythonPath
  } | Out-Null
  Ok "Install completed. Patch was skipped because -InstallOnly was used."
  exit 0
}

$PythonVersion = Get-PythonVersion -PythonPath $PythonPath
$Layout = Get-InstalledPackageLayout -PythonPath $PythonPath
$InstalledLangflowVersion = [string]$Layout.langflowVersion
$LangflowRoot = [string]$Layout.langflowRoot
$LfxRoot = [string]$Layout.lfxRoot
$InstallState = Read-InstallState $StateFile

Info ("Using Python: {0}" -f $PythonPath)
Ok ("Using Python {0} in local environment" -f $PythonVersion)
Info ("Detected Langflow {0}: {1}" -f $InstalledLangflowVersion, $LangflowRoot)

$HasMatchingPatchedInstall = (
  -not $Force -and
  $null -ne $InstallState -and
  $InstallState.pythonPath -eq $PythonPath -and
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
$backendCopied = Copy-Tree -sourceRoot $BackendPayloadRoot -destinationRoot $LangflowRoot -SkipAuthOverlay:$SkipAuthAddition
Ok "Copied $backendCopied backend files"
Patch-StockRouterForTWCOpenId -langflowRoot $LangflowRoot
Patch-StockLoginForTWCOpenId -langflowRoot $LangflowRoot
Patch-StockAlembicLegacyColumns -LangflowRoot $LangflowRoot
Patch-LangflowCliLocalOnlyVersionCheck -LangflowRoot $LangflowRoot
if (-not $SkipAuthAddition) {
  Patch-LangflowLoginLocalOnlyVariableInit -LangflowRoot $LangflowRoot
} else {
  Info "Skipped custom login/auth overlay; using Langflow's stock authentication"
}
Install-PythonStartupGuard -LangflowRoot $LangflowRoot

Info "Applying LFX patch files to $LfxRoot"
$lfxCopied = Copy-Tree -sourceRoot $LfxPayloadRoot -destinationRoot $LfxRoot -SkipAuthOverlay:$SkipAuthAddition
Ok "Copied $lfxCopied LFX files"

$staleLfxFiles = @(
  "components\models_and_agents\owui_models_agents.py",
  "components\vectorstores\local_path_vector_db.py"
)

foreach ($relativeStaleFile in $staleLfxFiles) {
  $stalePath = Join-Path $LfxRoot $relativeStaleFile
  Assert-PathWithinRoot -path $stalePath -root $LfxRoot
  if (Test-Path -LiteralPath $stalePath) {
    Remove-Item -LiteralPath $stalePath -Force
    Ok ("Removed stale experimental node file: {0}" -f $relativeStaleFile)
  }
}

$InstalledFrontendRoot = Join-Path $LangflowRoot "frontend"
if ($SkipAuthAddition -and -not (Test-Path -LiteralPath $FrontendBundlePath)) {
  Info "Keeping the freshly downloaded Langflow frontend; no custom GUI bundle supplied"
} else {
  Info "Replacing built frontend assets in $InstalledFrontendRoot"
  $frontendFiles = Install-FrontendBundle -bundlePath $FrontendBundlePath -destinationRoot $InstalledFrontendRoot
  Ok "Installed $frontendFiles frontend files"
  Install-TwcOpenIdUi -payloadRoot $PayloadRoot -frontendRoot $InstalledFrontendRoot
}

Info "Ensuring Langflow's default local auto-login mode in $EnvFile"
Ensure-EnvSetting -envFile $EnvFile -key "LANGFLOW_AUTO_LOGIN" -value "true"
Ok "Configured .env with LANGFLOW_AUTO_LOGIN=true"

Info "Ensuring LANGPATCHER_LOCAL_ONLY=true in $EnvFile"
Ensure-EnvSetting -envFile $EnvFile -key "LANGPATCHER_LOCAL_ONLY" -value "true"
Ok "Configured .env with LANGPATCHER_LOCAL_ONLY=true"

Write-InstallState `
  -path $StateFile `
  -installRoot $Root `
  -pythonPath $PythonPath `
  -pythonVersion $PythonVersion `
  -langflowVersion $InstalledLangflowVersion `
  -langflowRoot $LangflowRoot `
  -lfxRoot $LfxRoot `
  -payloadFingerprint $PayloadFingerprint `
  -installerFingerprint $InstallerFingerprint

$configPath = Save-PatcherConfig -Root $ConfigRoot -Updates @{
  langflow_target = $Root
  python_exe = $PythonPath
}

Ok "Patch completed."
Ok ("Saved local patcher defaults to {0}" -f $configPath)
Write-Host ""
Write-Host "Next:" -ForegroundColor White
Write-Host "  1. Use the GUI Launch button or run .\launcher.ps1." -ForegroundColor White
Write-Host "  2. Browse to http://127.0.0.1:7860 unless you changed host/port." -ForegroundColor White

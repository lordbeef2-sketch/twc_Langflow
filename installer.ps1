#!/usr/bin/env pwsh

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Info([string]$msg) { Write-Host "[installer] $msg" -ForegroundColor Cyan }
function Ok([string]$msg) { Write-Host "[installer] $msg" -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "[installer] $msg" -ForegroundColor Yellow }
function Fail([string]$msg) { Write-Host "[installer] $msg" -ForegroundColor Red; exit 1 }

function Test-IsWindows() {
  return [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
  )
}

function Ensure-Command([string]$name, [string]$installHint) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    Fail "Missing required command '$name'. $installHint"
  }
}

function Assert-PathWithinRoot([string]$path, [string]$root) {
  $resolvedPath = [System.IO.Path]::GetFullPath($path)
  $resolvedRoot = [System.IO.Path]::GetFullPath($root)
  if (-not $resolvedPath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    Fail "Refusing to modify path outside target root: $resolvedPath"
  }
}

function Get-InstallerPythonSpec() {
  if (-not [string]::IsNullOrWhiteSpace($env:LANGPATCHER_PYTHON)) {
    return $env:LANGPATCHER_PYTHON
  }

  return "3.11"
}

function Configure-UvForWindowsServer() {
  if ([string]::IsNullOrWhiteSpace($env:UV_TORCH_BACKEND)) {
    $env:UV_TORCH_BACKEND = "cpu"
    Info "Using CPU-only PyTorch wheels (UV_TORCH_BACKEND=cpu)"
  } else {
    Info "Using existing UV_TORCH_BACKEND=$($env:UV_TORCH_BACKEND)"
  }

  if (Test-IsWindows) {
    if ([string]::IsNullOrWhiteSpace($env:UV_NATIVE_TLS)) {
      $env:UV_NATIVE_TLS = "true"
    }
    if ([string]::IsNullOrWhiteSpace($env:UV_SYSTEM_CERTS)) {
      $env:UV_SYSTEM_CERTS = "true"
    }
    Info "Using Windows native/system TLS certificates for uv downloads"
  }
}

function Get-UvPipTorchBackendArgs() {
  $helpText = (& uv pip install --help) -join "`n"
  if ($helpText -match "--torch-backend") {
    return @("--torch-backend", "cpu")
  }

  Warn "This uv version does not support --torch-backend. Falling back to the PyTorch CPU wheel index."
  return @("--index", "https://download.pytorch.org/whl/cpu")
}

function Use-LocalVenv([string]$venvPath, [string]$pythonSpec) {
  if (-not (Test-Path $venvPath)) {
    Info "Creating folder-local Python environment at $venvPath with Python $pythonSpec"
    uv venv $venvPath --python $pythonSpec
    if ($LASTEXITCODE -ne 0) {
      Fail "uv venv failed. Install Python $pythonSpec with 'uv python install $pythonSpec' or set LANGPATCHER_PYTHON to another supported version, then rerun this installer."
    }
  } else {
    Info "Reusing local Python environment at $venvPath"
  }

  $activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
  if (-not (Test-Path $activateScript)) {
    Fail "Missing activation script: $activateScript"
  }

  . $activateScript
}

function Assert-SupportedPython() {
  $pythonVersion = (& python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($pythonVersion)) {
    Fail "Unable to determine the Python version in the local environment"
  }

  $parts = $pythonVersion.Split(".")
  if ($parts.Count -lt 2) {
    Fail "Unexpected Python version format: $pythonVersion"
  }

  $major = [int]$parts[0]
  $minor = [int]$parts[1]

  $minMinor = 10
  $maxMinor = 13
  $requiredMinor = $null
  $supportedRange = "3.10 through 3.13"
  if (Test-IsWindows) {
    $requiredMinor = 11
    $supportedRange = "3.11 on Windows"
  }

  if (
    $major -ne 3 -or
    $minor -lt $minMinor -or
    $minor -gt $maxMinor -or
    ($null -ne $requiredMinor -and $minor -ne $requiredMinor)
  ) {
    Fail "Langflow requires Python $supportedRange. Detected Python $pythonVersion. If this is an existing install, delete the local .venv folder or set LANGPATCHER_PYTHON=3.11 and rerun installer.ps1."
  }

  Ok "Using Python $pythonVersion in the local environment"
}

function Install-PytorchRuntime([array]$torchBackendArgs) {
  $installArgs = @(
    "pip",
    "install",
    "torch",
    "torchvision",
    "--only-binary",
    "torch",
    "--only-binary",
    "torchvision"
  ) + $torchBackendArgs

  Info "Preinstalling CPU-only torch and torchvision wheels"
  & uv @installArgs
  if ($LASTEXITCODE -ne 0) {
    Fail "Failed to install CPU-only torch/torchvision. On Windows Server, verify outbound HTTPS access to pypi.org and download.pytorch.org, update uv, and make sure the local environment is using Python 3.11."
  }
}

function Get-InstalledLangflowVersion() {
  $version = (& python -c "import importlib.metadata as metadata; print(metadata.version('langflow'))").Trim()
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

function Initialize-LangflowCheckout([string]$targetRoot, [string]$gitRef) {
  $repoUrl = "https://github.com/langflow-ai/langflow.git"

  if (-not (Test-Path $targetRoot)) {
    Info "Cloning Langflow source ref '$gitRef' into $targetRoot"
    git clone --depth 1 --branch $gitRef $repoUrl $targetRoot
    if ($LASTEXITCODE -ne 0) {
      Fail "git clone failed"
    }
    Ok "Created Langflow source checkout"
    return
  }

  $gitDir = Join-Path $targetRoot ".git"
  if (-not (Test-Path $gitDir)) {
    Fail "Target directory already exists and is not a git checkout: $targetRoot"
  }

  Warn "Existing Langflow checkout found at $targetRoot. Reusing it as-is."

  Push-Location $targetRoot
  try {
    $currentBranch = (& git branch --show-current).Trim()
    if (-not [string]::IsNullOrWhiteSpace($currentBranch) -and $currentBranch -ne $gitRef) {
      Warn "Current checkout is on '$currentBranch' instead of '$gitRef'. Continuing without switching branches."
    }
  } finally {
    Pop-Location
  }
}

$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $PackageRoot

$PayloadRoot = Join-Path $PackageRoot "patcher_payload"
$VenvPath = Join-Path $PackageRoot ".venv"
$TargetRoot = Join-Path $PackageRoot "langflow"

if (-not (Test-Path $PayloadRoot)) {
  Fail "Missing payload directory: $PayloadRoot"
}

Ensure-Command "uv" "Install uv, then rerun this script."
Ensure-Command "git" "Install Git, then rerun this script."
Ensure-Command "npm" "Install Node.js and npm, then rerun this script."

$PythonSpec = Get-InstallerPythonSpec
$TorchBackendArgs = Get-UvPipTorchBackendArgs
Configure-UvForWindowsServer

Use-LocalVenv -venvPath $VenvPath -pythonSpec $PythonSpec
Assert-SupportedPython

Install-PytorchRuntime -torchBackendArgs $TorchBackendArgs

Info "Installing Langflow into the local environment"
$langflowInstallArgs = @(
  "pip",
  "install",
  "langflow",
  "-U",
  "--only-binary",
  "torch",
  "--only-binary",
  "torchvision"
) + $TorchBackendArgs
& uv @langflowInstallArgs
if ($LASTEXITCODE -ne 0) {
  Fail "uv pip install langflow -U failed. The most common Windows Server cause is an incompatible Python or PyTorch wheel. This installer expects Python 3.11 and CPU torch wheels; delete .venv and rerun if the environment was created before this fix."
}

$InstalledLangflowVersion = Get-InstalledLangflowVersion
Ok "Installed Langflow $InstalledLangflowVersion into the local environment"

$SourceRef = Resolve-LangflowGitRef $InstalledLangflowVersion
Initialize-LangflowCheckout -targetRoot $TargetRoot -gitRef $SourceRef

$files = @(
  "src/backend/base/langflow/alembic/versions/f4a1c2d3e4b5_add_flow_share_table.py",
  "src/backend/base/langflow/api/v1/sso.py",
  "src/backend/base/langflow/api/v1/admin_settings.py",
  "src/backend/base/langflow/api/v1/__init__.py",
  "src/backend/base/langflow/api/router.py",
  "src/backend/base/langflow/api/v1/flows.py",
  "src/backend/base/langflow/api/v1/flows_helpers.py",
  "src/backend/base/langflow/api/v1/schemas/__init__.py",
  "src/backend/base/langflow/api/v1/users.py",
  "src/backend/base/langflow/main.py",
  "src/backend/base/langflow/services/database/models/__init__.py",
  "src/backend/base/langflow/services/database/models/flow/model.py",
  "src/backend/base/langflow/services/database/models/flow_share/__init__.py",
  "src/backend/base/langflow/services/database/models/flow_share/model.py",
  "src/lfx/src/lfx/services/settings/base.py",
  "src/frontend/src/components/core/appHeaderComponent/index.tsx",
  "src/frontend/src/components/core/appHeaderComponent/components/FlowMenu/index.tsx",
  "src/frontend/src/pages/SettingsPage/pages/GeneralPage/components/SsoSettingsCard/index.tsx",
  "src/frontend/src/components/core/flowSettingsComponent/index.tsx",
  "src/frontend/src/components/core/flowToolbarComponent/components/deploy-dropdown.tsx",
  "src/frontend/src/components/core/flowShareInvitePrompt/index.tsx",
  "src/frontend/src/components/core/folderSidebarComponent/components/sideBarFolderButtons/components/input-edit-folder-name.tsx",
  "src/frontend/src/pages/SettingsPage/pages/OAuthSSOPage/index.tsx",
  "src/frontend/src/pages/SettingsPage/pages/SAMLSSOPage/index.tsx",
  "src/frontend/src/pages/SettingsPage/pages/HTTPSPage/index.tsx",
  "src/frontend/src/pages/SettingsPage/index.tsx",
  "src/frontend/src/routes.tsx",
  "src/frontend/src/pages/SettingsPage/pages/GeneralPage/index.tsx",
  "src/frontend/src/pages/SettingsPage/pages/GeneralPage/components/AuthSecuritySettingsCard/index.tsx",
  "src/frontend/src/pages/AppInitPage/index.tsx",
  "src/frontend/src/modals/flowShareModal/index.tsx",
  "src/frontend/src/modals/saveChangesModal/index.tsx",
  "src/frontend/src/hooks/flows/use-save-flow.ts",
  "src/frontend/src/pages/FlowPage/index.tsx",
  "src/frontend/src/pages/FlowPage/components/PageComponent/index.tsx",
  "src/frontend/src/pages/MainPage/components/dropdown/index.tsx",
  "src/frontend/src/pages/MainPage/components/list/index.tsx",
  "src/frontend/src/pages/MainPage/entities/index.tsx",
  "src/frontend/src/pages/MainPage/pages/empty-page.tsx",
  "src/frontend/src/pages/MainPage/pages/homePage/index.tsx",
  "src/frontend/src/pages/MainPage/pages/homePage/utils/isFolderEmpty.ts",
  "src/frontend/src/pages/MainPage/pages/main-page-utils.ts",
  "src/frontend/src/controllers/API/index.ts",
  "src/frontend/src/pages/FlowPage/components/UpdateAllComponents/index.tsx",
  "src/frontend/src/CustomNodes/GenericNode/index.tsx",
  "src/frontend/src/controllers/API/helpers/constants.ts",
  "src/frontend/src/controllers/API/queries/config/use-get-config.ts",
  "src/frontend/src/controllers/API/queries/auth/use-get-sso-config.ts",
  "src/frontend/src/controllers/API/queries/auth/use-get-sso-providers.ts",
  "src/frontend/src/controllers/API/queries/auth/use-get-shareable-users.ts",
  "src/frontend/src/controllers/API/queries/auth/use-put-sso-config.ts",
  "src/frontend/src/controllers/API/queries/auth/use-get-saml-metadata.ts",
  "src/frontend/src/controllers/API/queries/auth/use-get-https-settings.ts",
  "src/frontend/src/controllers/API/queries/auth/use-put-https-settings.ts",
  "src/frontend/src/controllers/API/queries/auth/use-post-https-file-upload.ts",
  "src/frontend/src/controllers/API/queries/auth/use-get-sso-settings.ts",
  "src/frontend/src/controllers/API/queries/auth/use-put-sso-settings.ts",
  "src/frontend/src/controllers/API/queries/auth/index.ts",
  "src/frontend/src/controllers/API/queries/folders/use-get-folder.ts",
  "src/frontend/src/controllers/API/queries/folders/use-get-folders.ts",
  "src/frontend/src/controllers/API/queries/flows/use-create-flow-shares.ts",
  "src/frontend/src/controllers/API/queries/flows/use-get-incoming-flow-shares.ts",
  "src/frontend/src/controllers/API/queries/flows/use-respond-to-flow-share.ts",
  "src/frontend/src/components/core/appHeaderComponent/components/AccountMenu/index.tsx",
  "src/frontend/src/components/core/appHeaderComponent/components/langflow-counts.tsx",
  "src/frontend/src/components/core/folderSidebarComponent/components/sideBarFolderButtons/components/get-started-progress.tsx",
  "src/frontend/src/components/core/folderSidebarComponent/components/sideBarFolderButtons/components/header-buttons.tsx",
  "src/frontend/src/components/core/folderSidebarComponent/components/sideBarFolderButtons/components/select-options.tsx",
  "src/frontend/src/components/core/folderSidebarComponent/components/sideBarFolderButtons/index.tsx",
  "src/frontend/src/customization/components/custom-get-started-progress.tsx",
  "src/frontend/src/constants/constants.ts",
  "src/frontend/src/stores/flowStore.ts",
  "src/frontend/src/stores/flowsManagerStore.ts",
  "src/frontend/src/types/flow/index.ts",
  "src/frontend/src/utils/flowAccess.ts"
)

$authSecurityCardFallback = @'
import type { ConfigResponse } from "@/controllers/API/queries/config/use-get-config";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type AuthSecuritySettingsCardProps = {
  config: ConfigResponse;
};

export default function AuthSecuritySettingsCard({
  config,
}: AuthSecuritySettingsCardProps): JSX.Element {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Authentication Security</CardTitle>
        <CardDescription>
          Current authentication and account policy values loaded from server
          settings.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">Public Sign Up</p>
            <p className="font-medium">
              {config.enable_public_signup ? "Enabled" : "Disabled"}
            </p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">Password Minimum Length</p>
            <p className="font-medium">{config.password_min_length}</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">
              Password Character Classes
            </p>
            <p className="font-medium">{config.password_min_character_classes}</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">Login Max Attempts</p>
            <p className="font-medium">{config.login_max_attempts}</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">Login Attempt Window</p>
            <p className="font-medium">
              {config.login_attempt_window_seconds} seconds
            </p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">Lockout Duration</p>
            <p className="font-medium">{config.login_lockout_seconds} seconds</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">SSO Feature Flag</p>
            <p className="font-medium">
              {config.sso_enabled ? "Enabled" : "Disabled"}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
'@

$getSSOProvidersFallback = @'
import type { useQueryFunctionType } from "@/types/api";
import type { SSOConfigResponseType } from "./use-get-sso-config";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const useGetSSOProviders: useQueryFunctionType<
  undefined,
  SSOConfigResponseType[]
> = (options) => {
  const { query } = UseRequestProcessor();

  const getSSOProvidersFn = async () => {
    const response = await api.get<SSOConfigResponseType[]>(
      `${getURL("SSO")}/providers`,
    );
    return response.data;
  };

  return query(["useGetSSOProviders"], getSSOProvidersFn, {
    refetchOnWindowFocus: false,
    ...options,
  });
};
'@

Info "Restoring feature files from patcher_payload into $TargetRoot"
$restored = 0
foreach ($rel in $files) {
  $src = Join-Path $PayloadRoot $rel
  $dst = Join-Path $TargetRoot $rel
  $dstDir = Split-Path -Parent $dst

  if (-not (Test-Path $dstDir)) {
    New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
  }

  if (-not (Test-Path $src)) {
    if ($rel -eq "src/frontend/src/pages/SettingsPage/pages/GeneralPage/components/AuthSecuritySettingsCard/index.tsx") {
      if (-not (Test-Path $dst)) {
        Warn "Payload missing AuthSecuritySettingsCard. Creating fallback component at $rel"
        Set-Content -Path $dst -Value $authSecurityCardFallback -NoNewline
      } else {
        Warn "Payload missing AuthSecuritySettingsCard. Keeping existing file at $rel"
      }
      $restored++
      continue
    }

    if ($rel -eq "src/frontend/src/controllers/API/queries/auth/use-get-sso-providers.ts") {
      if (-not (Test-Path $dst)) {
        Warn "Payload missing use-get-sso-providers. Creating fallback hook at $rel"
        Set-Content -Path $dst -Value $getSSOProvidersFallback -NoNewline
      } else {
        Warn "Payload missing use-get-sso-providers. Keeping existing file at $rel"
      }
      $restored++
      continue
    }

    Fail "Missing payload file: $src"
  }

  Copy-Item -Path $src -Destination $dst -Force
  $restored++
}
Ok "Restored $restored files"

Info "Ensuring LANGFLOW_AUTO_LOGIN=false in langflow/.env"
$envFile = Join-Path $TargetRoot ".env"
$autoLoginLine = "LANGFLOW_AUTO_LOGIN=false"
if (Test-Path $envFile) {
  $envContent = Get-Content -Path $envFile -Raw
  if ($envContent -match "(?m)^\s*LANGFLOW_AUTO_LOGIN\s*=") {
    $updated = [regex]::Replace(
      $envContent,
      "(?m)^\s*LANGFLOW_AUTO_LOGIN\s*=.*$",
      $autoLoginLine
    )
    Set-Content -Path $envFile -Value $updated -NoNewline
  } else {
    $trimmed = $envContent.TrimEnd("`r", "`n")
    if ($trimmed.Length -gt 0) {
      $trimmed = $trimmed + "`r`n"
    }
    Set-Content -Path $envFile -Value ($trimmed + $autoLoginLine + "`r`n") -NoNewline
  }
} else {
  Set-Content -Path $envFile -Value ($autoLoginLine + "`r`n") -NoNewline
}
Ok "Configured langflow/.env with LANGFLOW_AUTO_LOGIN=false"

$authIndexPath = Join-Path $TargetRoot "src/frontend/src/controllers/API/queries/auth/index.ts"
if (Test-Path $authIndexPath) {
  $authIndex = Get-Content -Path $authIndexPath -Raw
  $matches = [regex]::Matches($authIndex, 'export \* from "\./([^"]+)";')
  $missing = @()
  foreach ($m in $matches) {
    $name = $m.Groups[1].Value
    $candidate = Join-Path $TargetRoot ("src/frontend/src/controllers/API/queries/auth/{0}.ts" -f $name)
    if (-not (Test-Path $candidate)) {
      $missing += $candidate
    }
  }

  if ($missing.Count -gt 0) {
    $list = ($missing | ForEach-Object { " - $_" }) -join "`n"
    Fail "Missing auth query files referenced by auth/index.ts:`n$list"
  }
}

Info "Syncing Python dependencies for the patched Langflow checkout into the active environment"
Push-Location $TargetRoot
try {
  uv sync --active --no-dev
  if ($LASTEXITCODE -ne 0) {
    Fail "uv sync --active --no-dev failed"
  }
} finally {
  Pop-Location
}

Info "Installing frontend dependencies"
Push-Location (Join-Path $TargetRoot "src/frontend")
try {
  npm install
  if ($LASTEXITCODE -ne 0) {
    Fail "npm install failed"
  }

  Info "Building frontend"
  npm run build
  if ($LASTEXITCODE -ne 0) {
    Fail "npm run build failed"
  }
} finally {
  Pop-Location
}

Info "Syncing build output to backend static frontend"
$frontendDest = Join-Path $TargetRoot "src/backend/base/langflow/frontend"
Assert-PathWithinRoot -path $frontendDest -root $TargetRoot

if (-not (Test-Path $frontendDest)) {
  New-Item -ItemType Directory -Path $frontendDest -Force | Out-Null
}

Get-ChildItem -Path $frontendDest -Force | Remove-Item -Recurse -Force
Copy-Item -Path (Join-Path $TargetRoot "src/frontend/build/*") -Destination $frontendDest -Recurse -Force

Ok "Install + patch completed."
Write-Host "Run: .\launcher.ps1" -ForegroundColor White

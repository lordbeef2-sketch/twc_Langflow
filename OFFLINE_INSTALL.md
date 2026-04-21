# Offline Windows Server Install

Use this when the Windows Server cannot reliably download Python packages through `uv`.

## 1. Build the bundle on a Windows machine with internet

Run from the LangPatcher folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-offline-bundle.ps1 -Clean
```

This creates:

```text
offline_bundle\
offline_bundle.zip
```

The bundle contains:

- Python wheels for the resolved Langflow environment
- CPU PyTorch / torchvision wheels
- A matching Langflow source archive
- A prebuilt patched frontend, so the server does not need `npm install`

Do not commit the bundle to Git. The PyTorch wheels are too large for normal GitHub repository files.

## 2. Copy the bundle to Windows Server 2022

Copy `offline_bundle.zip` next to `installer.ps1`, then extract it so the folder layout is:

```text
LangPatcher\
  installer.ps1
  launcher.ps1
  patcher_payload\
  offline_bundle\
    manifest.json
    python-wheels\
    langflow-source.zip
    frontend-build.zip
```

## 3. Run the installer offline

Install Python 3.11 on the server first. Then run:

```powershell
Remove-Item -Recurse -Force .\.venv -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\langflow -ErrorAction SilentlyContinue
powershell -ExecutionPolicy Bypass -File .\installer.ps1
```

When `offline_bundle\manifest.json` exists, `installer.ps1` automatically switches to offline mode. It uses the local wheelhouse and bundled source archive instead of downloading from package indexes or GitHub.

If you store the bundle somewhere else, point the installer at it:

```powershell
$env:LANGPATCHER_OFFLINE_BUNDLE = "D:\bundles\offline_bundle"
powershell -ExecutionPolicy Bypass -File .\installer.ps1
```

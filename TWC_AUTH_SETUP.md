# Langflow authentication and sharing

This package installs the current Langflow release and applies the local
knowledge-base, ingestion, component, and Windows runtime patches.

The package does **not** add a custom Teamwork Cloud authentication layer.
Langflow's stock authentication and authorization remain the source of truth.
Configure the normal Langflow credentials for the first run:

```env
LANGFLOW_SUPERUSER=admin
LANGFLOW_SUPERUSER_PASSWORD=choose-a-password
LANGFLOW_AUTO_LOGIN=false
```

Do not add TWC OAuth, OpenID, SAML, callback, or TWC preset-server variables to
this package. They are not consumed by the installed Langflow runtime.

## Flow sharing

User and team flow sharing remains provided by Langflow's native authorization
system. The native share UI and `/api/v1/authz/shares` routes are retained.
Sharing uses the Langflow users and authorization records; no separate TWC
identity bridge is installed.

## Install and verify

Run the installer from this directory, then validate the local runtime:

```powershell
.\installer.ps1 -InstallRoot . -Force -SkipAuthAddition
.\launcher.ps1 -ValidateOnly
.\launcher.ps1
```

The installer keeps the freshly downloaded Langflow frontend and skips the old
custom auth/sharing overlay. It also keeps the local-only runtime guard,
knowledge-base/ingestion patches, and LFX component overlays.

# Langflow TWC OpenID setup

This package keeps Langflow's native users, permissions, and flow/project
sharing. It adds one GUI-managed authentication lane for Teamwork Cloud:
OpenID Connect (OIDC).

The installer also keeps databases created by the retired v4 overlay readable:
its legacy compatibility columns are ignored by the current migration check, so
an existing database does not need to be reset or manually edited.

## Configure it in the GUI

1. Launch Langflow and sign in as the local administrator.
2. Open **Settings → OAuth SSO**.
3. Enable SSO, then enter the TWC OpenID client ID, client secret, discovery
   URL (or the explicit OIDC endpoints), redirect URI, and claim names. The
   patch fixes the TWC defaults to the same Refresh3 contract as Workbench:
   `openid` scope, AuthServer discovery on `/authentication/.well-known/oidc-configuration`,
   authorization on `/authentication/oidc/authorize`, token exchange on
   `/authentication/api/oidc/token` using `client_secret_basic` with
   `scope=openid`, and live user resolution through
   `/osmc/admin/currentUser?permission=true`. Langflow follows Workbench's
   token precedence when TWC returns both values: the ID token is sent to the
   live current-user endpoint first, with the access token as fallback.
4. Save. Langflow encrypts the client secret in its database and switches the
   live login path to TWC OpenID. No `.env` edit or hand-maintained config is
   required.

Register this exact callback in the TWC OpenID client:

```text
<public Langflow URL>/api/v1/sso/callback
```

The GUI hides the retired SAML lane. This patch does not add OAuth-password,
SAML, or a second TWC authentication system. The callback path is still
Langflow-specific (`/api/v1/sso/callback`); only the TWC AuthServer protocol
and endpoint contract are shared with Workbench.

## Sharing

Native Langflow flow/project sharing remains installed. After a user signs in
through TWC OpenID, Langflow maps the TWC subject to a local user profile, so
existing sharing and permissions apply to that user.

## Local fallback

Keep the local administrator session open while testing the provider. The GUI
toggle can disable the provider without editing environment files. The stock
local login route remains available for a configured Langflow administrator.

## Install and verify

```powershell
.\installer.ps1 -InstallRoot . -Force
.\launcher.ps1 -ValidateOnly
.\launcher.ps1
```

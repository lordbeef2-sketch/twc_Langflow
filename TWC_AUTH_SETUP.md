# Teamwork Cloud Login Setup

This patch adds Teamwork Cloud Authentication Server login to Langflow using the TWC authorization-code flow.

## Required operator config

Set these values in the environment for the Langflow process:

```env
APP_ORIGIN=https://langflow.example.com
TWC_PRESET_SERVERS=[{"id":"prod","name":"Production TWC","base_url":"https://twc.example.com:8111","verify_tls":true,"enabled":true,"display_order":1}]
TWC_AUTH_CLIENT_ID=langflow-client
TWC_AUTH_CLIENT_SECRET=replace-with-authentication-client-secret
TWC_AUTH_CALLBACK_PATH=/api/auth/callback
TWC_AUTH_SCOPE=openid
TWC_SAML_LOGIN_PATH=/authentication/authorize
TWC_SAML_LOGIN_PORT=8443
TWC_SAML_TOKEN_PATH=/authentication/api/token
TWC_SAML_RETURN_URL_PARAMETER=redirect_uri
```

Supported aliases:

- `authentication.client.ids`
- `authentication.client.secret`
- `TWC_AUTHENTICATION_CLIENT_ID`
- `TWC_AUTHENTICATION_CLIENT_IDS`
- `TWC_AUTHENTICATION_CLIENT_SECRET`

`TWC_PRESET_SERVERS` accepts:

- a JSON array of server objects
- a JSON object keyed by server id
- a comma-separated list such as `prod=https://twc.example.com:8111`

Each server object may include:

```json
{
  "id": "prod",
  "name": "Production TWC",
  "base_url": "https://twc.example.com:8111",
  "verify_tls": true,
  "ca_bundle_path": "C:/certs/internal-ca.pem",
  "enabled": true,
  "display_order": 1
}
```

Accepted server keys include:

- `base_url` or `rest_url`
- `name` or `label`
- `verify_tls`
- `ca_bundle_path`
- `enabled`
- `display_order`

## Optional per-server overrides

Use `TWC_AUTH_SERVER_OVERRIDES` when the Authentication Server host, path, client, or TLS behavior differs from the default derived values:

```env
TWC_AUTH_SERVER_OVERRIDES={
  "prod": {
    "authorize_url": "https://auth.example.com:8443/authentication/authorize",
    "token_url": "https://auth.example.com:8443/authentication/api/token",
    "verify_tls": "C:/certs/internal-ca.pem",
    "scope": "openid",
    "client_id": "langflow-client",
    "client_secret": "replace-with-secret",
    "return_url_parameter": "redirect_uri"
  }
}
```

Supported per-server override keys:

- `authorize_url`
- `token_url`
- `login_path`
- `login_port`
- `token_path`
- `return_url_parameter`
- `scope`
- `client_id`
- `client_secret`
- `authentication.client.id`
- `authentication.client.ids`
- `authentication_client_id`
- `authentication_client_ids`
- `authentication.client.secret`
- `authentication_client_secret`
- `verify_tls`
- `ca_bundle_path`

`verify_tls` supports:

- `true`
- `false`
- a CA bundle path

## Required TWC / AuthServer setup

TWC operators must make sure:

- the Langflow callback URL is whitelisted in `authentication.redirect.uri.whitelist`
- the configured client id exists in `authentication.client.ids`
- the configured secret matches `authentication.client.secret`

For the default callback path, whitelist:

```text
https://langflow.example.com/api/auth/callback
```

Backward-compatible callback routes still exist under `/api/v1/auth/twc/callback`, but a New Project-style setup can now use `/api/auth/callback` directly.

## Flow summary

1. Langflow redirects the browser to `/authentication/authorize`.
2. TWC Authentication Server handles the SAML/IdP portion.
3. TWC redirects back to Langflow with a `code`.
4. Langflow exchanges the code at `/authentication/api/token` using `X-Auth-Secret`.
5. Langflow validates the returned token against `/osmc/admin/currentUser?permission=true`.
6. Langflow keeps TWC session data server-side and uses `Authorization: Token <token>` for TWC REST calls.

## Local verification

Example local env:

```powershell
$env:APP_ORIGIN='http://127.0.0.1:7860'
$env:TWC_PRESET_SERVERS='[{"id":"alpha","name":"Alpha TWC","base_url":"https://alpha.example.com:8111","verify_tls":false}]'
$env:TWC_AUTH_CLIENT_ID='langflow-client'
$env:TWC_AUTH_CLIENT_SECRET='replace-with-secret'
$env:TWC_AUTH_CALLBACK_PATH='/api/auth/callback'
.\launcher.ps1
```

Expected routes:

- `GET /api/auth/servers`
- `GET /api/auth/signin/{server_id}`
- `GET /api/auth/callback`
- `POST /api/auth/logout`
- `GET /api/auth/status`
- `GET /api/v1/auth/twc/servers`
- `GET /api/v1/auth/twc/signin/{server_id}`
- `GET /api/v1/auth/twc/callback`
- `POST /api/v1/auth/twc/logout`
- `GET /api/v1/auth/twc/status`

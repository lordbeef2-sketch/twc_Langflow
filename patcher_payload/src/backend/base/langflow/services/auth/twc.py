from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import httpx
import jwt
from fastapi import HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlmodel import select

from langflow.api.utils import DbSession
from langflow.initial_setup.setup import get_or_create_default_folder
from langflow.services.database.models.auth.sso import SSOUserProfile
from langflow.services.database.models.user.model import User
from langflow.services.deps import get_auth_service, get_settings_service, get_variable_service

TWC_PROVIDER = "twc"
TWC_STATE_NONCE_COOKIE = "twc_state_nonce_lf"
TWC_STATE_SERVER_COOKIE = "twc_state_server_lf"
TWC_SESSION_ID_COOKIE = "twc_session_id_lf"
TWC_SESSION_VERSION = 1
TWC_STATE_TTL_SECONDS = 600
TWC_SESSION_LEEWAY_SECONDS = 60
TWC_CALLBACK_DEFAULT_PATH = "/api/auth/callback"
LEGACY_TWC_AUTH_PATHS = {
    "/osmc/authen/login",
    "/osmc/login.html",
    "/authentication/saml2/sso/tssd-twc2024x",
}


class TWCServerConfig(BaseModel):
    id: str
    label: str
    rest_url: str
    authorize_url: str
    token_url: str
    scope: str = "openid"
    client_id: str | None = None
    client_secret: str | None = None
    return_url_parameter: str = "redirect_uri"
    verify_tls: bool | str = True
    ca_bundle_path: str | None = None
    ready: bool = True
    error: str | None = None


class TWCIdentity(BaseModel):
    external_user_id: str
    username: str
    email: str | None = None
    display_name: str | None = None


class TWCSessionData(BaseModel):
    version: int = TWC_SESSION_VERSION
    session_id: str
    server_id: str
    server_label: str
    rest_url: str
    authorize_url: str
    token_url: str
    scope: str
    client_id: str
    return_url_parameter: str = "redirect_uri"
    verify_tls: bool | str = True
    id_token: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None
    current_user: dict[str, Any] = Field(default_factory=dict)
    external_user_id: str
    username: str
    email: str | None = None
    id_token_expires_at: datetime | None = None
    access_token_expires_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def current_token(self) -> str | None:
        return self.id_token or self.access_token

    def has_refresh_token(self) -> bool:
        return bool(self.refresh_token)


def _safe_next(next_url: str | None) -> str:
    if not next_url or not next_url.startswith("/"):
        return "/"
    return next_url


def _get_callback_path() -> str:
    callback_path = getattr(get_settings_service().settings, "twc_auth_callback_path", TWC_CALLBACK_DEFAULT_PATH)
    callback_path = str(callback_path or TWC_CALLBACK_DEFAULT_PATH).strip() or TWC_CALLBACK_DEFAULT_PATH
    return callback_path if callback_path.startswith("/") else f"/{callback_path}"


def _get_app_prefix_from_callback_url(callback_url: str) -> tuple[str, str, str]:
    parsed = urlparse(callback_url)
    callback_path = _get_callback_path()
    base_path = parsed.path
    if callback_path and base_path.endswith(callback_path):
        app_prefix = base_path[: -len(callback_path)]
    else:
        app_prefix = ""
    if app_prefix.endswith("/"):
        app_prefix = app_prefix.rstrip("/")
    return parsed.scheme, parsed.netloc, app_prefix


def build_post_login_redirect_url(*, request: Request, next_url: str | None) -> str:
    callback_url = get_twc_callback_url(request)
    scheme, netloc, app_prefix = _get_app_prefix_from_callback_url(callback_url)
    normalized_next = _safe_next(next_url)

    if app_prefix:
        if normalized_next == "/":
            target_path = f"{app_prefix}/"
        elif normalized_next == app_prefix or normalized_next.startswith(f"{app_prefix}/"):
            target_path = normalized_next
        else:
            target_path = f"{app_prefix}{normalized_next}"
    else:
        target_path = normalized_next

    return f"{scheme}://{netloc}{target_path}"


def _cookie_settings() -> Any:
    return get_settings_service().auth_settings


def set_cookie(response: Response, key: str, value: str, *, max_age: int | None = None) -> None:
    auth_settings = _cookie_settings()
    response.set_cookie(
        key,
        value,
        httponly=True,
        samesite=auth_settings.ACCESS_SAME_SITE,
        secure=auth_settings.ACCESS_SECURE,
        max_age=max_age,
        domain=auth_settings.COOKIE_DOMAIN,
    )


def delete_cookie(response: Response, key: str) -> None:
    auth_settings = _cookie_settings()
    response.delete_cookie(
        key,
        httponly=True,
        samesite=auth_settings.ACCESS_SAME_SITE,
        secure=auth_settings.ACCESS_SECURE,
        domain=auth_settings.COOKIE_DOMAIN,
    )


def _session_dir() -> Path:
    settings = get_settings_service().settings
    base_dir = Path(settings.config_dir or Path.home() / ".langflow").expanduser()
    twc_dir = base_dir / "twc_sessions"
    twc_dir.mkdir(parents=True, exist_ok=True)
    return twc_dir


def _session_file(session_id: str) -> Path:
    safe_session_id = "".join(char for char in session_id if char.isalnum() or char in {"-", "_"})
    return _session_dir() / f"{safe_session_id}.json"


def _state_signing_key() -> str:
    auth_settings = get_settings_service().auth_settings
    secret = auth_settings.SECRET_KEY.get_secret_value()
    if not secret:
        msg = "Langflow secret key is not configured."
        raise HTTPException(status_code=500, detail=msg)
    return secret


def create_signed_state(*, server_id: str, next_url: str, nonce: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "server_id": server_id,
        "next": _safe_next(next_url),
        "nonce": nonce,
        "iat": now,
        "exp": now + timedelta(seconds=TWC_STATE_TTL_SECONDS),
        "kind": "twc_state",
    }
    return jwt.encode(payload, _state_signing_key(), algorithm="HS256")


def decode_signed_state(state: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(state, _state_signing_key(), algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired TWC login state.") from exc
    if payload.get("kind") != "twc_state":
        raise HTTPException(status_code=400, detail="Invalid TWC login state.")
    return payload


def clear_twc_state_cookies(response: Response) -> None:
    delete_cookie(response, TWC_STATE_NONCE_COOKIE)
    delete_cookie(response, TWC_STATE_SERVER_COOKIE)


def set_twc_session_cookie(response: Response, session_id: str) -> None:
    auth_settings = _cookie_settings()
    response.set_cookie(
        TWC_SESSION_ID_COOKIE,
        session_id,
        httponly=True,
        samesite=auth_settings.REFRESH_SAME_SITE,
        secure=auth_settings.REFRESH_SECURE,
        expires=auth_settings.REFRESH_TOKEN_EXPIRE_SECONDS,
        domain=auth_settings.COOKIE_DOMAIN,
    )


def clear_twc_session_cookie(response: Response) -> None:
    auth_settings = _cookie_settings()
    response.delete_cookie(
        TWC_SESSION_ID_COOKIE,
        httponly=True,
        samesite=auth_settings.REFRESH_SAME_SITE,
        secure=auth_settings.REFRESH_SECURE,
        domain=auth_settings.COOKIE_DOMAIN,
    )


def _normalize_scope(scope: str | None) -> str:
    if not scope:
        return "openid"
    normalized = scope.strip()
    return normalized or "openid"


def _normalize_verify_tls(value: Any) -> bool | str:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    if isinstance(value, Path):
        return str(value.expanduser())
    if isinstance(value, (int, float)):
        return bool(value)
    value_str = str(value).strip()
    if not value_str:
        return True
    lowered = value_str.lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    return str(Path(value_str).expanduser())


def _normalize_ca_bundle_path(value: Any) -> str | None:
    if value is None:
        return None
    value_str = str(value).strip()
    if not value_str:
        return None
    return str(Path(value_str).expanduser())


def _resolve_httpx_verify(server: TWCServerConfig) -> bool | str:
    if server.verify_tls and server.ca_bundle_path:
        return server.ca_bundle_path
    return server.verify_tls


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
            continue
        return value
    return None


def _parse_complex_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def _normalize_rest_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("TWC server entry is missing a REST base URL.")
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    scheme = parsed.scheme or "https"
    host = parsed.hostname or parsed.path
    if not host:
        raise ValueError(f"Invalid TWC REST URL: {value}")
    port = parsed.port or 8111
    netloc = f"{host}:{port}"
    path = parsed.path.rstrip("/")
    return urlunparse((scheme, netloc, path, "", "", "")).rstrip("/")


def _normalize_auth_path(value: Any, *, default: str) -> str:
    if value is None:
        value = default
    raw = str(value).strip()
    if not raw:
        raw = default
    if default == "/authentication/authorize" and raw.lower() in LEGACY_TWC_AUTH_PATHS:
        raw = "/authentication/authorize"
    if not raw.startswith("/"):
        raw = f"/{raw}"
    return raw


def _derive_auth_url(rest_url: str, *, port: int, path: str) -> str:
    parsed = urlparse(rest_url)
    host = parsed.hostname
    if not host:
        raise ValueError(f"Invalid TWC REST URL: {rest_url}")
    auth_path = path if path.startswith("/") else f"/{path}"
    return f"https://{host}:{port}{auth_path}"


def _as_override_map(raw_value: Any) -> dict[str, dict[str, Any]]:
    parsed = _parse_complex_value(raw_value)
    if not parsed:
        return {}
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=500,
            detail="TWC_AUTH_SERVER_OVERRIDES must be a JSON object keyed by server id or host.",
        )
    result: dict[str, dict[str, Any]] = {}
    for key, value in parsed.items():
        if isinstance(value, dict):
            result[str(key)] = value
    return result


def _as_server_entries(raw_value: Any) -> list[dict[str, Any]]:
    parsed = _parse_complex_value(raw_value)
    if not parsed:
        return []
    if isinstance(parsed, dict):
        entries: list[dict[str, Any]] = []
        for key, value in parsed.items():
            if isinstance(value, str):
                entries.append({"id": str(key), "rest_url": value})
            elif isinstance(value, dict):
                entry = {"id": str(key)}
                entry.update(value)
                entries.append(entry)
        return entries
    if isinstance(parsed, list):
        entries = []
        for index, value in enumerate(parsed, start=1):
            if isinstance(value, str):
                entries.append({"rest_url": value, "id": f"server-{index}"})
            elif isinstance(value, dict):
                entries.append(value)
        return entries
    if isinstance(parsed, str):
        entries = []
        for index, part in enumerate(parsed.split(","), start=1):
            segment = part.strip()
            if not segment:
                continue
            if "=" in segment:
                server_id, rest_url = segment.split("=", 1)
                entries.append({"id": server_id.strip(), "rest_url": rest_url.strip()})
            else:
                entries.append({"rest_url": segment, "id": f"server-{index}"})
        return entries
    raise HTTPException(
        status_code=500,
        detail="TWC_PRESET_SERVERS must be a JSON array/object or a comma-separated list.",
    )


def load_twc_server_configs() -> list[TWCServerConfig]:
    settings = get_settings_service().settings
    overrides = _as_override_map(getattr(settings, "twc_auth_server_overrides", None))
    raw_entries = _as_server_entries(getattr(settings, "twc_preset_servers", None))
    global_client_id = _first_non_empty(getattr(settings, "twc_auth_client_id", None))
    global_client_secret = getattr(settings, "twc_auth_client_secret", None)
    if global_client_secret is not None and hasattr(global_client_secret, "get_secret_value"):
        global_client_secret = global_client_secret.get_secret_value()

    ordered_entries = sorted(
        raw_entries,
        key=lambda entry: (
            int(entry.get("display_order", entry.get("displayOrder", 0)) or 0),
            str(entry.get("id") or entry.get("server_id") or ""),
        ),
    )

    configs: list[TWCServerConfig] = []
    for index, entry in enumerate(ordered_entries, start=1):
        try:
            enabled = entry.get("enabled")
            if enabled is False:
                continue
            rest_url = _normalize_rest_url(
                str(
                    _first_non_empty(
                        entry.get("base_url"),
                        entry.get("baseUrl"),
                        entry.get("rest_url"),
                        entry.get("url"),
                        entry.get("server"),
                        entry.get("host"),
                    )
                )
            )
            host = urlparse(rest_url).hostname or f"server-{index}"
            server_id = str(_first_non_empty(entry.get("id"), entry.get("server_id"), host)).strip()
            override = overrides.get(server_id) or overrides.get(host) or overrides.get(rest_url) or {}
            label = str(_first_non_empty(entry.get("label"), entry.get("name"), override.get("label"), host))
            login_port = int(
                _first_non_empty(
                    entry.get("login_port"),
                    override.get("login_port"),
                    getattr(settings, "twc_saml_login_port", 8443),
                )
            )
            login_path = _normalize_auth_path(
                _first_non_empty(
                    entry.get("login_path"),
                    override.get("login_path"),
                    getattr(settings, "twc_saml_login_path", "/authentication/authorize"),
                ),
                default="/authentication/authorize",
            )
            token_path = _normalize_auth_path(
                _first_non_empty(
                    entry.get("token_path"),
                    override.get("token_path"),
                    getattr(settings, "twc_saml_token_path", "/authentication/api/token"),
                ),
                default="/authentication/api/token",
            )
            authorize_url = str(
                _first_non_empty(
                    entry.get("authorize_url"),
                    override.get("authorize_url"),
                    getattr(settings, "twc_saml_authorize_url", None),
                )
                or _derive_auth_url(rest_url, port=login_port, path=login_path)
            )
            token_url = str(
                _first_non_empty(
                    entry.get("token_url"),
                    override.get("token_url"),
                    getattr(settings, "twc_saml_token_url", None),
                )
                or _derive_auth_url(rest_url, port=login_port, path=token_path)
            )
            scope = _normalize_scope(
                _first_non_empty(
                    entry.get("scope"),
                    override.get("scope"),
                    getattr(settings, "twc_auth_scope", None),
                )
            )
            client_id = _first_non_empty(
                entry.get("client_id"),
                entry.get("authentication.client.id"),
                entry.get("authentication.client.ids"),
                entry.get("authentication_client_id"),
                entry.get("authentication_client_ids"),
                override.get("client_id"),
                override.get("authentication.client.id"),
                override.get("authentication.client.ids"),
                override.get("authentication_client_id"),
                override.get("authentication_client_ids"),
                global_client_id,
            )
            client_secret = _first_non_empty(
                entry.get("client_secret"),
                entry.get("authentication.client.secret"),
                entry.get("authentication_client_secret"),
                override.get("client_secret"),
                override.get("authentication.client.secret"),
                override.get("authentication_client_secret"),
                global_client_secret,
            )
            return_url_parameter = str(
                _first_non_empty(
                    entry.get("return_url_parameter"),
                    override.get("return_url_parameter"),
                    override.get("TWC_SAML_RETURN_URL_PARAMETER"),
                    getattr(settings, "twc_saml_return_url_parameter", "redirect_uri"),
                )
            )
            verify_tls = _normalize_verify_tls(_first_non_empty(entry.get("verify_tls"), override.get("verify_tls")))
            ca_bundle_path = _normalize_ca_bundle_path(
                _first_non_empty(
                    entry.get("ca_bundle_path"),
                    entry.get("caBundlePath"),
                    override.get("ca_bundle_path"),
                    override.get("caBundlePath"),
                )
            )

            error = None
            if not client_id:
                error = "Missing TWC client_id for this server."
            elif not client_secret:
                error = "Missing TWC client_secret for this server."

            configs.append(
                TWCServerConfig(
                    id=server_id,
                    label=label,
                    rest_url=rest_url,
                    authorize_url=authorize_url.rstrip("/"),
                    token_url=token_url.rstrip("/"),
                    scope=scope,
                    client_id=str(client_id) if client_id else None,
                    client_secret=str(client_secret) if client_secret else None,
                    return_url_parameter=return_url_parameter or "redirect_uri",
                    verify_tls=verify_tls,
                    ca_bundle_path=ca_bundle_path,
                    ready=error is None,
                    error=error,
                )
            )
        except Exception as exc:  # noqa: BLE001
            configs.append(
                TWCServerConfig(
                    id=str(entry.get("id") or f"server-{index}"),
                    label=str(entry.get("label") or entry.get("name") or entry.get("id") or f"Server {index}"),
                    rest_url=str(entry.get("rest_url") or ""),
                    authorize_url="",
                    token_url="",
                    ready=False,
                    error=str(exc),
                )
            )
    return configs


def get_twc_server(server_id: str, *, require_ready: bool = True) -> TWCServerConfig:
    for server in load_twc_server_configs():
        if server.id == server_id:
            if require_ready and not server.ready:
                raise HTTPException(status_code=503, detail=server.error or "Selected TWC server is not ready.")
            return server
    raise HTTPException(status_code=404, detail="Selected TWC server was not found.")


def get_twc_callback_url(request: Request | None = None) -> str:
    settings = get_settings_service().settings
    callback_path = getattr(settings, "twc_auth_callback_path", TWC_CALLBACK_DEFAULT_PATH) or TWC_CALLBACK_DEFAULT_PATH
    if not callback_path.startswith("/"):
        callback_path = f"/{callback_path}"

    app_origin = getattr(settings, "app_origin", None)
    if app_origin:
        return f"{str(app_origin).rstrip('/')}{callback_path}"

    if request is None:
        raise HTTPException(
            status_code=500,
            detail="APP_ORIGIN must be configured when no request context is available for TWC callbacks.",
        )

    base_origin = str(request.base_url).rstrip("/")
    return f"{base_origin}{callback_path}"


def build_signin_redirect(server: TWCServerConfig, *, callback_url: str, next_url: str) -> tuple[str, str]:
    nonce = secrets.token_urlsafe(24)
    state = create_signed_state(server_id=server.id, next_url=next_url, nonce=nonce)
    params = {
        "scope": server.scope,
        server.return_url_parameter: callback_url,
        "client_id": server.client_id,
        "response_type": "code",
        "state": state,
    }
    return f"{server.authorize_url}?{urlencode(params)}", nonce


async def _request_form_encoded(
    *,
    url: str,
    data: dict[str, Any],
    verify_tls: bool | str,
    client_secret: str,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=20.0, verify=verify_tls, follow_redirects=True) as client:
            response = await client.post(
                url,
                data=data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Auth-Secret": client_secret,
                },
            )
    except httpx.ConnectTimeout as exc:
        raise HTTPException(status_code=504, detail="Timed out connecting to the TWC Authentication Server.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"TWC Authentication Server request failed: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text.strip() or "Token exchange failed."
        raise HTTPException(status_code=400, detail=f"TWC token exchange failed: {detail}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="TWC token endpoint did not return JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Unexpected TWC token response payload.")
    return payload


async def exchange_code_for_tokens(server: TWCServerConfig, *, callback_url: str, code: str) -> dict[str, Any]:
    return await _request_form_encoded(
        url=server.token_url,
        verify_tls=_resolve_httpx_verify(server),
        client_secret=server.client_secret or "",
        data={
            "scope": server.scope,
            "redirect_uri": callback_url,
            "client_id": server.client_id,
            "grant_type": "authorization_code",
            "code": code,
        },
    )


async def refresh_tokens(server: TWCServerConfig, *, callback_url: str, refresh_token: str) -> dict[str, Any]:
    return await _request_form_encoded(
        url=server.token_url,
        verify_tls=_resolve_httpx_verify(server),
        client_secret=server.client_secret or "",
        data={
            "scope": server.scope,
            "redirect_uri": callback_url,
            "client_id": server.client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )


def decode_token_claims(token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    try:
        claims = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_aud": False,
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
            algorithms=["HS256", "RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
        )
    except Exception:  # noqa: BLE001
        return {}
    return claims if isinstance(claims, dict) else {}


def _claims_expiry(claims: dict[str, Any]) -> datetime | None:
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    return datetime.fromtimestamp(exp, tz=timezone.utc)


def _token_expiry(token_data: dict[str, Any], id_claims: dict[str, Any], access_claims: dict[str, Any]) -> tuple[datetime | None, datetime | None, datetime | None]:
    now = datetime.now(timezone.utc)
    id_expiry = _claims_expiry(id_claims)
    access_expiry = _claims_expiry(access_claims)
    expires_in = token_data.get("expires_in")
    computed_expiry = None
    if isinstance(expires_in, (int, float)):
        computed_expiry = now + timedelta(seconds=int(expires_in))
    current_expiry = id_expiry or access_expiry or computed_expiry
    return id_expiry, access_expiry, current_expiry


async def validate_current_user(server: TWCServerConfig, token: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=20.0, verify=_resolve_httpx_verify(server), follow_redirects=True) as client:
            response = await client.get(
                f"{server.rest_url}/osmc/admin/currentUser",
                params={"permission": "true"},
                headers={"Authorization": f"Token {token}"},
            )
    except httpx.ConnectTimeout as exc:
        raise HTTPException(status_code=504, detail="Timed out connecting to the TWC REST server.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"TWC REST validation request failed: {exc}") from exc

    if response.status_code in {401, 403}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="TWC currentUser validation failed. Check the client ID, secret, callback whitelist, or user permissions.",
        )
    if response.status_code >= 400:
        detail = response.text.strip() or "Unable to validate the TWC session."
        raise HTTPException(status_code=400, detail=f"TWC currentUser request failed: {detail}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="TWC currentUser response was not valid JSON.") from exc

    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        payload = payload[0]
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(status_code=400, detail="TWC currentUser returned an empty or invalid user payload.")
    return payload


def build_identity(*, server_id: str, current_user: dict[str, Any], claims: dict[str, Any]) -> TWCIdentity:
    user_id = _first_non_empty(
        claims.get("sub"),
        current_user.get("id"),
        current_user.get("userId"),
        current_user.get("subject"),
        current_user.get("name"),
    )
    username = _first_non_empty(
        current_user.get("username"),
        current_user.get("userName"),
        current_user.get("login"),
        current_user.get("name"),
        current_user.get("principal"),
        claims.get("preferred_username"),
        claims.get("username"),
        claims.get("upn"),
        claims.get("sub"),
    )
    email = _first_non_empty(current_user.get("email"), claims.get("email"), claims.get("upn"))
    display_name = _first_non_empty(current_user.get("displayName"), current_user.get("fullName"), username)

    if not user_id or not username:
        raise HTTPException(status_code=400, detail="TWC currentUser payload is missing a stable user identifier.")

    return TWCIdentity(
        external_user_id=f"{server_id}:{user_id}",
        username=str(username),
        email=str(email) if email else None,
        display_name=str(display_name) if display_name else None,
    )


async def get_or_create_twc_user(session: DbSession, identity: TWCIdentity, *, server_id: str) -> User:
    stmt = select(SSOUserProfile).where(
        SSOUserProfile.sso_provider == TWC_PROVIDER,
        SSOUserProfile.sso_user_id == identity.external_user_id,
    )
    profile = (await session.exec(stmt)).first()
    now = datetime.now(timezone.utc)

    if profile:
        user = await session.get(User, profile.user_id)
        if not user:
            raise HTTPException(status_code=400, detail="Corrupt TWC user mapping: local user not found.")
        profile.email = identity.email
        profile.sso_last_login_at = now
        profile.updated_at = now
        await session.flush()
        return user

    username_base = identity.username.strip().lower().replace(" ", "-")
    username_base = "".join(char for char in username_base if char.isalnum() or char in {"-", "_", "."})[:40] or "twc-user"

    username_candidates = [username_base]
    if server_id not in username_base:
        username_candidates.append(f"{username_base}-{server_id}"[:48])

    username = None
    for candidate in username_candidates:
        existing = (await session.exec(select(User).where(User.username == candidate))).first()
        if existing is None:
            username = candidate
            break

    if username is None:
        suffix = 1
        username = username_candidates[-1]
        base = username[:40]
        while (await session.exec(select(User).where(User.username == username))).first() is not None:
            suffix += 1
            username = f"{base[:40]}-{suffix}"[:50]

    user = User(
        username=username,
        password=get_auth_service().get_password_hash(secrets.token_urlsafe(48)),
        is_active=True,
        is_superuser=False,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)

    profile = SSOUserProfile(
        user_id=user.id,
        sso_provider=TWC_PROVIDER,
        sso_user_id=identity.external_user_id,
        email=identity.email,
        sso_last_login_at=now,
    )
    session.add(profile)
    await session.flush()
    return user


def create_langflow_login_response(*, response: Response, tokens: dict[str, str], user: User) -> None:
    auth_settings = _cookie_settings()
    response.set_cookie(
        "refresh_token_lf",
        tokens["refresh_token"],
        httponly=auth_settings.REFRESH_HTTPONLY,
        samesite=auth_settings.REFRESH_SAME_SITE,
        secure=auth_settings.REFRESH_SECURE,
        expires=auth_settings.REFRESH_TOKEN_EXPIRE_SECONDS,
        domain=auth_settings.COOKIE_DOMAIN,
    )
    response.set_cookie(
        "access_token_lf",
        tokens["access_token"],
        httponly=auth_settings.ACCESS_HTTPONLY,
        samesite=auth_settings.ACCESS_SAME_SITE,
        secure=auth_settings.ACCESS_SECURE,
        expires=auth_settings.ACCESS_TOKEN_EXPIRE_SECONDS,
        domain=auth_settings.COOKIE_DOMAIN,
    )
    response.set_cookie(
        "apikey_tkn_lflw",
        str(user.store_api_key or ""),
        httponly=auth_settings.ACCESS_HTTPONLY,
        samesite=auth_settings.ACCESS_SAME_SITE,
        secure=auth_settings.ACCESS_SECURE,
        expires=None,
        domain=auth_settings.COOKIE_DOMAIN,
    )


async def initialize_langflow_user(session: DbSession, user: User) -> None:
    await get_variable_service().initialize_user_variables(user.id, session)
    _ = await get_or_create_default_folder(session, user.id)
    if get_settings_service().settings.agentic_experience:
        from langflow.api.utils.mcp.agentic_mcp import initialize_agentic_user_variables

        await initialize_agentic_user_variables(user.id, session)


def _serialize_session(session_data: TWCSessionData) -> str:
    return session_data.model_dump_json()


def _deserialize_session(payload: str) -> TWCSessionData:
    return TWCSessionData.model_validate_json(payload)


async def save_twc_session(session_data: TWCSessionData) -> None:
    encrypted = get_auth_service().encrypt_api_key(_serialize_session(session_data))
    await asyncio.to_thread(_session_file(session_data.session_id).write_text, encrypted, "utf-8")


async def load_twc_session(session_id: str | None) -> TWCSessionData | None:
    if not session_id:
        return None
    session_path = _session_file(session_id)
    if not session_path.exists():
        return None
    encrypted = await asyncio.to_thread(session_path.read_text, "utf-8")
    try:
        decrypted = get_auth_service().decrypt_api_key(encrypted)
        return _deserialize_session(decrypted)
    except Exception:  # noqa: BLE001
        return None


async def delete_twc_session(session_id: str | None) -> None:
    if not session_id:
        return
    session_path = _session_file(session_id)
    if session_path.exists():
        await asyncio.to_thread(session_path.unlink)


def _token_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    return expires_at <= datetime.now(timezone.utc) + timedelta(seconds=TWC_SESSION_LEEWAY_SECONDS)


async def build_twc_session(
    *,
    server: TWCServerConfig,
    token_data: dict[str, Any],
    current_user: dict[str, Any],
    identity: TWCIdentity,
    session_id: str | None = None,
) -> TWCSessionData:
    id_claims = decode_token_claims(token_data.get("id_token"))
    access_claims = decode_token_claims(token_data.get("access_token"))
    id_expiry, access_expiry, current_expiry = _token_expiry(token_data, id_claims, access_claims)
    return TWCSessionData(
        session_id=session_id or secrets.token_urlsafe(32),
        server_id=server.id,
        server_label=server.label,
        rest_url=server.rest_url,
        authorize_url=server.authorize_url,
        token_url=server.token_url,
        scope=server.scope,
        client_id=server.client_id or "",
        return_url_parameter=server.return_url_parameter,
        verify_tls=server.verify_tls,
        id_token=token_data.get("id_token"),
        access_token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        token_type=token_data.get("token_type"),
        current_user=current_user,
        external_user_id=identity.external_user_id,
        username=identity.username,
        email=identity.email,
        id_token_expires_at=id_expiry,
        access_token_expires_at=access_expiry,
        expires_at=current_expiry,
        updated_at=datetime.now(timezone.utc),
    )


async def refresh_twc_session_if_needed(session_data: TWCSessionData, *, request: Request | None = None) -> TWCSessionData:
    if not _token_expired(session_data.expires_at):
        return session_data
    if not session_data.refresh_token:
        raise HTTPException(status_code=401, detail="The TWC session has expired and no refresh token is available.")

    server = get_twc_server(session_data.server_id, require_ready=True)
    callback_url = get_twc_callback_url(request)
    refreshed = await refresh_tokens(server, callback_url=callback_url, refresh_token=session_data.refresh_token)
    merged_token_data = {
        "id_token": refreshed.get("id_token") or session_data.id_token,
        "access_token": refreshed.get("access_token") or session_data.access_token,
        "refresh_token": refreshed.get("refresh_token") or session_data.refresh_token,
        "token_type": refreshed.get("token_type") or session_data.token_type,
        "expires_in": refreshed.get("expires_in"),
    }
    identity = TWCIdentity(
        external_user_id=session_data.external_user_id,
        username=session_data.username,
        email=session_data.email,
        display_name=session_data.username,
    )
    updated = await build_twc_session(
        server=server,
        token_data=merged_token_data,
        current_user=session_data.current_user,
        identity=identity,
        session_id=session_data.session_id,
    )
    await save_twc_session(updated)
    return updated


async def get_twc_session_from_request(request: Request, *, refresh_if_needed: bool = False) -> TWCSessionData | None:
    session_data = await load_twc_session(request.cookies.get(TWC_SESSION_ID_COOKIE))
    if not session_data:
        return None
    if refresh_if_needed:
        session_data = await refresh_twc_session_if_needed(session_data, request=request)
    return session_data


async def validate_and_refresh_twc_session(session_data: TWCSessionData, *, request: Request | None = None) -> tuple[TWCSessionData, dict[str, Any]]:
    active_session = await refresh_twc_session_if_needed(session_data, request=request)
    server = get_twc_server(active_session.server_id, require_ready=True)
    token = active_session.current_token()
    if not token:
        raise HTTPException(status_code=401, detail="The TWC session is missing an access token.")
    try:
        current_user = await validate_current_user(server, token)
    except HTTPException as exc:
        if exc.status_code in {401, 403} and active_session.refresh_token:
            active_session = await refresh_twc_session_if_needed(
                active_session.model_copy(update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}),
                request=request,
            )
            token = active_session.current_token()
            if not token:
                raise
            current_user = await validate_current_user(server, token)
        else:
            raise
    if current_user != active_session.current_user:
        active_session.current_user = current_user
        active_session.updated_at = datetime.now(timezone.utc)
        await save_twc_session(active_session)
    return active_session, current_user


def build_login_error_redirect(*, request: Request, message: str) -> str:
    callback_url = get_twc_callback_url(request)
    parsed = urlparse(callback_url)
    _, _, app_prefix = _get_app_prefix_from_callback_url(callback_url)
    normalized_login_path = f"{app_prefix}/login" if app_prefix else "/login"
    query = urlencode({"twc_error": message})
    return f"{parsed.scheme}://{parsed.netloc}{normalized_login_path}?{query}"


def extract_proxy_token_bundle(request: Request) -> dict[str, str] | None:
    id_token = (
        request.headers.get("X-Forwarded-Id-Token")
        or request.headers.get("X-Id-Token")
        or request.cookies.get("id_token")
        or request.cookies.get("twc_id_token")
    )
    access_token = (
        request.headers.get("X-Forwarded-Access-Token")
        or request.headers.get("X-Access-Token")
        or request.cookies.get("access_token")
        or request.cookies.get("twc_access_token")
    )
    refresh_token = (
        request.headers.get("X-Forwarded-Refresh-Token")
        or request.headers.get("X-Refresh-Token")
        or request.cookies.get("refresh_token")
        or request.cookies.get("twc_refresh_token")
    )
    auth_header = request.headers.get("Authorization")
    if auth_header and not access_token and not id_token:
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() in {"token", "bearer"} and token:
            access_token = token

    token_bundle = {
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
    if token_bundle["id_token"] or token_bundle["access_token"]:
        return token_bundle
    return None

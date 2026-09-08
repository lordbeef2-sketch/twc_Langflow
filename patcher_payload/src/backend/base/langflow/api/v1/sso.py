"""TWC OpenID Connect sign-in and admin settings.

This is intentionally a single OIDC lane.  Provider configuration is stored in
Langflow's native ``SSOConfig`` table and the secret is encrypted by Langflow's
native secret helper; operators do not edit environment files.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Annotated, Any
from urllib.parse import urlencode, urljoin, urlparse

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, SecretStr
from sqlmodel import select

from langflow.api.utils.core import DbSession
from langflow.services.auth.external import ExternalIdentity
from langflow.services.auth.utils import get_current_active_superuser
from langflow.services.database.models.auth.sso import OIDCProviderSettings, SSOConfig, SSOConfigCreate, SSOConfigUpdate
from langflow.services.database.models.user.model import User
from langflow.services.deps import get_auth_service, get_settings_service

router = APIRouter(tags=["TWC OpenID"], prefix="/sso")
admin_router = APIRouter(tags=["Admin Settings"], prefix="/admin/settings")

_STATE_COOKIE = "langflow_twc_oidc_state"
_NONCE_COOKIE = "langflow_twc_oidc_nonce"
_NEXT_COOKIE = "langflow_twc_oidc_next"
_CONFIG_SLUG = "twc-openid"
_DEFAULT_NEXT = "/"


class SSOSettingsResponse(BaseModel):
    sso_enabled: bool


class SSOSettingsUpdateRequest(BaseModel):
    sso_enabled: bool


class TWCSSOConfigRequest(BaseModel):
    # Kept compatible with the existing Langflow settings form.  ``oauth`` is
    # accepted as a legacy UI value but is always persisted as OIDC.
    provider: str = "oidc"
    provider_name: str = "twc-openid"
    enabled: bool = True
    enforce_sso: bool = False
    client_id: str = ""
    client_secret: SecretStr | None = Field(default=None, repr=False)
    discovery_url: str | None = None
    redirect_uri: str | None = None
    scopes: str = "openid email profile"
    token_endpoint: str | None = None
    authorization_endpoint: str | None = None
    jwks_uri: str | None = None
    issuer: str | None = None
    email_claim: str = "email"
    username_claim: str = "preferred_username"
    user_id_claim: str = "sub"


def _safe_next(value: str | None) -> str:
    if not value:
        return _DEFAULT_NEXT
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//"):
        return _DEFAULT_NEXT
    return value


def _config_response(config: SSOConfig) -> dict[str, Any]:
    settings = config.provider_settings
    return {
        "provider": "oidc",
        "provider_name": "twc-openid",
        "enabled": config.enabled,
        "enforce_sso": False,
        "client_id": settings.client_id,
        "discovery_url": settings.discovery_url,
        "redirect_uri": settings.redirect_uri,
        "scopes": settings.scopes,
        "token_endpoint": settings.token_endpoint,
        "authorization_endpoint": settings.authorization_endpoint,
        "jwks_uri": settings.jwks_uri,
        "issuer": settings.issuer,
        "email_claim": config.email_claim,
        "username_claim": config.username_claim,
        "user_id_claim": config.user_id_claim,
        "has_client_secret": config.client_secret_encrypted is not None,
    }


async def _get_config(db: DbSession, *, include_disabled: bool = True) -> SSOConfig | None:
    stmt = select(SSOConfig).where(SSOConfig.slug == _CONFIG_SLUG)
    if not include_disabled:
        stmt = stmt.where(SSOConfig.enabled.is_(True))
    return (await db.exec(stmt)).first()


async def _enabled_config(db: DbSession) -> SSOConfig:
    config = await _get_config(db, include_disabled=False)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TWC OpenID is not configured")
    return config


async def is_sso_enabled(db: DbSession) -> bool:
    """Return the persisted provider state for Langflow's login endpoint."""
    return await _get_config(db, include_disabled=False) is not None


async def _oidc_metadata(config: SSOConfig) -> dict[str, Any]:
    settings = config.provider_settings
    if settings.discovery_url:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.get(settings.discovery_url)
                response.raise_for_status()
                metadata = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=502, detail="Unable to reach the TWC OpenID discovery endpoint") from exc
    else:
        metadata = {}
    return {
        **metadata,
        "authorization_endpoint": settings.authorization_endpoint or metadata.get("authorization_endpoint"),
        "token_endpoint": settings.token_endpoint or metadata.get("token_endpoint"),
        "jwks_uri": settings.jwks_uri or metadata.get("jwks_uri"),
        "issuer": settings.issuer or metadata.get("issuer"),
        "userinfo_endpoint": metadata.get("userinfo_endpoint"),
    }


def _claims_from_id_token(token: str, metadata: dict[str, Any], client_id: str, nonce: str) -> dict[str, Any]:
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    # PyJWKClient performs the standard JWKS retrieval and selects the matching
    # key.  It is used only after the token endpoint has returned an ID token.
    jwks_uri = metadata.get("jwks_uri")
    if not jwks_uri:
        raise HTTPException(status_code=502, detail="TWC OpenID metadata has no JWKS endpoint")
    try:
        key = jwt.PyJWKClient(jwks_uri).get_signing_key_from_jwt(token).key
    except (jwt.PyJWTError, OSError) as exc:
        raise HTTPException(status_code=502, detail="Unable to validate the TWC OpenID signing key") from exc
    options = {"verify_aud": bool(client_id)}
    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=[header.get("alg", "RS256")],
            audience=client_id or None,
            issuer=metadata.get("issuer") or None,
            options=options,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid TWC OpenID ID token") from exc
    if claims.get("nonce") != nonce:
        raise HTTPException(status_code=400, detail="Invalid TWC OpenID nonce")
    if not claims.get("sub"):
        raise HTTPException(status_code=400, detail="TWC OpenID response has no subject")
    return claims


async def _materialize_user(config: SSOConfig, claims: dict[str, Any], db: DbSession) -> User:
    settings = get_settings_service().auth_settings
    email = claims.get(config.email_claim)
    username = claims.get(config.username_claim) or email or claims.get("name") or claims.get("sub")
    name = claims.get("name")
    identity = ExternalIdentity(
        provider=config.slug,
        subject=str(claims[config.user_id_claim] if config.user_id_claim in claims else claims["sub"]),
        username=str(username),
        email=str(email) if email else None,
        name=str(name) if name else None,
        claims=claims,
    )
    return await get_auth_service()._materialize_external_user(identity, db)  # noqa: SLF001


def _set_session_cookies(response: Response, tokens: dict[str, str], user: User) -> None:
    auth = get_settings_service().auth_settings
    response.set_cookie("refresh_token_lf", tokens["refresh_token"], httponly=auth.REFRESH_HTTPONLY,
                        samesite=auth.REFRESH_SAME_SITE, secure=auth.REFRESH_SECURE,
                        expires=auth.REFRESH_TOKEN_EXPIRE_SECONDS, domain=auth.COOKIE_DOMAIN)
    response.set_cookie("access_token_lf", tokens["access_token"], httponly=auth.ACCESS_HTTPONLY,
                        samesite=auth.ACCESS_SAME_SITE, secure=auth.ACCESS_SECURE,
                        expires=auth.ACCESS_TOKEN_EXPIRE_SECONDS, domain=auth.COOKIE_DOMAIN)
    response.set_cookie("apikey_tkn_lflw", str(user.store_api_key or ""), httponly=auth.ACCESS_HTTPONLY,
                        samesite=auth.ACCESS_SAME_SITE, secure=auth.ACCESS_SECURE,
                        expires=None, domain=auth.COOKIE_DOMAIN)


@router.get("/providers")
async def list_sso_providers(db: DbSession) -> list[dict[str, Any]]:
    config = await _get_config(db, include_disabled=False)
    return [] if config is None else [_config_response(config)]


@router.get("/config")
async def get_sso_config(
    _admin: Annotated[User, Depends(get_current_active_superuser)], db: DbSession
) -> list[dict[str, Any]]:
    config = await _get_config(db)
    return [] if config is None else [_config_response(config)]


@router.put("/config")
async def put_sso_config(
    payload: TWCSSOConfigRequest,
    admin: Annotated[User, Depends(get_current_active_superuser)],
    db: DbSession,
) -> dict[str, Any]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="OpenID client ID is required")
    provider_settings = OIDCProviderSettings(
        discovery_url=payload.discovery_url or None,
        redirect_uri=payload.redirect_uri or None,
        scopes=payload.scopes or "openid email profile",
        token_endpoint=payload.token_endpoint or None,
        authorization_endpoint=payload.authorization_endpoint or None,
        jwks_uri=payload.jwks_uri or None,
        issuer=payload.issuer or None,
        client_id=payload.client_id.strip(),
    )
    config = await _get_config(db)
    if config is None:
        create = SSOConfigCreate(
            display_name="TWC OpenID",
            enabled=payload.enabled,
            client_secret=payload.client_secret,
            provider_settings=provider_settings,
            email_claim=payload.email_claim,
            username_claim=payload.username_claim,
            user_id_claim=payload.user_id_claim,
        )
        config = create.to_model(get_settings_service(), actor_id=admin.id)
        config.slug = _CONFIG_SLUG
        db.add(config)
    else:
        update_values: dict[str, Any] = {
            "enabled": payload.enabled,
            "provider_settings": provider_settings,
            "email_claim": payload.email_claim,
            "username_claim": payload.username_claim,
            "user_id_claim": payload.user_id_claim,
        }
        if payload.client_secret is not None:
            update_values["client_secret"] = payload.client_secret
        update = SSOConfigUpdate(**update_values)
        config = update.apply_to(config, get_settings_service(), actor_id=admin.id)
        config.display_name = "TWC OpenID"
        db.add(config)
    await db.commit()
    await db.refresh(config)
    # The GUI controls the auth mode.  Langflow's own auto-login endpoint is
    # guarded below by the persisted provider, so no environment edit/restart
    # is required when SSO is enabled.
    get_settings_service().auth_settings.SSO_ENABLED = payload.enabled
    if payload.enabled:
        get_settings_service().auth_settings.AUTO_LOGIN = False
    return _config_response(config)


@admin_router.get("/sso", response_model=SSOSettingsResponse)
async def get_sso_settings(_admin: Annotated[User, Depends(get_current_active_superuser)], db: DbSession):
    config = await _get_config(db, include_disabled=False)
    return SSOSettingsResponse(sso_enabled=config is not None)


@admin_router.put("/sso", response_model=SSOSettingsResponse)
async def put_sso_settings(
    payload: SSOSettingsUpdateRequest,
    _admin: Annotated[User, Depends(get_current_active_superuser)],
    db: DbSession,
):
    config = await _get_config(db)
    if config is not None:
        config.enabled = payload.sso_enabled
        db.add(config)
        await db.commit()
        await db.refresh(config)
    get_settings_service().auth_settings.SSO_ENABLED = payload.sso_enabled
    if payload.sso_enabled:
        get_settings_service().auth_settings.AUTO_LOGIN = False
    return SSOSettingsResponse(sso_enabled=payload.sso_enabled)


@router.get("/start/{provider_name}", include_in_schema=False)
async def start_sso(
    provider_name: str,
    request: Request,
    response: Response,
    db: DbSession,
    next: str | None = Query(default=None),
):
    config = await _enabled_config(db)
    metadata = await _oidc_metadata(config)
    endpoint = metadata.get("authorization_endpoint")
    client_id = config.provider_settings.client_id
    redirect_uri = config.provider_settings.redirect_uri
    if not endpoint or not client_id or not redirect_uri:
        raise HTTPException(status_code=400, detail="TWC OpenID configuration is incomplete")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    scope = config.provider_settings.scopes or "openid email profile"
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "nonce": nonce,
    }
    redirect = RedirectResponse(url=f"{endpoint}?{urlencode(params)}", status_code=302)
    auth = get_settings_service().auth_settings
    for name, value in ((_STATE_COOKIE, state), (_NONCE_COOKIE, nonce), (_NEXT_COOKIE, _safe_next(next))):
        redirect.set_cookie(name, value, httponly=True, samesite="lax", secure=auth.ACCESS_SECURE,
                            max_age=600, domain=auth.COOKIE_DOMAIN)
    return redirect


@router.get("/callback", include_in_schema=False)
async def sso_callback(
    request: Request,
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        raise HTTPException(status_code=400, detail=f"TWC OpenID authorization failed: {error}")
    config = await _enabled_config(db)
    if not code or not state or state != request.cookies.get(_STATE_COOKIE):
        raise HTTPException(status_code=400, detail="Invalid TWC OpenID state")
    nonce = request.cookies.get(_NONCE_COOKIE)
    if not nonce:
        raise HTTPException(status_code=400, detail="Missing TWC OpenID nonce")
    metadata = await _oidc_metadata(config)
    token_endpoint = metadata.get("token_endpoint")
    client_id = config.provider_settings.client_id
    redirect_uri = config.provider_settings.redirect_uri
    if not token_endpoint or not client_id or not redirect_uri or config.client_secret_encrypted is None:
        raise HTTPException(status_code=400, detail="TWC OpenID token settings are incomplete")
    from langflow.services.database.models.auth.sso_secret import decrypt_sso_client_secret

    client_secret = decrypt_sso_client_secret(config.client_secret_encrypted, get_settings_service())
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        token_response = await client.post(token_endpoint, data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        })
    if token_response.is_error:
        raise HTTPException(status_code=502, detail="TWC OpenID token exchange failed")
    token_data = token_response.json()
    id_token = token_data.get("id_token")
    if not id_token:
        raise HTTPException(status_code=502, detail="TWC OpenID did not return an ID token")
    claims = _claims_from_id_token(id_token, metadata, client_id, nonce)
    user = await _materialize_user(config, claims, db)
    tokens = await get_auth_service().create_user_tokens(user.id, db, update_last_login=True)
    redirect = RedirectResponse(url=_safe_next(request.cookies.get(_NEXT_COOKIE)), status_code=303)
    _set_session_cookies(redirect, tokens, user)
    for name in (_STATE_COOKIE, _NONCE_COOKIE, _NEXT_COOKIE):
        redirect.delete_cookie(name, domain=get_settings_service().auth_settings.COOKIE_DOMAIN)
    return redirect

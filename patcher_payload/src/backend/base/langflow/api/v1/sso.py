from __future__ import annotations

from html import escape as xml_escape
import secrets
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlmodel import select

from langflow.api.utils import DbSession
from langflow.services.auth.utils import get_current_active_superuser
from langflow.initial_setup.setup import get_or_create_default_folder
from langflow.services.database.models.auth.sso import SSOConfig, SSOUserProfile
from langflow.services.database.models.user.model import User
from langflow.services.deps import get_auth_service, get_settings_service, get_variable_service

router = APIRouter(tags=["SSO"], prefix="/sso")

SSO_STATE_COOKIE = "sso_state_lf"
SSO_NONCE_COOKIE = "sso_nonce_lf"
SSO_PROVIDER_COOKIE = "sso_provider_lf"
SSO_NEXT_COOKIE = "sso_next_lf"


class SSOConfigRequest(BaseModel):
    provider: Literal["oauth", "oidc", "saml"] = "oauth"
    provider_name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    enforce_sso: bool = False
    client_id: str | None = None
    client_secret: str | None = None
    discovery_url: str | None = None
    redirect_uri: str | None = None
    scopes: str | None = "openid email profile"
    token_endpoint: str | None = None
    authorization_endpoint: str | None = None
    jwks_uri: str | None = None
    issuer: str | None = None

    # SAML 2.0 fields (persisted in existing SSOConfig columns).
    saml_entity_id: str | None = None
    saml_acs_url: str | None = None
    saml_idp_metadata_url: str | None = None
    saml_idp_entity_id: str | None = None
    saml_sso_url: str | None = None
    saml_slo_url: str | None = None
    saml_x509_cert: str | None = None
    saml_nameid_format: str | None = None

    email_claim: str = "email"
    username_claim: str = "preferred_username"
    user_id_claim: str = "sub"


class SSOConfigResponse(BaseModel):
    provider: str
    provider_name: str
    enabled: bool
    enforce_sso: bool
    client_id: str | None
    discovery_url: str | None
    redirect_uri: str | None
    scopes: str | None
    token_endpoint: str | None
    authorization_endpoint: str | None
    jwks_uri: str | None
    issuer: str | None
    email_claim: str
    username_claim: str
    user_id_claim: str
    has_client_secret: bool

    # Derived SAML fields.
    saml_entity_id: str | None = None
    saml_acs_url: str | None = None
    saml_idp_metadata_url: str | None = None
    saml_idp_entity_id: str | None = None
    saml_sso_url: str | None = None
    saml_slo_url: str | None = None
    saml_x509_cert: str | None = None
    saml_nameid_format: str | None = None


class SAMLMetadataResponse(BaseModel):
    provider_name: str
    metadata_xml: str


def _ensure_sso_enabled() -> None:
    if not get_settings_service().auth_settings.SSO_ENABLED:
        raise HTTPException(status_code=403, detail="SSO is disabled")


def _config_to_response(config: SSOConfig) -> SSOConfigResponse:
    is_saml = config.provider.lower() == "saml"
    return SSOConfigResponse(
        provider=config.provider,
        provider_name=config.provider_name,
        enabled=config.enabled,
        enforce_sso=config.enforce_sso,
        client_id=config.client_id,
        discovery_url=config.discovery_url,
        redirect_uri=config.redirect_uri,
        scopes=config.scopes,
                token_endpoint=config.token_endpoint,
                authorization_endpoint=config.authorization_endpoint,
                jwks_uri=config.jwks_uri,
                issuer=config.issuer,
        email_claim=config.email_claim,
        username_claim=config.username_claim,
        user_id_claim=config.user_id_claim,
        has_client_secret=bool(config.client_secret_encrypted),
                saml_entity_id=config.client_id if is_saml else None,
                saml_acs_url=config.redirect_uri if is_saml else None,
                saml_idp_metadata_url=config.discovery_url if is_saml else None,
                saml_idp_entity_id=config.issuer if is_saml else None,
                saml_sso_url=config.authorization_endpoint if is_saml else None,
                saml_slo_url=config.token_endpoint if is_saml else None,
                saml_x509_cert=config.jwks_uri if is_saml else None,
                saml_nameid_format=config.scopes if is_saml else None,
    )


def _normalize_provider(provider: str) -> str:
        p = provider.strip().lower()
        if p not in {"oauth", "oidc", "saml"}:
                raise HTTPException(status_code=400, detail="Provider must be one of: oauth, oidc, saml")
        return p


def _build_saml_metadata(config: SSOConfig) -> str:
        entity_id = (config.client_id or "").strip()
        acs_url = (config.redirect_uri or "").strip()
        idp_entity_id = (config.issuer or "").strip()
        idp_sso_url = (config.authorization_endpoint or "").strip()
        idp_slo_url = (config.token_endpoint or "").strip()
        cert = (config.jwks_uri or "").strip()
        nameid_format = (config.scopes or "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress").strip()

        if not entity_id or not acs_url:
                raise HTTPException(status_code=400, detail="SAML metadata requires saml_entity_id and saml_acs_url")

        cert_clean = cert.replace("-----BEGIN CERTIFICATE-----", "").replace("-----END CERTIFICATE-----", "")
        cert_clean = "".join(cert_clean.split())

        cert_block = (
                f"""
            <KeyDescriptor use=\"signing\"> 
                <KeyInfo xmlns=\"http://www.w3.org/2000/09/xmldsig#\"> 
                    <X509Data><X509Certificate>{xml_escape(cert_clean)}</X509Certificate></X509Data>
                </KeyInfo>
            </KeyDescriptor>"""
                if cert_clean
                else ""
        )

        sso_service = ""
        if idp_sso_url:
                sso_service = (
                        '<SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" '
                        f'Location="{xml_escape(idp_sso_url)}" />'
                )

        slo_service = ""
        if idp_slo_url:
                slo_service = (
                        '<SingleLogoutService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" '
                        f'Location="{xml_escape(idp_slo_url)}" />'
                )

        idp_descriptor = ""
        if idp_entity_id or idp_sso_url or idp_slo_url:
                idp_descriptor = f"""
    <IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
        {sso_service}
        {slo_service}
    </IDPSSODescriptor>"""

        return f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<EntityDescriptor xmlns=\"urn:oasis:names:tc:SAML:2.0:metadata\" entityID=\"{xml_escape(entity_id)}\">
    <SPSSODescriptor AuthnRequestsSigned=\"false\" WantAssertionsSigned=\"false\" protocolSupportEnumeration=\"urn:oasis:names:tc:SAML:2.0:protocol\">
        <NameIDFormat>{xml_escape(nameid_format)}</NameIDFormat>
        <AssertionConsumerService Binding=\"urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST\" Location=\"{xml_escape(acs_url)}\" index=\"0\" isDefault=\"true\" />
        {cert_block}
    </SPSSODescriptor>
    {idp_descriptor}
</EntityDescriptor>
"""


async def _get_config(session: DbSession, provider_name: str, *, allowed_providers: set[str] | None = None) -> SSOConfig:
    stmt = select(SSOConfig).where(SSOConfig.provider_name == provider_name)
    config = (await session.exec(stmt)).first()
    if not config or not config.enabled:
        raise HTTPException(status_code=404, detail="SSO provider not found or disabled")
        provider = config.provider.lower()
        if allowed_providers and provider not in allowed_providers:
                allowed = ", ".join(sorted(allowed_providers))
                raise HTTPException(status_code=400, detail=f"Provider '{provider}' is not supported for this operation. Allowed: {allowed}")
    return config


def _safe_next(next_url: str | None) -> str:
    if not next_url or not next_url.startswith("/"):
        return "/"
    return next_url


async def _fetch_discovery(discovery_url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(discovery_url)
        resp.raise_for_status()
        return resp.json()


def _set_cookie(response: Response, key: str, value: str, *, max_age: int | None = None) -> None:
    auth_settings = get_settings_service().auth_settings
    response.set_cookie(
        key,
        value,
        httponly=True,
        samesite=auth_settings.ACCESS_SAME_SITE,
        secure=auth_settings.ACCESS_SECURE,
        max_age=max_age,
        domain=auth_settings.COOKIE_DOMAIN,
    )


def _delete_cookie(response: Response, key: str) -> None:
    auth_settings = get_settings_service().auth_settings
    response.delete_cookie(
        key,
        httponly=True,
        samesite=auth_settings.ACCESS_SAME_SITE,
        secure=auth_settings.ACCESS_SECURE,
        domain=auth_settings.COOKIE_DOMAIN,
    )


def _set_auth_cookies(response: Response, tokens: dict[str, str], user: User) -> None:
    auth_settings = get_settings_service().auth_settings
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


async def _get_or_create_sso_user(
    session: DbSession,
    config: SSOConfig,
    claims: dict[str, Any],
) -> User:
    provider_user_id = str(claims.get(config.user_id_claim) or "")
    if not provider_user_id:
        raise HTTPException(status_code=400, detail=f"Missing claim: {config.user_id_claim}")

    stmt = select(SSOUserProfile).where(
        SSOUserProfile.sso_provider == config.provider_name,
        SSOUserProfile.sso_user_id == provider_user_id,
    )
    profile = (await session.exec(stmt)).first()
    now = datetime.now(timezone.utc)

    if profile:
        user = await session.get(User, profile.user_id)
        if not user:
            raise HTTPException(status_code=400, detail="Corrupt SSO profile: user not found")
        profile.sso_last_login_at = now
        profile.updated_at = now
        await session.flush()
        return user

    username_base = str(claims.get(config.username_claim) or claims.get(config.email_claim) or "sso-user").strip()
    username_base = username_base.lower().replace(" ", "-")
    username_base = "".join(c for c in username_base if c.isalnum() or c in {"-", "_", "."})[:40] or "sso-user"

    username = username_base
    suffix = 1
    while (await session.exec(select(User).where(User.username == username))).first() is not None:
        suffix += 1
        username = f"{username_base}-{suffix}"

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
        sso_provider=config.provider_name,
        sso_user_id=provider_user_id,
        email=str(claims.get(config.email_claim) or "") or None,
        sso_last_login_at=now,
    )
    session.add(profile)
    await session.flush()
    return user


@router.get("/providers", response_model=list[SSOConfigResponse])
async def list_sso_providers(session: DbSession):
    _ensure_sso_enabled()
    stmt = select(SSOConfig).where(SSOConfig.enabled == True)  # noqa: E712
    configs = (await session.exec(stmt)).all()
    # Only expose providers supported by /start and /callback.
    return [_config_to_response(cfg) for cfg in configs if cfg.provider.lower() in {"oauth", "oidc"}]


@router.get("/config", response_model=list[SSOConfigResponse])
async def list_sso_configs_admin(
    current_user: Annotated[User, Depends(get_current_active_superuser)],
    session: DbSession,
):
    _ = current_user
    _ensure_sso_enabled()
    configs = (await session.exec(select(SSOConfig))).all()
    return [_config_to_response(cfg) for cfg in configs]


@router.put("/config", response_model=SSOConfigResponse)
async def upsert_sso_config(
    payload: SSOConfigRequest,
    current_user: Annotated[User, Depends(get_current_active_superuser)],
    session: DbSession,
):
    _ensure_sso_enabled()
    provider = _normalize_provider(payload.provider)

    if provider in {"oauth", "oidc"}:
        if not (payload.client_id and payload.redirect_uri):
            raise HTTPException(status_code=400, detail="OAuth setup requires client_id and redirect_uri")
        has_discovery = bool(payload.discovery_url)
        has_manual_endpoints = bool(payload.authorization_endpoint and payload.token_endpoint and payload.jwks_uri)
        if not has_discovery and not has_manual_endpoints:
            raise HTTPException(
                status_code=400,
                detail="Provide discovery_url or all manual endpoints (authorization_endpoint, token_endpoint, jwks_uri)",
            )
    else:
        if not (payload.saml_entity_id and payload.saml_acs_url):
            raise HTTPException(status_code=400, detail="SAML setup requires saml_entity_id and saml_acs_url")

    stmt = select(SSOConfig).where(SSOConfig.provider_name == payload.provider_name)
    config = (await session.exec(stmt)).first()
    encrypted_secret = get_auth_service().encrypt_api_key(payload.client_secret) if payload.client_secret else None

    if not config:
        if provider in {"oauth", "oidc"} and not encrypted_secret:
            raise HTTPException(status_code=400, detail="client_secret is required for new OAuth providers")
        config = SSOConfig(
            provider=provider,
            provider_name=payload.provider_name,
            enabled=payload.enabled,
            enforce_sso=payload.enforce_sso,
            client_id=payload.client_id if provider in {"oauth", "oidc"} else payload.saml_entity_id,
            client_secret_encrypted=encrypted_secret,
            discovery_url=payload.discovery_url if provider in {"oauth", "oidc"} else payload.saml_idp_metadata_url,
            redirect_uri=payload.redirect_uri if provider in {"oauth", "oidc"} else payload.saml_acs_url,
            scopes=payload.scopes if provider in {"oauth", "oidc"} else payload.saml_nameid_format,
            email_claim=payload.email_claim,
            username_claim=payload.username_claim,
            user_id_claim=payload.user_id_claim,
            token_endpoint=payload.token_endpoint if provider in {"oauth", "oidc"} else payload.saml_slo_url,
            authorization_endpoint=payload.authorization_endpoint if provider in {"oauth", "oidc"} else payload.saml_sso_url,
            jwks_uri=payload.jwks_uri if provider in {"oauth", "oidc"} else payload.saml_x509_cert,
            issuer=payload.issuer if provider in {"oauth", "oidc"} else payload.saml_idp_entity_id,
            created_by=current_user.id,
        )
        session.add(config)
    else:
        config.provider = provider
        config.enabled = payload.enabled
        config.enforce_sso = payload.enforce_sso
        config.client_id = payload.client_id if provider in {"oauth", "oidc"} else payload.saml_entity_id
        if encrypted_secret:
            config.client_secret_encrypted = encrypted_secret
        config.discovery_url = payload.discovery_url if provider in {"oauth", "oidc"} else payload.saml_idp_metadata_url
        config.redirect_uri = payload.redirect_uri if provider in {"oauth", "oidc"} else payload.saml_acs_url
        config.scopes = payload.scopes if provider in {"oauth", "oidc"} else payload.saml_nameid_format
        config.email_claim = payload.email_claim
        config.username_claim = payload.username_claim
        config.user_id_claim = payload.user_id_claim
        config.token_endpoint = payload.token_endpoint if provider in {"oauth", "oidc"} else payload.saml_slo_url
        config.authorization_endpoint = payload.authorization_endpoint if provider in {"oauth", "oidc"} else payload.saml_sso_url
        config.jwks_uri = payload.jwks_uri if provider in {"oauth", "oidc"} else payload.saml_x509_cert
        config.issuer = payload.issuer if provider in {"oauth", "oidc"} else payload.saml_idp_entity_id
        config.updated_at = datetime.now(timezone.utc)

    await session.flush()
    await session.refresh(config)
    return _config_to_response(config)


@router.get("/config/{provider_name}/saml/metadata", response_model=SAMLMetadataResponse)
async def get_saml_metadata_admin(
    provider_name: str,
    current_user: Annotated[User, Depends(get_current_active_superuser)],
    session: DbSession,
):
    _ = current_user
    _ensure_sso_enabled()
    config = await _get_config(session, provider_name, allowed_providers={"saml"})
    return SAMLMetadataResponse(
        provider_name=provider_name,
        metadata_xml=_build_saml_metadata(config),
    )


@router.get("/config/{provider_name}/saml/metadata.xml")
async def download_saml_metadata_admin(
    provider_name: str,
    current_user: Annotated[User, Depends(get_current_active_superuser)],
    session: DbSession,
):
    _ = current_user
    _ensure_sso_enabled()
    config = await _get_config(session, provider_name, allowed_providers={"saml"})
    xml = _build_saml_metadata(config)
    response = Response(content=xml, media_type="application/samlmetadata+xml")
    response.headers["Content-Disposition"] = f'attachment; filename="{provider_name}-metadata.xml"'
    return response


@router.get("/start/{provider_name}")
async def sso_start(
    provider_name: str,
    session: DbSession,
    next_url: Annotated[str | None, Query(alias="next")] = None,
):
    _ensure_sso_enabled()
    config = await _get_config(session, provider_name, allowed_providers={"oauth", "oidc"})

    metadata: dict[str, Any] = {}
    if config.discovery_url:
        metadata = await _fetch_discovery(config.discovery_url)

    authorization_endpoint = config.authorization_endpoint or metadata.get("authorization_endpoint")
    if not authorization_endpoint:
        raise HTTPException(status_code=400, detail="OAuth authorization endpoint not configured")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": config.scopes or "openid email profile",
        "state": state,
        "nonce": nonce,
    }
    target = f"{authorization_endpoint}?{urlencode(params)}"

    response = RedirectResponse(url=target, status_code=307)
    _set_cookie(response, SSO_STATE_COOKIE, state, max_age=600)
    _set_cookie(response, SSO_NONCE_COOKIE, nonce, max_age=600)
    _set_cookie(response, SSO_PROVIDER_COOKIE, provider_name, max_age=600)
    _set_cookie(response, SSO_NEXT_COOKIE, _safe_next(next_url), max_age=600)
    return response


@router.get("/callback")
async def sso_callback(
    request: Request,
    session: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    _ensure_sso_enabled()

    if error:
        raise HTTPException(status_code=400, detail=error_description or error)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth callback parameters")

    cookie_state = request.cookies.get(SSO_STATE_COOKIE)
    cookie_nonce = request.cookies.get(SSO_NONCE_COOKIE)
    cookie_provider = request.cookies.get(SSO_PROVIDER_COOKIE)
    next_url = _safe_next(request.cookies.get(SSO_NEXT_COOKIE))

    if not cookie_state or not cookie_provider or not cookie_nonce:
        raise HTTPException(status_code=400, detail="Missing SSO handshake state")
    if cookie_state != state:
        raise HTTPException(status_code=400, detail="Invalid SSO state")

    config = await _get_config(session, cookie_provider, allowed_providers={"oauth", "oidc"})
    metadata: dict[str, Any] = {}
    if config.discovery_url:
        metadata = await _fetch_discovery(config.discovery_url)

    token_endpoint = config.token_endpoint or metadata.get("token_endpoint")
    jwks_uri = config.jwks_uri or metadata.get("jwks_uri")
    issuer = config.issuer or metadata.get("issuer")

    if not token_endpoint or not jwks_uri:
        raise HTTPException(status_code=400, detail="OAuth token/jwks endpoints are not configured")

    client_secret = get_auth_service().decrypt_api_key(config.client_secret_encrypted or "")
    if not client_secret:
        raise HTTPException(status_code=400, detail="SSO client secret is missing")

    async with httpx.AsyncClient(timeout=20.0) as client:
        token_resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.redirect_uri,
                "client_id": config.client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code >= 400:
            raise HTTPException(status_code=400, detail="Failed to exchange authorization code")
        token_data = token_resp.json()

    id_token = token_data.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="Missing id_token in token response")

    try:
        signing_key = jwt.PyJWKClient(jwks_uri).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            audience=config.client_id,
            issuer=issuer,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "HS256"],
            options={"require": ["exp", "iat", "sub"]},
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid id_token") from exc

    if claims.get("nonce") != cookie_nonce:
        raise HTTPException(status_code=400, detail="Invalid nonce")

    user = await _get_or_create_sso_user(session, config, claims)
    await get_variable_service().initialize_user_variables(user.id, session)
    _ = await get_or_create_default_folder(session, user.id)

    tokens = await get_auth_service().create_user_tokens(user_id=user.id, db=session, update_last_login=True)
    redirect_response = RedirectResponse(url=next_url, status_code=302)
    _set_auth_cookies(redirect_response, tokens, user)
    _delete_cookie(redirect_response, SSO_STATE_COOKIE)
    _delete_cookie(redirect_response, SSO_NONCE_COOKIE)
    _delete_cookie(redirect_response, SSO_PROVIDER_COOKIE)
    _delete_cookie(redirect_response, SSO_NEXT_COOKIE)
    return redirect_response

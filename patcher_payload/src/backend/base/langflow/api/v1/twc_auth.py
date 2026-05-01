from __future__ import annotations

from datetime import datetime
from typing import Any, Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from langflow.api.utils import DbSession
from langflow.services.auth.twc import (
    TWC_SESSION_ID_COOKIE,
    TWC_STATE_NONCE_COOKIE,
    TWC_STATE_SERVER_COOKIE,
    TWCServerConfig,
    build_identity,
    build_login_error_redirect,
    build_signin_redirect,
    build_twc_session,
    clear_twc_session_cookie,
    clear_twc_state_cookies,
    create_langflow_login_response,
    decode_signed_state,
    decode_token_claims,
    delete_cookie,
    delete_twc_session,
    exchange_code_for_tokens,
    extract_proxy_token_bundle,
    get_or_create_twc_user,
    get_twc_callback_url,
    get_twc_server,
    get_twc_session_from_request,
    initialize_langflow_user,
    load_twc_server_configs,
    save_twc_session,
    set_cookie,
    set_twc_session_cookie,
    validate_and_refresh_twc_session,
    validate_current_user,
)
from langflow.services.deps import get_auth_service

router = APIRouter(tags=["TWC Authentication"], prefix="/auth/twc")


class TWCServerResponse(BaseModel):
    id: str
    label: str
    rest_url: str
    authorize_url: str
    ready: bool
    error: str | None = None


class TWCServersResponse(BaseModel):
    enabled: bool
    single_server: bool
    default_server_id: str | None = None
    servers: list[TWCServerResponse]


class TWCAuthStatusResponse(BaseModel):
    enabled: bool
    configured: bool
    authenticated: bool
    server_id: str | None = None
    server_label: str | None = None
    username: str | None = None
    external_user_id: str | None = None
    has_refresh_token: bool = False
    expires_at: datetime | None = None
    current_user: dict[str, Any] | None = None
    error: str | None = None


def _clear_langflow_auth_cookies(response: Response) -> None:
    delete_cookie(response, "refresh_token_lf")
    delete_cookie(response, "access_token_lf")
    delete_cookie(response, "apikey_tkn_lflw")


def _redirect_with_error(request: Request, message: str) -> RedirectResponse:
    response = RedirectResponse(url=build_login_error_redirect(request=request, message=message), status_code=302)
    clear_twc_state_cookies(response)
    return response


def _serialize_server(server: TWCServerConfig) -> TWCServerResponse:
    return TWCServerResponse(
        id=server.id,
        label=server.label,
        rest_url=server.rest_url,
        authorize_url=server.authorize_url,
        ready=server.ready,
        error=server.error,
    )


@router.get("/servers", response_model=TWCServersResponse)
async def list_twc_servers():
    servers = load_twc_server_configs()
    ready_servers = [server for server in servers if server.ready]
    default_server_id = ready_servers[0].id if len(ready_servers) == 1 else None
    return TWCServersResponse(
        enabled=bool(servers),
        single_server=len(ready_servers) == 1,
        default_server_id=default_server_id,
        servers=[_serialize_server(server) for server in servers],
    )


@router.get("/signin/{server_id}")
async def twc_signin(
    request: Request,
    server_id: str,
    next_url: Annotated[str | None, Query(alias="next")] = None,
):
    server = get_twc_server(server_id, require_ready=True)
    callback_url = get_twc_callback_url(request)
    target_url, nonce = build_signin_redirect(server, callback_url=callback_url, next_url=next_url or "/")

    response = RedirectResponse(url=target_url, status_code=307)
    set_cookie(response, TWC_STATE_NONCE_COOKIE, nonce, max_age=600)
    set_cookie(response, TWC_STATE_SERVER_COOKIE, server.id, max_age=600)
    return response


@router.get("/callback")
async def twc_callback(
    request: Request,
    session: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    if not state:
        return _redirect_with_error(request, "Missing TWC callback state.")

    try:
        state_payload = decode_signed_state(state)
    except Exception as exc:  # noqa: BLE001
        return _redirect_with_error(request, str(getattr(exc, "detail", exc)))

    cookie_nonce = request.cookies.get(TWC_STATE_NONCE_COOKIE)
    cookie_server = request.cookies.get(TWC_STATE_SERVER_COOKIE)
    if not cookie_nonce or cookie_nonce != state_payload.get("nonce"):
        return _redirect_with_error(request, "Invalid or tampered TWC login state.")
    if cookie_server and cookie_server != state_payload.get("server_id"):
        return _redirect_with_error(request, "The selected TWC server changed during login.")

    if error:
        message = error_description or error
        return _redirect_with_error(request, f"TWC login was canceled or failed: {message}")

    try:
        server = get_twc_server(str(state_payload["server_id"]), require_ready=True)
        callback_url = get_twc_callback_url(request)

        if code:
            token_data = await exchange_code_for_tokens(server, callback_url=callback_url, code=code)
        else:
            token_data = extract_proxy_token_bundle(request)
            if not token_data:
                return _redirect_with_error(
                    request,
                    "Missing authorization code from the TWC Authentication Server callback.",
                )

        rest_token = token_data.get("id_token") or token_data.get("access_token")
        if not rest_token:
            return _redirect_with_error(
                request,
                "TWC token response did not include an id_token or access_token.",
            )

        current_user = await validate_current_user(server, rest_token)
        identity = build_identity(
            server_id=server.id,
            current_user=current_user,
            claims=decode_token_claims(token_data.get("id_token") or token_data.get("access_token")),
        )
        user = await get_or_create_twc_user(session, identity, server_id=server.id)
        await initialize_langflow_user(session, user)

        langflow_tokens = await get_auth_service().create_user_tokens(user_id=user.id, db=session, update_last_login=True)
        session_data = await build_twc_session(
            server=server,
            token_data=token_data,
            current_user=current_user,
            identity=identity,
        )
        await save_twc_session(session_data)

        response = RedirectResponse(url=str(state_payload.get("next") or "/"), status_code=302)
        create_langflow_login_response(response=response, tokens=langflow_tokens, user=user)
        set_twc_session_cookie(response, session_data.session_id)
        clear_twc_state_cookies(response)
        return response
    except Exception as exc:  # noqa: BLE001
        message = getattr(exc, "detail", str(exc))
        return _redirect_with_error(request, str(message))


@router.post("/logout")
async def twc_logout(request: Request, response: Response):
    await delete_twc_session(request.cookies.get(TWC_SESSION_ID_COOKIE))
    clear_twc_session_cookie(response)
    clear_twc_state_cookies(response)
    _clear_langflow_auth_cookies(response)
    return {"message": "Logout successful"}


@router.get("/status", response_model=TWCAuthStatusResponse)
async def twc_status(request: Request):
    servers = load_twc_server_configs()
    ready_servers = [server for server in servers if server.ready]
    session_data = await get_twc_session_from_request(request)

    if not session_data:
        return TWCAuthStatusResponse(
            enabled=bool(servers),
            configured=bool(ready_servers),
            authenticated=False,
        )

    try:
        active_session, current_user = await validate_and_refresh_twc_session(session_data, request=request)
        return TWCAuthStatusResponse(
            enabled=bool(servers),
            configured=bool(ready_servers),
            authenticated=True,
            server_id=active_session.server_id,
            server_label=active_session.server_label,
            username=active_session.username,
            external_user_id=active_session.external_user_id,
            has_refresh_token=active_session.has_refresh_token(),
            expires_at=active_session.expires_at,
            current_user=current_user,
        )
    except Exception as exc:  # noqa: BLE001
        return TWCAuthStatusResponse(
            enabled=bool(servers),
            configured=bool(ready_servers),
            authenticated=False,
            server_id=session_data.server_id,
            server_label=session_data.server_label,
            username=session_data.username,
            external_user_id=session_data.external_user_id,
            has_refresh_token=session_data.has_refresh_token(),
            expires_at=session_data.expires_at,
            current_user=session_data.current_user,
            error=str(getattr(exc, "detail", exc)),
        )

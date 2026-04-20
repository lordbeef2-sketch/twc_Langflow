from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from langflow.services.auth.utils import get_current_active_superuser
from langflow.services.database.models.user.model import User
from langflow.services.deps import get_settings_service

router = APIRouter(tags=["Admin Settings"], prefix="/admin/settings")


class HTTPSSettingsResponse(BaseModel):
    ssl_enabled: bool
    ssl_cert_file: str | None
    ssl_key_file: str | None
    host: str
    port: int
    access_secure_cookie: bool
    refresh_secure_cookie: bool
    https_hsts_enabled: bool
    https_hsts_max_age: int
    https_hsts_include_subdomains: bool
    https_hsts_preload: bool
    restart_required: bool = True


class HTTPSSettingsUpdateRequest(BaseModel):
    ssl_enabled: bool
    ssl_cert_file: str | None = Field(default=None)
    ssl_key_file: str | None = Field(default=None)
    host: str | None = Field(default=None, min_length=1)
    port: int | None = Field(default=None, ge=1, le=65535)
    https_hsts_enabled: bool | None = Field(default=None)
    https_hsts_max_age: int | None = Field(default=None, ge=0, le=63072000)
    https_hsts_include_subdomains: bool | None = Field(default=None)
    https_hsts_preload: bool | None = Field(default=None)


class HTTPSUploadResponse(BaseModel):
    file_type: str
    file_path: str


class SSOSettingsResponse(BaseModel):
    sso_enabled: bool


class SSOSettingsUpdateRequest(BaseModel):
    sso_enabled: bool


def _get_certs_dir() -> Path:
    settings = get_settings_service().settings
    if settings.config_dir:
        base_dir = Path(settings.config_dir).expanduser()
    else:
        base_dir = Path.home() / ".langflow"
    certs_dir = base_dir / "certs"
    certs_dir.mkdir(parents=True, exist_ok=True)
    return certs_dir


def _validate_ssl_paths(cert_file: str, key_file: str) -> tuple[str, str]:
    cert = Path(cert_file).expanduser()
    key = Path(key_file).expanduser()

    if not cert.exists() or not cert.is_file():
        raise HTTPException(status_code=400, detail=f"SSL certificate file not found: {cert}")
    if not key.exists() or not key.is_file():
        raise HTTPException(status_code=400, detail=f"SSL key file not found: {key}")

    return str(cert), str(key)


@router.get("/sso", response_model=SSOSettingsResponse)
async def get_sso_settings(
    current_user: Annotated[User, Depends(get_current_active_superuser)],
):
    _ = current_user
    auth_settings = get_settings_service().auth_settings
    return SSOSettingsResponse(sso_enabled=auth_settings.SSO_ENABLED)


@router.put("/sso", response_model=SSOSettingsResponse)
async def update_sso_settings(
    payload: SSOSettingsUpdateRequest,
    current_user: Annotated[User, Depends(get_current_active_superuser)],
):
    _ = current_user
    auth_settings = get_settings_service().auth_settings
    # Keep this mutable from admin settings so SSO can be toggled without env edits.
    auth_settings.SSO_ENABLED = payload.sso_enabled
    return SSOSettingsResponse(sso_enabled=auth_settings.SSO_ENABLED)


@router.get("/https", response_model=HTTPSSettingsResponse)
async def get_https_settings(
    current_user: Annotated[User, Depends(get_current_active_superuser)],
):
    _ = current_user
    settings_service = get_settings_service()
    settings = settings_service.settings
    auth_settings = settings_service.auth_settings

    ssl_enabled = bool(settings.ssl_cert_file and settings.ssl_key_file)
    return HTTPSSettingsResponse(
        ssl_enabled=ssl_enabled,
        ssl_cert_file=settings.ssl_cert_file,
        ssl_key_file=settings.ssl_key_file,
        host=settings.host,
        port=settings.port,
        access_secure_cookie=auth_settings.ACCESS_SECURE,
        refresh_secure_cookie=auth_settings.REFRESH_SECURE,
        https_hsts_enabled=settings.https_hsts_enabled,
        https_hsts_max_age=settings.https_hsts_max_age,
        https_hsts_include_subdomains=settings.https_hsts_include_subdomains,
        https_hsts_preload=settings.https_hsts_preload,
    )


@router.put("/https", response_model=HTTPSSettingsResponse)
async def update_https_settings(
    payload: HTTPSSettingsUpdateRequest,
    current_user: Annotated[User, Depends(get_current_active_superuser)],
):
    _ = current_user
    settings_service = get_settings_service()
    settings = settings_service.settings
    auth_settings = settings_service.auth_settings

    next_host = payload.host if payload.host is not None else settings.host
    next_port = payload.port if payload.port is not None else settings.port

    cert_file = payload.ssl_cert_file or settings.ssl_cert_file
    key_file = payload.ssl_key_file or settings.ssl_key_file

    if payload.ssl_enabled:
        if not cert_file or not key_file:
            raise HTTPException(
                status_code=400,
                detail="Enabling HTTPS requires both ssl_cert_file and ssl_key_file.",
            )
        cert_file, key_file = _validate_ssl_paths(cert_file, key_file)
        settings.update_settings(
            ssl_cert_file=cert_file,
            ssl_key_file=key_file,
            host=next_host,
            port=next_port,
        )
        # Ensure auth cookies are marked secure when HTTPS is enabled.
        auth_settings.set("ACCESS_SECURE", True)
        auth_settings.set("REFRESH_SECURE", True)
    else:
        settings.update_settings(
            ssl_cert_file=None,
            ssl_key_file=None,
            host=next_host,
            port=next_port,
        )
        # Keep behavior consistent for non-TLS local runs.
        auth_settings.set("ACCESS_SECURE", False)
        auth_settings.set("REFRESH_SECURE", False)

    settings.update_settings(
        https_hsts_enabled=(
            payload.https_hsts_enabled
            if payload.https_hsts_enabled is not None
            else settings.https_hsts_enabled
        ),
        https_hsts_max_age=(
            payload.https_hsts_max_age
            if payload.https_hsts_max_age is not None
            else settings.https_hsts_max_age
        ),
        https_hsts_include_subdomains=(
            payload.https_hsts_include_subdomains
            if payload.https_hsts_include_subdomains is not None
            else settings.https_hsts_include_subdomains
        ),
        https_hsts_preload=(
            payload.https_hsts_preload
            if payload.https_hsts_preload is not None
            else settings.https_hsts_preload
        ),
    )

    return HTTPSSettingsResponse(
        ssl_enabled=payload.ssl_enabled,
        ssl_cert_file=settings.ssl_cert_file,
        ssl_key_file=settings.ssl_key_file,
        host=settings.host,
        port=settings.port,
        access_secure_cookie=auth_settings.ACCESS_SECURE,
        refresh_secure_cookie=auth_settings.REFRESH_SECURE,
        https_hsts_enabled=settings.https_hsts_enabled,
        https_hsts_max_age=settings.https_hsts_max_age,
        https_hsts_include_subdomains=settings.https_hsts_include_subdomains,
        https_hsts_preload=settings.https_hsts_preload,
    )


@router.post("/https/upload", response_model=HTTPSUploadResponse)
async def upload_https_file(
    current_user: Annotated[User, Depends(get_current_active_superuser)],
    file_type: Annotated[str, Form()],
    file: UploadFile = File(...),
):
    _ = current_user
    if file_type not in {"cert", "key"}:
        raise HTTPException(status_code=400, detail="file_type must be 'cert' or 'key'")

    certs_dir = _get_certs_dir()
    original_name = Path(file.filename or "uploaded").name
    suffix = Path(original_name).suffix or (".crt" if file_type == "cert" else ".key")
    dest_name = f"langflow-{file_type}{suffix}"
    dest_path = certs_dir / dest_name

    # 2 MB hard limit for cert/key uploads.
    max_size = 2 * 1024 * 1024
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > max_size:
        raise HTTPException(status_code=400, detail="Uploaded file exceeds 2 MB")

    with dest_path.open("wb") as out_file:
        shutil.copyfileobj(file.file, out_file)

    settings = get_settings_service().settings
    if file_type == "cert":
        settings.update_settings(ssl_cert_file=str(dest_path))
    else:
        settings.update_settings(ssl_key_file=str(dest_path))

    return HTTPSUploadResponse(file_type=file_type, file_path=str(dest_path))

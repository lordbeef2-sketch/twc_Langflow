from __future__ import annotations

import asyncio
import io
import threading
import zipfile
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi_pagination import Page, Params
from fastapi_pagination.ext.sqlmodel import apaginate
from lfx.services.cache.utils import CACHE_MISS
from sqlmodel import and_, col, select

from langflow.api.utils import (
    CurrentActiveUser,
    DbSession,
    cascade_delete_flow,
    normalize_code_for_import,
    validate_is_component,
)
from langflow.api.utils.zip_utils import extract_flows_from_zip
from langflow.api.v1.flows_helpers import (
    _build_flows_download_response,
    _get_safe_flow_path,
    _new_flow,
    _patch_flow,
    _read_flow,
    _read_flow_with_access,
    _read_shared_flows,
    _save_flow_to_fs,
    _serialize_flow,
    _update_existing_flow,
    _upsert_flow_list,
    _verify_fs_path,
)
from langflow.api.v1.schemas import FlowListCreate
from langflow.helpers.user import get_user_by_flow_id_or_endpoint_name
from langflow.initial_setup.constants import STARTER_FOLDER_NAME
from langflow.services.auth.utils import get_current_active_user
from langflow.services.cache.service import ThreadingInMemoryCache
from langflow.services.database.models.flow.model import (
    AccessTypeEnum,
    Flow,
    FlowCreate,
    FlowHeader,
    FlowRead,
    FlowUpdate,
)
from langflow.services.database.models.flow_share.model import (
    FlowAccessLevel,
    FlowShare,
    FlowShareCreate,
    FlowSharePermission,
    FlowShareRead,
    FlowShareRespond,
    FlowShareStatus,
    IncomingFlowShareRead,
)

# TODO: Full-version import/export is planned as a follow-up feature. When implemented,
# re-add imports for create_flow_version_entry, get_flow_version_list, strip_version_data,
# and FlowVersionError from the flow_version modules.
from langflow.services.database.models.folder.constants import DEFAULT_FOLDER_NAME
from langflow.services.database.models.folder.model import Folder
from langflow.services.deps import get_settings_service, get_storage_service
from langflow.services.storage.service import StorageService
from langflow.utils.compression import compress_response

# Re-export helpers so existing ``from langflow.api.v1.flows import ...`` still works.
__all__ = [
    "_get_safe_flow_path",
    "_new_flow",
    "_read_flow",
    "_save_flow_to_fs",
    "_update_existing_flow",
    "_verify_fs_path",
]


def _handle_unique_constraint_error(exc: Exception, *, status_code: int = 400) -> HTTPException:
    """Parse a UNIQUE constraint error and return an appropriate HTTPException."""
    msg = str(exc)
    if "UNIQUE constraint failed" not in msg:
        return HTTPException(status_code=500, detail=msg)
    columns = msg.split("UNIQUE constraint failed: ")[1].split(".")[1].split("\n")[0]
    column = columns.split(",")[1] if "id" in columns.split(",")[0] else columns.split(",")[0]
    return HTTPException(status_code=status_code, detail=f"{column.capitalize().replace('_', ' ')} must be unique")


# build router
router = APIRouter(prefix="/flows", tags=["Flows"])


@router.post("/", response_model=FlowRead, status_code=201)
async def create_flow(
    *,
    session: DbSession,
    flow: FlowCreate,
    current_user: CurrentActiveUser,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
):
    try:
        return await _new_flow(session=session, flow=flow, user_id=current_user.id, storage_service=storage_service)
    except HTTPException:
        raise
    except Exception as e:
        raise _handle_unique_constraint_error(e) from e


@router.get("/", response_model=list[FlowRead] | Page[FlowRead] | list[FlowHeader], status_code=200)
async def read_flows(
    *,
    current_user: CurrentActiveUser,
    session: DbSession,
    remove_example_flows: bool = False,
    components_only: bool = False,
    get_all: bool = True,
    folder_id: UUID | None = None,
    params: Annotated[Params, Depends()],
    header_flows: bool = False,
):
    """Retrieve a list of flows with optional pagination, filtering, and header-only mode."""
    try:
        auth_settings = get_settings_service().auth_settings

        default_folder = (await session.exec(select(Folder).where(Folder.name == DEFAULT_FOLDER_NAME))).first()
        default_folder_id = default_folder.id if default_folder else None

        starter_folder = (await session.exec(select(Folder).where(Folder.name == STARTER_FOLDER_NAME))).first()
        starter_folder_id = starter_folder.id if starter_folder else None

        if not starter_folder and not default_folder:
            raise HTTPException(
                status_code=404,
                detail="Starter project and default project not found. Please create a project and add flows to it.",
            )

        if not folder_id:
            folder_id = default_folder_id

        if auth_settings.AUTO_LOGIN:
            stmt = select(Flow).where(
                (Flow.user_id == None) | (Flow.user_id == current_user.id)  # noqa: E711
            )
        else:
            stmt = select(Flow).where(Flow.user_id == current_user.id)

        if remove_example_flows:
            stmt = stmt.where(Flow.folder_id != starter_folder_id)

        if components_only:
            stmt = stmt.where(Flow.is_component == True)  # noqa: E712

        if get_all:
            owner_flows = (await session.exec(stmt)).all()
            owner_flows = validate_is_component(owner_flows)
            if components_only:
                owner_flows = [flow for flow in owner_flows if flow.is_component]
            if remove_example_flows and starter_folder_id:
                owner_flows = [flow for flow in owner_flows if flow.folder_id != starter_folder_id]

            shared_flows = await _read_shared_flows(
                session,
                current_user.id,
                components_only=True if components_only else None,
            )
            serialized_flows = [
                _serialize_flow(flow) for flow in owner_flows
            ] + [
                _serialize_flow(
                    flow,
                    permission=(
                        FlowAccessLevel.EDIT
                        if share.permission == FlowSharePermission.EDIT
                        else FlowAccessLevel.READ
                    ),
                    shared_by_username=owner_username,
                )
                for flow, share, owner_username in shared_flows
            ]
            serialized_flows = sorted(
                serialized_flows,
                key=lambda flow: flow.updated_at or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            if header_flows:
                flow_headers = [
                    FlowHeader.model_validate(flow.model_dump())
                    for flow in serialized_flows
                ]
                return compress_response(flow_headers)

            return compress_response(serialized_flows)

        stmt = stmt.where(Flow.folder_id == folder_id)

        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", category=DeprecationWarning, module=r"fastapi_pagination\.ext\.sqlalchemy"
            )
            return await apaginate(session, stmt, params=params)

    except Exception as e:
        import logging as _logging

        _logging.getLogger(__name__).exception("Error listing flows")
        raise HTTPException(status_code=500, detail="An internal error occurred while listing flows.") from e


@router.get("/{flow_id}", response_model=FlowRead, status_code=200)
async def read_flow(
    *,
    session: DbSession,
    flow_id: UUID,
    current_user: CurrentActiveUser,
):
    """Read a flow."""
    flow, permission, _share, owner_username = await _read_flow_with_access(session, flow_id, current_user.id)
    if flow and permission:
        return _serialize_flow(
            flow,
            permission=permission,
            shared_by_username=owner_username,
        )
    raise HTTPException(status_code=404, detail="Flow not found")


@router.get("/public_flow/{flow_id}", response_model=FlowRead, status_code=200)
async def read_public_flow(
    *,
    session: DbSession,
    flow_id: UUID,
):
    """Read a public flow."""
    access_type = (await session.exec(select(Flow.access_type).where(Flow.id == flow_id))).first()
    if access_type is not AccessTypeEnum.PUBLIC:
        raise HTTPException(status_code=403, detail="Flow is not public")

    current_user = await get_user_by_flow_id_or_endpoint_name(str(flow_id))
    return await read_flow(session=session, flow_id=flow_id, current_user=current_user)


@router.patch("/{flow_id}", response_model=FlowRead, status_code=200)
async def update_flow(
    *,
    session: DbSession,
    flow_id: UUID,
    flow: FlowUpdate,
    current_user: CurrentActiveUser,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
):
    """Update a flow."""
    try:
        db_flow, permission, _share, _owner_username = await _read_flow_with_access(
            session=session,
            flow_id=flow_id,
            user_id=current_user.id,
        )
        if not db_flow or permission is None:
            raise HTTPException(status_code=404, detail="Flow not found")
        if permission not in {FlowAccessLevel.OWNER, FlowAccessLevel.EDIT}:
            raise HTTPException(status_code=403, detail="You only have read access to this flow")
        if permission != FlowAccessLevel.OWNER:
            protected_fields = {"folder_id", "access_type", "endpoint_name", "fs_path"}
            attempted_protected_fields = protected_fields.intersection(flow.model_fields_set)
            if attempted_protected_fields:
                raise HTTPException(
                    status_code=403,
                    detail="Only the owner can update sharing, folder, endpoint, or file path settings",
                )

        updated_flow = await _patch_flow(
            session=session,
            db_flow=db_flow,
            flow=flow,
            user_id=db_flow.user_id,
            storage_service=storage_service,
        )
        return _serialize_flow(
            db_flow,
            permission=permission,
            shared_by_username=_owner_username,
        ) if permission != FlowAccessLevel.OWNER else updated_flow
    except HTTPException:
        raise
    except Exception as e:
        raise _handle_unique_constraint_error(e) from e


@router.put("/{flow_id}", response_model=FlowRead)
async def upsert_flow(
    *,
    session: DbSession,
    flow_id: UUID,
    flow: FlowCreate,
    current_user: CurrentActiveUser,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
):
    """Create or update a flow with a specific ID (upsert).

    Returns 201 for creation, 200 for update.  Returns 404 if owned by another user.
    """
    from fastapi.responses import JSONResponse

    try:
        # Check if flow exists (without user filter to distinguish ownership vs CREATE)
        existing_flow = (await session.exec(select(Flow).where(Flow.id == flow_id))).first()

        if existing_flow is not None:
            # Flow exists - check ownership (return 404 to avoid leaking resource existence)
            if existing_flow.user_id != current_user.id:
                raise HTTPException(status_code=404, detail="Flow not found")

            # UPDATE path
            flow_read = await _update_existing_flow(
                session=session,
                existing_flow=existing_flow,
                flow=flow,
                current_user=current_user,
                storage_service=storage_service,
            )
            status_code = 200
        else:
            # CREATE path - flow doesn't exist
            flow_read = await _new_flow(
                session=session,
                flow=flow,
                user_id=current_user.id,
                storage_service=storage_service,
                flow_id=flow_id,
                fail_on_endpoint_conflict=True,
                validate_folder=True,
            )
            status_code = 201

        return JSONResponse(status_code=status_code, content=jsonable_encoder(flow_read))

    except HTTPException:
        raise
    except Exception as e:
        raise _handle_unique_constraint_error(e, status_code=409) from e


@router.delete("/{flow_id}", status_code=200)
async def delete_flow(
    *,
    session: DbSession,
    flow_id: UUID,
    current_user: CurrentActiveUser,
):
    """Delete a flow."""
    flow = await _read_flow(
        session=session,
        flow_id=flow_id,
        user_id=current_user.id,
    )
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    await cascade_delete_flow(session, flow.id)
    return {"message": "Flow deleted successfully"}


@router.get("/shared/accepted", response_model=list[FlowRead], status_code=200)
async def read_accepted_shared_flows(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    is_component: bool = False,
    is_flow: bool = False,
    search: str = "",
):
    component_filter: bool | None = None
    if is_component:
        component_filter = True
    elif is_flow:
        component_filter = False

    shared_flows = await _read_shared_flows(
        session,
        current_user.id,
        components_only=component_filter,
        search=search or None,
    )

    return [
        _serialize_flow(
            flow,
            permission=(
                FlowAccessLevel.EDIT
                if share.permission == FlowSharePermission.EDIT
                else FlowAccessLevel.READ
            ),
            shared_by_username=owner_username,
        )
        for flow, share, owner_username in shared_flows
    ]


@router.get("/shared/incoming", response_model=list[IncomingFlowShareRead], status_code=200)
async def read_incoming_flow_shares(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    from langflow.services.database.models.user.model import User

    stmt = (
        select(FlowShare, Flow.name, User.username)
        .join(Flow, Flow.id == FlowShare.flow_id)
        .join(User, User.id == FlowShare.owner_user_id)
        .where(FlowShare.recipient_user_id == current_user.id)
        .where(FlowShare.status == FlowShareStatus.PENDING)
        .order_by(FlowShare.created_at.desc())
    )
    incoming_shares = (await session.exec(stmt)).all()

    return [
        IncomingFlowShareRead(
            id=share.id,
            flow_id=share.flow_id,
            flow_name=flow_name,
            owner_user_id=share.owner_user_id,
            owner_username=owner_username,
            permission=share.permission,
            status=share.status,
            created_at=share.created_at,
            responded_at=share.responded_at,
        )
        for share, flow_name, owner_username in incoming_shares
    ]


@router.post("/{flow_id}/shares", response_model=list[FlowShareRead], status_code=200)
async def create_flow_shares(
    *,
    session: DbSession,
    flow_id: UUID,
    payload: FlowShareCreate,
    current_user: CurrentActiveUser,
):
    from langflow.services.database.models.user.model import User

    flow = await _read_flow(session=session, flow_id=flow_id, user_id=current_user.id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    recipient_ids = list(dict.fromkeys(payload.recipient_user_ids))
    if not recipient_ids:
        raise HTTPException(status_code=400, detail="Select at least one recipient")

    if current_user.id in recipient_ids:
        raise HTTPException(status_code=400, detail="You can't share a flow with yourself")

    recipients = (
        await session.exec(
            select(User).where(col(User.id).in_(recipient_ids)).where(User.is_active == True)  # noqa: E712
        )
    ).all()
    recipients_by_id = {recipient.id: recipient for recipient in recipients}

    missing_user_ids = [recipient_id for recipient_id in recipient_ids if recipient_id not in recipients_by_id]
    if missing_user_ids:
        raise HTTPException(status_code=404, detail="One or more selected users could not be found")

    existing_shares = (
        await session.exec(
            select(FlowShare).where(FlowShare.flow_id == flow_id).where(col(FlowShare.recipient_user_id).in_(recipient_ids))
        )
    ).all()
    existing_by_recipient = {share.recipient_user_id: share for share in existing_shares}

    updated_at = datetime.now(timezone.utc)
    shares: list[FlowShare] = []
    for recipient_id in recipient_ids:
        share = existing_by_recipient.get(recipient_id)
        if not share:
            share = FlowShare(
                flow_id=flow_id,
                owner_user_id=current_user.id,
                recipient_user_id=recipient_id,
                permission=payload.permission,
                status=FlowShareStatus.PENDING,
            )
        else:
            share.owner_user_id = current_user.id
            share.permission = payload.permission
            share.status = FlowShareStatus.PENDING
            share.responded_at = None
            share.updated_at = updated_at

        session.add(share)
        shares.append(share)

    await session.flush()
    for share in shares:
        await session.refresh(share)

    return [
        FlowShareRead(
            id=share.id,
            flow_id=share.flow_id,
            recipient_user_id=share.recipient_user_id,
            recipient_username=recipients_by_id[share.recipient_user_id].username,
            permission=share.permission,
            status=share.status,
            created_at=share.created_at,
            updated_at=share.updated_at,
            responded_at=share.responded_at,
        )
        for share in shares
    ]


@router.patch("/shares/{share_id}", response_model=IncomingFlowShareRead, status_code=200)
async def respond_to_flow_share(
    *,
    session: DbSession,
    share_id: UUID,
    payload: FlowShareRespond,
    current_user: CurrentActiveUser,
):
    from langflow.services.database.models.user.model import User

    share_data = (
        await session.exec(
            select(FlowShare, Flow.name, User.username)
            .join(Flow, Flow.id == FlowShare.flow_id)
            .join(User, User.id == FlowShare.owner_user_id)
            .where(FlowShare.id == share_id)
            .where(FlowShare.recipient_user_id == current_user.id)
        )
    ).first()

    if not share_data:
        raise HTTPException(status_code=404, detail="Share invite not found")

    share, flow_name, owner_username = share_data
    if share.status != FlowShareStatus.PENDING:
        raise HTTPException(status_code=409, detail="This share invite has already been handled")

    share.status = FlowShareStatus.ACCEPTED if payload.accept else FlowShareStatus.REJECTED
    share.responded_at = datetime.now(timezone.utc)
    share.updated_at = share.responded_at
    session.add(share)
    await session.flush()
    await session.refresh(share)

    return IncomingFlowShareRead(
        id=share.id,
        flow_id=share.flow_id,
        flow_name=flow_name,
        owner_user_id=share.owner_user_id,
        owner_username=owner_username,
        permission=share.permission,
        status=share.status,
        created_at=share.created_at,
        responded_at=share.responded_at,
    )


@router.post("/batch/", response_model=list[FlowRead], status_code=201)
async def create_flows(
    *,
    session: DbSession,
    flow_list: FlowListCreate,
    current_user: CurrentActiveUser,
):
    """Create multiple new flows."""
    # Guard against duplicate IDs up-front so callers get a clean 422 instead
    # of an unhandled DB IntegrityError.  Use upload_file() for upsert semantics.
    requested_ids = [f.id for f in flow_list.flows if f.id is not None]
    if requested_ids:
        existing_ids = (await session.exec(select(Flow.id).where(col(Flow.id).in_(requested_ids)))).all()
        if existing_ids:
            conflict = ", ".join(str(i) for i in existing_ids)
            msg = (
                f"Flow(s) with the following IDs already exist: {conflict}. "
                "Use the update endpoint or upload_file() for upsert semantics."
            )
            raise HTTPException(status_code=422, detail=msg)

    db_flows = []
    for flow in flow_list.flows:
        flow.user_id = current_user.id
        # Exclude id from model_validate (same reasoning as _new_flow) and apply separately.
        db_flow = Flow.model_validate(flow.model_dump(exclude={"id"}))
        if flow.id is not None:
            db_flow.id = flow.id
        session.add(db_flow)
        db_flows.append(db_flow)

    await session.flush()
    for db_flow in db_flows:
        await session.refresh(db_flow)

    return [FlowRead.model_validate(db_flow, from_attributes=True) for db_flow in db_flows]


@router.post("/upload/", response_model=list[FlowRead], status_code=201)
async def upload_file(
    *,
    session: DbSession,
    file: Annotated[UploadFile | None, File()] = None,
    current_user: CurrentActiveUser,
    folder_id: UUID | None = None,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
):
    """Upload flows from a JSON or ZIP file (upsert semantics for flows with stable IDs)."""
    if file is None:
        raise HTTPException(status_code=400, detail="No file provided")

    contents = await file.read()

    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")

    if zipfile.is_zipfile(io.BytesIO(contents)):
        try:
            flows_data = await extract_flows_from_zip(contents)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if not flows_data:
            raise HTTPException(status_code=400, detail="No valid flow JSON files found in the ZIP")
        data = {"flows": flows_data}
    else:
        try:
            data = orjson.loads(contents)
        except orjson.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON file: {e}") from e

    # Normalise code fields: if exported with code-as-lines format, rejoin to
    # strings before creating the Pydantic models so the DB always stores strings.
    if "flows" in data:
        data = {**data, "flows": [normalize_code_for_import(f) for f in data["flows"]]}
        flow_list = FlowListCreate(**data)
    else:
        flow_list = FlowListCreate(flows=[FlowCreate(**normalize_code_for_import(data))])

    # TODO: Full-version import is planned as a follow-up feature.
    # When implemented, extract raw flow dicts here to read embedded "version"
    # arrays and create FlowVersion entries for each imported flow.

    try:
        return await _upsert_flow_list(
            session=session,
            flows=flow_list.flows,
            current_user=current_user,
            storage_service=storage_service,
            folder_id=folder_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise _handle_unique_constraint_error(e) from e


@router.delete("/")
async def delete_multiple_flows(
    flow_ids: list[UUID],
    user: CurrentActiveUser,
    db: DbSession,
):
    """Delete multiple flows by their IDs."""
    try:
        flows_to_delete = (
            await db.exec(select(Flow).where(col(Flow.id).in_(flow_ids)).where(Flow.user_id == user.id))
        ).all()
        for flow in flows_to_delete:
            await cascade_delete_flow(db, flow.id)

        await db.flush()
        return {"deleted": len(flows_to_delete)}
    except Exception as exc:
        import logging as _logging

        _logging.getLogger(__name__).exception("Error deleting multiple flows")
        raise HTTPException(status_code=500, detail="An internal error occurred while deleting flows.") from exc


@router.post("/download/", status_code=200)
async def download_multiple_file(
    flow_ids: list[UUID],
    user: CurrentActiveUser,
    db: DbSession,
):
    """Download all flows as a zip file."""
    # TODO: Full-version download (include_version parameter) is planned as a follow-up feature.
    # When implemented, add an include_version: bool = False parameter and embed version
    # entries in each flow dict using get_flow_version_list and strip_version_data.
    flows = (await db.exec(select(Flow).where(and_(Flow.user_id == user.id, Flow.id.in_(flow_ids))))).all()  # type: ignore[attr-defined]

    if not flows:
        raise HTTPException(status_code=404, detail="No flows found.")

    return _build_flows_download_response(flows)


# 5 minutes
_STARTER_FLOWS_TTL_SECONDS: float = 300.0
_starter_flows_cache: ThreadingInMemoryCache[threading.RLock] = ThreadingInMemoryCache(
    max_size=1,
    expiration_time=int(_STARTER_FLOWS_TTL_SECONDS),
)
_starter_flows_lock = asyncio.Lock()


@router.get("/basic_examples/", response_model=list[FlowRead], status_code=200)
async def read_basic_examples(
    *,
    session: DbSession,
):
    """Retrieve a list of basic example flows."""
    cached_response = _starter_flows_cache.get("starter_flows")
    if cached_response is not CACHE_MISS:
        return cached_response

    async with _starter_flows_lock:
        cached_response = _starter_flows_cache.get("starter_flows")
        if cached_response is not CACHE_MISS:
            return cached_response

        try:
            starter_folder = (await session.exec(select(Folder).where(Folder.name == STARTER_FOLDER_NAME))).first()

            if not starter_folder:
                return []

            all_starter_folder_flows = (
                await session.exec(select(Flow).where(Flow.folder_id == starter_folder.id))
            ).all()

            flow_reads = [FlowRead.model_validate(flow, from_attributes=True) for flow in all_starter_folder_flows]
            response = compress_response(flow_reads)
            _starter_flows_cache.set("starter_flows", response)

        except Exception as e:
            import logging as _logging

            _logging.getLogger(__name__).exception("Error loading basic examples")
            raise HTTPException(status_code=500, detail="An internal error occurred while loading examples.") from e
        else:
            return response


@router.post("/expand/", status_code=200, dependencies=[Depends(get_current_active_user)], include_in_schema=False)
async def expand_compact_flow_endpoint(
    compact_data: dict,
):
    """Expand a compact flow format (minimal nodes/edges) to the full flow format."""
    from lfx.interface.components import component_cache, get_and_cache_all_types_dict

    from langflow.processing.expand_flow import expand_compact_flow

    # Ensure component cache is loaded
    if component_cache.all_types_dict is None:
        settings_service = get_settings_service()
        await get_and_cache_all_types_dict(settings_service)

    if component_cache.all_types_dict is None:
        raise HTTPException(status_code=500, detail="Component cache not initialized")

    try:
        return expand_compact_flow(compact_data, component_cache.all_types_dict)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

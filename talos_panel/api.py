import asyncio
import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from talos_panel.auth import record_audit, require_csrf, require_user
from talos_panel.config import get_settings
from talos_panel.db import get_session
from talos_panel.install_service import InstallationManager
from talos_panel.installer import ArtifactResolver, InstallationError
from talos_panel.models import (
    DesiredState,
    InstallationJob,
    InstallationState,
    MinecraftServer,
    ServerMember,
    ServerRole,
    ServerType,
)
from talos_panel.permissions import accessible_servers, require_server_access
from talos_panel.runtime import DockerRuntime
from talos_panel.schemas import (
    InstallationCreate,
    InstallationRead,
    RuntimeStatus,
    ServerCreate,
    ServerDelete,
    ServerRead,
    ServerSettingsRead,
    ServerSettingsUpdate,
    VersionList,
)
from talos_panel.server_lifecycle import archive_server_directory
from talos_panel.server_settings import (
    ServerProperties,
    ServerSettingsError,
    read_server_properties,
    write_server_properties,
)

router = APIRouter(prefix="/servers", tags=["servers"])


def get_runtime(request: Request) -> DockerRuntime:
    return request.app.state.runtime


def get_installation_manager(request: Request) -> InstallationManager:
    return request.app.state.installation_manager


@router.post("", response_model=ServerRead, status_code=status.HTTP_201_CREATED)
async def create_server(
    request: Request,
    payload: ServerCreate,
    x_csrf_token: str = Header(),
    session: AsyncSession = Depends(get_session),
    runtime: DockerRuntime = Depends(get_runtime),
) -> MinecraftServer:
    user = require_user(request)
    require_csrf(request, x_csrf_token)
    server = MinecraftServer(**payload.model_dump(exclude={"settings"}))
    session.add(server)
    try:
        await session.flush()
        root = await runtime.prepare_directory(server.id)
        await asyncio.to_thread(write_server_properties, root, payload.settings)
        session.add(ServerMember(server_id=server.id, user_id=user.id, role=ServerRole.OWNER))
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Host port is already assigned") from exc
    except ServerSettingsError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.refresh(server)
    await record_audit(request, "server.create", server_id=server.id, details=server.name)
    return server


@router.get("", response_model=list[ServerRead])
async def list_servers(
    request: Request, session: AsyncSession = Depends(get_session)
) -> list[MinecraftServer]:
    return await accessible_servers(session, require_user(request))


@router.get("/{server_id}", response_model=ServerRead)
async def get_server(
    request: Request, server_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> MinecraftServer:
    return await require_server_access(session, require_user(request), server_id)


@router.get("/{server_id}/settings", response_model=ServerSettingsRead)
async def get_server_settings(
    request: Request,
    server_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    runtime: DockerRuntime = Depends(get_runtime),
) -> ServerSettingsRead:
    server = await require_server_access(session, require_user(request), server_id)
    try:
        properties = await asyncio.to_thread(read_server_properties, runtime.data_path(server.id))
    except ServerSettingsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ServerSettingsRead(
        **properties.model_dump(), memory_mb=server.memory_mb, host_port=server.host_port
    )


@router.put("/{server_id}/settings", response_model=ServerSettingsRead)
async def update_server_settings(
    request: Request,
    server_id: uuid.UUID,
    payload: ServerSettingsUpdate,
    x_csrf_token: str = Header(),
    session: AsyncSession = Depends(get_session),
    runtime: DockerRuntime = Depends(get_runtime),
) -> ServerSettingsRead:
    require_csrf(request, x_csrf_token)
    server = await require_server_access(session, require_user(request), server_id, owner=True)
    properties = ServerProperties.model_validate(
        payload.model_dump(exclude={"memory_mb", "host_port"})
    )
    server.memory_mb = payload.memory_mb
    server.host_port = payload.host_port
    try:
        await session.flush()
        await asyncio.to_thread(write_server_properties, runtime.data_path(server.id), properties)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Host port is already assigned") from exc
    except ServerSettingsError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit(request, "server.settings_update", server_id=server.id)
    return ServerSettingsRead(**payload.model_dump())


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(
    request: Request,
    server_id: uuid.UUID,
    payload: ServerDelete,
    x_csrf_token: str = Header(),
    session: AsyncSession = Depends(get_session),
    runtime: DockerRuntime = Depends(get_runtime),
) -> Response:
    require_csrf(request, x_csrf_token)
    server = await require_server_access(session, require_user(request), server_id, owner=True)
    if payload.confirmation != server.name:
        raise HTTPException(status_code=422, detail="Enter the exact server name to confirm")
    server_name = server.name
    await session.delete(server)
    await session.flush()
    try:
        await runtime.remove(server)
        archived = await asyncio.to_thread(
            archive_server_directory, get_settings().minecraft_data_root, server.id
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await record_audit(
        request,
        "server.delete",
        server_reference_id=server.id,
        server_name=server_name,
        details=f"{server.id}:{server_name}:files_archived={archived is not None}",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{server_id}/start", response_model=RuntimeStatus)
async def start_server(
    request: Request,
    server_id: uuid.UUID,
    x_csrf_token: str = Header(),
    session: AsyncSession = Depends(get_session),
    runtime: DockerRuntime = Depends(get_runtime),
) -> RuntimeStatus:
    require_csrf(request, x_csrf_token)
    server = await require_server_access(session, require_user(request), server_id)
    if server.installation_state is not InstallationState.COMPLETED:
        raise HTTPException(status_code=409, detail="Server installation is not complete")
    container_id, runtime_state = await runtime.start(server)
    server.container_id = container_id
    server.desired_state = DesiredState.RUNNING
    await session.commit()
    await record_audit(request, "server.start", server_id=server.id)
    return RuntimeStatus(server_id=server.id, state=runtime_state, container_id=container_id)


@router.get("/types/{server_type}/versions", response_model=VersionList)
async def list_versions(server_type: ServerType) -> VersionList:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            timeout=settings.download_timeout_seconds,
            headers={"User-Agent": settings.download_user_agent},
        ) as client:
            versions = await ArtifactResolver(client).versions(server_type)
    except InstallationError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    return VersionList(server_type=server_type, versions=versions)


@router.post(
    "/{server_id}/install", response_model=InstallationRead, status_code=status.HTTP_202_ACCEPTED
)
async def install_server(
    request: Request,
    server_id: uuid.UUID,
    payload: InstallationCreate,
    x_csrf_token: str = Header(),
    session: AsyncSession = Depends(get_session),
    manager: InstallationManager = Depends(get_installation_manager),
) -> InstallationJob:
    require_csrf(request, x_csrf_token)
    if not payload.eula_accepted:
        raise HTTPException(status_code=422, detail="Minecraft EULA acceptance is required")
    server = await require_server_access(session, require_user(request), server_id, owner=True)
    active = await session.scalar(
        select(InstallationJob).where(
            InstallationJob.server_id == server.id,
            InstallationJob.state.not_in([InstallationState.COMPLETED, InstallationState.FAILED]),
        )
    )
    if active:
        return active
    if server.installation_state is InstallationState.COMPLETED:
        raise HTTPException(status_code=409, detail="Server is already installed")
    job = InstallationJob(
        server_id=server.id,
        requested_version=server.game_version,
        state=InstallationState.QUEUED,
        eula_accepted_at=datetime.now(UTC),
    )
    server.installation_state = InstallationState.QUEUED
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await manager.enqueue(job.id)
    await record_audit(request, "server.install", server_id=server.id)
    return job


@router.get("/{server_id}/installation", response_model=InstallationRead)
async def installation_status(
    request: Request, server_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> InstallationJob:
    await require_server_access(session, require_user(request), server_id)
    job = await session.scalar(
        select(InstallationJob)
        .where(InstallationJob.server_id == server_id)
        .order_by(InstallationJob.created_at.desc())
        .limit(1)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Installation has not been requested")
    return job


@router.post("/{server_id}/stop", response_model=RuntimeStatus)
async def stop_server(
    request: Request,
    server_id: uuid.UUID,
    x_csrf_token: str = Header(),
    session: AsyncSession = Depends(get_session),
    runtime: DockerRuntime = Depends(get_runtime),
) -> RuntimeStatus:
    require_csrf(request, x_csrf_token)
    server = await require_server_access(session, require_user(request), server_id)
    container_id, runtime_state = await runtime.stop(server)
    server.container_id = container_id
    server.desired_state = DesiredState.STOPPED
    await session.commit()
    await record_audit(request, "server.stop", server_id=server.id)
    return RuntimeStatus(server_id=server.id, state=runtime_state, container_id=container_id)


@router.post("/{server_id}/restart", response_model=RuntimeStatus)
async def restart_server(
    request: Request,
    server_id: uuid.UUID,
    x_csrf_token: str = Header(),
    session: AsyncSession = Depends(get_session),
    runtime: DockerRuntime = Depends(get_runtime),
) -> RuntimeStatus:
    require_csrf(request, x_csrf_token)
    server = await require_server_access(session, require_user(request), server_id)
    if server.installation_state is not InstallationState.COMPLETED:
        raise HTTPException(status_code=409, detail="Server installation is not complete")
    container_id, runtime_state = await runtime.restart(server)
    server.container_id = container_id
    server.desired_state = DesiredState.RUNNING
    await session.commit()
    await record_audit(request, "server.restart", server_id=server.id)
    return RuntimeStatus(server_id=server.id, state=runtime_state, container_id=container_id)


@router.get("/{server_id}/status", response_model=RuntimeStatus)
async def server_status(
    request: Request,
    server_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    runtime: DockerRuntime = Depends(get_runtime),
) -> RuntimeStatus:
    server = await require_server_access(session, require_user(request), server_id)
    snapshot = await runtime.snapshot(server)
    return RuntimeStatus(server_id=server.id, **snapshot.__dict__)

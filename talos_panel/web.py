import asyncio
import re
import shutil
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from talos_panel.auth import load_identity, record_audit, require_admin, require_csrf, require_user
from talos_panel.avatar_service import AvatarError, get_player_avatar
from talos_panel.backup_service import (
    BackupError,
    create_backup,
    delete_backup,
    resolve_backup_file,
    restore_backup,
)
from talos_panel.config import get_settings
from talos_panel.db import SessionFactory, get_session
from talos_panel.file_service import (
    FileServiceError,
    archive_path,
    create_directory,
    create_directory_archive,
    list_directory,
    read_text_file,
    resolve_server_path,
    set_plugin_enabled,
    store_upload,
    write_text_file,
)
from talos_panel.i18n import (
    LANGUAGE_COOKIE,
    SUPPORTED_LANGUAGES,
    language_from_request,
    template_context,
    translate,
)
from talos_panel.install_service import InstallationManager
from talos_panel.installer import (
    ArtifactResolver,
    InstallationError,
    JarDownloader,
    java_version_for,
)
from talos_panel.minecraft_status import MinecraftStatusError, query_minecraft_status
from talos_panel.models import (
    AuditEvent,
    Backup,
    DesiredState,
    InstallationJob,
    InstallationState,
    MetricSample,
    MinecraftServer,
    ServerMember,
    ServerRole,
    ServerType,
    ServerUpdate,
    User,
    UserRole,
)
from talos_panel.permissions import accessible_servers, can_manage_server, require_server_access
from talos_panel.player_service import load_player_profiles, validate_player_name
from talos_panel.runtime import DockerRuntime, normalize_console_command
from talos_panel.schemas import ServerCreate
from talos_panel.server_lifecycle import archive_server_directory
from talos_panel.server_settings import (
    ServerProperties,
    ServerSettingsError,
    read_server_properties,
    write_server_properties,
)

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="talos_panel/templates", context_processors=[template_context])
PLAYER_LIST_PATTERN = re.compile(
    r"There are (?P<online>\d+) of a max of (?P<maximum>\d+) players online:?(?P<names>[^\r\n]*)"
)


def ui_message(request: Request, text: str) -> str:
    return translate(text, language_from_request(request))


@router.post("/language/{language}")
async def set_language(request: Request, language: str, next_path: str = Form("/")):
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=404, detail="Unsupported language")
    if not next_path.startswith("/") or next_path.startswith("//"):
        next_path = "/"
    response = RedirectResponse(next_path, status_code=303)
    response.set_cookie(
        LANGUAGE_COOKIE,
        language,
        max_age=365 * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=get_settings().secure_cookies,
        path="/",
    )
    return response


def player_snapshot(logs: str) -> tuple[int | None, int | None, list[str]]:
    matches = list(PLAYER_LIST_PATTERN.finditer(logs))
    if not matches:
        return None, None, []
    match = matches[-1]
    names = [name.strip() for name in match.group("names").split(",") if name.strip()]
    return int(match.group("online")), int(match.group("maximum")), names


def minecraft_is_ready(runtime_state: str, logs: str) -> bool:
    return runtime_state == "running" and (
        "Done (" in logs or 'For help, type "help"' in logs
    )


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, session: AsyncSession = Depends(get_session)):
    servers = await accessible_servers(session, require_user(request))
    cards = [{"server": server, "runtime_state": "loading"} for server in servers]
    return templates.TemplateResponse(request, "index.html", {"cards": cards})


@router.get("/servers/{server_id}/summary")
async def server_summary(
    request: Request, server_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    server = await require_server_access(session, require_user(request), server_id)
    runtime: DockerRuntime = request.app.state.runtime
    try:
        snapshot = await runtime.status_snapshot(server)
    except Exception:
        return JSONResponse({"runtime_state": "error", "minecraft_ready": False})
    payload = {
        "runtime_state": snapshot.state,
        "installation_state": server.installation_state.value if server.installation_state else None,
        "started_at": snapshot.started_at.isoformat() if snapshot.started_at else None,
        "minecraft_ready": False,
        "players_online": None,
        "players_max": None,
        "ping_ms": None,
        "motd": None,
        "reported_version": None,
    }
    if snapshot.state != "running":
        return JSONResponse(payload)
    settings = get_settings()
    try:
        minecraft = await query_minecraft_status(
            settings.minecraft_status_host,
            server.host_port,
            settings.minecraft_status_timeout_seconds,
        )
    except MinecraftStatusError:
        return JSONResponse(payload)
    payload.update(
        {
            "minecraft_ready": True,
            "players_online": minecraft.online,
            "players_max": minecraft.maximum,
            "ping_ms": minecraft.latency_ms,
            "motd": minecraft.motd,
            "reported_version": minecraft.version_name,
        }
    )
    return JSONResponse(payload)


@router.get("/servers/new", response_class=HTMLResponse)
async def new_server(request: Request):
    return templates.TemplateResponse(request, "new_server.html", {})


@router.get("/servers/version-options", response_class=HTMLResponse)
async def version_options(request: Request, server_type: ServerType):
    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            timeout=settings.download_timeout_seconds,
            headers={"User-Agent": settings.download_user_agent},
        ) as client:
            versions = await ArtifactResolver(client).versions(server_type)
    except InstallationError:
        versions = []
    return templates.TemplateResponse(request, "version_options.html", {"versions": versions})


@router.post("/servers")
async def create_server(
    request: Request,
    name: str = Form(),
    server_type: ServerType = Form(),
    game_version: str = Form(),
    memory_mb: int = Form(),
    host_port: int = Form(),
    motd: str = Form(min_length=1, max_length=100),
    gamemode: str = Form(pattern=r"^(survival|creative|adventure|spectator)$"),
    difficulty: str = Form(pattern=r"^(peaceful|easy|normal|hard)$"),
    max_players: int = Form(ge=1, le=1000),
    whitelist: bool = Form(False),
    pvp: bool = Form(False),
    allow_flight: bool = Form(False),
    view_distance: int = Form(ge=2, le=32),
    simulation_distance: int = Form(ge=2, le=32),
    eula_accepted: bool = Form(False),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    user = require_user(request)
    require_csrf(request, csrf_token)
    if not eula_accepted:
        raise HTTPException(status_code=422, detail="Minecraft EULA acceptance is required")
    properties = ServerProperties(
        motd=motd,
        gamemode=gamemode,
        difficulty=difficulty,
        max_players=max_players,
        whitelist=whitelist,
        pvp=pvp,
        allow_flight=allow_flight,
        view_distance=view_distance,
        simulation_distance=simulation_distance,
    )
    payload = ServerCreate(
        name=name,
        server_type=server_type,
        game_version=game_version,
        memory_mb=memory_mb,
        host_port=host_port,
        settings=properties,
    )
    runtime: DockerRuntime = request.app.state.runtime
    manager: InstallationManager = request.app.state.installation_manager
    server = MinecraftServer(
        **payload.model_dump(exclude={"settings"}),
        installation_state=InstallationState.QUEUED,
    )
    session.add(server)
    try:
        await session.flush()
        root = await runtime.prepare_directory(server.id)
        await asyncio.to_thread(write_server_properties, root, properties)
        job = InstallationJob(
            server_id=server.id,
            requested_version=server.game_version,
            state=InstallationState.QUEUED,
            eula_accepted_at=datetime.now(UTC),
        )
        session.add(job)
        session.add(ServerMember(server_id=server.id, user_id=user.id, role=ServerRole.OWNER))
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Host port is already assigned") from exc
    except ServerSettingsError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await manager.enqueue(job.id)
    await record_audit(request, "server.create", server_id=server.id, details=server.name)
    return RedirectResponse(f"/servers/{server.id}", status_code=303)


async def _server_and_job(server_id: uuid.UUID, session: AsyncSession, user, *, owner=False):
    server = await require_server_access(session, user, server_id, owner=owner)
    job = await session.scalar(
        select(InstallationJob)
        .where(InstallationJob.server_id == server_id)
        .order_by(InstallationJob.created_at.desc())
        .limit(1)
    )
    return server, job


async def _require_stopped(
    runtime: DockerRuntime,
    server: MinecraftServer,
    message: str = "Stop the server before changing its files",
) -> None:
    _, state = await runtime.status(server)
    if state == "running":
        raise HTTPException(status_code=409, detail=message)


def _file_error(exc: FileServiceError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/servers/{server_id}", response_class=HTMLResponse)
async def server_detail(
    request: Request, server_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    server, job = await _server_and_job(server_id, session, require_user(request))
    runtime: DockerRuntime = request.app.state.runtime
    container_id, runtime_state = await runtime.status(server)
    can_manage = await can_manage_server(session, request.state.user, server.id)
    settings_error = None
    try:
        properties = await asyncio.to_thread(
            read_server_properties, runtime.data_path(server.id)
        )
    except ServerSettingsError as exc:
        properties = ServerProperties()
        settings_error = str(exc)
    message = request.query_params.get("message")
    users = []
    memberships = []
    member_rows = []
    backups = []
    updates = []
    metrics = []
    disk = None
    runtime_events = []
    if can_manage:
        backups = list(
            await session.scalars(
                select(Backup)
                .where(Backup.server_id == server.id)
                .order_by(Backup.created_at.desc())
            )
        )
        updates = list(
            await session.scalars(
                select(ServerUpdate)
                .where(ServerUpdate.server_id == server.id)
                .order_by(ServerUpdate.created_at.desc())
                .limit(20)
            )
        )
        metrics = list(
            await session.scalars(
                select(MetricSample)
                .where(
                    MetricSample.server_id == server.id,
                    MetricSample.recorded_at >= datetime.now(UTC) - timedelta(hours=24),
                )
                .order_by(MetricSample.recorded_at)
            )
        )
        try:
            disk_usage = await asyncio.to_thread(shutil.disk_usage, runtime.data_path(server.id))
            disk = {"free": disk_usage.free, "total": disk_usage.total}
        except OSError:
            disk = None
        runtime_events = list(
            await session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.server_id == server.id,
                    AuditEvent.action.in_(
                        [
                            "server.start",
                            "server.stop",
                            "server.restart",
                            "server.crash_detected",
                            "server.auto_restart",
                            "server.auto_restart_failed",
                        ]
                    ),
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(30)
            )
        )
    if request.state.user.role is UserRole.ADMIN:
        users = list(await session.scalars(select(User).order_by(User.email)))
        memberships = list(
            await session.scalars(select(ServerMember).where(ServerMember.server_id == server.id))
        )
        users_by_id = {user.id: user for user in users}
        member_rows = [
            (users_by_id[member.user_id], member)
            for member in memberships
            if member.user_id in users_by_id
        ]
    return templates.TemplateResponse(
        request,
        "server_detail.html",
        {
            "server": server,
            "job": job,
            "runtime_state": runtime_state,
            "container_id": container_id,
            "message": message,
            "users": users,
            "memberships": memberships,
            "member_rows": member_rows,
            "backups": backups,
            "updates": updates,
            "metrics": metrics,
            "metric_data": [
                {
                    "time": sample.recorded_at.isoformat(),
                    "cpu": sample.cpu_percent,
                    "memory": sample.memory_bytes,
                    "players": sample.players_online,
                    "state": sample.runtime_state,
                }
                for sample in metrics
            ],
            "disk": disk,
            "runtime_events": runtime_events,
            "can_manage": can_manage,
            "properties": properties,
            "settings_error": settings_error,
        },
    )


@router.get("/servers/{server_id}/installation-fragment", response_class=HTMLResponse)
async def installation_fragment(
    request: Request, server_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    server, job = await _server_and_job(server_id, session, require_user(request))
    return templates.TemplateResponse(request, "installation.html", {"server": server, "job": job})


@router.post("/servers/{server_id}/start")
async def start_server_ui(
    request: Request,
    server_id: uuid.UUID,
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request))
    if server.installation_state is not InstallationState.COMPLETED:
        raise HTTPException(status_code=409, detail="Server installation is not complete")
    runtime: DockerRuntime = request.app.state.runtime
    container_id, _ = await runtime.start(server)
    server.container_id = container_id
    server.desired_state = DesiredState.RUNNING
    await session.commit()
    await record_audit(request, "server.start", server_id=server.id)
    if request.headers.get("X-Talos-Async") == "true":
        return JSONResponse({"ok": True, "message": ui_message(request, "Server started")})
    return RedirectResponse(f"/servers/{server.id}?message=Server+started", status_code=303)


@router.post("/servers/{server_id}/stop")
async def stop_server_ui(
    request: Request,
    server_id: uuid.UUID,
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request))
    runtime: DockerRuntime = request.app.state.runtime
    server.desired_state = DesiredState.STOPPED
    await session.commit()
    try:
        await runtime.stop(server)
    except Exception:
        server.desired_state = DesiredState.RUNNING
        await session.commit()
        raise
    await record_audit(request, "server.stop", server_id=server.id)
    if request.headers.get("X-Talos-Async") == "true":
        return JSONResponse({"ok": True, "message": ui_message(request, "Server stopped")})
    return RedirectResponse(f"/servers/{server.id}?message=Server+stopped", status_code=303)


@router.post("/servers/{server_id}/restart")
async def restart_server_ui(
    request: Request,
    server_id: uuid.UUID,
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request))
    if server.installation_state is not InstallationState.COMPLETED:
        raise HTTPException(status_code=409, detail="Server installation is not complete")
    runtime: DockerRuntime = request.app.state.runtime
    container_id, _ = await runtime.restart(server)
    server.container_id = container_id
    server.desired_state = DesiredState.RUNNING
    await session.commit()
    await record_audit(request, "server.restart", server_id=server.id)
    if request.headers.get("X-Talos-Async") == "true":
        return JSONResponse({"ok": True, "message": ui_message(request, "Server restarted")})
    return RedirectResponse(f"/servers/{server.id}?message=Server+restarted", status_code=303)


@router.post("/servers/{server_id}/command")
async def server_command_ui(
    request: Request,
    server_id: uuid.UUID,
    command: str = Form(min_length=1, max_length=256),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request))
    runtime: DockerRuntime = request.app.state.runtime
    try:
        await runtime.send_command(server, command)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit(
        request,
        "server.command",
        server_id=server.id,
        details=normalize_console_command(command).split(maxsplit=1)[0],
    )
    if request.headers.get("X-Talos-Async") == "true":
        return JSONResponse({"ok": True, "message": ui_message(request, "Command sent")})
    return RedirectResponse(f"/servers/{server.id}?message=Command+sent", status_code=303)


@router.get("/servers/{server_id}/players")
async def server_players(
    request: Request, server_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    server, _ = await _server_and_job(server_id, session, require_user(request))
    runtime: DockerRuntime = request.app.state.runtime
    _, runtime_state = await runtime.status(server)
    online_names: list[str] = []
    online_count = None
    if runtime_state == "running":
        try:
            minecraft = await query_minecraft_status(
                get_settings().minecraft_status_host,
                server.host_port,
                get_settings().minecraft_status_timeout_seconds,
            )
            online_names = minecraft.sample_players
            online_count = minecraft.online
        except MinecraftStatusError:
            pass
    profiles = await asyncio.to_thread(
        load_player_profiles, runtime.data_path(server.id), online_names
    )
    can_manage = await can_manage_server(session, request.state.user, server.id)
    return JSONResponse(
        {
            "runtime_state": runtime_state,
            "online_count": online_count,
            "online_list_complete": online_count == len(online_names) if online_count is not None else False,
            "can_manage": can_manage,
            "players": [
                {
                    "name": player.name,
                    "uuid": player.player_uuid,
                    "online": player.online,
                    "last_active": player.last_active.isoformat() if player.last_active else None,
                    "play_time_seconds": player.play_time_seconds,
                    "operator": player.operator,
                    "whitelisted": player.whitelisted,
                    "banned": player.banned,
                }
                for player in profiles
            ],
        }
    )


@router.get("/servers/{server_id}/players/{player_uuid}/avatar")
async def player_avatar(
    request: Request,
    server_id: uuid.UUID,
    player_uuid: str,
    session: AsyncSession = Depends(get_session),
):
    await require_server_access(session, require_user(request), server_id)
    settings = get_settings()
    try:
        avatar = await get_player_avatar(
            player_uuid,
            settings.minecraft_data_root / "cache" / "player-avatars",
            settings.player_avatar_cache_hours,
            settings.player_avatar_timeout_seconds,
            settings.max_player_skin_bytes,
        )
    except AvatarError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        avatar,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=86400"},
    )


PLAYER_ACTION_COMMANDS = {
    "kick": "kick {name}",
    "ban": "ban {name}",
    "pardon": "pardon {name}",
    "whitelist_add": "whitelist add {name}",
    "whitelist_remove": "whitelist remove {name}",
    "op": "op {name}",
    "deop": "deop {name}",
}


@router.post("/servers/{server_id}/players/{player_name}/action")
async def player_action(
    request: Request,
    server_id: uuid.UUID,
    player_name: str,
    action: str = Form(),
    reason: str = Form("", max_length=120),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request))
    if not await can_manage_server(session, request.state.user, server.id):
        raise HTTPException(status_code=403, detail="Owner access required")
    try:
        name = validate_player_name(player_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    command_template = PLAYER_ACTION_COMMANDS.get(action)
    if not command_template:
        raise HTTPException(status_code=422, detail="Unsupported player action")
    normalized_reason = reason.strip()
    if any(ord(character) < 32 for character in normalized_reason):
        raise HTTPException(status_code=422, detail="Reason contains unsupported characters")
    command = command_template.format(name=name)
    if action in {"kick", "ban"} and normalized_reason:
        command = f"{command} {normalized_reason}"
    runtime: DockerRuntime = request.app.state.runtime
    try:
        await runtime.send_command(server, command)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit(
        request,
        f"player.{action}",
        server_id=server.id,
        details=f"{name}: {normalized_reason}" if normalized_reason else name,
    )
    return JSONResponse({"ok": True, "message": ui_message(request, "Player action sent")})


@router.post("/servers/{server_id}/members")
async def add_server_member(
    request: Request,
    server_id: uuid.UUID,
    user_id: uuid.UUID = Form(),
    role: ServerRole = Form(),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_admin(request)
    require_csrf(request, csrf_token)
    server = await require_server_access(session, request.state.user, server_id)
    member = await session.scalar(
        select(ServerMember).where(
            ServerMember.server_id == server_id, ServerMember.user_id == user_id
        )
    )
    if member:
        member.role = role
    else:
        session.add(ServerMember(server_id=server_id, user_id=user_id, role=role))
    await session.commit()
    await record_audit(
        request, "server.member_set", server_id=server.id, details=f"{user_id}:{role.value}"
    )
    return RedirectResponse(f"/servers/{server.id}?message=Member+updated", status_code=303)


@router.post("/servers/{server_id}/members/{user_id}/remove")
async def remove_server_member(
    request: Request,
    server_id: uuid.UUID,
    user_id: uuid.UUID,
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_admin(request)
    require_csrf(request, csrf_token)
    server = await require_server_access(session, request.state.user, server_id)
    member = await session.scalar(
        select(ServerMember).where(
            ServerMember.server_id == server_id, ServerMember.user_id == user_id
        )
    )
    if member is not None:
        await session.delete(member)
        await session.commit()
        await record_audit(
            request, "server.member_remove", server_id=server.id, details=str(user_id)
        )
    return RedirectResponse(f"/servers/{server.id}#access", status_code=303)


async def _server_backup(
    session: AsyncSession, server_id: uuid.UUID, backup_id: uuid.UUID
) -> Backup:
    backup = await session.get(Backup, backup_id)
    if backup is None or backup.server_id != server_id:
        raise HTTPException(status_code=404, detail="Backup not found")
    return backup


@router.post("/servers/{server_id}/backups")
async def create_server_backup(
    request: Request,
    server_id: uuid.UUID,
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    runtime: DockerRuntime = request.app.state.runtime
    await _require_stopped(runtime, server, "Stop the server before creating a backup")
    settings = get_settings()
    try:
        artifact = await asyncio.to_thread(
            create_backup,
            runtime.data_path(server.id),
            settings.minecraft_data_root,
            server.id,
        )
    except BackupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    backup = Backup(
        server_id=server.id,
        file_name=artifact.path.name,
        size_bytes=artifact.size_bytes,
        checksum_sha256=artifact.checksum_sha256,
    )
    session.add(backup)
    try:
        await session.commit()
    except Exception:
        artifact.path.unlink(missing_ok=True)
        raise
    await record_audit(
        request, "server.backup_create", server_id=server.id, details=str(backup.id)
    )
    return RedirectResponse(f"/servers/{server.id}#backups", status_code=303)


@router.post("/servers/{server_id}/backup-policy")
async def update_backup_policy(
    request: Request,
    server_id: uuid.UUID,
    backup_enabled: bool = Form(False),
    backup_interval_hours: int = Form(ge=1, le=720),
    backup_retention: int = Form(ge=1, le=100),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    server.backup_enabled = backup_enabled
    server.backup_interval_hours = backup_interval_hours
    server.backup_retention = backup_retention
    server.next_backup_at = (
        datetime.now(UTC) + timedelta(hours=backup_interval_hours) if backup_enabled else None
    )
    await session.commit()
    await record_audit(request, "server.backup_policy", server_id=server.id)
    return RedirectResponse(f"/servers/{server.id}#backups", status_code=303)


@router.get("/servers/{server_id}/update-options")
async def server_update_options(
    request: Request, server_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            timeout=settings.download_timeout_seconds,
            headers={"User-Agent": settings.download_user_agent},
        ) as client:
            versions = await ArtifactResolver(client).versions(server.server_type)
    except (httpx.HTTPError, InstallationError):
        versions = []
    return JSONResponse(
        {
            "current": server.installed_version,
            "latest": versions[0] if versions else None,
            "versions": versions[:50],
        }
    )


@router.post("/servers/{server_id}/update")
async def update_server_version(
    request: Request,
    server_id: uuid.UUID,
    target_version: str = Form(min_length=2, max_length=32),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    runtime: DockerRuntime = request.app.state.runtime
    await _require_stopped(runtime, server, "Stop the server before updating it")
    if not server.installed_version:
        raise HTTPException(status_code=409, detail="Server is not installed")
    settings = get_settings()
    artifact = await asyncio.to_thread(
        create_backup, runtime.data_path(server.id), settings.minecraft_data_root, server.id
    )
    backup = Backup(
        server_id=server.id,
        file_name=artifact.path.name,
        size_bytes=artifact.size_bytes,
        checksum_sha256=artifact.checksum_sha256,
    )
    session.add(backup)
    await session.flush()
    update = ServerUpdate(
        server_id=server.id,
        backup_id=backup.id,
        from_version=server.installed_version,
        to_version=target_version,
        state="downloading",
    )
    session.add(update)
    await session.commit()
    try:
        async with httpx.AsyncClient(
            timeout=settings.download_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.download_user_agent},
        ) as client:
            resolved = await ArtifactResolver(client).resolve(server.server_type, target_version)

            async def progress(downloaded: int, total: int | None) -> None:
                return None

            await JarDownloader(client, settings).download(
                resolved, runtime.data_path(server.id) / "server.jar", progress
            )
        server.installed_version = resolved.version
        server.game_version = resolved.version
        server.java_version = resolved.java_version
        update.state = "completed"
        update.finished_at = datetime.now(UTC)
        await session.commit()
    except (InstallationError, httpx.HTTPError) as exc:
        update.state = "failed"
        update.error_message = str(exc)[:500]
        update.finished_at = datetime.now(UTC)
        await session.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit(
        request,
        "server.update",
        server_id=server.id,
        details=f"{update.from_version}->{update.to_version}",
    )
    return RedirectResponse(f"/servers/{server.id}#updates", status_code=303)


@router.post("/servers/{server_id}/updates/{update_id}/rollback")
async def rollback_server_update(
    request: Request,
    server_id: uuid.UUID,
    update_id: uuid.UUID,
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    runtime: DockerRuntime = request.app.state.runtime
    await _require_stopped(runtime, server, "Stop the server before rolling back")
    update = await session.get(ServerUpdate, update_id)
    if update is None or update.server_id != server.id or update.backup_id is None:
        raise HTTPException(status_code=404, detail="Update recovery point not found")
    backup = await _server_backup(session, server.id, update.backup_id)
    await asyncio.to_thread(
        restore_backup,
        runtime.data_path(server.id),
        get_settings().minecraft_data_root,
        server.id,
        backup.file_name,
        get_settings().max_backup_restore_bytes,
        backup.checksum_sha256,
    )
    server.installed_version = update.from_version
    server.game_version = update.from_version
    server.java_version = java_version_for(update.from_version)
    update.state = "rolled_back"
    await session.commit()
    await record_audit(request, "server.update_rollback", server_id=server.id)
    return RedirectResponse(f"/servers/{server.id}#updates", status_code=303)


@router.get("/servers/{server_id}/backups/{backup_id}/download")
async def download_server_backup(
    request: Request,
    server_id: uuid.UUID,
    backup_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    backup = await _server_backup(session, server.id, backup_id)
    try:
        path = await asyncio.to_thread(
            resolve_backup_file, get_settings().minecraft_data_root, server.id, backup.file_name
        )
    except BackupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, filename=backup.file_name, media_type="application/gzip")


@router.post("/servers/{server_id}/backups/{backup_id}/restore")
async def restore_server_backup(
    request: Request,
    server_id: uuid.UUID,
    backup_id: uuid.UUID,
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    backup = await _server_backup(session, server.id, backup_id)
    runtime: DockerRuntime = request.app.state.runtime
    await _require_stopped(runtime, server, "Stop the server before restoring a backup")
    settings = get_settings()
    try:
        safety_artifact = await asyncio.to_thread(
            create_backup,
            runtime.data_path(server.id),
            settings.minecraft_data_root,
            server.id,
        )
        safety_backup = Backup(
            server_id=server.id,
            file_name=safety_artifact.path.name,
            size_bytes=safety_artifact.size_bytes,
            checksum_sha256=safety_artifact.checksum_sha256,
        )
        session.add(safety_backup)
        await session.commit()
        await asyncio.to_thread(
            restore_backup,
            runtime.data_path(server.id),
            settings.minecraft_data_root,
            server.id,
            backup.file_name,
            settings.max_backup_restore_bytes,
            backup.checksum_sha256,
        )
    except BackupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit(
        request, "server.backup_restore", server_id=server.id, details=str(backup.id)
    )
    return RedirectResponse(f"/servers/{server.id}#backups", status_code=303)


@router.post("/servers/{server_id}/backups/{backup_id}/delete")
async def delete_server_backup(
    request: Request,
    server_id: uuid.UUID,
    backup_id: uuid.UUID,
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    backup = await _server_backup(session, server.id, backup_id)
    try:
        await asyncio.to_thread(
            delete_backup, get_settings().minecraft_data_root, server.id, backup.file_name
        )
    except BackupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.delete(backup)
    await session.commit()
    await record_audit(
        request, "server.backup_delete", server_id=server.id, details=str(backup.id)
    )
    return RedirectResponse(f"/servers/{server.id}#backups", status_code=303)


@router.post("/servers/{server_id}/settings")
async def update_server_settings_ui(
    request: Request,
    server_id: uuid.UUID,
    motd: str = Form(min_length=1, max_length=100),
    gamemode: str = Form(pattern=r"^(survival|creative|adventure|spectator)$"),
    difficulty: str = Form(pattern=r"^(peaceful|easy|normal|hard)$"),
    max_players: int = Form(ge=1, le=1000),
    whitelist: bool = Form(False),
    pvp: bool = Form(False),
    allow_flight: bool = Form(False),
    view_distance: int = Form(ge=2, le=32),
    simulation_distance: int = Form(ge=2, le=32),
    memory_mb: int = Form(ge=1024, le=32768),
    host_port: int = Form(ge=1024, le=65535),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    properties = ServerProperties(
        motd=motd,
        gamemode=gamemode,
        difficulty=difficulty,
        max_players=max_players,
        whitelist=whitelist,
        pvp=pvp,
        allow_flight=allow_flight,
        view_distance=view_distance,
        simulation_distance=simulation_distance,
    )
    profile_changed = server.memory_mb != memory_mb or server.host_port != host_port
    server.memory_mb = memory_mb
    server.host_port = host_port
    try:
        await session.flush()
        runtime: DockerRuntime = request.app.state.runtime
        await asyncio.to_thread(write_server_properties, runtime.data_path(server.id), properties)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Host port is already assigned") from exc
    except ServerSettingsError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit(request, "server.settings_update", server_id=server.id)
    message = "Settings saved. Restart the server to apply them."
    if profile_changed:
        message = "Settings saved. Restart will recreate the container for the new port or memory."
    if request.headers.get("X-Talos-Async") == "true":
        return JSONResponse(
            {
                "ok": True,
                "message": ui_message(request, message),
                "host_port": server.host_port,
                "memory_mb": server.memory_mb,
            }
        )
    return RedirectResponse(f"/servers/{server.id}?message=Settings+saved", status_code=303)


@router.post("/servers/{server_id}/restart-policy")
async def update_restart_policy(
    request: Request,
    server_id: uuid.UUID,
    auto_restart: bool = Form(False),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    server.auto_restart = auto_restart
    if not auto_restart:
        server.restart_failures = 0
    await session.commit()
    await record_audit(request, "server.restart_policy", server_id=server.id)
    return RedirectResponse(f"/servers/{server.id}#monitoring", status_code=303)


@router.post("/servers/{server_id}/delete")
async def delete_server_ui(
    request: Request,
    server_id: uuid.UUID,
    confirmation: str = Form(min_length=1, max_length=80),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    if confirmation != server.name:
        raise HTTPException(status_code=422, detail="Enter the exact server name to confirm")
    server_name = server.name
    runtime: DockerRuntime = request.app.state.runtime
    settings = get_settings()
    await session.delete(server)
    await session.flush()
    try:
        await runtime.remove(server)
        archived = await asyncio.to_thread(
            archive_server_directory, settings.minecraft_data_root, server.id
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await record_audit(
        request,
        "server.delete",
        details=f"{server.id}:{server_name}:files_archived={archived is not None}",
    )
    return RedirectResponse("/?message=Server+deleted", status_code=303)


@router.get("/servers/{server_id}/files")
async def server_files(
    request: Request,
    server_id: uuid.UUID,
    path: str = "",
    session: AsyncSession = Depends(get_session),
):
    server, _ = await _server_and_job(server_id, session, require_user(request))
    runtime: DockerRuntime = request.app.state.runtime
    try:
        entries = await asyncio.to_thread(list_directory, runtime.data_path(server.id), path)
    except FileServiceError as exc:
        raise _file_error(exc) from exc
    parent = ""
    if path:
        parts = path.rstrip("/").split("/")
        parent = "/".join(parts[:-1])
    return JSONResponse(
        {
            "path": path.strip("/"),
            "parent": parent,
            "entries": [entry.__dict__ for entry in entries],
        }
    )


@router.get("/servers/{server_id}/files/download")
async def download_server_file(
    request: Request,
    server_id: uuid.UUID,
    path: str,
    session: AsyncSession = Depends(get_session),
):
    server, _ = await _server_and_job(server_id, session, require_user(request))
    runtime: DockerRuntime = request.app.state.runtime
    try:
        file_path = await asyncio.to_thread(
            resolve_server_path, runtime.data_path(server.id), path, allow_root=False
        )
        if file_path.is_dir():
            archive, download_name = await asyncio.to_thread(
                create_directory_archive, runtime.data_path(server.id), path
            )
            return FileResponse(
                archive,
                filename=download_name,
                media_type="application/zip",
                background=BackgroundTask(archive.unlink, missing_ok=True),
            )
        if not file_path.is_file():
            raise FileServiceError("File or directory does not exist")
    except FileServiceError as exc:
        raise _file_error(exc) from exc
    return FileResponse(file_path, filename=file_path.name, media_type="application/octet-stream")


@router.get("/servers/{server_id}/files/text")
async def read_server_text_file(
    request: Request,
    server_id: uuid.UUID,
    path: str,
    session: AsyncSession = Depends(get_session),
):
    server, _ = await _server_and_job(server_id, session, require_user(request))
    runtime: DockerRuntime = request.app.state.runtime
    settings = get_settings()
    try:
        content = await asyncio.to_thread(
            read_text_file, runtime.data_path(server.id), path, settings.max_text_edit_bytes
        )
    except FileServiceError as exc:
        raise _file_error(exc) from exc
    return JSONResponse({"path": path, "content": content})


@router.post("/servers/{server_id}/files/upload")
async def upload_server_file(
    request: Request,
    server_id: uuid.UUID,
    parent: str = Form(""),
    upload: UploadFile = File(),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    runtime: DockerRuntime = request.app.state.runtime
    await _require_stopped(runtime, server)
    try:
        destination = await store_upload(
            runtime.data_path(server.id), parent, upload, get_settings().max_file_upload_bytes
        )
    except FileServiceError as exc:
        raise _file_error(exc) from exc
    relative = destination.relative_to(runtime.data_path(server.id)).as_posix()
    await record_audit(request, "server.file_upload", server_id=server.id, details=relative)
    return JSONResponse({"ok": True, "message": ui_message(request, "File uploaded")})


@router.post("/servers/{server_id}/files/mkdir")
async def create_server_directory(
    request: Request,
    server_id: uuid.UUID,
    parent: str = Form(""),
    name: str = Form(min_length=1, max_length=255),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    runtime: DockerRuntime = request.app.state.runtime
    await _require_stopped(runtime, server)
    try:
        destination = await asyncio.to_thread(
            create_directory, runtime.data_path(server.id), parent, name
        )
    except FileServiceError as exc:
        raise _file_error(exc) from exc
    relative = destination.relative_to(runtime.data_path(server.id)).as_posix()
    await record_audit(request, "server.directory_create", server_id=server.id, details=relative)
    return JSONResponse({"ok": True, "message": ui_message(request, "Directory created")})


@router.post("/servers/{server_id}/files/text")
async def save_server_text_file(
    request: Request,
    server_id: uuid.UUID,
    path: str = Form(),
    content: str = Form(),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    runtime: DockerRuntime = request.app.state.runtime
    await _require_stopped(runtime, server)
    try:
        await asyncio.to_thread(
            write_text_file,
            runtime.data_path(server.id),
            path,
            content,
            get_settings().max_text_edit_bytes,
        )
    except FileServiceError as exc:
        raise _file_error(exc) from exc
    await record_audit(request, "server.file_edit", server_id=server.id, details=path)
    return JSONResponse({"ok": True, "message": ui_message(request, "File saved")})


@router.post("/servers/{server_id}/files/delete")
async def delete_server_file(
    request: Request,
    server_id: uuid.UUID,
    path: str = Form(),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    runtime: DockerRuntime = request.app.state.runtime
    await _require_stopped(runtime, server)
    try:
        await asyncio.to_thread(archive_path, runtime.data_path(server.id), path)
    except FileServiceError as exc:
        raise _file_error(exc) from exc
    await record_audit(request, "server.file_delete", server_id=server.id, details=path)
    return JSONResponse({"ok": True, "message": ui_message(request, "Item moved to trash")})


@router.post("/servers/{server_id}/plugins/upload")
async def upload_plugin(
    request: Request,
    server_id: uuid.UUID,
    upload: UploadFile = File(),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    if server.server_type is not ServerType.PAPER:
        raise HTTPException(status_code=409, detail="Plugins are supported only for Paper")
    runtime: DockerRuntime = request.app.state.runtime
    await _require_stopped(runtime, server)
    plugins = runtime.data_path(server.id) / "plugins"
    await asyncio.to_thread(plugins.mkdir, parents=True, exist_ok=True)
    try:
        destination = await store_upload(
            runtime.data_path(server.id),
            "plugins",
            upload,
            get_settings().max_file_upload_bytes,
            plugin=True,
        )
    except FileServiceError as exc:
        raise _file_error(exc) from exc
    await record_audit(
        request, "server.plugin_upload", server_id=server.id, details=destination.name
    )
    return JSONResponse(
        {"ok": True, "message": ui_message(request, "Plugin uploaded; start the server to load it")}
    )


@router.post("/servers/{server_id}/plugins/toggle")
async def toggle_plugin(
    request: Request,
    server_id: uuid.UUID,
    path: str = Form(),
    enabled: bool = Form(),
    csrf_token: str = Form(),
    session: AsyncSession = Depends(get_session),
):
    require_csrf(request, csrf_token)
    server, _ = await _server_and_job(server_id, session, require_user(request), owner=True)
    if server.server_type is not ServerType.PAPER:
        raise HTTPException(status_code=409, detail="Plugins are supported only for Paper")
    runtime: DockerRuntime = request.app.state.runtime
    await _require_stopped(runtime, server)
    try:
        destination = await asyncio.to_thread(
            set_plugin_enabled, runtime.data_path(server.id), path, enabled
        )
    except FileServiceError as exc:
        raise _file_error(exc) from exc
    await record_audit(
        request, "server.plugin_toggle", server_id=server.id, details=destination.name
    )
    return JSONResponse({"ok": True, "message": ui_message(request, "Plugin state updated")})


@router.websocket("/servers/{server_id}/console")
async def server_console(websocket: WebSocket, server_id: uuid.UUID):
    origin = websocket.headers.get("origin")
    allowed_origins = {
        f"http://{websocket.headers.get('host')}",
        f"https://{websocket.headers.get('host')}",
    }
    if origin not in allowed_origins:
        await websocket.close(code=4403)
        return
    user, _ = await load_identity(websocket, get_settings())
    if user is None:
        await websocket.close(code=4401)
        return
    async with SessionFactory() as session:
        try:
            server = await require_server_access(session, user, server_id)
        except HTTPException:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        runtime: DockerRuntime = websocket.app.state.runtime
        settings = get_settings()
        previous = None
        try:
            while True:
                snapshot = await runtime.snapshot(server)
                minecraft = None
                if snapshot.state == "running":
                    try:
                        minecraft = await query_minecraft_status(
                            settings.minecraft_status_host,
                            server.host_port,
                            settings.minecraft_status_timeout_seconds,
                        )
                    except MinecraftStatusError:
                        minecraft = None
                logs = await runtime.logs(server)
                ready = minecraft is not None
                payload = {
                    "state": snapshot.state,
                    "ready": ready,
                    "logs": logs,
                    "started_at": snapshot.started_at.isoformat()
                    if snapshot.started_at
                    else None,
                    "cpu_percent": snapshot.cpu_percent,
                    "memory_bytes": snapshot.memory_bytes,
                    "memory_limit_bytes": snapshot.memory_limit_bytes,
                    "players_online": minecraft.online if minecraft else None,
                    "players_max": minecraft.maximum if minecraft else None,
                    "players": minecraft.sample_players if minecraft else [],
                }
                if payload != previous:
                    await websocket.send_json(payload)
                    previous = payload
                await asyncio.sleep(2)
        except WebSocketDisconnect:
            pass

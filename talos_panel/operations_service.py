import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from talos_panel.backup_service import BackupError, create_backup, delete_backup
from talos_panel.config import Settings
from talos_panel.minecraft_status import MinecraftStatusError, query_minecraft_status
from talos_panel.models import (
    AuditEvent,
    Backup,
    DesiredState,
    MetricSample,
    MinecraftServer,
)
from talos_panel.runtime import DockerRuntime

logger = logging.getLogger(__name__)


class OperationsManager:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker,
        runtime: DockerRuntime,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.runtime = runtime
        self.task: asyncio.Task | None = None
        self.stopping = asyncio.Event()

    async def start(self) -> None:
        self.task = asyncio.create_task(self._worker(), name="operations-worker")

    async def stop(self) -> None:
        self.stopping.set()
        if self.task:
            await self.task

    async def _worker(self) -> None:
        while not self.stopping.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("Operations maintenance pass failed")
            try:
                await asyncio.wait_for(
                    self.stopping.wait(), timeout=max(10, self.settings.operations_poll_seconds)
                )
            except TimeoutError:
                pass

    async def run_once(self) -> None:
        async with self.session_factory() as session:
            servers = list(await session.scalars(select(MinecraftServer)))
            for server in servers:
                await self._sample_and_recover(server, session)
                await self._scheduled_backup(server, session)
            cutoff = datetime.now(UTC) - timedelta(days=self.settings.metric_retention_days)
            await session.execute(delete(MetricSample).where(MetricSample.recorded_at < cutoff))
            await session.commit()

    async def _sample_and_recover(self, server: MinecraftServer, session) -> None:
        await self.runtime.use_panel_restart_policy(server)
        snapshot = await self.runtime.snapshot(server)
        players = None
        if snapshot.state == "running":
            try:
                status = await query_minecraft_status(
                    self.settings.minecraft_status_host,
                    server.host_port,
                    self.settings.minecraft_status_timeout_seconds,
                )
                players = status.online
            except MinecraftStatusError:
                pass
        session.add(
            MetricSample(
                server_id=server.id,
                runtime_state=snapshot.state,
                cpu_percent=round(snapshot.cpu_percent) if snapshot.cpu_percent is not None else None,
                memory_bytes=snapshot.memory_bytes,
                players_online=players,
            )
        )
        crashed = (
            server.last_runtime_state == "running"
            and snapshot.state not in {"running", "created"}
            and server.desired_state is DesiredState.RUNNING
        )
        if snapshot.state == "running":
            server.restart_failures = 0
        elif crashed:
            server.restart_failures += 1
            session.add(
                AuditEvent(
                    action="server.crash_detected",
                    server_id=server.id,
                    details=f"state={snapshot.state}; attempt={server.restart_failures}",
                )
            )
            if server.auto_restart and server.restart_failures <= self.settings.crash_restart_limit:
                try:
                    container_id, state = await self.runtime.start(server)
                    server.container_id = container_id
                    snapshot = snapshot.__class__(container_id=container_id, state=state)
                    session.add(
                        AuditEvent(
                            action="server.auto_restart",
                            server_id=server.id,
                            details=f"attempt={server.restart_failures}",
                        )
                    )
                except Exception as exc:
                    session.add(
                        AuditEvent(
                            action="server.auto_restart_failed",
                            server_id=server.id,
                            details=str(exc)[:500],
                        )
                    )
        server.last_runtime_state = snapshot.state

    async def _scheduled_backup(self, server: MinecraftServer, session) -> None:
        now = datetime.now(UTC)
        if not server.backup_enabled:
            return
        if server.next_backup_at is None:
            server.next_backup_at = now + timedelta(hours=server.backup_interval_hours)
            return
        if server.next_backup_at > now:
            return
        _, state = await self.runtime.status(server)
        saves_paused = False
        try:
            if state == "running":
                await self.runtime.send_command(server, "save-off")
                saves_paused = True
                await self.runtime.send_command(server, "save-all flush")
                await asyncio.sleep(1)
            artifact = await asyncio.to_thread(
                create_backup,
                self.runtime.data_path(server.id),
                self.settings.minecraft_data_root,
                server.id,
            )
        except BackupError as exc:
            session.add(
                AuditEvent(
                    action="backup.scheduled_failed",
                    server_id=server.id,
                    details=str(exc),
                )
            )
            server.next_backup_at = now + timedelta(hours=1)
            return
        finally:
            if saves_paused:
                try:
                    await self.runtime.send_command(server, "save-on")
                except RuntimeError:
                    logger.warning("Could not resume saves for server %s", server.id)
        session.add(
            Backup(
                server_id=server.id,
                file_name=artifact.path.name,
                size_bytes=artifact.size_bytes,
                checksum_sha256=artifact.checksum_sha256,
            )
        )
        server.next_backup_at = now + timedelta(hours=server.backup_interval_hours)
        existing = list(
            await session.scalars(
                select(Backup)
                .where(Backup.server_id == server.id)
                .order_by(Backup.created_at.desc())
            )
        )
        for expired in existing[max(0, server.backup_retention - 1) :]:
            try:
                await asyncio.to_thread(
                    delete_backup,
                    self.settings.minecraft_data_root,
                    server.id,
                    expired.file_name,
                )
            except BackupError:
                continue
            await session.delete(expired)

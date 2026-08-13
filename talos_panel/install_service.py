import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from talos_panel.config import Settings
from talos_panel.installer import InstallationError, java_version_for
from talos_panel.models import InstallationJob, InstallationState, MinecraftServer


class InstallationManager:
    """Prepares an ITZG server; its distribution is downloaded on first container start."""

    def __init__(self, settings: Settings, session_factory: async_sessionmaker) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self.worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        async with self.session_factory() as session:
            active = list(
                await session.scalars(
                    select(InstallationJob).where(
                        InstallationJob.state.not_in(
                            [InstallationState.COMPLETED, InstallationState.FAILED]
                        )
                    )
                )
            )
            for job in active:
                job.state = InstallationState.QUEUED
                job.error_code = None
                job.error_message = None
                await self.queue.put(job.id)
            await session.commit()
        self.worker_task = asyncio.create_task(self._worker(), name="installation-worker")

    async def stop(self) -> None:
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass

    async def enqueue(self, job_id: uuid.UUID) -> None:
        await self.queue.put(job_id)

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await self._run(job_id)
            finally:
                self.queue.task_done()

    async def _run(self, job_id: uuid.UUID) -> None:
        async with self.session_factory() as session:
            job = await session.get(InstallationJob, job_id)
            if job is None or job.state is InstallationState.COMPLETED:
                return
            server = await session.get(MinecraftServer, job.server_id)
            if server is None:
                return
            job.started_at = datetime.now(UTC)
            job.state = InstallationState.INSTALLING
            server.installation_state = InstallationState.INSTALLING
            await session.commit()
            try:
                root = self.settings.minecraft_data_root / "servers" / str(server.id)
                await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
                java_version = java_version_for(server.game_version)
                concrete_version = server.game_version
                job.installed_version = concrete_version
                job.java_version = java_version
                job.state = InstallationState.COMPLETED
                job.finished_at = datetime.now(UTC)
                server.installed_version = concrete_version
                server.java_version = java_version
                server.installation_state = InstallationState.COMPLETED
            except (OSError, InstallationError) as exc:
                job.state = InstallationState.FAILED
                job.error_code = getattr(exc, "code", "configuration_failed")
                job.error_message = str(exc)[:500]
                job.finished_at = datetime.now(UTC)
                server.installation_state = InstallationState.FAILED
            await session.commit()

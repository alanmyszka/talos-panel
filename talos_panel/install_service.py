import asyncio
import os
import tempfile
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from talos_panel.config import Settings
from talos_panel.installer import ArtifactResolver, InstallationError, JarDownloader
from talos_panel.models import InstallationJob, InstallationState, MinecraftServer


class InstallationManager:
    def __init__(self, settings: Settings, session_factory: async_sessionmaker) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self.worker_task: asyncio.Task | None = None
        self.client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=self.settings.download_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": self.settings.download_user_agent},
        )
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
        if self.client:
            await self.client.aclose()

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
        assert self.client is not None
        async with self.session_factory() as session:
            job = await session.get(InstallationJob, job_id)
            if job is None or job.state is InstallationState.COMPLETED:
                return
            server = await session.get(MinecraftServer, job.server_id)
            if server is None:
                return
            try:
                await self._set_state(job, server, InstallationState.RESOLVING, session)
                artifact = await ArtifactResolver(self.client).resolve(
                    server.server_type, job.requested_version
                )
                job.installed_version = artifact.version
                job.build_id = artifact.build_id
                job.java_version = artifact.java_version
                job.checksum_algorithm = artifact.checksum_algorithm
                job.expected_checksum = artifact.checksum
                job.total_bytes = artifact.size
                await self._set_state(job, server, InstallationState.DOWNLOADING, session)
                last_saved = 0

                async def progress(downloaded: int, total: int | None) -> None:
                    nonlocal last_saved
                    if downloaded - last_saved >= 1024 * 1024 or downloaded == total:
                        job.bytes_downloaded = downloaded
                        job.total_bytes = total
                        await session.commit()
                        last_saved = downloaded

                root = self.settings.minecraft_data_root / "servers" / str(server.id)
                actual = await JarDownloader(self.client, self.settings).download(
                    artifact, root / "server.jar", progress
                )
                job.actual_checksum = actual
                await self._set_state(job, server, InstallationState.VERIFYING, session)
                await self._set_state(job, server, InstallationState.INSTALLING, session)
                await asyncio.to_thread(self._write_eula, root)
                server.installed_version = artifact.version
                server.java_version = artifact.java_version
                job.finished_at = datetime.now(UTC)
                await self._set_state(job, server, InstallationState.COMPLETED, session)
            except InstallationError as exc:
                job.state = InstallationState.FAILED
                server.installation_state = InstallationState.FAILED
                job.error_code = exc.code
                job.error_message = exc.message
                job.finished_at = datetime.now(UTC)
                await session.commit()
            except Exception:
                job.state = InstallationState.FAILED
                server.installation_state = InstallationState.FAILED
                job.error_code = "internal_error"
                job.error_message = "Installation failed unexpectedly"
                job.finished_at = datetime.now(UTC)
                await session.commit()

    async def _set_state(self, job, server, state, session) -> None:
        job.state = state
        server.installation_state = state
        if job.started_at is None:
            job.started_at = datetime.now(UTC)
        await session.commit()

    @staticmethod
    def _write_eula(root) -> None:
        root.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".eula-", suffix=".tmp", dir=root)
        temporary = root / name
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write("eula=true\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, root / "eula.txt")
        finally:
            temporary.unlink(missing_ok=True)

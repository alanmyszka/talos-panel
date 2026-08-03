import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import docker
from docker.errors import APIError, NotFound

from talos_panel.config import Settings
from talos_panel.jvm_flags import startup_jvm_arguments
from talos_panel.models import MinecraftServer


@dataclass(frozen=True)
class RuntimeProfile:
    image: str
    jar_name: str = "server.jar"


@dataclass(frozen=True)
class RuntimeSnapshot:
    container_id: str | None
    state: str
    started_at: datetime | None = None
    cpu_percent: float | None = None
    memory_bytes: int | None = None
    memory_limit_bytes: int | None = None


SUPPORTED_JAVA_IMAGES = {
    8: "eclipse-temurin:8-jre",
    11: "eclipse-temurin:11-jre",
    16: "eclipse-temurin:16-jre",
    17: "eclipse-temurin:17-jre",
    21: "eclipse-temurin:21-jre",
    25: "eclipse-temurin:25-jre",
}


def normalize_console_command(command: str) -> str:
    normalized = command.strip()
    if normalized.startswith("/"):
        normalized = normalized[1:].lstrip()
    if not normalized or len(normalized) > 256:
        raise ValueError("Command must contain between 1 and 256 characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError("Command contains unsupported control characters")
    return normalized


def profile_for(server: MinecraftServer) -> RuntimeProfile:
    if server.java_version not in SUPPORTED_JAVA_IMAGES:
        raise ValueError("Server does not have a supported installed Java profile")
    return RuntimeProfile(image=SUPPORTED_JAVA_IMAGES[server.java_version])


class DockerRuntime:
    """The only component allowed to translate panel data into Docker operations."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = docker.from_env()

    def data_path(self, server_id: uuid.UUID) -> Path:
        return self.settings.minecraft_data_root / "servers" / str(server_id)

    def host_data_path(self, server_id: uuid.UUID) -> Path:
        return self.settings.minecraft_host_data_root / "servers" / str(server_id)

    def container_name(self, server_id: uuid.UUID) -> str:
        return f"talos-mc-{server_id}"

    def _managed_container(self, server_id: uuid.UUID):
        container = self.client.containers.get(self.container_name(server_id))
        labels = container.attrs.get("Config", {}).get("Labels", {})
        if (
            labels.get("io.talos-panel.managed") != "true"
            or labels.get("io.talos-panel.server-id") != str(server_id)
        ):
            raise RuntimeError("Refusing to operate on an unmanaged container")
        return container

    async def prepare_directory(self, server_id: uuid.UUID) -> Path:
        path = self.data_path(server_id)
        await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
        return path

    async def ensure_network(self) -> None:
        def ensure() -> None:
            try:
                self.client.networks.get(self.settings.minecraft_network)
            except NotFound:
                self.client.networks.create(self.settings.minecraft_network)

        await asyncio.to_thread(ensure)

    async def start(self, server: MinecraftServer) -> tuple[str, str]:
        await self.prepare_directory(server.id)
        await self.ensure_network()
        return await asyncio.to_thread(self._start_sync, server)

    def _start_sync(self, server: MinecraftServer) -> tuple[str, str]:
        name = self.container_name(server.id)
        try:
            container = self._managed_container(server.id)
            container.reload()
            labels = container.attrs.get("Config", {}).get("Labels", {})
            profile_matches = (
                labels.get("io.talos-panel.memory-mb") == str(server.memory_mb)
                and labels.get("io.talos-panel.host-port") == str(server.host_port)
                and labels.get("io.talos-panel.jvm-profile") == self._jvm_profile_hash(server)
            )
            if container.status == "running" or profile_matches:
                if container.status != "running":
                    container.start()
                return container.id, "running"
            container.remove()
        except NotFound:
            pass

        profile = profile_for(server)
        data_path = self.host_data_path(server.id)
        command = [
            "java",
            *startup_jvm_arguments(
                server.memory_mb, server.use_aikar_flags, server.custom_jvm_flags
            ),
            "-jar",
            profile.jar_name,
            "nogui",
        ]
        container = self.client.containers.run(
            profile.image,
            command=command,
            name=name,
            detach=True,
            init=True,
            network=self.settings.minecraft_network,
            ports={"25565/tcp": server.host_port},
            volumes={str(data_path): {"bind": "/server", "mode": "rw"}},
            working_dir="/server",
            mem_limit=f"{server.memory_mb}m",
            labels={
                "io.talos-panel.managed": "true",
                "io.talos-panel.server-id": str(server.id),
                "io.talos-panel.memory-mb": str(server.memory_mb),
                "io.talos-panel.host-port": str(server.host_port),
                "io.talos-panel.jvm-profile": self._jvm_profile_hash(server),
            },
            restart_policy={"Name": "no"},
            stdin_open=True,
        )
        return container.id, "running"

    @staticmethod
    def _jvm_profile_hash(server: MinecraftServer) -> str:
        value = f"{server.use_aikar_flags}\0{server.custom_jvm_flags}".encode()
        return hashlib.sha256(value).hexdigest()[:16]

    async def use_panel_restart_policy(self, server: MinecraftServer) -> None:
        def configure() -> None:
            try:
                container = self._managed_container(server.id)
            except NotFound:
                return
            policy = container.attrs.get("HostConfig", {}).get("RestartPolicy", {})
            if policy.get("Name") != "no":
                container.update(restart_policy={"Name": "no"})

        await asyncio.to_thread(configure)

    async def stop(self, server: MinecraftServer) -> tuple[str | None, str]:
        def stop() -> tuple[str | None, str]:
            try:
                container = self._managed_container(server.id)
            except NotFound:
                return None, "not_created"
            container.stop(timeout=30)
            return container.id, "exited"

        return await asyncio.to_thread(stop)

    async def status(self, server: MinecraftServer) -> tuple[str | None, str]:
        def inspect() -> tuple[str | None, str]:
            try:
                container = self._managed_container(server.id)
            except NotFound:
                return None, "not_created"
            container.reload()
            return container.id, container.status

        return await asyncio.to_thread(inspect)

    async def status_snapshot(self, server: MinecraftServer) -> RuntimeSnapshot:
        def inspect() -> RuntimeSnapshot:
            try:
                container = self._managed_container(server.id)
            except NotFound:
                return RuntimeSnapshot(container_id=None, state="not_created")
            container.reload()
            state = container.status
            started_at = None
            started_value = container.attrs.get("State", {}).get("StartedAt")
            if state == "running" and started_value:
                try:
                    started_at = datetime.fromisoformat(started_value).astimezone(UTC)
                except ValueError:
                    started_at = None
            return RuntimeSnapshot(container.id, state, started_at)

        return await asyncio.to_thread(inspect)

    async def snapshot(self, server: MinecraftServer) -> RuntimeSnapshot:
        def inspect() -> RuntimeSnapshot:
            try:
                container = self._managed_container(server.id)
            except NotFound:
                return RuntimeSnapshot(container_id=None, state="not_created")
            container.reload()
            state = container.status
            started_at = None
            started_value = container.attrs.get("State", {}).get("StartedAt")
            if state == "running" and started_value:
                try:
                    started_at = datetime.fromisoformat(started_value)
                    started_at = started_at.astimezone(UTC)
                except ValueError:
                    started_at = None
            if state != "running":
                return RuntimeSnapshot(container.id, state, started_at)

            stats = container.stats(stream=False)
            memory = stats.get("memory_stats", {})
            usage = memory.get("usage")
            cache = memory.get("stats", {}).get("inactive_file", 0)
            memory_bytes = max(0, usage - cache) if isinstance(usage, int) else None
            memory_limit = memory.get("limit")
            cpu = stats.get("cpu_stats", {})
            previous_cpu = stats.get("precpu_stats", {})
            cpu_delta = cpu.get("cpu_usage", {}).get("total_usage", 0) - previous_cpu.get(
                "cpu_usage", {}
            ).get("total_usage", 0)
            system_delta = cpu.get("system_cpu_usage", 0) - previous_cpu.get(
                "system_cpu_usage", 0
            )
            online_cpus = cpu.get("online_cpus") or len(
                cpu.get("cpu_usage", {}).get("percpu_usage", [])
            )
            cpu_percent = None
            if cpu_delta > 0 and system_delta > 0 and online_cpus:
                cpu_percent = cpu_delta / system_delta * online_cpus * 100
            return RuntimeSnapshot(
                container.id,
                state,
                started_at,
                round(cpu_percent, 1) if cpu_percent is not None else None,
                memory_bytes,
                memory_limit if isinstance(memory_limit, int) else None,
            )

        return await asyncio.to_thread(inspect)

    async def logs(self, server: MinecraftServer, tail: int = 300) -> str:
        def read() -> str:
            try:
                container = self._managed_container(server.id)
            except NotFound:
                return ""
            output = container.logs(stdout=True, stderr=True, tail=tail, timestamps=False)
            return output.decode("utf-8", errors="replace")

        return await asyncio.to_thread(read)

    async def send_command(self, server: MinecraftServer, command: str) -> None:
        normalized = normalize_console_command(command)

        def send() -> None:
            try:
                container = self._managed_container(server.id)
            except NotFound as exc:
                raise RuntimeError("Server container does not exist") from exc
            container.reload()
            if container.status != "running":
                raise RuntimeError("Server is not running")
            connection = container.attach_socket(
                params={"stdin": 1, "stream": 1}, ws=False
            )
            payload = f"{normalized}\n".encode()
            try:
                socket = getattr(connection, "_sock", connection)
                if hasattr(socket, "sendall"):
                    socket.sendall(payload)
                else:
                    connection.write(payload)
            except (APIError, OSError) as exc:
                raise RuntimeError("Command could not be sent") from exc
            finally:
                connection.close()

        await asyncio.to_thread(send)

    async def restart(self, server: MinecraftServer) -> tuple[str, str]:
        await self.stop(server)
        return await self.start(server)

    async def remove(self, server: MinecraftServer) -> str | None:
        def remove() -> str | None:
            try:
                container = self._managed_container(server.id)
            except NotFound:
                return None
            container.reload()
            if container.status == "running":
                container.stop(timeout=30)
            container_id = container.id
            container.remove()
            return container_id

        return await asyncio.to_thread(remove)

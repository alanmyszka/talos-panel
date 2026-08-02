import uuid
from pathlib import Path

import pytest

from talos_panel.config import Settings
from talos_panel.runtime import DockerRuntime, profile_for


def test_runtime_paths_are_derived_from_server_id() -> None:
    runtime = object.__new__(DockerRuntime)
    runtime.settings = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        minecraft_data_root=Path("/safe-root"),
        minecraft_host_data_root=Path("/host-root"),
    )
    server_id = uuid.UUID("29fc0af2-5480-4d6e-88aa-e0e592d7f4e6")
    assert runtime.data_path(server_id) == Path("/safe-root/servers") / str(server_id)
    assert runtime.host_data_path(server_id) == Path("/host-root/servers") / str(server_id)
    assert runtime.container_name(server_id) == f"talos-mc-{server_id}"


def test_runtime_profile_uses_installed_java_version() -> None:
    server = type("Server", (), {"java_version": 25})()
    assert profile_for(server).image == "eclipse-temurin:25-jre"


@pytest.mark.asyncio
async def test_console_rejects_empty_and_oversized_commands() -> None:
    runtime = object.__new__(DockerRuntime)
    server = type("Server", (), {})()
    with pytest.raises(ValueError, match="between 1 and 256"):
        await runtime.send_command(server, "   ")
    with pytest.raises(ValueError, match="between 1 and 256"):
        await runtime.send_command(server, "x" * 257)


@pytest.mark.asyncio
async def test_console_rejects_control_characters() -> None:
    runtime = object.__new__(DockerRuntime)
    server = type("Server", (), {})()
    with pytest.raises(ValueError, match="control"):
        await runtime.send_command(server, "say hello\tworld")


@pytest.mark.asyncio
async def test_runtime_snapshot_calculates_container_metrics() -> None:
    class Container:
        id = "container-id"
        status = "running"

        def __init__(self) -> None:
            self.attrs = {"State": {"StartedAt": "2026-08-02T10:00:00Z"}}

        def reload(self) -> None:
            pass

        def stats(self, *, stream: bool):
            assert stream is False
            return {
                "memory_stats": {
                    "usage": 1_000,
                    "limit": 2_000,
                    "stats": {"inactive_file": 100},
                },
                "cpu_stats": {
                    "cpu_usage": {"total_usage": 200},
                    "system_cpu_usage": 1_000,
                    "online_cpus": 2,
                },
                "precpu_stats": {
                    "cpu_usage": {"total_usage": 100},
                    "system_cpu_usage": 500,
                },
            }

    runtime = object.__new__(DockerRuntime)
    runtime._managed_container = lambda server_id: Container()
    server = type("Server", (), {"id": uuid.uuid4()})()

    snapshot = await runtime.snapshot(server)

    assert snapshot.state == "running"
    assert snapshot.cpu_percent == 40.0
    assert snapshot.memory_bytes == 900
    assert snapshot.memory_limit_bytes == 2_000


@pytest.mark.asyncio
async def test_remove_stops_and_removes_only_managed_container() -> None:
    class Container:
        id = "container-id"
        status = "running"

        def __init__(self) -> None:
            self.stopped = False
            self.removed = False

        def reload(self) -> None:
            pass

        def stop(self, *, timeout: int) -> None:
            assert timeout == 30
            self.stopped = True

        def remove(self) -> None:
            self.removed = True

    container = Container()
    runtime = object.__new__(DockerRuntime)
    runtime._managed_container = lambda server_id: container
    server = type("Server", (), {"id": uuid.uuid4()})()

    assert await runtime.remove(server) == "container-id"
    assert container.stopped is True
    assert container.removed is True

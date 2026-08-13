import uuid
from pathlib import Path

import pytest

from talos_panel.config import Settings
from talos_panel.jvm_flags import AIKAR_FLAGS, JvmFlagsError, startup_jvm_arguments
from talos_panel.runtime import (
    DockerRuntime,
    clean_console_logs,
    clean_console_response,
    normalize_console_command,
    profile_for,
)


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
    server = type(
        "Server", (), {"java_version": 25, "server_type": type("Type", (), {"value": "paper"})()}
    )()
    profile = profile_for(server)
    assert profile.image == "itzg/minecraft-server:java25"
    assert profile.itzg_type == "PAPER"


def test_jvm_startup_arguments_include_safe_custom_and_optional_aikar_flags() -> None:
    arguments = startup_jvm_arguments(4096, True, "-Dexample.enabled=true")
    assert arguments[:2] == ["-Xms4096M", "-Xmx4096M"]
    assert list(AIKAR_FLAGS) == arguments[2:-1]
    assert arguments[-1] == "-Dexample.enabled=true"


def test_jvm_startup_arguments_reject_managed_or_entrypoint_flags() -> None:
    for flags in ("-Xmx64G", "-jar other.jar", "-javaagent:plugin.jar", "plain-value"):
        with pytest.raises(JvmFlagsError):
            startup_jvm_arguments(4096, False, flags)


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


def test_console_accepts_commands_with_or_without_a_leading_slash() -> None:
    assert normalize_console_command("help") == "help"
    assert normalize_console_command(" /help ") == "help"
    assert normalize_console_command("/ say hello") == "say hello"
    with pytest.raises(ValueError, match="between 1 and 256"):
        normalize_console_command("/")


def test_console_hides_rcon_connection_noise() -> None:
    logs = (
        "[INFO]: Thread RCON Client /0:0:0:0:0:0:0:1 started\n"
        "[INFO]: Available commands\n"
        "[INFO]: Thread RCON Client /0:0:0:0:0:0:0:1 shutting down"
    )
    assert clean_console_logs(logs) == "[INFO]: Available commands"


def test_console_strips_ansi_colors_from_legacy_rcon_output() -> None:
    assert clean_console_response("\x1b[33mHelp:\x1b[0m Index") == "Help: Index"


@pytest.mark.asyncio
async def test_itzg_console_returns_rcon_output() -> None:
    class Result:
        exit_code = 0
        output = b"Available commands: help, list"

    class Container:
        status = "running"

        def __init__(self) -> None:
            self.attrs = {"Config": {"Labels": {"io.talos-panel.runtime": "itzg"}}}

        def reload(self) -> None:
            pass

        def exec_run(self, command):
            assert command == ["rcon-cli", "help"]
            return Result()

    runtime = object.__new__(DockerRuntime)
    runtime._managed_container = lambda server_id: Container()
    server = type("Server", (), {"id": uuid.uuid4()})()

    assert await runtime.send_command(server, "help") == "Available commands: help, list"


@pytest.mark.asyncio
async def test_itzg_console_pipe_sends_command_without_rcon() -> None:
    class Result:
        exit_code = 0
        output = b""

    class Container:
        status = "running"

        def __init__(self) -> None:
            self.attrs = {
                "Config": {
                    "Labels": {
                        "io.talos-panel.runtime": "itzg",
                        "io.talos-panel.console-mode": "pipe",
                    }
                }
            }

        def reload(self) -> None:
            pass

        def exec_run(self, command, *, user):
            assert command == ["mc-send-to-console", "help"]
            assert user == "1000"
            return Result()

    runtime = object.__new__(DockerRuntime)
    runtime._managed_container = lambda server_id: Container()
    server = type("Server", (), {"id": uuid.uuid4()})()

    assert await runtime.send_command(server, "help") == ""


@pytest.mark.asyncio
async def test_log_stream_follows_once_and_closes() -> None:
    class Stream:
        def __init__(self) -> None:
            self.chunks = iter(
                [
                    b"[INFO]: Server started\n",
                    b"[INFO]: Thread RCON Client /127.0.0.1 started\n",
                    b"[INFO]: Steve joined the game\n",
                ]
            )
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.chunks)

        def close(self) -> None:
            self.closed = True

    class Container:
        def __init__(self, stream) -> None:
            self.stream = stream
            self.calls = 0

        def logs(self, **kwargs):
            self.calls += 1
            assert kwargs == {
                "stdout": True,
                "stderr": True,
                "tail": 300,
                "timestamps": False,
                "stream": True,
                "follow": True,
            }
            return self.stream

    stream = Stream()
    container = Container(stream)
    runtime = object.__new__(DockerRuntime)
    runtime._managed_container = lambda server_id: container
    server = type("Server", (), {"id": uuid.uuid4()})()

    chunks = [chunk async for chunk in runtime.stream_logs(server)]

    assert chunks == ["[INFO]: Server started", "[INFO]: Steve joined the game"]
    assert container.calls == 1
    assert stream.closed is True


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

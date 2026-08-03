from types import SimpleNamespace

import pytest

from talos_panel.models import DesiredState, MinecraftServer, ServerType
from talos_panel.operations_service import OperationsManager
from talos_panel.runtime import RuntimeSnapshot


class FakeSession:
    def __init__(self) -> None:
        self.added = []

    def add(self, value) -> None:
        self.added.append(value)


class FailingThenRunningRuntime:
    def __init__(self) -> None:
        self.start_calls = 0

    async def use_panel_restart_policy(self, server) -> None:
        return None

    async def snapshot(self, server) -> RuntimeSnapshot:
        return RuntimeSnapshot(container_id="container", state="exited")

    async def start(self, server):
        self.start_calls += 1
        if self.start_calls < 3:
            raise RuntimeError("start failed")
        return "container", "running"


@pytest.mark.asyncio
async def test_crash_recovery_retries_until_start_succeeds() -> None:
    runtime = FailingThenRunningRuntime()
    manager = OperationsManager(
        SimpleNamespace(crash_restart_limit=3),
        session_factory=None,
        runtime=runtime,
    )
    server = MinecraftServer(
        name="Survival",
        server_type=ServerType.PAPER,
        game_version="1.21.4",
        memory_mb=2048,
        host_port=25565,
        desired_state=DesiredState.RUNNING,
        auto_restart=True,
        restart_failures=0,
        last_runtime_state="running",
    )
    session = FakeSession()

    await manager._sample_and_recover(server, session)
    await manager._sample_and_recover(server, session)
    await manager._sample_and_recover(server, session)

    assert runtime.start_calls == 3
    assert server.last_runtime_state == "running"
    assert server.restart_failures == 3
    actions = [event.action for event in session.added if hasattr(event, "action")]
    assert actions.count("server.crash_detected") == 1
    assert actions.count("server.auto_restart_failed") == 2
    assert actions.count("server.auto_restart") == 1


@pytest.mark.asyncio
async def test_crash_recovery_stops_at_configured_limit() -> None:
    runtime = FailingThenRunningRuntime()
    manager = OperationsManager(
        SimpleNamespace(crash_restart_limit=2),
        session_factory=None,
        runtime=runtime,
    )
    server = MinecraftServer(
        name="Survival",
        server_type=ServerType.PAPER,
        game_version="1.21.4",
        memory_mb=2048,
        host_port=25565,
        desired_state=DesiredState.RUNNING,
        auto_restart=True,
        restart_failures=2,
        last_runtime_state="exited",
    )

    await manager._sample_and_recover(server, FakeSession())

    assert runtime.start_calls == 0
    assert server.restart_failures == 2

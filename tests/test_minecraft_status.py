import asyncio
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from talos_panel.minecraft_status import (
    concrete_minecraft_version,
    installed_version_from_data,
    query_minecraft_status,
)
from talos_panel.web import build_server_summary, minecraft_is_ready, player_snapshot


def varint(value: int) -> bytes:
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        output.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(output)


def test_concrete_version_is_extracted_from_server_status() -> None:
    assert concrete_minecraft_version("Paper 26.2") == "26.2"
    assert concrete_minecraft_version("Paper 1.21.8") == "1.21.8"
    assert concrete_minecraft_version(None) is None


def test_player_snapshot_uses_latest_list_response() -> None:
    logs = """There are 0 of a max of 20 players online:
There are 2 of a max of 20 players online: Steve, Alex
"""
    assert player_snapshot(logs) == (2, 20, ["Steve", "Alex"])


def test_player_snapshot_is_unknown_before_list_response() -> None:
    assert player_snapshot('Done (1.23s)! For help, type "help"') == (None, None, [])


def test_minecraft_ready_requires_a_running_container() -> None:
    logs = 'Done (1.23s)! For help, type "help"'
    assert minecraft_is_ready("running", logs) is True
    assert minecraft_is_ready("exited", logs) is False
    assert minecraft_is_ready("running", "Starting Minecraft server") is False


def test_installed_version_is_read_from_itzg_environment(tmp_path) -> None:
    (tmp_path / ".paper.env").write_text(
        'SERVER="/data/paper-26.2-112.jar"\nVERSION="26.2"\nTYPE="PAPER"\n',
        encoding="utf-8",
    )

    assert installed_version_from_data(tmp_path) == "26.2"


def test_installed_version_is_read_from_itzg_manifest(tmp_path) -> None:
    (tmp_path / ".papermc-manifest.json").write_text(
        json.dumps({"minecraftVersion": "1.21.8", "build": 42}),
        encoding="utf-8",
    )

    assert installed_version_from_data(tmp_path) == "1.21.8"


@pytest.mark.asyncio
async def test_server_summary_contains_id_and_offline_runtime_data(tmp_path) -> None:
    server_id = uuid.uuid4()
    server = SimpleNamespace(
        id=server_id,
        installation_state=SimpleNamespace(value="completed"),
        installed_version="1.21.8",
        host_port=25565,
    )
    runtime = SimpleNamespace(
        data_path=lambda _: tmp_path,
        status_snapshot=lambda _: asyncio.sleep(
            0,
            result=SimpleNamespace(
                state="exited", started_at=datetime(2026, 8, 13, tzinfo=UTC)
            ),
        ),
    )

    summary = await build_server_summary(runtime, server)

    assert summary["server_id"] == str(server_id)
    assert summary["runtime_state"] == "exited"
    assert summary["minecraft_ready"] is False
    assert summary["installed_version"] == "1.21.8"
    assert summary["started_at"] == "2026-08-13T00:00:00+00:00"


@pytest.mark.asyncio
async def test_server_summary_isolated_runtime_failure(tmp_path) -> None:
    async def unavailable(_):
        raise RuntimeError("Docker is unavailable")

    server_id = uuid.uuid4()
    server = SimpleNamespace(
        id=server_id,
        installation_state=SimpleNamespace(value="completed"),
        installed_version="1.21.8",
        host_port=25565,
    )
    runtime = SimpleNamespace(data_path=lambda _: tmp_path, status_snapshot=unavailable)

    summary = await build_server_summary(runtime, server)

    assert summary["server_id"] == str(server_id)
    assert summary["runtime_state"] == "error"
    assert summary["minecraft_ready"] is False


@pytest.mark.asyncio
async def test_status_query_reads_players_version_motd_and_sample() -> None:
    async def respond(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(1024)
        status = json.dumps(
            {
                "version": {"name": "Paper 1.21.8", "protocol": 772},
                "players": {
                    "max": 20,
                    "online": 2,
                    "sample": [{"name": "Steve"}, {"name": "Alex"}],
                },
                "description": {"text": "Talos ", "extra": [{"text": "Server"}]},
            }
        ).encode()
        packet = varint(0) + varint(len(status)) + status
        writer.write(varint(len(packet)) + packet)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(respond, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        result = await query_minecraft_status("127.0.0.1", port)
    finally:
        server.close()
        await server.wait_closed()

    assert result.online == 2
    assert result.maximum == 20
    assert result.version_name == "Paper 1.21.8"
    assert result.protocol == 772
    assert result.motd == "Talos Server"
    assert result.sample_players == ["Steve", "Alex"]
    assert result.latency_ms >= 0

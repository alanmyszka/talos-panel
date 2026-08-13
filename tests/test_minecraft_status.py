import asyncio
import json

import pytest

from talos_panel.minecraft_status import concrete_minecraft_version, query_minecraft_status


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

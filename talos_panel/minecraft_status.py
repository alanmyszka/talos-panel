import asyncio
import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

MAX_PACKET_BYTES = 2 * 1024 * 1024
MAX_STRING_BYTES = 32767 * 4
MINECRAFT_VERSION = re.compile(r"\b(?:\d+\.)+\d+\b")
ITZG_VERSION_LINE = re.compile(r'^VERSION=["\']?([^"\'\r\n]+)')


class MinecraftStatusError(Exception):
    pass


def concrete_minecraft_version(version_name: str | None) -> str | None:
    if not version_name:
        return None
    match = MINECRAFT_VERSION.search(version_name)
    return match.group(0) if match else None


def installed_version_from_data(data_path: Path) -> str | None:
    """Read the concrete Minecraft version recorded by the ITZG image."""
    try:
        env_files = sorted(data_path.glob(".*.env"))
    except OSError:
        return None
    for path in env_files:
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                match = ITZG_VERSION_LINE.match(line.strip())
                if match:
                    version = concrete_minecraft_version(match.group(1))
                    if version:
                        return version
        except OSError:
            continue

    try:
        manifests = sorted(data_path.glob(".*manifest.json"))
    except OSError:
        manifests = []
    for path in manifests:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        for key in ("minecraftVersion", "version"):
            version = concrete_minecraft_version(str(payload.get(key, "")))
            if version:
                return version
    return None


@dataclass(frozen=True)
class MinecraftStatus:
    online: int
    maximum: int
    latency_ms: float
    version_name: str | None
    protocol: int | None
    motd: str
    sample_players: list[str]


def _varint(value: int) -> bytes:
    value &= 0xFFFFFFFF
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        encoded.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(encoded)


def _string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return _varint(len(encoded)) + encoded


async def _read_varint(reader: asyncio.StreamReader) -> int:
    result = 0
    for position in range(5):
        byte = (await reader.readexactly(1))[0]
        result |= (byte & 0x7F) << (7 * position)
        if not byte & 0x80:
            return result
    raise MinecraftStatusError("Minecraft returned an invalid VarInt")


async def _read_packet(reader: asyncio.StreamReader) -> bytes:
    length = await _read_varint(reader)
    if length < 1 or length > MAX_PACKET_BYTES:
        raise MinecraftStatusError("Minecraft returned an invalid status packet size")
    return await reader.readexactly(length)


def _decode_varint(payload: bytes, offset: int = 0) -> tuple[int, int]:
    result = 0
    for position in range(5):
        if offset >= len(payload):
            raise MinecraftStatusError("Minecraft returned a truncated VarInt")
        byte = payload[offset]
        offset += 1
        result |= (byte & 0x7F) << (7 * position)
        if not byte & 0x80:
            return result, offset
    raise MinecraftStatusError("Minecraft returned an invalid VarInt")


def _plain_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_plain_text(item) for item in value)
    if isinstance(value, dict):
        return str(value.get("text", "")) + _plain_text(value.get("extra", []))
    return ""


async def query_minecraft_status(host: str, port: int, timeout: float = 1.0) -> MinecraftStatus:
    async def query() -> MinecraftStatus:
        started = perf_counter()
        reader, writer = await asyncio.open_connection(host, port)
        try:
            handshake = _varint(0) + _varint(-1) + _string(host) + struct.pack(">H", port) + _varint(1)
            writer.write(_varint(len(handshake)) + handshake)
            writer.write(_varint(1) + _varint(0))
            await writer.drain()
            packet = await _read_packet(reader)
            packet_id, offset = _decode_varint(packet)
            if packet_id != 0:
                raise MinecraftStatusError("Minecraft returned an unexpected status packet")
            string_length, offset = _decode_varint(packet, offset)
            if string_length > MAX_STRING_BYTES or offset + string_length != len(packet):
                raise MinecraftStatusError("Minecraft returned an invalid status response")
            payload = json.loads(packet[offset:].decode("utf-8"))
            players = payload.get("players", {})
            version = payload.get("version", {})
            sample = players.get("sample") or []
            return MinecraftStatus(
                online=int(players.get("online", 0)),
                maximum=int(players.get("max", 0)),
                latency_ms=round((perf_counter() - started) * 1000, 1),
                version_name=version.get("name"),
                protocol=version.get("protocol"),
                motd=_plain_text(payload.get("description", "")),
                sample_players=[str(player.get("name")) for player in sample if player.get("name")],
            )
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise MinecraftStatusError("Minecraft returned malformed status data") from exc
        finally:
            writer.close()
            await writer.wait_closed()

    try:
        return await asyncio.wait_for(query(), timeout=timeout)
    except (OSError, asyncio.IncompleteReadError, TimeoutError) as exc:
        raise MinecraftStatusError("Minecraft status is unavailable") from exc

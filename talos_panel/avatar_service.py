import asyncio
import base64
import binascii
import io
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from PIL import Image, UnidentifiedImageError

TEXTURE_PATH = re.compile(r"^/texture/([0-9a-f]{32,128})$")


class AvatarError(Exception):
    pass


def _cache_is_fresh(path: Path, max_age: timedelta) -> bool:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        return path.is_file() and not path.is_symlink() and datetime.now(UTC) - modified < max_age
    except OSError:
        return False


def _skin_url(profile: dict) -> str:
    properties = profile.get("properties", [])
    encoded = next(
        (
            item.get("value")
            for item in properties
            if isinstance(item, dict) and item.get("name") == "textures"
        ),
        None,
    )
    if not isinstance(encoded, str):
        raise AvatarError("Minecraft profile does not contain a skin")
    try:
        payload = json.loads(base64.b64decode(encoded, validate=True))
        source_url = payload["textures"]["SKIN"]["url"]
    except (binascii.Error, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AvatarError("Minecraft returned malformed skin data") from exc
    parsed = httpx.URL(source_url)
    match = TEXTURE_PATH.fullmatch(parsed.path)
    if parsed.host != "textures.minecraft.net" or not match:
        raise AvatarError("Minecraft returned an untrusted skin URL")
    return f"https://textures.minecraft.net/texture/{match.group(1)}"


def _render_head(skin_bytes: bytes, destination: Path) -> None:
    try:
        with Image.open(io.BytesIO(skin_bytes)) as source:
            if source.format != "PNG" or source.size not in {(64, 64), (64, 32)}:
                raise AvatarError("Minecraft returned an unsupported skin image")
            source.load()
            skin = source.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise AvatarError("Minecraft returned an invalid skin image") from exc

    face = skin.crop((8, 8, 16, 16))
    overlay = skin.crop((40, 8, 48, 16))
    face.alpha_composite(overlay)
    avatar = face.resize((64, 64), Image.Resampling.NEAREST)
    temporary = destination.with_suffix(".tmp")
    avatar.save(temporary, format="PNG", optimize=True)
    temporary.replace(destination)


async def get_player_avatar(
    player_uuid: str,
    cache_root: Path,
    cache_hours: int,
    timeout_seconds: float,
    max_skin_bytes: int,
    client: httpx.AsyncClient | None = None,
) -> Path:
    try:
        normalized_uuid = uuid.UUID(player_uuid)
    except ValueError as exc:
        raise AvatarError("Invalid player UUID") from exc
    cache_root.mkdir(parents=True, exist_ok=True)
    destination = cache_root / f"{normalized_uuid}.png"
    if _cache_is_fresh(destination, timedelta(hours=max(1, cache_hours))):
        return destination

    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=False,
        headers={"User-Agent": "talos-panel/0.1.0"},
    )
    try:
        profile_url = (
            "https://sessionserver.mojang.com/session/minecraft/profile/"
            f"{normalized_uuid.hex}"
        )
        profile_response = await http.get(profile_url)
        profile_response.raise_for_status()
        skin_response = await http.get(_skin_url(profile_response.json()))
        skin_response.raise_for_status()
        content_length = int(skin_response.headers.get("content-length", "0"))
        if content_length > max_skin_bytes or len(skin_response.content) > max_skin_bytes:
            raise AvatarError("Minecraft skin exceeds the download limit")
        await asyncio.to_thread(_render_head, skin_response.content, destination)
        return destination
    except (httpx.HTTPError, json.JSONDecodeError, ValueError, AvatarError) as exc:
        if destination.is_file() and not destination.is_symlink():
            return destination
        if isinstance(exc, AvatarError):
            raise
        raise AvatarError("Minecraft avatar service is unavailable") from exc
    finally:
        if owns_client:
            await http.aclose()

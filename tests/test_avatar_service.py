import base64
import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from talos_panel.avatar_service import AvatarError, get_player_avatar

PLAYER_UUID = "8667ba71-b85a-4004-af54-457a9734eed7"
TEXTURE_ID = "a" * 64


def profile_payload(texture_url: str) -> dict:
    textures = base64.b64encode(
        json.dumps({"textures": {"SKIN": {"url": texture_url}}}).encode()
    ).decode()
    return {"properties": [{"name": "textures", "value": textures}]}


def skin_png() -> bytes:
    skin = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    skin.paste((255, 0, 0, 255), (8, 8, 16, 16))
    skin.paste((0, 0, 255, 255), (40, 8, 48, 16))
    output = io.BytesIO()
    skin.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_avatar_downloads_renders_and_reuses_cache(tmp_path: Path) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.host == "sessionserver.mojang.com":
            return httpx.Response(
                200,
                json=profile_payload(f"http://textures.minecraft.net/texture/{TEXTURE_ID}"),
            )
        return httpx.Response(200, content=skin_png(), headers={"content-type": "image/png"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        avatar = await get_player_avatar(PLAYER_UUID, tmp_path, 24, 1, 1024 * 1024, client)
        cached = await get_player_avatar(PLAYER_UUID, tmp_path, 24, 1, 1024 * 1024, client)

    assert avatar == cached
    assert len(requests) == 2
    with Image.open(avatar) as image:
        assert image.size == (64, 64)
        assert image.getpixel((32, 32)) == (0, 0, 255, 255)


@pytest.mark.asyncio
async def test_avatar_rejects_untrusted_texture_host(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=profile_payload(f"https://example.com/texture/{TEXTURE_ID}"),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AvatarError, match="untrusted"):
            await get_player_avatar(PLAYER_UUID, tmp_path, 24, 1, 1024 * 1024, client)


@pytest.mark.asyncio
async def test_avatar_rejects_oversized_skin(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "sessionserver.mojang.com":
            return httpx.Response(
                200,
                json=profile_payload(f"https://textures.minecraft.net/texture/{TEXTURE_ID}"),
            )
        return httpx.Response(200, content=b"x" * 100)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AvatarError, match="download limit"):
            await get_player_avatar(PLAYER_UUID, tmp_path, 24, 1, 10, client)

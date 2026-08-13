import re

import httpx

from talos_panel.models import ServerType

PAPER_PROJECT_URL = "https://fill.papermc.io/v3/projects/paper"
VANILLA_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
RELEASE_VERSION = re.compile(r"^\d+(?:\.\d+){1,2}$")
MIN_VANILLA_SERVER_VERSION = (1, 2, 5)


class InstallationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def java_version_for(game_version: str) -> int:
    if game_version.upper() == "LATEST":
        return 25
    try:
        parts = game_version.split(".")
        if parts[0].isdigit() and int(parts[0]) >= 26:
            return 25
        minor = int(parts[1])
    except (IndexError, ValueError) as exc:
        raise InstallationError("unsupported_version", "Unsupported Minecraft version") from exc
    if minor >= 20:
        return 21
    if minor >= 17:
        return 17
    if minor >= 12:
        return 11
    return 8


def vanilla_server_artifact_available(game_version: str) -> bool:
    if not RELEASE_VERSION.fullmatch(game_version):
        return False
    parts = tuple(int(part) for part in game_version.split("."))
    padded = parts + (0,) * (3 - len(parts))
    return padded >= MIN_VANILLA_SERVER_VERSION


class ArtifactResolver:
    """Lists game versions; ITZG resolves and downloads the actual server distribution."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def versions(self, server_type: ServerType) -> list[str]:
        if server_type is ServerType.PAPER:
            versions = await self._paper_versions()
        else:
            versions = await self._minecraft_versions()
        return ["LATEST", *versions]

    async def _paper_versions(self) -> list[str]:
        response = await self._get(PAPER_PROJECT_URL)
        groups = response.json().get("versions", {})
        return [
            version
            for versions in groups.values()
            for version in versions
            if RELEASE_VERSION.fullmatch(version)
        ]

    async def _minecraft_versions(self) -> list[str]:
        response = await self._get(VANILLA_MANIFEST_URL)
        return [
            item["id"]
            for item in response.json()["versions"]
            if item["type"] == "release" and vanilla_server_artifact_available(item["id"])
        ]

    async def _get(self, url: str) -> httpx.Response:
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise InstallationError(
                "source_unavailable", "Minecraft version information is unavailable"
            ) from exc

import asyncio
import hashlib
import os
import re
import tempfile
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlparse

import httpx

from talos_panel.config import Settings
from talos_panel.models import ServerType

PAPER_PROJECT_URL = "https://fill.papermc.io/v3/projects/paper"
VANILLA_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ProgressCallback = Callable[[int, int | None], Awaitable[None]]
RELEASE_VERSION = re.compile(r"^\d+(?:\.\d+){1,2}$")


class InstallationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Artifact:
    version: str
    url: str
    checksum_algorithm: str
    checksum: str
    size: int | None
    java_version: int
    build_id: str | None = None


def java_version_for(game_version: str) -> int:
    try:
        parts = game_version.split(".")
        if parts[0].isdigit() and int(parts[0]) >= 26:
            return 25
        minor = int(parts[1])
        patch = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    except (IndexError, ValueError) as exc:
        raise InstallationError("unsupported_version", "Unsupported Minecraft version") from exc
    if minor >= 20:
        return 21
    if minor >= 17:
        return 17
    if minor == 16 and patch >= 5:
        return 16
    if minor >= 12:
        return 11
    return 8


class ArtifactResolver:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def versions(self, server_type: ServerType) -> list[str]:
        if server_type is ServerType.PAPER:
            response = await self._get(PAPER_PROJECT_URL)
            groups = response.json().get("versions", {})
            return [
                version
                for versions in groups.values()
                for version in versions
                if RELEASE_VERSION.fullmatch(version)
            ]
        response = await self._get(VANILLA_MANIFEST_URL)
        return [item["id"] for item in response.json()["versions"] if item["type"] == "release"]

    async def resolve(self, server_type: ServerType, version: str) -> Artifact:
        if server_type is ServerType.PAPER:
            return await self._resolve_paper(version)
        return await self._resolve_vanilla(version)

    async def _resolve_paper(self, version: str) -> Artifact:
        response = await self._get(f"{PAPER_PROJECT_URL}/versions/{version}/builds")
        builds = response.json()
        stable = next((build for build in builds if build.get("channel") == "STABLE"), None)
        if stable is None:
            raise InstallationError("version_not_found", "No stable Paper build exists for this version")
        download = stable.get("downloads", {}).get("server:default")
        if not download:
            raise InstallationError("artifact_not_found", "Paper server artifact is unavailable")
        return Artifact(
            version=version,
            url=download["url"],
            checksum_algorithm="sha256",
            checksum=download["checksums"]["sha256"],
            size=download.get("size"),
            java_version=java_version_for(version),
            build_id=str(stable.get("id", stable.get("number"))),
        )

    async def _resolve_vanilla(self, version: str) -> Artifact:
        manifest = (await self._get(VANILLA_MANIFEST_URL)).json()
        item = next(
            (entry for entry in manifest["versions"] if entry["id"] == version and entry["type"] == "release"),
            None,
        )
        if item is None:
            raise InstallationError("version_not_found", "Vanilla release was not found")
        details = (await self._get(item["url"])).json()
        download = details.get("downloads", {}).get("server")
        if not download:
            raise InstallationError("artifact_not_found", "Vanilla server artifact is unavailable")
        java = details.get("javaVersion", {}).get("majorVersion") or java_version_for(version)
        return Artifact(version, download["url"], "sha1", download["sha1"], download.get("size"), java)

    async def _get(self, url: str) -> httpx.Response:
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response
        except (httpx.HTTPError, ValueError) as exc:
            raise InstallationError("source_unavailable", "The official download service is unavailable") from exc


class JarDownloader:
    allowed_hosts: ClassVar[set[str]] = {
        "fill-data.papermc.io",
        "piston-data.mojang.com",
        "launcher.mojang.com",
    }

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def download(
        self, artifact: Artifact, destination: Path, progress: ProgressCallback
    ) -> str:
        if urlparse(artifact.url).hostname not in self.allowed_hosts:
            raise InstallationError("untrusted_source", "The download source is not trusted")
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".server-", suffix=".jar.tmp", dir=destination.parent)
        temporary = Path(temporary_name)
        digest = hashlib.new(artifact.checksum_algorithm)
        downloaded = 0
        try:
            with os.fdopen(descriptor, "wb") as output:
                async with self.client.stream("GET", artifact.url) as response:
                    response.raise_for_status()
                    header_size = response.headers.get("content-length")
                    total = artifact.size or (int(header_size) if header_size else None)
                    if total and total > self.settings.max_server_jar_bytes:
                        raise InstallationError("artifact_too_large", "The server JAR exceeds the size limit")
                    async for chunk in response.aiter_bytes():
                        downloaded += len(chunk)
                        if downloaded > self.settings.max_server_jar_bytes:
                            raise InstallationError("artifact_too_large", "The server JAR exceeds the size limit")
                        digest.update(chunk)
                        await asyncio.to_thread(output.write, chunk)
                        await progress(downloaded, total)
                await asyncio.to_thread(output.flush)
                await asyncio.to_thread(os.fsync, output.fileno())
            actual = digest.hexdigest()
            if artifact.size is not None and downloaded != artifact.size:
                raise InstallationError("size_mismatch", "The downloaded JAR has an unexpected size")
            if actual.lower() != artifact.checksum.lower():
                raise InstallationError("checksum_mismatch", "The downloaded JAR failed integrity verification")
            if not await asyncio.to_thread(zipfile.is_zipfile, temporary):
                raise InstallationError("invalid_jar", "The downloaded artifact is not a valid JAR")
            await asyncio.to_thread(os.replace, temporary, destination)
            return actual
        except InstallationError:
            temporary.unlink(missing_ok=True)
            raise
        except (httpx.HTTPError, OSError, zipfile.BadZipFile) as exc:
            temporary.unlink(missing_ok=True)
            raise InstallationError("download_failed", "The server JAR could not be downloaded") from exc

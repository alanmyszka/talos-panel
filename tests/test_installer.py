import hashlib
import io
import zipfile
from pathlib import Path

import httpx
import pytest

from talos_panel.config import Settings
from talos_panel.installer import (
    RELEASE_VERSION,
    Artifact,
    ArtifactResolver,
    InstallationError,
    JarDownloader,
    java_version_for,
    vanilla_server_artifact_available,
)
from talos_panel.models import ServerType


def jar_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
    return output.getvalue()


def test_java_version_is_selected_from_game_version() -> None:
    assert java_version_for("1.19.4") == 17
    assert java_version_for("1.21.11") == 21
    assert java_version_for("26.1") == 25


def test_release_filter_rejects_prereleases() -> None:
    assert RELEASE_VERSION.fullmatch("1.21.11")
    assert RELEASE_VERSION.fullmatch("26.1.2")
    assert not RELEASE_VERSION.fullmatch("1.21.11-rc1")


def test_vanilla_versions_without_official_server_jar_are_rejected() -> None:
    assert not vanilla_server_artifact_available("1.0")
    assert not vanilla_server_artifact_available("1.2.4")
    assert vanilla_server_artifact_available("1.2.5")
    assert vanilla_server_artifact_available("1.21.11")
    assert not vanilla_server_artifact_available("1.21-rc1")


@pytest.mark.asyncio
async def test_vanilla_version_list_hides_client_only_releases() -> None:
    manifest = {
        "versions": [
            {"id": "1.21.11", "type": "release"},
            {"id": "1.2.5", "type": "release"},
            {"id": "1.2.4", "type": "release"},
            {"id": "1.0", "type": "release"},
            {"id": "1.22-pre1", "type": "snapshot"},
        ]
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=manifest))
    async with httpx.AsyncClient(transport=transport) as client:
        versions = await ArtifactResolver(client).versions(ServerType.VANILLA)

    assert versions == ["1.21.11", "1.2.5"]


@pytest.mark.asyncio
async def test_download_is_verified_and_published_atomically(tmp_path: Path) -> None:
    content = jar_bytes()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    artifact = Artifact(
        "1.21.4",
        "https://piston-data.mojang.com/server.jar",
        "sha1",
        hashlib.sha1(content).hexdigest(),
        len(content),
        21,
    )
    settings = Settings(database_url="postgresql+asyncpg://x:x@localhost/x")
    async with httpx.AsyncClient(transport=transport) as client:
        actual = await JarDownloader(client, settings).download(
            artifact, tmp_path / "server.jar", _ignore_progress
        )
    assert actual == artifact.checksum
    assert (tmp_path / "server.jar").read_bytes() == content
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
async def test_checksum_failure_preserves_existing_jar(tmp_path: Path) -> None:
    content = jar_bytes()
    destination = tmp_path / "server.jar"
    destination.write_bytes(b"old")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    artifact = Artifact(
        "1.21.4", "https://piston-data.mojang.com/server.jar", "sha1", "0" * 40, len(content), 21
    )
    settings = Settings(database_url="postgresql+asyncpg://x:x@localhost/x")
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(InstallationError, match="integrity"):
            await JarDownloader(client, settings).download(artifact, destination, _ignore_progress)
    assert destination.read_bytes() == b"old"


async def _ignore_progress(downloaded: int, total: int | None) -> None:
    pass

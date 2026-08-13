import httpx
import pytest

from talos_panel.installer import (
    RELEASE_VERSION,
    ArtifactResolver,
    java_version_for,
    vanilla_server_artifact_available,
)
from talos_panel.models import ServerType


def test_java_version_is_selected_from_game_version() -> None:
    assert java_version_for("1.19.4") == 17
    assert java_version_for("1.21.11") == 21
    assert java_version_for("26.1") == 25
    assert java_version_for("LATEST") == 25


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
@pytest.mark.parametrize(
    "server_type",
    [
        ServerType.VANILLA,
        ServerType.PURPUR,
        ServerType.PUFFERFISH,
        ServerType.FABRIC,
        ServerType.QUILT,
        ServerType.FORGE,
        ServerType.NEOFORGE,
    ],
)
async def test_itzg_types_use_minecraft_release_list(server_type: ServerType) -> None:
    manifest = {
        "versions": [
            {"id": "1.21.11", "type": "release"},
            {"id": "1.2.5", "type": "release"},
            {"id": "1.2.4", "type": "release"},
            {"id": "1.22-pre1", "type": "snapshot"},
        ]
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=manifest))
    async with httpx.AsyncClient(transport=transport) as client:
        versions = await ArtifactResolver(client).versions(server_type)

    assert versions == ["LATEST", "1.21.11", "1.2.5"]


@pytest.mark.asyncio
async def test_paper_uses_paper_version_catalog() -> None:
    payload = {"versions": {"1.21": ["1.21.11", "1.21.10-rc1"]}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        versions = await ArtifactResolver(client).versions(ServerType.PAPER)

    assert versions == ["LATEST", "1.21.11"]

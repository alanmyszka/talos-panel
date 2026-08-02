from pathlib import Path

import pytest

from talos_panel.server_settings import (
    ServerProperties,
    ServerSettingsError,
    read_server_properties,
    write_server_properties,
)


def test_properties_round_trip_preserves_unmanaged_values(tmp_path: Path) -> None:
    destination = tmp_path / "server.properties"
    destination.write_text("# generated\nonline-mode=true\nmotd=Old\npvp=false\n", encoding="utf-8")
    settings = ServerProperties(
        motd="Talos Survival",
        gamemode="survival",
        difficulty="hard",
        max_players=12,
        whitelist=True,
        pvp=True,
        allow_flight=False,
        view_distance=14,
        simulation_distance=8,
    )

    write_server_properties(tmp_path, settings)

    content = destination.read_text(encoding="utf-8")
    assert "online-mode=true" in content
    assert "motd=Talos Survival" in content
    assert "difficulty=hard" in content
    assert read_server_properties(tmp_path) == settings
    assert not list(tmp_path.glob("*.tmp"))


def test_properties_reject_symlink(tmp_path: Path) -> None:
    target = tmp_path / "outside.properties"
    target.write_text("motd=Do not replace\n", encoding="utf-8")
    (tmp_path / "server.properties").symlink_to(target)

    with pytest.raises(ServerSettingsError, match="symbolic link"):
        write_server_properties(tmp_path, ServerProperties())

    assert target.read_text(encoding="utf-8") == "motd=Do not replace\n"


def test_properties_defaults_when_server_has_not_created_file(tmp_path: Path) -> None:
    assert read_server_properties(tmp_path) == ServerProperties()

import pytest
from pydantic import ValidationError

from talos_panel.schemas import ServerCreate, ServerSettingsUpdate


def test_server_create_rejects_privileged_port() -> None:
    with pytest.raises(ValidationError):
        ServerCreate(
            name="Survival", server_type="paper", game_version="1.21.4", memory_mb=4096, host_port=22
        )


def test_server_create_rejects_unbounded_memory() -> None:
    with pytest.raises(ValidationError):
        ServerCreate(
            name="Survival", server_type="paper", game_version="1.21.4", memory_mb=999999, host_port=25565
        )


def test_server_settings_enforce_backend_bounds() -> None:
    with pytest.raises(ValidationError):
        ServerSettingsUpdate(
            motd="Server",
            gamemode="survival",
            difficulty="normal",
            max_players=20,
            whitelist=False,
            pvp=True,
            allow_flight=False,
            view_distance=64,
            simulation_distance=10,
            memory_mb=512,
            host_port=80,
        )

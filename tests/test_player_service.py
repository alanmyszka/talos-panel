import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from talos_panel.player_service import load_player_profiles, validate_player_name

PLAYER_UUID = "8667ba71-b85a-4004-af54-457a9734eed7"


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_profiles_merge_minecraft_sources_and_stats(tmp_path: Path) -> None:
    write_json(tmp_path / "usercache.json", [{"name": "Steve", "uuid": PLAYER_UUID}])
    write_json(tmp_path / "ops.json", [{"name": "Steve", "uuid": PLAYER_UUID}])
    write_json(tmp_path / "whitelist.json", [{"name": "Alex", "uuid": PLAYER_UUID}])
    write_json(
        tmp_path / "banned-players.json",
        [{"name": "Griefer", "uuid": "ec561538-f3fd-461d-aff5-086b22154bce"}],
    )
    stats = tmp_path / "world" / "stats" / f"{PLAYER_UUID}.json"
    write_json(stats, {"stats": {"minecraft:custom": {"minecraft:play_time": 2400}}})
    timestamp = datetime(2025, 1, 2, tzinfo=UTC).timestamp()
    os.utime(stats, (timestamp, timestamp))

    profiles = load_player_profiles(tmp_path, ["Steve"])
    by_name = {profile.name: profile for profile in profiles}

    assert by_name["Steve"].online is True
    assert by_name["Steve"].operator is True
    assert by_name["Steve"].play_time_seconds == 120
    assert by_name["Steve"].last_active == datetime(2025, 1, 2, tzinfo=UTC)
    assert by_name["Alex"].whitelisted is True
    assert by_name["Griefer"].banned is True


def test_profiles_respect_custom_level_name(tmp_path: Path) -> None:
    (tmp_path / "server.properties").write_text("level-name=survival\n", encoding="utf-8")
    write_json(tmp_path / "usercache.json", [{"name": "Steve", "uuid": PLAYER_UUID}])
    write_json(
        tmp_path / "survival" / "stats" / f"{PLAYER_UUID}.json",
        {"stats": {"minecraft:custom": {"minecraft:play_time": 20}}},
    )
    assert load_player_profiles(tmp_path, [])[0].play_time_seconds == 1


def test_profiles_support_new_players_subdirectory_layout(tmp_path: Path) -> None:
    write_json(tmp_path / "usercache.json", [{"name": "Steve", "uuid": PLAYER_UUID}])
    stats = tmp_path / "world" / "players" / "stats" / f"{PLAYER_UUID}.json"
    write_json(stats, {"stats": {"minecraft:custom": {"minecraft:play_time": 400}}})

    profile = load_player_profiles(tmp_path, [])[0]

    assert profile.play_time_seconds == 20
    assert profile.last_active is not None


@pytest.mark.parametrize("name", ["", "has space", "../Steve", "a" * 17, "Steve\nban Alan"])
def test_player_name_validation_rejects_command_injection(name: str) -> None:
    with pytest.raises(ValueError):
        validate_player_name(name)

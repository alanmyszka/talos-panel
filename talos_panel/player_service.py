import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PLAYER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,16}$")


@dataclass(frozen=True)
class PlayerProfile:
    name: str
    player_uuid: str | None
    online: bool
    last_active: datetime | None
    play_time_seconds: int | None
    operator: bool
    whitelisted: bool
    banned: bool


def validate_player_name(name: str) -> str:
    normalized = name.strip()
    if not PLAYER_NAME_PATTERN.fullmatch(normalized):
        raise ValueError("Player name must contain 1–16 letters, numbers, or underscores")
    return normalized


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return fallback


def _normalized_uuid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _named_entries(path: Path) -> dict[str, dict]:
    entries = _read_json(path, [])
    if not isinstance(entries, list):
        return {}
    return {
        str(entry["name"]).casefold(): entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("name")
    }


def _world_path(server_root: Path) -> Path:
    level_name = "world"
    try:
        for line in (server_root / "server.properties").read_text(encoding="utf-8").splitlines():
            if line.startswith("level-name="):
                candidate = line.partition("=")[2].strip()
                if candidate and candidate not in {".", ".."} and "/" not in candidate:
                    level_name = candidate
                break
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        pass
    return server_root / level_name


def _play_time_seconds(stats_path: Path) -> int | None:
    payload = _read_json(stats_path, {})
    custom = payload.get("stats", {}).get("minecraft:custom", {}) if isinstance(payload, dict) else {}
    ticks = custom.get("minecraft:play_time", custom.get("minecraft:play_one_minute"))
    return max(0, int(ticks) // 20) if isinstance(ticks, (int, float)) else None


def _player_paths(world: Path, player_uuid: str) -> tuple[list[Path], list[Path]]:
    roots = [world, world / "players"]
    stats = [root / "stats" / f"{player_uuid}.json" for root in roots]
    activity = [
        path
        for root in roots
        for path in (
            root / "playerdata" / f"{player_uuid}.dat",
            root / "stats" / f"{player_uuid}.json",
            root / "advancements" / f"{player_uuid}.json",
        )
    ]
    return stats, activity


def _last_active(paths: list[Path]) -> datetime | None:
    mtimes = []
    for path in paths:
        try:
            mtimes.append(path.stat().st_mtime)
        except OSError:
            pass
    return datetime.fromtimestamp(max(mtimes), UTC) if mtimes else None


def load_player_profiles(server_root: Path, online_names: list[str]) -> list[PlayerProfile]:
    world = _world_path(server_root)
    cache = _named_entries(server_root / "usercache.json")
    operators = _named_entries(server_root / "ops.json")
    whitelist = _named_entries(server_root / "whitelist.json")
    banned = _named_entries(server_root / "banned-players.json")
    online = {name.casefold(): name for name in online_names if PLAYER_NAME_PATTERN.fullmatch(name)}

    known = set(cache) | set(operators) | set(whitelist) | set(banned) | set(online)
    profiles = []
    for key in known:
        records = [source.get(key, {}) for source in (cache, operators, whitelist, banned)]
        name = online.get(key) or next(
            (str(record["name"]) for record in records if record.get("name")), key
        )
        player_uuid = next(
            (_normalized_uuid(str(record.get("uuid", ""))) for record in records if record.get("uuid")),
            None,
        )
        stats_paths, activity_paths = _player_paths(world, player_uuid or "")
        play_time = next(
            (value for path in stats_paths if (value := _play_time_seconds(path)) is not None),
            None,
        )
        profiles.append(
            PlayerProfile(
                name=name,
                player_uuid=player_uuid,
                online=key in online,
                last_active=_last_active(activity_paths),
                play_time_seconds=play_time if player_uuid else None,
                operator=key in operators,
                whitelisted=key in whitelist,
                banned=key in banned,
            )
        )
    return sorted(profiles, key=lambda player: (not player.online, player.name.casefold()))

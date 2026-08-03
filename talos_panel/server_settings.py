import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field


class ServerSettingsError(Exception):
    pass


class ServerProperties(BaseModel):
    motd: str = Field(default="A Minecraft Server", min_length=1, max_length=100)
    gamemode: str = Field(default="survival", pattern=r"^(survival|creative|adventure|spectator)$")
    difficulty: str = Field(default="easy", pattern=r"^(peaceful|easy|normal|hard)$")
    max_players: int = Field(default=20, ge=1, le=1000)
    whitelist: bool = False
    pvp: bool = True
    allow_flight: bool = False
    view_distance: int = Field(default=10, ge=2, le=32)
    simulation_distance: int = Field(default=10, ge=2, le=32)


PROPERTY_FIELDS = {
    "motd": "motd",
    "gamemode": "gamemode",
    "difficulty": "difficulty",
    "max-players": "max_players",
    "white-list": "whitelist",
    "pvp": "pvp",
    "allow-flight": "allow_flight",
    "view-distance": "view_distance",
    "simulation-distance": "simulation_distance",
}
FIELD_PROPERTIES = {field: key for key, field in PROPERTY_FIELDS.items()}
LEGACY_GAMEMODES = {"0": "survival", "1": "creative", "2": "adventure", "3": "spectator"}
LEGACY_DIFFICULTIES = {"0": "peaceful", "1": "easy", "2": "normal", "3": "hard"}
LIVE_SETTING_FIELDS = {"difficulty", "gamemode", "whitelist"}


def _parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def read_server_properties(root: Path) -> ServerProperties:
    path = root / "server.properties"
    if path.is_symlink():
        raise ServerSettingsError("Refusing to read a symbolic link as server.properties")
    if not path.exists():
        return ServerProperties()
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ServerSettingsError("Server properties could not be read") from exc
    values: dict[str, object] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        field = PROPERTY_FIELDS.get(key.strip())
        if field is None:
            continue
        value = value.strip()
        if field in {"whitelist", "pvp", "allow_flight"}:
            values[field] = _parse_bool(value)
        elif field in {"max_players", "view_distance", "simulation_distance"}:
            try:
                parsed = int(value)
            except ValueError:
                continue
            minimum, maximum = (1, 1000) if field == "max_players" else (2, 32)
            if minimum <= parsed <= maximum:
                values[field] = parsed
        elif field == "gamemode":
            normalized = LEGACY_GAMEMODES.get(value.lower(), value.lower())
            if normalized in {"survival", "creative", "adventure", "spectator"}:
                values[field] = normalized
        elif field == "difficulty":
            normalized = LEGACY_DIFFICULTIES.get(value.lower(), value.lower())
            if normalized in {"peaceful", "easy", "normal", "hard"}:
                values[field] = normalized
        elif field == "motd":
            values[field] = value[:100] or ServerProperties.model_fields["motd"].default
        else:
            values[field] = value
    return ServerProperties.model_validate(values)


def changed_setting_fields(before: ServerProperties, after: ServerProperties) -> set[str]:
    return {
        field
        for field in ServerProperties.model_fields
        if getattr(before, field) != getattr(after, field)
    }


def live_setting_commands(
    before: ServerProperties, after: ServerProperties
) -> list[tuple[str, str]]:
    changed = changed_setting_fields(before, after)
    commands: list[tuple[str, str]] = []
    if "difficulty" in changed:
        commands.append(("difficulty", f"difficulty {after.difficulty}"))
    if "gamemode" in changed:
        commands.append(("gamemode", f"defaultgamemode {after.gamemode}"))
    if "whitelist" in changed:
        commands.append(("whitelist", f"whitelist {'on' if after.whitelist else 'off'}"))
    return commands


def write_server_properties(root: Path, settings: ServerProperties) -> None:
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "server.properties"
    if destination.is_symlink():
        raise ServerSettingsError("Refusing to replace a symbolic link as server.properties")
    try:
        existing = destination.read_text(encoding="utf-8").splitlines() if destination.exists() else []
    except (OSError, UnicodeError) as exc:
        raise ServerSettingsError("Server properties could not be read") from exc

    serialized = {
        "motd": settings.motd.replace("\r", " ").replace("\n", " "),
        "gamemode": settings.gamemode,
        "difficulty": settings.difficulty,
        "max-players": str(settings.max_players),
        "white-list": str(settings.whitelist).lower(),
        "pvp": str(settings.pvp).lower(),
        "allow-flight": str(settings.allow_flight).lower(),
        "view-distance": str(settings.view_distance),
        "simulation-distance": str(settings.simulation_distance),
    }
    output: list[str] = []
    written: set[str] = set()
    for line in existing:
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key in serialized:
            if key not in written:
                output.append(f"{key}={serialized[key]}")
                written.add(key)
        else:
            output.append(line)
    for key, value in serialized.items():
        if key not in written:
            output.append(f"{key}={value}")

    descriptor, name = tempfile.mkstemp(prefix=".properties-", suffix=".tmp", dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(output) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except OSError as exc:
        raise ServerSettingsError("Server properties could not be saved") from exc
    finally:
        temporary.unlink(missing_ok=True)

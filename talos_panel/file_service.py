import os
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from fastapi import UploadFile

TEXT_SUFFIXES = {".conf", ".json", ".log", ".md", ".properties", ".toml", ".txt", ".yaml", ".yml"}
HIDDEN_ROOT_NAMES = {".trash"}
PROTECTED_ROOT_NAMES = {".trash", "eula.txt", "server.jar"}
LIVE_PROTECTED_SUFFIXES = {".dat", ".db", ".ldb", ".log", ".mca", ".sqlite", ".sqlite3"}
LIVE_PROTECTED_NAMES = {"level.dat", "level.dat_old", "session.lock"}


class FileServiceError(Exception):
    pass


@dataclass(frozen=True)
class FileEntry:
    name: str
    path: str
    is_directory: bool
    size: int | None
    editable: bool
    managed: bool


def mutation_requires_stopped_server(root: Path, value: str, operation: str) -> bool:
    """Return whether changing a path while Minecraft is running is unsafe.

    Ordinary configuration and newly uploaded files are safe because Talos writes
    them atomically. Live world data, databases, logs and loaded plugin JARs are
    kept immutable until the server stops.
    """
    path = resolve_server_path(root, value, allow_root=False)
    relative = path.relative_to(root)
    parts = relative.parts
    lowered_parts = tuple(part.lower() for part in parts)
    name = path.name.lower()

    if operation == "plugin_toggle":
        return True
    if name in LIVE_PROTECTED_NAMES or path.suffix.lower() in LIVE_PROTECTED_SUFFIXES:
        return True
    if "plugins" in lowered_parts and name.endswith((".jar", ".jar.disabled")):
        # A brand-new plugin is not loaded until restart. Existing plugin JARs
        # must not be moved or removed while the JVM may still use them.
        return operation != "upload" or path.exists()

    level_name = "world"
    properties = root / "server.properties"
    try:
        for line in properties.read_text(encoding="utf-8").splitlines():
            if line.startswith("level-name=") and line.partition("=")[2].strip():
                level_name = line.partition("=")[2].strip()
                break
    except (OSError, UnicodeError):
        pass
    world_roots = {level_name.lower(), f"{level_name.lower()}_nether", f"{level_name.lower()}_the_end"}
    return bool(lowered_parts and lowered_parts[0] in world_roots)


def _relative_path(value: str) -> PurePosixPath:
    if "\\" in value or "\x00" in value or any(ord(character) < 32 for character in value):
        raise FileServiceError("Invalid file path")
    relative = PurePosixPath(value or ".")
    if relative.is_absolute() or ".." in relative.parts:
        raise FileServiceError("Invalid file path")
    return relative


def resolve_server_path(
    root: Path,
    value: str,
    *,
    allow_root: bool = True,
    allow_protected: bool = False,
) -> Path:
    if root.is_symlink():
        raise FileServiceError("The server directory cannot be a symbolic link")
    relative = _relative_path(value)
    if not allow_protected and relative.parts and relative.parts[0] in PROTECTED_ROOT_NAMES:
        raise FileServiceError("This path is managed by Talos Panel")
    candidate = root.joinpath(*relative.parts)
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve(strict=False)
    if not resolved_candidate.is_relative_to(resolved_root):
        raise FileServiceError("File path escapes the server directory")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise FileServiceError("Symbolic links are not supported")
    if not allow_root and resolved_candidate == resolved_root:
        raise FileServiceError("The server root cannot be modified")
    return candidate


def list_directory(root: Path, value: str = "") -> list[FileEntry]:
    directory = resolve_server_path(root, value)
    if not directory.exists() or not directory.is_dir():
        raise FileServiceError("Directory does not exist")
    entries: list[FileEntry] = []
    for child in directory.iterdir():
        if child.is_symlink() or (directory == root and child.name in HIDDEN_ROOT_NAMES):
            continue
        relative = child.relative_to(root).as_posix()
        is_directory = child.is_dir()
        try:
            size = _directory_size(child) if is_directory else child.stat().st_size
        except OSError:
            continue
        entries.append(
            FileEntry(
                name=child.name,
                path=relative,
                is_directory=is_directory,
                size=size,
                editable=not is_directory and child.suffix.lower() in TEXT_SUFFIXES,
                managed=directory == root and child.name in PROTECTED_ROOT_NAMES,
            )
        )
    return sorted(entries, key=lambda item: (not item.is_directory, item.name.lower()))


def _directory_size(directory: Path) -> int:
    total = 0
    for current, directories, files in os.walk(directory, followlinks=False):
        current_path = Path(current)
        directories[:] = [name for name in directories if not (current_path / name).is_symlink()]
        for name in files:
            path = current_path / name
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except OSError:
                continue
    return total


def create_directory_archive(root: Path, value: str) -> tuple[Path, str]:
    source = resolve_server_path(root, value, allow_root=False)
    if not source.exists() or not source.is_dir():
        raise FileServiceError("Directory does not exist")
    descriptor, temporary_name = tempfile.mkstemp(prefix="talos-download-", suffix=".zip")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:
            for current, directories, files in os.walk(source, followlinks=False):
                current_path = Path(current)
                directories[:] = [
                    name for name in directories if not (current_path / name).is_symlink()
                ]
                relative_directory = current_path.relative_to(source)
                archive_directory = Path(source.name) / relative_directory
                if not directories and not files:
                    archive.writestr(f"{archive_directory.as_posix().rstrip('/')}/", b"")
                for name in files:
                    file_path = current_path / name
                    if file_path.is_symlink():
                        continue
                    archive.write(file_path, (archive_directory / name).as_posix())
        return temporary, f"{source.name}.zip"
    except (OSError, zipfile.BadZipFile) as exc:
        temporary.unlink(missing_ok=True)
        raise FileServiceError("The directory could not be archived") from exc


def read_text_file(root: Path, value: str, max_bytes: int) -> str:
    path = resolve_server_path(root, value, allow_root=False)
    if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
        raise FileServiceError("This file type cannot be edited")
    if path.stat().st_size > max_bytes:
        raise FileServiceError("The text file exceeds the edit limit")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FileServiceError("The text file could not be read as UTF-8") from exc


def write_text_file(root: Path, value: str, content: str, max_bytes: int) -> None:
    path = resolve_server_path(root, value, allow_root=False)
    if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
        raise FileServiceError("This file type cannot be edited")
    encoded = content.encode("utf-8")
    if len(encoded) > max_bytes:
        raise FileServiceError("The text file exceeds the edit limit")
    _atomic_write(path, encoded, overwrite=True)


def create_directory(root: Path, parent: str, name: str) -> Path:
    _validate_name(name)
    directory = resolve_server_path(root, parent) / name
    resolve_server_path(root, directory.relative_to(root).as_posix(), allow_root=False)
    try:
        directory.mkdir()
    except FileExistsError as exc:
        raise FileServiceError("A file or directory with this name already exists") from exc
    return directory


async def store_upload(
    root: Path,
    parent: str,
    upload: UploadFile,
    max_bytes: int,
    *,
    relative_name: str | None = None,
) -> Path:
    relative = _relative_path(relative_name or upload.filename or "")
    if not relative.parts:
        raise FileServiceError("Invalid filename")
    for part in relative.parts:
        _validate_name(part)
    destination = resolve_server_path(root, parent).joinpath(*relative.parts)
    resolve_server_path(root, destination.relative_to(root).as_posix(), allow_root=False)
    if destination.exists():
        raise FileServiceError("A file with this name already exists")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FileServiceError("The upload directory could not be created") from exc
    descriptor, temporary_name = tempfile.mkstemp(prefix=".upload-", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    total = 0
    try:
        with os.fdopen(descriptor, "wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise FileServiceError("The upload exceeds the configured size limit")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        return destination
    except (OSError, zipfile.BadZipFile) as exc:
        raise FileServiceError("The file could not be uploaded") from exc
    finally:
        temporary.unlink(missing_ok=True)
        await upload.close()


def archive_path(root: Path, value: str) -> Path:
    source = resolve_server_path(root, value, allow_root=False)
    if not source.exists():
        raise FileServiceError("File or directory does not exist")
    trash = root / ".trash" / "files"
    trash.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    safe_name = source.relative_to(root).as_posix().replace("/", "__")
    destination = trash / f"{timestamp}-{safe_name}"
    os.replace(source, destination)
    return destination


def set_plugin_enabled(root: Path, value: str, enabled: bool) -> Path:
    path = resolve_server_path(root, value, allow_root=False)
    plugins = root / "plugins"
    if path.parent != plugins or not path.is_file():
        raise FileServiceError("Plugin path is invalid")
    if enabled:
        if not path.name.endswith(".jar.disabled"):
            raise FileServiceError("Plugin is already enabled")
        destination = path.with_name(path.name.removesuffix(".disabled"))
    else:
        if path.suffix.lower() != ".jar":
            raise FileServiceError("Plugin is already disabled")
        destination = path.with_name(f"{path.name}.disabled")
    if destination.exists():
        raise FileServiceError("The target plugin filename already exists")
    os.replace(path, destination)
    return destination


def _validate_name(name: str) -> None:
    if (
        not name
        or len(name.encode("utf-8")) > 255
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or "\x00" in name
        or any(ord(character) < 32 for character in name)
    ):
        raise FileServiceError("Invalid filename")


def _atomic_write(destination: Path, content: bytes, *, overwrite: bool) -> None:
    if destination.is_symlink() or (destination.exists() and not overwrite):
        raise FileServiceError("The destination cannot be replaced")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}-", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except OSError as exc:
        raise FileServiceError("The file could not be saved") from exc
    finally:
        temporary.unlink(missing_ok=True)

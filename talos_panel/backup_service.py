import hashlib
import os
import re
import shutil
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

BACKUP_NAME = re.compile(r"^backup-\d{8}T\d{6}Z-[0-9a-f]{8}\.tar\.gz$")


class BackupError(Exception):
    pass


@dataclass(frozen=True)
class BackupArtifact:
    path: Path
    size_bytes: int
    checksum_sha256: str


def file_sha256(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def backup_directory(data_root: Path, server_id: uuid.UUID) -> Path:
    root = data_root.resolve()
    directory = root / "backups" / str(server_id)
    if not directory.resolve(strict=False).is_relative_to(root):
        raise BackupError("Invalid backup directory")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def resolve_backup_file(data_root: Path, server_id: uuid.UUID, file_name: str) -> Path:
    if not BACKUP_NAME.fullmatch(file_name) or Path(file_name).name != file_name:
        raise BackupError("Invalid backup filename")
    directory = backup_directory(data_root, server_id)
    path = directory / file_name
    if not path.is_file() or path.is_symlink():
        raise BackupError("Backup file does not exist")
    return path


def create_backup(server_root: Path, data_root: Path, server_id: uuid.UUID) -> BackupArtifact:
    if not server_root.is_dir() or server_root.is_symlink():
        raise BackupError("Server directory does not exist")
    destination_root = backup_directory(data_root, server_id)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    file_name = f"backup-{timestamp}-{uuid.uuid4().hex[:8]}.tar.gz"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".backup-", suffix=".tmp", dir=destination_root
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    destination = destination_root / file_name
    try:
        with tarfile.open(temporary, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            for current, directories, files in os.walk(server_root, followlinks=False):
                current_path = Path(current)
                directories[:] = [
                    name
                    for name in directories
                    if not (current_path / name).is_symlink()
                    and not (current_path == server_root and name == ".trash")
                ]
                for name in directories:
                    path = current_path / name
                    archive.add(path, path.relative_to(server_root).as_posix(), recursive=False)
                for name in files:
                    path = current_path / name
                    if not path.is_symlink():
                        archive.add(path, path.relative_to(server_root).as_posix(), recursive=False)
        os.replace(temporary, destination)
        return BackupArtifact(destination, destination.stat().st_size, file_sha256(destination))
    except (OSError, tarfile.TarError) as exc:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise BackupError("Backup could not be created") from exc


def delete_backup(data_root: Path, server_id: uuid.UUID, file_name: str) -> None:
    path = resolve_backup_file(data_root, server_id, file_name)
    try:
        path.unlink()
    except OSError as exc:
        raise BackupError("Backup could not be deleted") from exc


def restore_backup(
    server_root: Path,
    data_root: Path,
    server_id: uuid.UUID,
    file_name: str,
    max_restore_bytes: int,
    expected_checksum: str | None = None,
) -> None:
    archive_path = resolve_backup_file(data_root, server_id, file_name)
    if expected_checksum and file_sha256(archive_path) != expected_checksum:
        raise BackupError("Backup checksum verification failed")
    parent = server_root.parent
    staging = Path(tempfile.mkdtemp(prefix=f".restore-{server_id}-", dir=parent))
    previous = parent / f".restore-previous-{server_id}-{uuid.uuid4().hex}"
    moved_previous = False
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            total_size = sum(member.size for member in members if member.isfile())
            if total_size > max_restore_bytes:
                raise BackupError("Backup exceeds the configured restore limit")
            for member in members:
                relative = PurePosixPath(member.name)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not relative.parts
                    or member.issym()
                    or member.islnk()
                    or not (member.isdir() or member.isfile())
                ):
                    raise BackupError("Backup contains an unsafe entry")
                destination = staging.joinpath(*relative.parts)
                if not destination.resolve(strict=False).is_relative_to(staging.resolve()):
                    raise BackupError("Backup entry escapes the server directory")
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise BackupError("Backup contains an unreadable file")
                with source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                destination.chmod(member.mode & 0o777)
        if server_root.exists():
            os.replace(server_root, previous)
            moved_previous = True
        os.replace(staging, server_root)
        if moved_previous:
            shutil.rmtree(previous, ignore_errors=True)
    except BackupError:
        if moved_previous and not server_root.exists() and previous.exists():
            os.replace(previous, server_root)
        raise
    except (OSError, tarfile.TarError) as exc:
        if moved_previous and not server_root.exists() and previous.exists():
            os.replace(previous, server_root)
        raise BackupError("Backup could not be restored") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path


def archive_server_directory(data_root: Path, server_id: uuid.UUID) -> Path | None:
    servers_root = data_root / "servers"
    source = servers_root / str(server_id)
    if not source.exists() and not source.is_symlink():
        return None
    if source.parent != servers_root or source.name != str(server_id):
        raise ValueError("Invalid server directory")
    trash = servers_root / ".trash"
    trash.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = trash / f"{server_id}-{timestamp}"
    os.replace(source, destination)
    return destination

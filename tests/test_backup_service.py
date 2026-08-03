import hashlib
import io
import tarfile
import uuid
from pathlib import Path

import pytest

from talos_panel.backup_service import (
    BackupError,
    backup_directory,
    create_backup,
    delete_backup,
    restore_backup,
)


def test_backup_create_restore_and_delete_round_trip(tmp_path: Path) -> None:
    server_id = uuid.uuid4()
    server_root = tmp_path / "servers" / str(server_id)
    (server_root / "world").mkdir(parents=True)
    (server_root / "world" / "level.dat").write_bytes(b"original-world")
    (server_root / ".trash").mkdir()
    (server_root / ".trash" / "deleted.txt").write_text("skip", encoding="utf-8")
    (server_root / "linked").symlink_to(tmp_path)

    artifact = create_backup(server_root, tmp_path, server_id)

    assert artifact.path.is_file()
    assert artifact.size_bytes == artifact.path.stat().st_size
    assert artifact.checksum_sha256 == hashlib.sha256(artifact.path.read_bytes()).hexdigest()
    with tarfile.open(artifact.path, "r:gz") as archive:
        names = archive.getnames()
        assert "world/level.dat" in names
        assert not any(name.startswith(".trash") for name in names)
        assert "linked" not in names

    (server_root / "world" / "level.dat").write_bytes(b"changed")
    (server_root / "new-file.txt").write_text("remove", encoding="utf-8")
    restore_backup(
        server_root,
        tmp_path,
        server_id,
        artifact.path.name,
        1024 * 1024,
        artifact.checksum_sha256,
    )

    assert (server_root / "world" / "level.dat").read_bytes() == b"original-world"
    assert not (server_root / "new-file.txt").exists()
    delete_backup(tmp_path, server_id, artifact.path.name)
    assert not artifact.path.exists()


def test_restore_rejects_unsafe_archive_entries(tmp_path: Path) -> None:
    server_id = uuid.uuid4()
    server_root = tmp_path / "servers" / str(server_id)
    server_root.mkdir(parents=True)
    (server_root / "safe.txt").write_text("safe", encoding="utf-8")
    archive_path = backup_directory(tmp_path, server_id) / "backup-20260803T120000Z-deadbeef.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        entry = tarfile.TarInfo("../outside.txt")
        entry.size = 6
        archive.addfile(entry, io.BytesIO(b"unsafe"))

    with pytest.raises(BackupError, match="unsafe"):
        restore_backup(server_root, tmp_path, server_id, archive_path.name, 1024)

    assert (server_root / "safe.txt").read_text(encoding="utf-8") == "safe"
    assert not (tmp_path / "outside.txt").exists()


def test_restore_rejects_checksum_mismatch(tmp_path: Path) -> None:
    server_id = uuid.uuid4()
    server_root = tmp_path / "servers" / str(server_id)
    server_root.mkdir(parents=True)
    artifact = create_backup(server_root, tmp_path, server_id)

    with pytest.raises(BackupError, match="checksum"):
        restore_backup(server_root, tmp_path, server_id, artifact.path.name, 1024, "0" * 64)

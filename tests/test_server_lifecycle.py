import uuid
from pathlib import Path

from talos_panel.server_lifecycle import archive_server_directory


def test_archive_moves_only_exact_server_directory_to_trash(tmp_path: Path) -> None:
    server_id = uuid.uuid4()
    source = tmp_path / "servers" / str(server_id)
    source.mkdir(parents=True)
    (source / "world.dat").write_bytes(b"world")

    destination = archive_server_directory(tmp_path, server_id)

    assert destination is not None
    assert destination.parent == tmp_path / "servers" / ".trash"
    assert (destination / "world.dat").read_bytes() == b"world"
    assert not source.exists()


def test_archive_missing_server_is_idempotent(tmp_path: Path) -> None:
    assert archive_server_directory(tmp_path, uuid.uuid4()) is None

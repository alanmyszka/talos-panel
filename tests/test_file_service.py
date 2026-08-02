import io
import zipfile
from pathlib import Path

import pytest
from fastapi import UploadFile

from talos_panel.file_service import (
    FileServiceError,
    archive_path,
    list_directory,
    read_text_file,
    resolve_server_path,
    store_upload,
    write_text_file,
)


def plugin_jar(*, descriptor: bool = True) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("Example.class", b"bytecode")
        if descriptor:
            archive.writestr("plugin.yml", "name: Example\nmain: example.Plugin\nversion: 1\n")
    return output.getvalue()


def test_paths_reject_traversal_absolute_paths_and_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "server"
    root.mkdir()
    (root / "link").symlink_to(outside)

    for value in ("../outside", "/etc/passwd", "link/file.txt", "folder\\file"):
        with pytest.raises(FileServiceError):
            resolve_server_path(root, value)

    linked_root = tmp_path / "linked-server"
    linked_root.symlink_to(root)
    with pytest.raises(FileServiceError, match="server directory"):
        resolve_server_path(linked_root, "world")


def test_listing_hides_protected_files_and_symlinks(tmp_path: Path) -> None:
    (tmp_path / "world").mkdir()
    (tmp_path / "server.jar").write_bytes(b"jar")
    (tmp_path / "eula.txt").write_text("eula=true", encoding="utf-8")
    (tmp_path / "server.properties").write_text("motd=Talos", encoding="utf-8")
    (tmp_path / "link").symlink_to(tmp_path / "world")

    entries = list_directory(tmp_path)

    assert [entry.name for entry in entries] == ["world", "server.properties"]
    assert entries[1].editable is True


def test_text_edits_are_bounded_and_atomic(tmp_path: Path) -> None:
    path = tmp_path / "server.properties"
    path.write_text("motd=Old\n", encoding="utf-8")

    write_text_file(tmp_path, "server.properties", "motd=New\n", 100)

    assert read_text_file(tmp_path, "server.properties", 100) == "motd=New\n"
    with pytest.raises(FileServiceError, match="limit"):
        write_text_file(tmp_path, "server.properties", "x" * 101, 100)
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
async def test_plugin_upload_requires_descriptor_and_is_atomic(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    content = plugin_jar()
    valid = UploadFile(file=io.BytesIO(content), filename="Example.jar")
    destination = await store_upload(tmp_path, "plugins", valid, 1024 * 1024, plugin=True)
    assert destination.read_bytes() == content

    invalid = UploadFile(file=io.BytesIO(plugin_jar(descriptor=False)), filename="Bad.jar")
    with pytest.raises(FileServiceError, match="descriptor"):
        await store_upload(tmp_path, "plugins", invalid, 1024 * 1024, plugin=True)
    assert not (tmp_path / "plugins" / "Bad.jar").exists()
    assert not list((tmp_path / "plugins").glob("*.tmp"))


def test_delete_moves_item_to_server_trash(tmp_path: Path) -> None:
    target = tmp_path / "world" / "level.dat"
    target.parent.mkdir()
    target.write_bytes(b"world")

    archived = archive_path(tmp_path, "world/level.dat")

    assert archived.read_bytes() == b"world"
    assert archived.is_relative_to(tmp_path / ".trash" / "files")
    assert not target.exists()

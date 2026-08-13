import io
import zipfile
from pathlib import Path

import pytest
from fastapi import UploadFile

from talos_panel.file_service import (
    FileServiceError,
    archive_path,
    copy_path,
    create_directory_archive,
    extract_zip,
    list_directory,
    move_path,
    mutation_requires_stopped_server,
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


def test_listing_shows_server_files_but_hides_internal_files_and_symlinks(tmp_path: Path) -> None:
    (tmp_path / "world").mkdir()
    (tmp_path / "server.jar").write_bytes(b"jar")
    (tmp_path / "eula.txt").write_text("eula=true", encoding="utf-8")
    (tmp_path / "server.properties").write_text("motd=Talos", encoding="utf-8")
    (tmp_path / "link").symlink_to(tmp_path / "world")

    entries = list_directory(tmp_path)

    assert [entry.name for entry in entries] == [
        "world",
        "eula.txt",
        "server.jar",
        "server.properties",
    ]
    assert entries[-1].editable is True
    assert resolve_server_path(tmp_path, "server.jar").is_file()
    assert resolve_server_path(tmp_path, "eula.txt").is_file()


def test_server_jar_and_eula_support_regular_file_operations(tmp_path: Path) -> None:
    (tmp_path / "server.jar").write_bytes(b"jar")
    (tmp_path / "eula.txt").write_text("eula=true", encoding="utf-8")
    (tmp_path / "storage").mkdir()

    moved = move_path(tmp_path, "server.jar", "storage", "minecraft.jar")
    copied = copy_path(tmp_path, "eula.txt", "storage", "eula-copy.txt")
    archived = archive_path(tmp_path, "eula.txt")

    assert moved.read_bytes() == b"jar"
    assert copied.read_text(encoding="utf-8") == "eula=true"
    assert archived.read_text(encoding="utf-8") == "eula=true"


def test_listing_calculates_directory_size_without_following_symlinks(tmp_path: Path) -> None:
    directory = tmp_path / "world"
    directory.mkdir()
    (directory / "region.dat").write_bytes(b"region")
    outside = tmp_path / "outside.dat"
    outside.write_bytes(b"outside-content")
    (directory / "linked.dat").symlink_to(outside)

    entry = list_directory(tmp_path)[0]

    assert entry.name == "world"
    assert entry.size == 6


def test_directory_download_creates_zip_and_ignores_symlinks(tmp_path: Path) -> None:
    directory = tmp_path / "world"
    (directory / "region").mkdir(parents=True)
    (directory / "region" / "r.0.0.mca").write_bytes(b"region")
    (directory / "empty").mkdir()
    (directory / "unsafe").symlink_to(tmp_path)

    archive_path, download_name = create_directory_archive(tmp_path, "world")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            assert download_name == "world.zip"
            assert "world/region/r.0.0.mca" in archive.namelist()
            assert "world/empty/" in archive.namelist()
            assert not any("unsafe" in name for name in archive.namelist())
    finally:
        archive_path.unlink()


def test_text_edits_are_bounded_and_atomic(tmp_path: Path) -> None:
    path = tmp_path / "server.properties"
    path.write_text("motd=Old\n", encoding="utf-8")

    write_text_file(tmp_path, "server.properties", "motd=New\n", 100)

    assert read_text_file(tmp_path, "server.properties", 100) == "motd=New\n"
    with pytest.raises(FileServiceError, match="limit"):
        write_text_file(tmp_path, "server.properties", "x" * 101, 100)
    assert not list(tmp_path.glob("*.tmp"))
    assert path.stat().st_uid == tmp_path.stat().st_uid
    assert path.stat().st_gid == tmp_path.stat().st_gid


@pytest.mark.asyncio
async def test_upload_accepts_jars_and_preserves_a_relative_directory(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    content = b"plugin-data"
    valid = UploadFile(file=io.BytesIO(content), filename="Example.jar")
    destination = await store_upload(
        tmp_path,
        "plugins",
        valid,
        1024 * 1024,
        relative_name="Example/config/Example.jar",
    )
    assert destination.read_bytes() == content
    assert destination == tmp_path / "plugins" / "Example" / "config" / "Example.jar"
    assert destination.stat().st_uid == tmp_path.stat().st_uid
    assert destination.stat().st_gid == tmp_path.stat().st_gid


@pytest.mark.asyncio
async def test_upload_rejects_relative_path_traversal(tmp_path: Path) -> None:
    upload = UploadFile(file=io.BytesIO(b"unsafe"), filename="unsafe.txt")
    with pytest.raises(FileServiceError, match="Invalid file path"):
        await store_upload(
            tmp_path, "", upload, 1024, relative_name="folder/../../unsafe.txt"
        )


def test_delete_moves_item_to_server_trash(tmp_path: Path) -> None:
    target = tmp_path / "world" / "level.dat"
    target.parent.mkdir()
    target.write_bytes(b"world")

    archived = archive_path(tmp_path, "world/level.dat")

    assert archived.read_bytes() == b"world"
    assert archived.is_relative_to(tmp_path / ".trash" / "files")
    assert not target.exists()


def test_move_rename_and_copy_preserve_contents(tmp_path: Path) -> None:
    source = tmp_path / "plugins" / "Example"
    source.mkdir(parents=True)
    (source / "config.yml").write_text("enabled: true", encoding="utf-8")
    (tmp_path / "archive").mkdir()

    renamed = move_path(tmp_path, "plugins/Example", "plugins", "Renamed")
    copied = copy_path(tmp_path, "plugins/Renamed", "archive", "Renamed copy")

    assert renamed == tmp_path / "plugins" / "Renamed"
    assert copied.joinpath("config.yml").read_text(encoding="utf-8") == "enabled: true"
    assert renamed.joinpath("config.yml").is_file()


def test_copy_rejects_destination_inside_source_and_nested_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(FileServiceError, match="itself"):
        copy_path(tmp_path, "source", "source", "copy")
    (source / "link").symlink_to(tmp_path)
    with pytest.raises(FileServiceError, match="symbolic links"):
        copy_path(tmp_path, "source", "", "copy")


def test_extract_zip_is_bounded_and_blocks_traversal_and_symlinks(tmp_path: Path) -> None:
    valid = tmp_path / "valid.zip"
    with zipfile.ZipFile(valid, "w") as archive:
        archive.writestr("Example/config.yml", "enabled: true")
        archive.writestr("Example/empty/", b"")
    assert extract_zip(tmp_path, "valid.zip", "plugins", 1024) == 1
    assert (tmp_path / "plugins" / "Example" / "config.yml").is_file()

    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")
    with pytest.raises(FileServiceError, match="Invalid file path"):
        extract_zip(tmp_path, "unsafe.zip", "", 1024)
    assert not (tmp_path.parent / "outside.txt").exists()

    symlink = tmp_path / "symlink.zip"
    with zipfile.ZipFile(symlink, "w") as archive:
        entry = zipfile.ZipInfo("link")
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        archive.writestr(entry, "/etc")
    with pytest.raises(FileServiceError, match="symbolic links"):
        extract_zip(tmp_path, "symlink.zip", "", 1024)


def test_extract_zip_refuses_overwrite_and_size_limit(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("keep", encoding="utf-8")
    archive_path = tmp_path / "files.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("existing.txt", "replace")
    with pytest.raises(FileServiceError, match="overwrite"):
        extract_zip(tmp_path, "files.zip", "", 1024)
    assert (tmp_path / "existing.txt").read_text(encoding="utf-8") == "keep"

    large = tmp_path / "large.zip"
    with zipfile.ZipFile(large, "w") as archive:
        archive.writestr("large.bin", b"x" * 20)
    with pytest.raises(FileServiceError, match="size limit"):
        extract_zip(tmp_path, "large.zip", "", 10)


def test_live_mutations_only_protect_active_server_data(tmp_path: Path) -> None:
    (tmp_path / "server.properties").write_text("level-name=survival\n", encoding="utf-8")
    (tmp_path / "survival" / "region").mkdir(parents=True)
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / "Loaded.jar").write_bytes(b"jar")

    assert not mutation_requires_stopped_server(tmp_path, "server.properties", "edit")
    assert not mutation_requires_stopped_server(tmp_path, "configs/new", "mkdir")
    assert not mutation_requires_stopped_server(tmp_path, "plugins/New.jar", "upload")
    assert mutation_requires_stopped_server(tmp_path, "survival/region/r.0.0.mca", "delete")
    assert mutation_requires_stopped_server(tmp_path, "plugins/Loaded.jar", "delete")
    assert mutation_requires_stopped_server(tmp_path, "plugins/Loaded.jar", "plugin_toggle")

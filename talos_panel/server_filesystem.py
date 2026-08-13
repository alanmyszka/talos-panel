import os
from pathlib import Path


def apply_server_ownership(root: Path, path: Path) -> None:
    """Make a panel-created item accessible to the server process.

    The itzg container makes its mounted data directory owned by the UID/GID it
    runs as.  The panel can therefore follow that directory instead of assuming
    the image's default 1000:1000 identity.
    """
    identity = root.stat()
    os.chown(path, identity.st_uid, identity.st_gid, follow_symlinks=False)


def apply_server_ownership_tree(root: Path, path: Path) -> None:
    apply_server_ownership(root, path)
    if not path.is_dir():
        return
    for current, directories, files in os.walk(path, followlinks=False):
        current_path = Path(current)
        for name in directories + files:
            child = current_path / name
            if not child.is_symlink():
                apply_server_ownership(root, child)

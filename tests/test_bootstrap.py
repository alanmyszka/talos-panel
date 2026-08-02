from pathlib import Path

from talos_panel.bootstrap import ensure_secret


def test_secret_is_generated_once_and_reused(tmp_path: Path) -> None:
    secret_file = tmp_path / "secrets" / "app-secret"
    first = ensure_secret(secret_file)
    second = ensure_secret(secret_file)

    assert first == second
    assert len(first) >= 48
    assert secret_file.stat().st_mode & 0o777 == 0o600

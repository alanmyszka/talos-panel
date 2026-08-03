from pathlib import Path

from talos_panel.config import Settings
from talos_panel.security_service import security_findings


def test_security_review_warns_about_development_defaults(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.write_text("x", encoding="utf-8")
    secret.chmod(0o644)
    settings = Settings(
        database_url="postgresql+asyncpg://talos_panel:change-me@postgres/talos_panel",
        secret_file=secret,
        secure_cookies=False,
    )

    titles = {finding["title"] for finding in security_findings(settings, None)}

    assert "HTTPS cookies are disabled" in titles
    assert "Default database password" in titles
    assert "Application secret permissions are broad" in titles
    assert "Docker socket grants host-level control" in titles

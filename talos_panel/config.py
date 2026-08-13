from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Talos Panel"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://talos_panel:change-me@postgres/talos_panel"
    secret_file: Path = Path("/data/secrets/app-secret")
    minecraft_data_root: Path = Path("/data/servers")
    minecraft_host_data_root: Path = Path("/data/servers")
    minecraft_network: str = "talos-network"
    minecraft_status_host: str = "host.docker.internal"
    minecraft_status_timeout_seconds: float = 1.0
    player_avatar_cache_hours: int = 24
    player_avatar_timeout_seconds: float = 5.0
    max_player_skin_bytes: int = 1024 * 1024
    operations_poll_seconds: int = 60
    metric_retention_days: int = 7
    crash_restart_limit: int = 3
    download_timeout_seconds: float = 60.0
    max_file_upload_bytes: int = 128 * 1024 * 1024
    max_text_edit_bytes: int = 1024 * 1024
    max_backup_restore_bytes: int = 20 * 1024 * 1024 * 1024
    download_user_agent: str = "talos-panel/0.1.0 (https://github.com/talos-panel/talos-panel)"
    session_cookie_name: str = "talos_session"
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    secure_cookies: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()

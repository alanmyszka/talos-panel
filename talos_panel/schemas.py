import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from talos_panel.jvm_flags import JvmFlagsError, parse_custom_jvm_flags
from talos_panel.models import DesiredState, InstallationState, ServerType
from talos_panel.server_settings import ServerProperties


class ServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    server_type: ServerType
    game_version: str = Field(min_length=3, max_length=32, pattern=r"^\d+(?:\.\d+){1,2}$")
    memory_mb: int = Field(ge=1024, le=32768)
    host_port: int = Field(ge=1024, le=65535)
    use_aikar_flags: bool = False
    custom_jvm_flags: str = Field(default="", max_length=2048)
    settings: ServerProperties = Field(default_factory=ServerProperties)

    @field_validator("custom_jvm_flags")
    @classmethod
    def validate_custom_jvm_flags(cls, value: str) -> str:
        try:
            parse_custom_jvm_flags(value)
        except JvmFlagsError as exc:
            raise ValueError(str(exc)) from exc
        return value.strip()


class ServerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    server_type: ServerType
    game_version: str
    memory_mb: int
    host_port: int
    desired_state: DesiredState
    container_id: str | None
    installation_state: InstallationState | None
    installed_version: str | None
    java_version: int | None
    created_at: datetime
    updated_at: datetime


class RuntimeStatus(BaseModel):
    server_id: uuid.UUID
    state: str
    container_id: str | None = None
    started_at: datetime | None = None
    cpu_percent: float | None = None
    memory_bytes: int | None = None
    memory_limit_bytes: int | None = None


class Health(BaseModel):
    status: str = "ok"


class InstallationCreate(BaseModel):
    eula_accepted: bool


class InstallationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    server_id: uuid.UUID
    state: InstallationState
    requested_version: str
    installed_version: str | None
    build_id: str | None
    java_version: int | None
    bytes_downloaded: int
    total_bytes: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class VersionList(BaseModel):
    server_type: ServerType
    versions: list[str]


class ServerSettingsRead(ServerProperties):
    memory_mb: int
    host_port: int


class ServerSettingsUpdate(ServerProperties):
    memory_mb: int = Field(ge=1024, le=32768)
    host_port: int = Field(ge=1024, le=65535)


class ServerDelete(BaseModel):
    confirmation: str = Field(min_length=1, max_length=80)

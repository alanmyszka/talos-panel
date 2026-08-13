import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from talos_panel.db import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"


class ServerRole(str, enum.Enum):
    OWNER = "owner"
    OPERATOR = "operator"


class ServerType(str, enum.Enum):
    PAPER = "paper"
    VANILLA = "vanilla"
    PURPUR = "purpur"
    PUFFERFISH = "pufferfish"
    FABRIC = "fabric"
    QUILT = "quilt"
    FORGE = "forge"
    NEOFORGE = "neoforge"


class DesiredState(str, enum.Enum):
    RUNNING = "running"
    STOPPED = "stopped"


class InstallationState(str, enum.Enum):
    QUEUED = "queued"
    RESOLVING = "resolving"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    INSTALLING = "installing"
    COMPLETED = "completed"
    FAILED = "failed"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), default=UserRole.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_recovery_codes: Mapped[str | None] = mapped_column(Text, nullable=True)
    memberships: Mapped[list["ServerMember"]] = relationship(back_populates="user")
    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(TimestampMixin, Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_secret: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user: Mapped[User] = relationship(back_populates="sessions")


class AuditEvent(TimestampMixin, Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    server_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("minecraft_servers.id", ondelete="SET NULL"),
        nullable=True,
    )
    server_reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    server_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)


class MinecraftServer(TimestampMixin, Base):
    __tablename__ = "minecraft_servers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80))
    server_type: Mapped[ServerType] = mapped_column(Enum(ServerType, name="server_type"))
    game_version: Mapped[str] = mapped_column(String(32))
    memory_mb: Mapped[int] = mapped_column(Integer)
    host_port: Mapped[int] = mapped_column(Integer, unique=True)
    use_aikar_flags: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_jvm_flags: Mapped[str] = mapped_column(Text, default="")
    desired_state: Mapped[DesiredState] = mapped_column(
        Enum(DesiredState, name="desired_state"), default=DesiredState.STOPPED
    )
    container_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    installation_state: Mapped[InstallationState | None] = mapped_column(
        Enum(InstallationState, name="installation_state"), nullable=True
    )
    installed_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    java_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backup_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    backup_retention: Mapped[int] = mapped_column(Integer, default=7)
    next_backup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_restart: Mapped[bool] = mapped_column(Boolean, default=False)
    restart_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_runtime_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    members: Mapped[list["ServerMember"]] = relationship(
        back_populates="server", cascade="all, delete-orphan"
    )
    backups: Mapped[list["Backup"]] = relationship(
        back_populates="server", cascade="all, delete-orphan"
    )
    installation_jobs: Mapped[list["InstallationJob"]] = relationship(
        back_populates="server", cascade="all, delete-orphan"
    )
    update_jobs: Mapped[list["ServerUpdate"]] = relationship(
        back_populates="server", cascade="all, delete-orphan"
    )
    metric_samples: Mapped[list["MetricSample"]] = relationship(
        back_populates="server", cascade="all, delete-orphan"
    )


class InstallationJob(TimestampMixin, Base):
    __tablename__ = "installation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("minecraft_servers.id", ondelete="CASCADE"), index=True
    )
    state: Mapped[InstallationState] = mapped_column(
        Enum(InstallationState, name="installation_state"), default=InstallationState.QUEUED
    )
    requested_version: Mapped[str] = mapped_column(String(32))
    installed_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    build_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    java_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_algorithm: Mapped[str | None] = mapped_column(String(16), nullable=True)
    expected_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actual_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bytes_downloaded: Mapped[int] = mapped_column(BigInteger, default=0)
    total_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    eula_accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    server: Mapped[MinecraftServer] = relationship(back_populates="installation_jobs")


class ServerMember(TimestampMixin, Base):
    __tablename__ = "server_members"
    __table_args__ = (UniqueConstraint("server_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("minecraft_servers.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    role: Mapped[ServerRole] = mapped_column(Enum(ServerRole, name="server_role"))
    server: Mapped[MinecraftServer] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class Backup(TimestampMixin, Base):
    __tablename__ = "backups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("minecraft_servers.id", ondelete="CASCADE"), index=True
    )
    file_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    installed_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    game_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    java_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    server: Mapped[MinecraftServer] = relationship(back_populates="backups")


class ServerUpdate(TimestampMixin, Base):
    __tablename__ = "server_updates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("minecraft_servers.id", ondelete="CASCADE"), index=True
    )
    backup_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("backups.id", ondelete="SET NULL"), nullable=True
    )
    from_version: Mapped[str] = mapped_column(String(32))
    to_version: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    server: Mapped[MinecraftServer] = relationship(back_populates="update_jobs")


class MetricSample(Base):
    __tablename__ = "metric_samples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("minecraft_servers.id", ondelete="CASCADE"), index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    runtime_state: Mapped[str] = mapped_column(String(32))
    cpu_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    players_online: Mapped[int | None] = mapped_column(Integer, nullable=True)
    server: Mapped[MinecraftServer] = relationship(back_populates="metric_samples")

# Модели этапа 2: users, roles, role_permissions, user_roles (LLD §2.2).
# Полная модель — этапы 3–10; таблицы не затронутых этапов добавляются своими миграциями.
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_uuid


class User(TimestampMixin, Base):
    """users (FR-001, FR-151; минимум ПДн). Provisioning при первом запросе (§6.1 HLD)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    keycloak_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_deactivated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_service: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    email_cache: Mapped[str | None] = mapped_column(Text, nullable=True)  # 16.1-119
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class Role(TimestampMixin, Base):
    """roles — шаблоны ролей (FR-008)."""

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    is_virtual_all_users: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )  # FR-009

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan", lazy="selectin"
    )


class PermissionCode(str, enum.Enum):
    """permission_code (LLD §2.1, FR-106)."""

    view = "view"
    create = "create"
    edit = "edit"
    delete = "delete"
    review = "review"
    publish = "publish"
    archive = "archive"
    copy = "copy"
    move = "move"
    download = "download"
    manage_permissions = "manage_permissions"


class RolePermission(Base):
    """role_permissions — состав шаблона (FR-008)."""

    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission: Mapped[PermissionCode] = mapped_column(
        String(32), primary_key=True
    )

    role: Mapped[Role] = relationship(back_populates="permissions")


class UserRole(Base):
    """user_roles (FR-007, FR-010): совмещение нескольких ролей = несколько записей."""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_roles_pair"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )

    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship(lazy="selectin")

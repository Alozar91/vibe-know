# Модели этапа 3: groups, material_types, attributes, dictionaries,
# dictionary_values, attribute_type_bindings, tags (LLD §2.1–2.2).
# models этапа 2 (users/roles) — в начале файла; materials/attribute_values — этап 4.
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
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


class MaterialStatus(str, enum.Enum):
    """material_status (LLD §2.1, FR-065)."""

    draft = "draft"
    in_review = "in_review"
    approved = "approved"
    published = "published"
    archived = "archived"


class AttrValueType(str, enum.Enum):
    """attr_value_type (LLD §2.1, FR-044)."""

    string = "string"
    number = "number"
    date = "date"
    url = "url"
    dictionary = "dictionary"


class Group(TimestampMixin, Base):
    """groups (4.1, FR-015–023): materialized path; перенос не предусмотрен (FR-023)."""

    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)  # ≤ name_max_len (FR-017) — сервис
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)  # lower(trim(name)), «е»≠«ё» (16.1-54)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("groups.id", ondelete="RESTRICT"), nullable=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)  # /id1/…/idN/ — неизменен (FR-023)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    parent: Mapped["Group | None"] = relationship(
        back_populates="children", remote_side=lambda: [Group.id]
    )
    children: Mapped[list["Group"]] = relationship(back_populates="parent")

    __table_args__ = (
        Index("ix_groups_parent_id", "parent_id"),
        Index("ix_groups_path", "path"),
        Index("ix_groups_normalized", "parent_id", "normalized_name"),
    )


class MaterialType(TimestampMixin, Base):
    """material_types (6.1, FR-043): удаление — при отсутствии неудалённых материалов (FR-050)."""

    __tablename__ = "material_types"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)

    bindings: Mapped[list["AttributeTypeBinding"]] = relationship(
        back_populates="material_type", cascade="all, delete-orphan", lazy="selectin"
    )


class Attribute(TimestampMixin, Base):
    """attributes — глобальный пул (6.1, FR-044/045). value_type/is_multivalue неизменяемы (FR-045)."""

    __tablename__ = "attributes"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    value_type: Mapped[AttrValueType] = mapped_column(String(16), nullable=False)
    is_multivalue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    display_order: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    dictionary_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("dictionaries.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    dictionary: Mapped["Dictionary | None"] = relationship(lazy="selectin")
    bindings: Mapped[list["AttributeTypeBinding"]] = relationship(
        back_populates="attribute", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        # dictionary_id NOT NULL при value_type='dictionary' (LLD §2.2)
        CheckConstraint(
            "(value_type != 'dictionary') OR (dictionary_id IS NOT NULL)",
            name="dictionary_attr_requires_dict",
        ),
    )


class Dictionary(TimestampMixin, Base):
    """dictionaries (FR-047)."""

    __tablename__ = "dictionaries"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)

    values: Mapped[list["DictionaryValue"]] = relationship(
        back_populates="dictionary", cascade="all, delete-orphan", lazy="selectin",
        order_by="DictionaryValue.value",
    )


class DictionaryValue(TimestampMixin, Base):
    """dictionary_values (FR-047): удаление — запрет при использовании (сервис, этап 4+)."""

    __tablename__ = "dictionary_values"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    dictionary_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("dictionaries.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)

    dictionary: Mapped["Dictionary"] = relationship(back_populates="values")

    __table_args__ = (
        UniqueConstraint("dictionary_id", "value", name="uq_dictionary_values_pair"),
    )


class AttributeTypeBinding(Base):
    """attribute_type_bindings (FR-044): ≤ attributes_max_per_type (50) — сервис.

    Исключение атрибута из типа — DELETE записи, значения материалов остаются (FR-051).
    """

    __tablename__ = "attribute_type_bindings"

    type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("material_types.id", ondelete="CASCADE"),
        primary_key=True,
    )
    attribute_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("attributes.id", ondelete="CASCADE"),
        primary_key=True,
    )

    material_type: Mapped["MaterialType"] = relationship(back_populates="bindings")
    attribute: Mapped["Attribute"] = relationship(back_populates="bindings")


class Tag(TimestampMixin, Base):
    """tags — глобальный словарь (FR-052); слияние — FR-053; удаление — FR-054."""

    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)

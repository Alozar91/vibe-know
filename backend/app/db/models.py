# Модели этапа 3: groups, material_types, attributes, dictionaries,
# dictionary_values, attribute_type_bindings, tags (LLD §2.1–2.2).
# models этапа 2 (users/roles) — в начале файла; materials/attribute_values — этап 4.
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_uuid
from app.db.tsvector import TSVector


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


# ==========================================================================
# Этап 4: права (permission_snapshots/entries, §2.2, §3) и материалы (§2.2, 4.2)
# ==========================================================================

class ObjectType(str, enum.Enum):
    """object_type полиморфных прав (LLD §2.2)."""

    group = "group"
    material = "material"


class PermissionSnapshot(TimestampMixin, Base):
    """permission_snapshots (FR-099/100, 8.1): копия набора прав шаблона на объекте.

    object_id — без FK (полиморфный доступ); каскадное удаление — сервисом.
    """

    __tablename__ = "permission_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    object_type: Mapped[ObjectType] = mapped_column(String(16), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=True
    )  # NULL → виртуальная роль «Все пользователи» (FR-009)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    entries: Mapped[list["PermissionEntry"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan", lazy="selectin"
    )
    role: Mapped["Role"] = relationship(lazy="selectin")

    __table_args__ = (
        Index("ix_snapshots_object", "object_type", "object_id"),
    )


class PermissionEntry(Base):
    """permission_entries (8.3): отсутствие записи = «не задано»."""

    __tablename__ = "permission_entries"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("permission_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    permission: Mapped[PermissionCode] = mapped_column(String(32), primary_key=True)
    state: Mapped[str] = mapped_column(String(8), nullable=False)  # 'allow' | 'deny'

    snapshot: Mapped[PermissionSnapshot] = relationship(back_populates="entries")


class FileObject(TimestampMixin, Base):
    """file_objects (6.2, NFR-010): CAS-ключ silo; конвейер — этап 6 (заглушка scan_state)."""

    __tablename__ = "file_objects"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    cas_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # sha256 (§6.1)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    ref_count: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    scan_state: Mapped[str] = mapped_column(String(16), nullable=False, default="ready", server_default="ready")
    pdf_state: Mapped[str] = mapped_column(String(16), nullable=False, default="none", server_default="none")
    pdf_cas_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("ix_file_objects_cas", "cas_key"),
    )


class Material(TimestampMixin, Base):
    """materials (4.2, FR-024–028): одна группа, статус, версия = ETag (FR-093–095)."""

    __tablename__ = "materials"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("groups.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)  # ≤ 255 (FR-027) — сервис
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)  # lower(trim) — уникальность в группе
    type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("material_types.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[MaterialStatus] = mapped_column(
        String(16), nullable=False, default=MaterialStatus.draft, server_default="draft"
    )
    master_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("materials.id", ondelete="RESTRICT"), nullable=True
    )  # NULL — мастер/самостоятельный; один уровень (FR-032)
    author_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )  # авторство — видимость, не права (FR-014)
    signatory_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    signatory_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_editor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    current_file_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("file_objects.id", ondelete="RESTRICT"), nullable=True
    )  # NULL — «пустышка»
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)  # Markdown (16.1-4)
    text_out_of_sync: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Этап 8 (LLD §7.1): FTS-конфигурация и вектор (не generated — динамическая конфигурация)
    search_lang: Mapped[str] = mapped_column(String(20), nullable=False, server_default="russian")
    search_tsv: Mapped[str | None] = mapped_column(TSVector, nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    group: Mapped["Group"] = relationship(lazy="selectin")
    type: Mapped["MaterialType"] = relationship(lazy="selectin")
    author: Mapped["User"] = relationship(foreign_keys=[author_id], lazy="selectin")

    __table_args__ = (
        Index("ix_materials_group", "group_id"),
        Index("ix_materials_author", "author_id"),
        Index("ix_materials_status", "status"),
        # Этап 7 (LLD §2.3/§2.4): FR-032; список подчинённых/валидаторы
        CheckConstraint("master_id IS NULL OR master_id <> id", name="ck_materials_master_not_self"),
        Index("ix_materials_master", "master_id"),
        # Этап 8 (LLD §7.2): GIN search_tsv / GIN trgm name,text_content —
        # создаются миграцией 0008 (USING gin/trgm в декларативной модели
        # непортабелен на SQLite)
    )


class AttributeValue(TimestampMixin, Base):
    """attribute_values (6.1, FR-051): ровно одно из пяти значений NOT NULL (CHECK)."""

    __tablename__ = "attribute_values"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    material_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    attribute_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("attributes.id", ondelete="RESTRICT"), nullable=False
    )
    value_string: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_number: Mapped[float | None] = mapped_column(nullable=True)
    value_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    value_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    dictionary_value_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("dictionary_values.id", ondelete="RESTRICT"), nullable=True
    )

    attribute: Mapped["Attribute"] = relationship(lazy="selectin")

    __table_args__ = (
        Index("ix_attribute_values_material", "material_id"),
        CheckConstraint(
            "(CASE WHEN value_string IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN value_number IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN value_date IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN value_url IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN dictionary_value_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_attribute_values_one_value",
        ),
    )


class MaterialTag(Base):
    """material_tags (6.4): лимит 20 — сервис; FK без каскада (этап 4: RESTRICT)."""

    __tablename__ = "material_tags"
    __table_args__ = (
        UniqueConstraint("material_id", "tag_id", name="uq_material_tags_pair"),
        Index("ix_material_tags_tag", "tag_id"),
    )

    material_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tags.id", ondelete="RESTRICT"), primary_key=True
    )


# --- Этап 5: жизненный цикл (LLD §4.1, §2.2; FR-065–095) ---

class TransitionRule(Base):
    """transition_rules (7.4, FR-070–074): строка матрицы переходов.

    from_status NULL = «*» (любой статус, кроме «Архива»); правила с
    from_status='archived' запрещены (FR-073) — частичный UNIQUE-индекс +
    проверка сервиса (ARCHIVED_SOURCE_RULE_FORBIDDEN, §12.2).
    """

    __tablename__ = "transition_rules"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    from_status: Mapped[MaterialStatus | None] = mapped_column(String(16), nullable=True)  # NULL = «*»
    to_status: Mapped[MaterialStatus] = mapped_column(String(16), nullable=False)
    is_protected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    permissions: Mapped[list["TransitionRulePermission"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("from_status", "to_status", name="uq_transition_rules_pair"),
        Index(
            "ix_transition_rules_pair",
            "from_status", "to_status",
            unique=True,
            postgresql_where="from_status IS NULL OR from_status <> 'archived'",
        ),
    )


class TransitionRulePermission(Base):
    """transition_rule_permissions: PK (rule_id, permission); достаточно любого права (FR-070)."""

    __tablename__ = "transition_rule_permissions"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("transition_rules.id", ondelete="CASCADE"), primary_key=True
    )
    permission: Mapped[PermissionCode] = mapped_column(String(32), primary_key=True)

    rule: Mapped["TransitionRule"] = relationship(back_populates="permissions")


class StatusLog(TimestampMixin, Base):
    """status_log (FR-075): запись при каждом переходе, включая каскадную архивацию."""

    __tablename__ = "status_log"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    material_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[MaterialStatus | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[MaterialStatus] = mapped_column(String(16), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        Index("ix_status_log_material", "material_id"),
        Index("ix_status_log_user", "user_id"),
    )


class AuditEntry(Base):
    """audit_entries (12.1, §11, FR-140–143) — append-only; записи с этапа 5,
    просмотр/экспорт/очистка — этап 10."""

    __tablename__ = "audit_entries"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )  # NULL — системные события (конвейер файлов)
    actor_is_service: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)


# ==========================================================================
# Этап 6: файлы и версии (LLD §5, §6, §9; FR-055–064, FR-144–148, NFR-014)
# ==========================================================================

class MaterialVersion(Base):
    """material_versions (LLD §5.1, FR-144–148): снапшот версии материала.

    Снапшот: {"file_id", "text", "name", "type_id",
    "attributes": [{attribute_id, values[]}], "tags"} — без master_id и прав
    (FR-144). Номер с 1, уникален в материале (§2.4). Бессрочно (FR-147).
    """

    __tablename__ = "material_versions"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    material_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False
    )
    number: Mapped[int] = mapped_column(nullable=False)  # с 1, UNIQUE в материале (§5.1)
    snapshot: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("uq_material_versions_number", "material_id", "number", unique=True),
    )


class TaskState(str, enum.Enum):
    """task_state (LLD §2.1, NFR-014)."""

    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class TaskType(str, enum.Enum):
    """task_type (LLD §2.1): на этапах 6/9/10 добавляются обработчики."""

    antivirus = "antivirus"
    conversion = "conversion"
    email = "email"
    digest = "digest"
    audit_cleanup = "audit_cleanup"
    inapp_cleanup = "inapp_cleanup"
    analytics_rollup = "analytics_rollup"
    cas_gc = "cas_gc"
    cas_reconcile = "cas_reconcile"
    keycloak_sync = "keycloak_sync"
    integrity_check = "integrity_check"
    fts_rebuild = "fts_rebuild"


class SystemTask(TimestampMixin, Base):
    """system_tasks (LLD §2.2, §9, NFR-014): источник истины по состояниям задач.

    Брокер Valkey — транспорт; восстановление после сбоя — задачи в queued
    перезапускаются при старте worker (reconcile очереди из БД).
    """

    __tablename__ = "system_tasks"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)  # task_type (§2.1)
    object_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    object_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )  # task_state
    attempts: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # B-tree (task_type, state) — мониторинг очередей (NFR-019, §2.4)
        Index("ix_system_tasks_type_state", "task_type", "state"),
        Index("ix_system_tasks_object", "object_type", "object_id"),
    )


# ==========================================================================
# Этап 7: мастер-подчинённый (LLD §2.2 comments, §2.3; FR-032–042, FR-096–098)
# ==========================================================================

class Comment(TimestampMixin, Base):
    """comments (7.6, FR-096–098): append-only — без UPDATE/DELETE (§2.2).

    created_at перекрывает TimestampMixin (нужен server_default по LLD §2.2).
    """

    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    material_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # B-tree по объекту/дате (§2.4): лента комментариев карточки
        Index("ix_comments_material", "material_id", "created_at"),
        Index("ix_comments_author", "author_id"),
    )


# ==========================================================================
# Этап 8: поиск (LLD §7; FR-110–127)
# ==========================================================================

class SearchEvent(Base):
    """search_events (9.9, FR-127): факт поискового запроса.

    Без ПДн: user_id не хранится (§7.6). created_at перекрывает TimestampMixin.
    """

    __tablename__ = "search_events"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    query_normalized: Mapped[str] = mapped_column(Text, nullable=False)  # lower, trim
    result_count: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_search_events_query", "query_normalized"),
        Index("ix_search_events_created", "created_at"),
    )


class SearchOpen(Base):
    """search_opens (9.9, FR-127): факт открытия материала из выдачи (CTR, 3.2)."""

    __tablename__ = "search_opens"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    search_event_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("search_events.id", ondelete="CASCADE"), nullable=False
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_search_opens_event", "search_event_id"),
        Index("ix_search_opens_material", "material_id"),
    )


class SearchAnalytics(Base):
    """search_analytics (9.9, FR-127): свёртка за период (worker, ежедневно).

    Период — день (period_start); пересвёртка периода безопасна (§9).
    """

    __tablename__ = "search_analytics"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    hit_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    zero_result_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    open_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")

    __table_args__ = (
        UniqueConstraint("period_start", "query", name="uq_search_analytics_period_query"),
        Index("ix_search_analytics_period", "period_start"),
    )


class SystemSetting(Base):
    """system_settings (NFR-020): реестр параметров §2.5 (значения — jsonb).

    value хранится строкой JSON (Text) — jsonb-тип непортабелен на SQLite;
    в PostgreSQL миграция 0008 создаёт колонку как JSONB.
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-строка
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

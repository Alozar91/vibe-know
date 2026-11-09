# Списковый предикат прав (LLD §3.2 inline) — фильтр WHERE для списков/поиска.
#
# На каждый материал m применяется та же семантика §3.2: eff-подзапрос правил
# ролей пользователя по объектам цепочки (материал m + группы-предки его
# группы по path-префиксу); deny побеждает; default deny; СА — в обход.
# Портабельно: bool_or ≡ max(case); «path LIKE path || '%'» — concat.
from sqlalchemy import and_, case, exists, func, literal, or_, select, true
from sqlalchemy.orm import Session, aliased

from app.db import models

PROCESS_PERMS = ("edit", "delete", "review", "publish", "archive")
DRAFT_STATUSES = ("draft", "in_review", "approved")
PUBLIC_STATUSES = ("published", "archived")


def visible_materials_condition(user, permission: str, M, MG):
    """Условие «материал M разрешён» (§3.2) для внешнего запроса.

    M — алиас materials в запросе, MG — алиас groups, соединённый по
    M.group_id == MG.id (path группы материала для поиска предков).
    """
    if user.is_super:
        return true()  # FR-104

    P = models.PermissionSnapshot
    E = models.PermissionEntry
    ANC = aliased(models.Group)

    uid = user.user_id
    virtual_exists = select(models.Role.id).where(models.Role.is_virtual_all_users).exists()

    # eff: свернутые правила по объектам цепочки (материал + предки группы)
    eff = (
        select(
            E.permission.label("perm"),
            func.max(case((E.state == "allow", 1), else_=0)).label("allow"),
            func.max(case((E.state == "deny", 1), else_=0)).label("deny"),
        )
        .join(P, P.id == E.snapshot_id)
        .where(
            or_(
                P.role_id.in_(
                    select(models.UserRole.role_id).where(models.UserRole.user_id == uid)
                ),
                and_(P.role_id.is_(None), virtual_exists),
            ),
            or_(
                and_(P.object_type == "material", P.object_id == M.id),
                and_(
                    P.object_type == "group",
                    P.object_id.in_(
                        select(ANC.id).where(
                            ANC.is_deleted.is_(False),
                            MG.path.like(ANC.path.concat("%")),  # предки по path-префиксу
                        )
                    ),
                ),
            ),
        )
        .group_by(E.permission)
        .subquery()
    )

    def _has(perm_expr):
        return exists(
            select(literal(1)).select_from(eff).where(
                eff.c.perm == perm_expr, eff.c.allow == 1, eff.c.deny == 0
            )
        )

    # Ветки видимости (FR-066): черновик/процесс — автор или носители прав процесса;
    # публикация/архив — носители view
    visible = or_(
        and_(
            M.status.in_(DRAFT_STATUSES),
            or_(M.author_id == uid, _has(literal("edit")), _has(literal("delete")),
                _has(literal("review")), _has(literal("publish")), _has(literal("archive"))),
        ),
        and_(M.status.in_(PUBLIC_STATUSES), _has(literal("view"))),
    )

    # Хвост §3.2: view не требует отдельного правила (достаточно видимости);
    # прочие действия — по праву (FR-102)
    if permission == "view":
        return visible
    return and_(visible, or_(literal(False), _has(literal(permission))))

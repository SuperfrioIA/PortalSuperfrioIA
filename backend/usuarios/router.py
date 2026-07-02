"""Administração de roles e usuários (/api/admin).

Princípios (herdados do CRUD original):
- Toggle ativo/inativo em vez de DELETE (auditável).
- PATCH é parcial; slug/username são stable.
- Lockouts: admin não desativa a si mesmo nem remove o próprio is_admin.

Slugs de apps (domínio do Portal) são resolvidos via portal.service — este
módulo não lê a tabela `apps`.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select, update

from backend.auth.dependencies import require_admin
from backend.auth.service import hash_password
from backend.core.database import _now, db
from backend.core.http import apply_update, ensure_slug, ids_por_slug_or_400, row_or_404, unique_or_409
from backend.portal import service as portal_service
from backend.usuarios.models import Role, Usuario, role_apps, usuario_roles

PASSWORD_MIN_LEN = 8

router_admin = APIRouter(prefix="/api/admin", tags=["admin"])


# ============ Roles ============

class RoleCreate(BaseModel):
    slug: str
    nome: str
    descricao: Optional[str] = None
    apps: list[str] = Field(default_factory=list)  # slugs dos apps


class RoleUpdate(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    apps: Optional[list[str]] = None


def _set_role_apps(session, role_id: int, app_ids: list[int]) -> None:
    session.execute(delete(role_apps).where(role_apps.c.role_id == role_id))
    for aid in app_ids:
        session.execute(insert(role_apps).values(role_id=role_id, app_id=aid))


def _app_slugs_da_role(session, role_id: int) -> list[str]:
    app_ids = session.execute(
        select(role_apps.c.app_id).where(role_apps.c.role_id == role_id)
    ).scalars().all()
    slugs = portal_service.slugs_por_app_ids(session, list(app_ids))
    return sorted(slugs.values())


def _select_role(session, role_id: int) -> dict:
    row = row_or_404(session, Role, role_id, "roles")
    return {**row, "apps": _app_slugs_da_role(session, role_id)}


@router_admin.get("/roles")
def listar_roles(_: dict = Depends(require_admin)):
    with db() as session:
        rows = session.execute(
            select(Role.__table__).order_by(Role.nome)
        ).mappings().fetchall()
        vinculos = session.execute(
            select(role_apps.c.role_id, role_apps.c.app_id)
        ).all()
        slug_por_app = portal_service.slugs_por_app_ids(
            session, [app_id for _rid, app_id in vinculos]
        )
        apps_por_role: dict[int, list[str]] = {}
        for role_id, app_id in vinculos:
            apps_por_role.setdefault(role_id, []).append(slug_por_app[app_id])
        for slugs in apps_por_role.values():
            slugs.sort()
        users_por_role: dict[int, int] = {}
        for role_id, n in session.execute(
            select(usuario_roles.c.role_id, func.count())
            .group_by(usuario_roles.c.role_id)
        ):
            users_por_role[role_id] = n
    return [
        {
            **dict(r),
            "apps": apps_por_role.get(r["id"], []),
            "usuarios_count": users_por_role.get(r["id"], 0),
        }
        for r in rows
    ]


@router_admin.post("/roles", status_code=201)
def criar_role(body: RoleCreate, _: dict = Depends(require_admin)):
    ensure_slug(body.slug)
    with db() as session:
        app_ids = portal_service.app_ids_por_slug(session, body.apps)
        with unique_or_409("slug", body.slug):
            cur = session.execute(
                insert(Role).values(slug=body.slug, nome=body.nome, descricao=body.descricao)
            )
        role_id = cur.inserted_primary_key[0]
        _set_role_apps(session, role_id, app_ids)
        return _select_role(session, role_id)


@router_admin.patch("/roles/{role_id}")
def atualizar_role(role_id: int, body: RoleUpdate, _: dict = Depends(require_admin)):
    with db() as session:
        row_or_404(session, Role, role_id, "roles")
        fields = body.model_dump(exclude_unset=True)
        apps = fields.pop("apps", None)
        if fields:
            apply_update(session, Role, role_id, fields)
        if apps is not None:
            app_ids = portal_service.app_ids_por_slug(session, apps)
            _set_role_apps(session, role_id, app_ids)
        return _select_role(session, role_id)


@router_admin.post("/roles/{role_id}/toggle")
def toggle_role(role_id: int, _: dict = Depends(require_admin)):
    with db() as session:
        row = row_or_404(session, Role, role_id, "roles")
        novo = 0 if row["ativo"] else 1
        session.execute(update(Role).where(Role.id == role_id).values(ativo=novo))
        return _select_role(session, role_id)


# ============ Usuários ============

class UsuarioCreate(BaseModel):
    username: str
    senha: str
    nome: Optional[str] = None
    email: Optional[str] = None
    is_admin: bool = False
    roles: list[str] = Field(default_factory=list)  # slugs


class UsuarioUpdate(BaseModel):
    nome: Optional[str] = None
    email: Optional[str] = None
    is_admin: Optional[bool] = None
    roles: Optional[list[str]] = None


class PasswordReset(BaseModel):
    senha: str = Field(min_length=PASSWORD_MIN_LEN)


# nunca devolve password_hash
_USUARIO_PUBLICO = select(
    Usuario.id, Usuario.username, Usuario.nome, Usuario.email, Usuario.auth_source,
    Usuario.ativo, Usuario.is_admin, Usuario.criado_em, Usuario.atualizado_em,
)


def _set_user_roles(session, user_id: int, role_ids: list[int]) -> None:
    session.execute(delete(usuario_roles).where(usuario_roles.c.usuario_id == user_id))
    for rid in role_ids:
        session.execute(insert(usuario_roles).values(usuario_id=user_id, role_id=rid))


def _select_usuario(session, user_id: int) -> dict:
    row = session.execute(
        _USUARIO_PUBLICO.where(Usuario.id == user_id)
    ).mappings().fetchone()
    if not row:
        raise HTTPException(404, f"usuário {user_id} não encontrado")
    roles = session.execute(
        select(Role.slug)
        .join_from(usuario_roles, Role, Role.id == usuario_roles.c.role_id)
        .where(usuario_roles.c.usuario_id == user_id)
        .order_by(Role.slug)
    ).scalars().all()
    return {**dict(row), "roles": list(roles)}


@router_admin.get("/usuarios")
def listar_usuarios(_: dict = Depends(require_admin)):
    with db() as session:
        rows = session.execute(
            _USUARIO_PUBLICO.order_by(Usuario.username)
        ).mappings().fetchall()
        roles_por_user: dict[int, list[str]] = {}
        for usuario_id, slug in session.execute(
            select(usuario_roles.c.usuario_id, Role.slug)
            .join_from(usuario_roles, Role, Role.id == usuario_roles.c.role_id)
            .order_by(Role.slug)
        ):
            roles_por_user.setdefault(usuario_id, []).append(slug)
    return [{**dict(r), "roles": roles_por_user.get(r["id"], [])} for r in rows]


@router_admin.post("/usuarios", status_code=201)
def criar_usuario(body: UsuarioCreate, _: dict = Depends(require_admin)):
    if not body.username or not body.username.strip():
        raise HTTPException(400, "username obrigatório")
    if len(body.senha) < PASSWORD_MIN_LEN:
        raise HTTPException(400, f"senha deve ter ao menos {PASSWORD_MIN_LEN} caracteres")
    with db() as session:
        role_ids = ids_por_slug_or_400(session, Role, body.roles, "role")
        with unique_or_409("username", body.username):
            cur = session.execute(
                insert(Usuario).values(
                    username=body.username.strip(),
                    nome=body.nome,
                    email=body.email,
                    password_hash=hash_password(body.senha),
                    auth_source="local",
                    is_admin=1 if body.is_admin else 0,
                )
            )
        user_id = cur.inserted_primary_key[0]
        _set_user_roles(session, user_id, role_ids)
        return _select_usuario(session, user_id)


@router_admin.patch("/usuarios/{user_id}")
def atualizar_usuario(
    user_id: int,
    body: UsuarioUpdate,
    me: dict = Depends(require_admin),
):
    with db() as session:
        row_or_404(session, Usuario, user_id, "usuarios")
        fields = body.model_dump(exclude_unset=True)
        roles = fields.pop("roles", None)

        # Não permite admin tirar o próprio bit de admin (evita lockout)
        if "is_admin" in fields and user_id == me["id"] and not fields["is_admin"]:
            raise HTTPException(400, "Você não pode remover o próprio acesso de administrador")

        if "is_admin" in fields:
            fields["is_admin"] = 1 if fields["is_admin"] else 0

        if fields:
            apply_update(session, Usuario, user_id, fields, touch_updated=True)

        if roles is not None:
            role_ids = ids_por_slug_or_400(session, Role, roles, "role")
            _set_user_roles(session, user_id, role_ids)

        return _select_usuario(session, user_id)


@router_admin.post("/usuarios/{user_id}/toggle")
def toggle_usuario(user_id: int, me: dict = Depends(require_admin)):
    if user_id == me["id"]:
        raise HTTPException(400, "Você não pode desativar a própria conta")
    with db() as session:
        row = row_or_404(session, Usuario, user_id, "usuarios")
        novo = 0 if row["ativo"] else 1
        session.execute(
            update(Usuario).where(Usuario.id == user_id).values(ativo=novo, atualizado_em=_now())
        )
        return _select_usuario(session, user_id)


@router_admin.post("/usuarios/{user_id}/password")
def resetar_senha(user_id: int, body: PasswordReset, _: dict = Depends(require_admin)):
    with db() as session:
        row_or_404(session, Usuario, user_id, "usuarios")
        session.execute(
            update(Usuario)
            .where(Usuario.id == user_id)
            .values(
                password_hash=hash_password(body.senha),
                token_version=Usuario.token_version + 1,
                atualizado_em=_now(),
            )
        )
        return {"ok": True}

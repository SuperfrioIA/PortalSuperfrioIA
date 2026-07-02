"""
CRUD admin do Hub SuperFrio & Icestar.

Princípios:
- Toggle ativo/inativo em vez de DELETE (auditável).
- PATCH é parcial: só atualiza o que vier no body.
- Slug é stable: nunca é editado depois de criado.
- Validações no boundary, erros HTTP claros.
"""
from contextlib import contextmanager
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from backend.auth import hash_password, require_admin
from backend.database import App, Role, Secao, Usuario, _now, db, role_apps, usuario_roles

PASSWORD_MIN_LEN = 8

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ============ Helpers ============

_TABELAS = {"secoes": Secao, "apps": App, "roles": Role, "usuarios": Usuario}


@contextmanager
def _unique_or_409(field: str, value: str):
    """Converte violação de UNIQUE do banco em 409 com mensagem clara."""
    try:
        yield
    except IntegrityError as e:
        msg = str(e.orig)
        # "UNIQUE constraint failed" (SQLite) / "duplicate key value" (Postgres)
        if "UNIQUE" in msg or "duplicate key" in msg:
            raise HTTPException(409, f"{field} '{value}' já existe")
        raise


def _slug_ok(slug: str) -> bool:
    return bool(slug) and all(c.isalnum() or c in "-_" for c in slug) and slug == slug.lower()


def _ensure_slug(slug: str) -> None:
    if not _slug_ok(slug):
        raise HTTPException(
            status_code=400,
            detail="slug deve ser minúsculo, com letras, números, '-' ou '_'",
        )


def _row_or_404(session, table: str, row_id: int) -> dict:
    model = _TABELAS[table]
    row = session.execute(
        select(model.__table__).where(model.id == row_id)
    ).mappings().fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"{table} {row_id} não encontrado")
    return dict(row)


def _apply_update(session, table: str, row_id: int, fields: dict, touch_updated: bool = False) -> None:
    """UPDATE parcial: só as colunas em `fields`. Se touch_updated, seta atualizado_em=agora."""
    model = _TABELAS[table]
    values = dict(fields)
    if touch_updated:
        values["atualizado_em"] = _now()
    session.execute(update(model).where(model.id == row_id).values(**values))


def _ids_por_slug(session, table: str, slugs: list[str], label: str) -> list[int]:
    """Resolve uma lista de slugs para ids da `table`; 400 se algum não existir."""
    if not slugs:
        return []
    model = _TABELAS[table]
    rows = session.execute(
        select(model.id, model.slug).where(model.slug.in_(slugs))
    ).all()
    encontrados = {slug: id_ for id_, slug in rows}
    faltando = [s for s in slugs if s not in encontrados]
    if faltando:
        raise HTTPException(400, f"{label} slug(s) inexistente(s): {', '.join(faltando)}")
    return [encontrados[s] for s in slugs]


# ============ Seções ============

class SecaoCreate(BaseModel):
    slug: str
    nome: str
    nome_es: Optional[str] = None
    descricao: Optional[str] = None
    descricao_es: Optional[str] = None
    icone: Optional[str] = None
    ordem: int = 0


class SecaoUpdate(BaseModel):
    nome: Optional[str] = None
    nome_es: Optional[str] = None
    descricao: Optional[str] = None
    descricao_es: Optional[str] = None
    icone: Optional[str] = None
    ordem: Optional[int] = None


@router.get("/secoes")
def listar_secoes(_: dict = Depends(require_admin)):
    with db() as session:
        rows = session.execute(
            select(*Secao.__table__.c, func.count(App.id).label("apps_count"))
            .join_from(Secao, App, App.secao_id == Secao.id, isouter=True)
            .group_by(Secao.id)
            .order_by(Secao.ordem, Secao.nome)
        ).mappings().fetchall()
    return [dict(r) for r in rows]


@router.post("/secoes", status_code=201)
def criar_secao(body: SecaoCreate, _: dict = Depends(require_admin)):
    _ensure_slug(body.slug)
    with db() as session:
        with _unique_or_409("slug", body.slug):
            cur = session.execute(
                insert(Secao).values(
                    slug=body.slug, nome=body.nome, nome_es=body.nome_es,
                    descricao=body.descricao, descricao_es=body.descricao_es,
                    icone=body.icone, ordem=body.ordem,
                )
            )
        return _row_or_404(session, "secoes", cur.inserted_primary_key[0])


@router.patch("/secoes/{secao_id}")
def atualizar_secao(secao_id: int, body: SecaoUpdate, _: dict = Depends(require_admin)):
    with db() as session:
        _row_or_404(session, "secoes", secao_id)
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            return _row_or_404(session, "secoes", secao_id)
        _apply_update(session, "secoes", secao_id, fields)
        return _row_or_404(session, "secoes", secao_id)


@router.post("/secoes/{secao_id}/toggle")
def toggle_secao(secao_id: int, _: dict = Depends(require_admin)):
    with db() as session:
        row = _row_or_404(session, "secoes", secao_id)
        novo = 0 if row["ativo"] else 1
        session.execute(update(Secao).where(Secao.id == secao_id).values(ativo=novo))
        return _row_or_404(session, "secoes", secao_id)


# ============ Apps ============

class AppCreate(BaseModel):
    slug: str
    nome: str
    nome_es: Optional[str] = None
    secao_id: int
    url: str
    descricao: Optional[str] = None
    descricao_es: Optional[str] = None
    icone: Optional[str] = None
    tipo_acesso: str = "url"
    badge: Optional[str] = None
    ordem: int = 0


class AppUpdate(BaseModel):
    nome: Optional[str] = None
    nome_es: Optional[str] = None
    descricao: Optional[str] = None
    descricao_es: Optional[str] = None
    icone: Optional[str] = None
    secao_id: Optional[int] = None
    url: Optional[str] = None
    tipo_acesso: Optional[str] = None
    badge: Optional[str] = None
    ordem: Optional[int] = None


def _check_tipo_acesso(tipo: Optional[str]) -> None:
    if tipo is not None and tipo not in ("url", "iframe"):
        raise HTTPException(400, "tipo_acesso deve ser 'url' ou 'iframe'")


def _check_url(url: Optional[str]) -> None:
    if url is None:
        return
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "url deve começar com http:// ou https://")


_APP_COM_SECAO = (
    select(
        *App.__table__.c,
        Secao.slug.label("secao_slug"),
        Secao.nome.label("secao_nome"),
    )
    .join_from(App, Secao, Secao.id == App.secao_id)
)


def _select_app(session, app_id: int) -> dict:
    row = session.execute(
        _APP_COM_SECAO.where(App.id == app_id)
    ).mappings().fetchone()
    if not row:
        raise HTTPException(404, f"app {app_id} não encontrado")
    return dict(row)


@router.get("/apps")
def listar_apps(_: dict = Depends(require_admin)):
    with db() as session:
        rows = session.execute(
            _APP_COM_SECAO.order_by(Secao.ordem, App.ordem, App.nome)
        ).mappings().fetchall()
    return [dict(r) for r in rows]


@router.post("/apps", status_code=201)
def criar_app(body: AppCreate, _: dict = Depends(require_admin)):
    _ensure_slug(body.slug)
    _check_tipo_acesso(body.tipo_acesso)
    _check_url(body.url)
    with db() as session:
        _row_or_404(session, "secoes", body.secao_id)
        with _unique_or_409("slug", body.slug):
            cur = session.execute(
                insert(App).values(
                    slug=body.slug, nome=body.nome, nome_es=body.nome_es,
                    descricao=body.descricao, descricao_es=body.descricao_es,
                    icone=body.icone, secao_id=body.secao_id, url=body.url,
                    tipo_acesso=body.tipo_acesso, badge=body.badge, ordem=body.ordem,
                )
            )
        return _select_app(session, cur.inserted_primary_key[0])


@router.patch("/apps/{app_id}")
def atualizar_app(app_id: int, body: AppUpdate, _: dict = Depends(require_admin)):
    _check_tipo_acesso(body.tipo_acesso)
    _check_url(body.url)
    with db() as session:
        _row_or_404(session, "apps", app_id)
        if body.secao_id is not None:
            _row_or_404(session, "secoes", body.secao_id)
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            return _select_app(session, app_id)
        _apply_update(session, "apps", app_id, fields, touch_updated=True)
        return _select_app(session, app_id)


@router.post("/apps/{app_id}/toggle")
def toggle_app(app_id: int, _: dict = Depends(require_admin)):
    with db() as session:
        row = _row_or_404(session, "apps", app_id)
        novo = 0 if row["ativo"] else 1
        session.execute(
            update(App).where(App.id == app_id).values(ativo=novo, atualizado_em=_now())
        )
        return _select_app(session, app_id)


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


def _select_role(session, role_id: int) -> dict:
    row = _row_or_404(session, "roles", role_id)
    app_slugs = session.execute(
        select(App.slug)
        .join_from(role_apps, App, App.id == role_apps.c.app_id)
        .where(role_apps.c.role_id == role_id)
        .order_by(App.slug)
    ).scalars().all()
    return {**row, "apps": list(app_slugs)}


@router.get("/roles")
def listar_roles(_: dict = Depends(require_admin)):
    with db() as session:
        rows = session.execute(
            select(Role.__table__).order_by(Role.nome)
        ).mappings().fetchall()
        apps_por_role: dict[int, list[str]] = {}
        for role_id, slug in session.execute(
            select(role_apps.c.role_id, App.slug)
            .join_from(role_apps, App, App.id == role_apps.c.app_id)
            .order_by(App.slug)
        ):
            apps_por_role.setdefault(role_id, []).append(slug)
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


@router.post("/roles", status_code=201)
def criar_role(body: RoleCreate, _: dict = Depends(require_admin)):
    _ensure_slug(body.slug)
    with db() as session:
        app_ids = _ids_por_slug(session, "apps", body.apps, "app")
        with _unique_or_409("slug", body.slug):
            cur = session.execute(
                insert(Role).values(slug=body.slug, nome=body.nome, descricao=body.descricao)
            )
        role_id = cur.inserted_primary_key[0]
        _set_role_apps(session, role_id, app_ids)
        return _select_role(session, role_id)


@router.patch("/roles/{role_id}")
def atualizar_role(role_id: int, body: RoleUpdate, _: dict = Depends(require_admin)):
    with db() as session:
        _row_or_404(session, "roles", role_id)
        fields = body.model_dump(exclude_unset=True)
        apps = fields.pop("apps", None)
        if fields:
            _apply_update(session, "roles", role_id, fields)
        if apps is not None:
            app_ids = _ids_por_slug(session, "apps", apps, "app")
            _set_role_apps(session, role_id, app_ids)
        return _select_role(session, role_id)


@router.post("/roles/{role_id}/toggle")
def toggle_role(role_id: int, _: dict = Depends(require_admin)):
    with db() as session:
        row = _row_or_404(session, "roles", role_id)
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


@router.get("/usuarios")
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


@router.post("/usuarios", status_code=201)
def criar_usuario(body: UsuarioCreate, _: dict = Depends(require_admin)):
    if not body.username or not body.username.strip():
        raise HTTPException(400, "username obrigatório")
    if len(body.senha) < PASSWORD_MIN_LEN:
        raise HTTPException(400, f"senha deve ter ao menos {PASSWORD_MIN_LEN} caracteres")
    with db() as session:
        role_ids = _ids_por_slug(session, "roles", body.roles, "role")
        with _unique_or_409("username", body.username):
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


@router.patch("/usuarios/{user_id}")
def atualizar_usuario(
    user_id: int,
    body: UsuarioUpdate,
    me: dict = Depends(require_admin),
):
    with db() as session:
        _row_or_404(session, "usuarios", user_id)
        fields = body.model_dump(exclude_unset=True)
        roles = fields.pop("roles", None)

        # Não permite admin tirar o próprio bit de admin (evita lockout)
        if "is_admin" in fields and user_id == me["id"] and not fields["is_admin"]:
            raise HTTPException(400, "Você não pode remover o próprio acesso de administrador")

        if "is_admin" in fields:
            fields["is_admin"] = 1 if fields["is_admin"] else 0

        if fields:
            _apply_update(session, "usuarios", user_id, fields, touch_updated=True)

        if roles is not None:
            role_ids = _ids_por_slug(session, "roles", roles, "role")
            _set_user_roles(session, user_id, role_ids)

        return _select_usuario(session, user_id)


@router.post("/usuarios/{user_id}/toggle")
def toggle_usuario(user_id: int, me: dict = Depends(require_admin)):
    if user_id == me["id"]:
        raise HTTPException(400, "Você não pode desativar a própria conta")
    with db() as session:
        row = _row_or_404(session, "usuarios", user_id)
        novo = 0 if row["ativo"] else 1
        session.execute(
            update(Usuario).where(Usuario.id == user_id).values(ativo=novo, atualizado_em=_now())
        )
        return _select_usuario(session, user_id)


@router.post("/usuarios/{user_id}/password")
def resetar_senha(user_id: int, body: PasswordReset, _: dict = Depends(require_admin)):
    with db() as session:
        _row_or_404(session, "usuarios", user_id)
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

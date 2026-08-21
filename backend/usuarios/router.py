"""Administração de roles e usuários (/api/admin).

Princípios (herdados do CRUD original):
- Toggle ativo/inativo em vez de DELETE (auditável).
- PATCH é parcial; slug/username são stable.
- Lockouts: admin não desativa a si mesmo nem remove o próprio is_admin.

Slugs de apps (domínio do Portal) são resolvidos via portal.service — este
módulo não lê a tabela `apps`.

Permissão é a matriz app × ação (`backend/core/permissoes.py`). A role concede as
duas metades: a coluna `ver` via `apps` (grava em `role_apps`) e as demais ações
via `permissoes` (grava em `role_permissoes`). A API mantém os dois campos
separados porque são tabelas diferentes; a tela junta tudo numa grade só.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select, update

from backend.auth.dependencies import require_admin
from backend.auth.service import hash_password
from backend.core import permissoes as catalogo
from backend.core.database import _now, db
from backend.core.http import apply_update, ensure_slug, ids_por_slug_or_400, row_or_404, unique_or_409
from backend.portal import service as portal_service
from backend.projetos_ia import service as projetos_ia_service
from backend.usuarios.models import Role, Usuario, role_apps, role_permissoes, usuario_roles

PASSWORD_MIN_LEN = 8

router_admin = APIRouter(prefix="/api/admin", tags=["admin"])


# ============ Roles ============

class RoleCreate(BaseModel):
    slug: str
    nome: str
    descricao: Optional[str] = None
    apps: list[str] = Field(default_factory=list)         # coluna `ver` da matriz
    permissoes: list[str] = Field(default_factory=list)   # demais ações


class RoleUpdate(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    apps: Optional[list[str]] = None
    permissoes: Optional[list[str]] = None


def _validar_permissoes(slugs: list[str]) -> None:
    """400 com mensagem útil se algum slug não existir no catálogo em código."""
    faltando = catalogo.validar_slugs(slugs)
    if faltando:
        conhecidas = ", ".join(p.slug for p in catalogo.listar()) or "(nenhuma)"
        raise HTTPException(
            400,
            f"permissão(ões) inexistente(s): {', '.join(faltando)}. "
            f"O catálogo é declarado em backend/<modulo>/permissoes.py. "
            f"Disponíveis: {conhecidas}",
        )


def _set_role_apps(session, role_id: int, app_ids: list[int]) -> None:
    session.execute(delete(role_apps).where(role_apps.c.role_id == role_id))
    for aid in app_ids:
        session.execute(insert(role_apps).values(role_id=role_id, app_id=aid))


def _set_role_permissoes(session, role_id: int, slugs: list[str]) -> None:
    session.execute(delete(role_permissoes).where(role_permissoes.c.role_id == role_id))
    for slug in dict.fromkeys(slugs):  # dedup preservando ordem
        session.execute(
            insert(role_permissoes).values(role_id=role_id, permissao_slug=slug)
        )


def _app_slugs_da_role(session, role_id: int) -> list[str]:
    app_ids = session.execute(
        select(role_apps.c.app_id).where(role_apps.c.role_id == role_id)
    ).scalars().all()
    slugs = portal_service.slugs_por_app_ids(session, list(app_ids))
    return sorted(slugs.values())


def _permissoes_da_role(session, role_id: int) -> list[str]:
    return sorted(
        session.execute(
            select(role_permissoes.c.permissao_slug).where(
                role_permissoes.c.role_id == role_id
            )
        ).scalars().all()
    )


def _select_role(session, role_id: int) -> dict:
    row = row_or_404(session, Role, role_id, "roles")
    return {
        **row,
        "apps": _app_slugs_da_role(session, role_id),
        "permissoes": _permissoes_da_role(session, role_id),
    }


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
        perms_por_role: dict[int, list[str]] = {}
        for role_id, slug in session.execute(
            select(role_permissoes.c.role_id, role_permissoes.c.permissao_slug)
            .order_by(role_permissoes.c.permissao_slug)
        ):
            perms_por_role.setdefault(role_id, []).append(slug)
    return [
        {
            **dict(r),
            "apps": apps_por_role.get(r["id"], []),
            "permissoes": perms_por_role.get(r["id"], []),
            "usuarios_count": users_por_role.get(r["id"], 0),
        }
        for r in rows
    ]


@router_admin.post("/roles", status_code=201)
def criar_role(body: RoleCreate, _: dict = Depends(require_admin)):
    ensure_slug(body.slug)
    _validar_permissoes(body.permissoes)
    with db() as session:
        app_ids = portal_service.app_ids_por_slug(session, body.apps)
        with unique_or_409("slug", body.slug):
            cur = session.execute(
                insert(Role).values(slug=body.slug, nome=body.nome, descricao=body.descricao)
            )
        role_id = cur.inserted_primary_key[0]
        _set_role_apps(session, role_id, app_ids)
        _set_role_permissoes(session, role_id, body.permissoes)
        return _select_role(session, role_id)


@router_admin.patch("/roles/{role_id}")
def atualizar_role(role_id: int, body: RoleUpdate, _: dict = Depends(require_admin)):
    if body.permissoes is not None:
        _validar_permissoes(body.permissoes)
    with db() as session:
        row_or_404(session, Role, role_id, "roles")
        fields = body.model_dump(exclude_unset=True)
        apps = fields.pop("apps", None)
        permissoes = fields.pop("permissoes", None)
        if fields:
            apply_update(session, Role, role_id, fields)
        if apps is not None:
            app_ids = portal_service.app_ids_por_slug(session, apps)
            _set_role_apps(session, role_id, app_ids)
        if permissoes is not None:
            _set_role_permissoes(session, role_id, permissoes)
        return _select_role(session, role_id)


@router_admin.post("/roles/{role_id}/toggle")
def toggle_role(role_id: int, _: dict = Depends(require_admin)):
    with db() as session:
        row = row_or_404(session, Role, role_id, "roles")
        novo = 0 if row["ativo"] else 1
        session.execute(update(Role).where(Role.id == role_id).values(ativo=novo))
        return _select_role(session, role_id)


# ============ Matriz de acesso ============

@router_admin.get("/matriz")
def matriz(_: dict = Depends(require_admin)):
    """Estrutura da grade app × ação para a tela de Administração.

    As **linhas** vêm do catálogo de apps (banco, editável pelo admin); as
    **colunas** vêm do vocabulário fixo em código. Cada app diz quais ações
    entende: `ver` sempre, as demais só se algum módulo as declarou.

    `orfas` lista permissões declaradas por um módulo cujo app não está cadastrado
    neste ambiente — acontece porque o cadastro de apps é por ambiente. Sem isso a
    permissão sumiria da tela sem explicação.
    """
    acoes_extra = catalogo.acoes_por_app()
    descricoes = {p.slug: p.descricao for p in catalogo.listar()}

    with db() as session:
        apps = portal_service.apps_ativos_com_secao(session)

    secoes: dict[str, dict] = {}
    for a in apps:
        s = secoes.setdefault(
            a["secao_slug"],
            {"slug": a["secao_slug"], "nome": a["secao_nome"], "apps": []},
        )
        s["apps"].append({
            "slug": a["slug"],
            "nome": a["nome"],
            "acoes": [catalogo.ACAO_VER] + acoes_extra.get(a["slug"], []),
        })

    cadastrados = {a["slug"] for a in apps}
    orfas = [
        {"slug": p.slug, "app_slug": p.app_slug, "modulo": p.modulo, "acao": p.acao}
        for p in catalogo.listar()
        if p.app_slug not in cadastrados
    ]

    return {
        "acoes": [{"slug": k, "nome": v} for k, v in catalogo.ACOES.items()],
        "secoes": list(secoes.values()),
        "descricoes": descricoes,
        "orfas": orfas,
    }


# ============ Usuários ============

class UsuarioCreate(BaseModel):
    username: str
    # Sem senha = acesso pela Microsoft (`auth_source="ad"`), o caminho padrão desde
    # 21/08/2026: a pessoa nunca tem senha local, entra pelo botão do Entra. Com
    # senha = usuário local, mantido para o acesso de emergência do admin — se o SSO
    # cair (segredo expirado, Entra fora do ar), alguém precisa conseguir entrar.
    senha: Optional[str] = None
    nome: Optional[str] = None
    email: Optional[str] = None
    is_admin: bool = False
    filial_id: Optional[int] = None
    roles: list[str] = Field(default_factory=list)  # slugs


class UsuarioUpdate(BaseModel):
    nome: Optional[str] = None
    email: Optional[str] = None
    is_admin: Optional[bool] = None
    filial_id: Optional[int] = None
    roles: Optional[list[str]] = None


class PasswordReset(BaseModel):
    senha: str = Field(min_length=PASSWORD_MIN_LEN)


# nunca devolve password_hash
_USUARIO_PUBLICO = select(
    Usuario.id, Usuario.username, Usuario.nome, Usuario.email, Usuario.auth_source,
    Usuario.ativo, Usuario.is_admin, Usuario.filial_id, Usuario.criado_em,
    Usuario.atualizado_em,
)


def _email_normalizado(email: Optional[str]) -> Optional[str]:
    """Minúsculas e sem espaço — a mesma forma que `provisioning.py` usa para casar
    o claim do Entra, e a que o índice único da migration 0005 indexa."""
    return (email or "").strip().lower() or None


def _checa_email_livre(session, email: Optional[str], ignorar_id: Optional[int] = None) -> None:
    """409 antes de bater no índice único, com mensagem que diz de quem é o e-mail.

    Sem isto, um e-mail repetido viraria IntegrityError não tratado (500) — e o
    `unique_or_409` do arquivo tem o nome do campo fixo, então não serve aqui.
    """
    if email is None:
        return
    stmt = select(Usuario.username).where(func.lower(Usuario.email) == email)
    if ignorar_id is not None:
        stmt = stmt.where(Usuario.id != ignorar_id)
    dono = session.execute(stmt).scalars().first()
    if dono:
        raise HTTPException(409, f"e-mail '{email}' já está no cadastro de '{dono}'")


def _valida_filial(session, filial_id) -> None:
    """Filial inexistente é erro do chamador (400). Consulta pelo serviço do módulo
    dono — Usuários não lê a tabela `filiais` direto."""
    if filial_id is None:
        return
    if projetos_ia_service.filial_por_id(session, filial_id) is None:
        raise HTTPException(400, f"filial {filial_id} não existe")


def _com_filial(session, usuarios: list[dict]) -> list[dict]:
    """Enriquecimento on-read: acrescenta `filial_codigo`/`filial_nome`, para a tela
    não precisar cruzar duas listas no navegador."""
    ids = {u["filial_id"] for u in usuarios if u.get("filial_id")}
    mapa = (
        {f["id"]: f for f in projetos_ia_service.listar_filiais(session) if f["id"] in ids}
        if ids
        else {}
    )
    return [
        {
            **u,
            "filial_codigo": (mapa.get(u["filial_id"]) or {}).get("codigo"),
            "filial_nome": (mapa.get(u["filial_id"]) or {}).get("nome"),
        }
        for u in usuarios
    ]


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
    return _com_filial(session, [{**dict(row), "roles": list(roles)}])[0]


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
        usuarios = [{**dict(r), "roles": roles_por_user.get(r["id"], [])} for r in rows]
        return _com_filial(session, usuarios)


@router_admin.post("/usuarios", status_code=201)
def criar_usuario(body: UsuarioCreate, _: dict = Depends(require_admin)):
    if not body.username or not body.username.strip():
        raise HTTPException(400, "username obrigatório")

    email = _email_normalizado(body.email)
    if body.senha is None:
        # Acesso pela Microsoft: o e-mail é a única coisa que casa a pessoa com o
        # token do Entra. Sem ele o cadastro nasce impossível de logar.
        if email is None:
            raise HTTPException(
                400,
                "e-mail obrigatório para acesso com Microsoft — é o que casa com a conta do Entra",
            )
    elif len(body.senha) < PASSWORD_MIN_LEN:
        raise HTTPException(400, f"senha deve ter ao menos {PASSWORD_MIN_LEN} caracteres")

    with db() as session:
        role_ids = ids_por_slug_or_400(session, Role, body.roles, "role")
        _valida_filial(session, body.filial_id)
        _checa_email_livre(session, email)
        with unique_or_409("username", body.username):
            cur = session.execute(
                insert(Usuario).values(
                    username=body.username.strip(),
                    nome=body.nome,
                    email=email,
                    password_hash=hash_password(body.senha) if body.senha else None,
                    auth_source="local" if body.senha else "ad",
                    is_admin=1 if body.is_admin else 0,
                    filial_id=body.filial_id,
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

        if "filial_id" in fields:
            _valida_filial(session, fields["filial_id"])
        if "email" in fields:
            # Normaliza e checa antes de gravar: sem isto, e-mail repetido bateria
            # no índice único da migration 0005 e viraria 500.
            fields["email"] = _email_normalizado(fields["email"])
            _checa_email_livre(session, fields["email"], ignorar_id=user_id)

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

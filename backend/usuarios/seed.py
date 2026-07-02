"""Seed de roles e usuários — idempotente, insere só o que não existe.

Os grants role→app resolvem slugs via `portal.service` (apps são do Portal).
"""
from sqlalchemy import insert, select

from backend.auth.service import hash_password
from backend.portal import service as portal_service
from backend.usuarios.models import Role, Usuario, role_apps, usuario_roles

ROLES = [
    {
        "slug": "armazem-full",
        "nome": "Armazém — Acesso completo",
        "descricao": "Acesso a todos os apps da seção Armazém.",
        "apps": ["faq-blueyonder", "faq-slin", "conciliacao-estoque"],
    },
    {
        "slug": "backoffice-full",
        "nome": "Backoffice — Acesso completo",
        "descricao": "Acesso a todos os apps da seção Backoffice.",
        "apps": ["duvidas-financeiro", "compras-2-0", "conciliafat", "controle-recebimento"],
    },
    {
        "slug": "faq-leitor",
        "nome": "FAQ — Somente leitura",
        "descricao": "Acesso restrito aos FAQs (BlueYonder e Slin).",
        "apps": ["faq-blueyonder", "faq-slin"],
    },
]

USUARIOS = [
    {
        "username": "admin",
        "nome": "Administrador",
        "email": "admin@superfrio.com.br",
        "senha": "admin123",
        "is_admin": 1,
        "roles": [],
    },
    {
        "username": "operador.armazem",
        "nome": "Operador Armazém",
        "email": "armazem@superfrio.com.br",
        "senha": "armazem123",
        "is_admin": 0,
        "roles": ["armazem-full"],
    },
    {
        "username": "analista.bo",
        "nome": "Analista Backoffice",
        "email": "bo@superfrio.com.br",
        "senha": "backoffice123",
        "is_admin": 0,
        "roles": ["backoffice-full", "faq-leitor"],
    },
]


def seed(session) -> None:
    for r in ROLES:
        role_id = session.execute(
            select(Role.id).where(Role.slug == r["slug"])
        ).scalar_one_or_none()
        if role_id is None:
            role_id = session.execute(
                insert(Role).values(slug=r["slug"], nome=r["nome"], descricao=r["descricao"])
            ).inserted_primary_key[0]
        app_ids = portal_service.app_ids_por_slug(session, r["apps"])
        for app_id in app_ids:
            vinculo = session.execute(
                select(role_apps.c.role_id).where(
                    role_apps.c.role_id == role_id,
                    role_apps.c.app_id == app_id,
                )
            ).fetchone()
            if vinculo is None:
                session.execute(
                    insert(role_apps).values(role_id=role_id, app_id=app_id)
                )

    role_id_map = {
        slug: id_ for id_, slug in session.execute(select(Role.id, Role.slug))
    }

    for u in USUARIOS:
        user_id = session.execute(
            select(Usuario.id).where(Usuario.username == u["username"])
        ).scalar_one_or_none()
        if user_id is None:
            user_id = session.execute(
                insert(Usuario).values(
                    username=u["username"], nome=u["nome"], email=u["email"],
                    password_hash=hash_password(u["senha"]),
                    auth_source="local", is_admin=u["is_admin"],
                )
            ).inserted_primary_key[0]

        for role_slug in u["roles"]:
            vinculo = session.execute(
                select(usuario_roles.c.usuario_id).where(
                    usuario_roles.c.usuario_id == user_id,
                    usuario_roles.c.role_id == role_id_map[role_slug],
                )
            ).fetchone()
            if vinculo is None:
                session.execute(
                    insert(usuario_roles).values(
                        usuario_id=user_id, role_id=role_id_map[role_slug]
                    )
                )
